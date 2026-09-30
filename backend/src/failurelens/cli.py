from __future__ import annotations

import argparse
import os
from dataclasses import asdict
import hashlib
import re
import json
import socket
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .api import app  # noqa: F401
from .config import get_settings
from .db import SessionLocal, initialize_database
from .demo import seed_demo
from .github_report import render_markdown
from .github_snapshot import report_snapshot
from .github_publication import GitHubPublisher, PublicationError
from .impact import create_impact_recommendation, impact_recommendation_to_schema
from .infrastructure import (
    build_infrastructure_correlation,
    create_infrastructure_event,
    infrastructure_event_to_schema,
)
from .jobs import process_next
from .models import (
    Analysis,
    Failure,
    Ingestion,
    PerformancePolicy,
    Project,
    Run,
    TestExecution,
)
from .performance import (
    create_run_performance_comparisons,
    ensure_default_performance_policy,
    performance_comparison_to_schema,
)
from .schemas import (
    ImpactRecommendationCreate,
    InfrastructureEventCreate,
    RunMetadata,
)
from .service import analyze_and_persist, create_project, enqueue_artifact_ingestion
from .storage import store_bytes


def main() -> None:
    parser = argparse.ArgumentParser(prog="failurelens")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("demo")
    sub.add_parser("demo-history", help="explicit synthetic 100-run history; demo mode only")

    ingest = sub.add_parser("ingest")
    ingest.add_argument("report", type=Path)
    ingest.add_argument("--project", required=True)
    ingest.add_argument("--external-id", required=True)
    ingest.add_argument("--attempt", type=int, default=1)
    ingest.add_argument("--repository")
    ingest.add_argument("--commit-sha")
    ingest.add_argument("--base-sha")
    ingest.add_argument("--branch")
    ingest.add_argument(
        "--run-scope",
        choices=["full_suite", "impact_selected", "unknown"],
        default="unknown",
    )
    ingest.add_argument(
        "--comparison-trust",
        choices=["self_reported", "authenticated_lookup", "trusted_workflow"],
        default="self_reported",
        help="trusted transport provenance for changed-file input; artifact claims are ignored",
    )
    ingest.add_argument("--environment")
    ingest.add_argument("--timezone")
    ingest.add_argument("--worker-count", type=int)
    ingest.add_argument("--shard-count", type=int)
    ingest.add_argument("--expected-inputs", type=int)
    ingest.add_argument("--format", default="auto")
    ingest.add_argument(
        "--process",
        action="store_true",
        help="claim and process the queued ingestion in this invocation",
    )

    status_parser = sub.add_parser("ingestion-status")
    status_parser.add_argument("--ingestion", required=True)

    analyze = sub.add_parser("analyze")
    analyze.add_argument("--run", required=True)

    report = sub.add_parser("report")
    report.add_argument("--run", required=True)
    report.add_argument("--format", choices=["markdown", "json"], default="markdown")

    publish = sub.add_parser("publish-github", help="opt-in advisory PR comment; serialize per PR/project")
    publish.add_argument("--run", required=True)
    publish.add_argument("--repository", required=True)
    publish.add_argument("--pull-number", required=True, type=int)
    publish.add_argument("--bot-login", default="github-actions[bot]")

    impact = sub.add_parser(
        "impact",
        help="create a deterministic impact recommendation for an ingested changed-file run",
    )
    impact.add_argument("--project", required=True, help="project slug")
    impact.add_argument("--run", required=True, help="run ID containing changed-files input")
    impact.add_argument("--mapping-snapshot", required=True)
    impact.add_argument("--changed-input")

    performance = sub.add_parser(
        "performance",
        help="compare normalized run metrics with compatible prior-only baselines",
    )
    performance.add_argument("--run", required=True, help="run ID to compare")
    performance.add_argument("--policy", help="immutable performance policy ID")
    performance.add_argument(
        "--observation",
        action="append",
        default=[],
        help="optional performance observation ID; repeat to compare a subset",
    )

    infrastructure_event = sub.add_parser(
        "infrastructure-event",
        help="ingest one independently recorded infrastructure event from JSON",
    )
    infrastructure_event.add_argument("event", type=Path)
    infrastructure_event.add_argument("--project", required=True, help="project slug")

    infrastructure_correlation = sub.add_parser(
        "infrastructure-correlate",
        help="persist a prior-only exposed-versus-unexposed correlation snapshot",
    )
    infrastructure_correlation.add_argument("--execution", required=True)
    infrastructure_correlation.add_argument("--event-kind")
    infrastructure_correlation.add_argument("--window-seconds", type=int, default=900)
    infrastructure_correlation.add_argument("--minimum-support", type=int, default=3)

    recovery = sub.add_parser("recover-account", help="explicit local database-operator recovery; never a startup action")
    recovery.add_argument("--username", required=True)
    recovery.add_argument("--reason", required=True)
    recovery.add_argument("--activate", action="store_true", help="explicitly reactivate an inactive account")
    recovery.add_argument("--confirm-local-administrator-access", action="store_true", required=True)

    trace_inspect = sub.add_parser("trace-inspect", help="Validate a local original and print pinned, local-only viewer instructions")
    trace_inspect.add_argument("trace", type=Path)
    trace_inspect.add_argument("--sha256", required=True)
    args = parser.parse_args()
    if args.command == "trace-inspect":
        from .ingestion import IngestionError
        from .trace_evidence import build_trace_index
        if not re.fullmatch(r"[0-9a-fA-F]{64}", args.sha256):
            raise SystemExit("Expected a 64-character SHA-256 digest")
        settings = get_settings()
        try:
            with args.trace.open("rb") as handle:
                content = handle.read(settings.max_file_bytes + 1)
        except OSError:
            raise SystemExit("Local trace could not be read") from None
        if len(content) > settings.max_file_bytes:
            raise SystemExit("Local trace exceeds the configured file limit")
        if hashlib.sha256(content).hexdigest() != args.sha256.lower():
            raise SystemExit("Local trace digest does not match the recorded original")
        try:
            index, warnings = build_trace_index(content, settings)
        except IngestionError as exc:
            raise SystemExit(f"Local trace rejected: {exc.code}") from None
        print(json.dumps({"status": "verified_local_original", "sha256": args.sha256.lower(),
            "producer_versions": index["producer_versions"], "schema_versions": index["schema_versions"],
            "events": index["event_count"], "warnings": warnings,
            "viewer_argv": ["npx", "--no-install", "playwright", "show-trace", str(args.trace.resolve())],
            "instructions": "Use an isolated local workspace with Playwright 1.63.0 already installed and network disabled. "
                "Original DOM, network and image content has NOT been sanitized. Do not host it on the dashboard origin. "
                "This command has not installed software, fetched resources, or launched a viewer."}, indent=2))
        return
    initialize_database()
    settings = get_settings()
    with SessionLocal() as session:
        if args.command == "doctor":
            session.execute(select(1))
            print(
                json.dumps(
                    {
                        "database": "ok",
                        "artifact_root": str(settings.artifact_root),
                        "deterministic_mode": True,
                        "external_model_required": False,
                    }
                )
            )
        elif args.command == "recover-account":
            from .accounts import operator_recovery
            if not args.reason.strip():
                raise SystemExit("a non-empty audit reason is required")
            user, record, raw = operator_recovery(session, args.username, reason=args.reason, activate=args.activate)
            print(json.dumps({"user_id": user.id, "token": raw, "expires_at": record.expires_at.isoformat(),
                              "notice": "Shown once. Redeem in the recovery form; keep this output private."}))
        elif args.command == "demo-history":
            from .demo_history import seed_history
            print(json.dumps(seed_history(session), indent=2))
        elif args.command == "demo":
            print(json.dumps(seed_demo(session), indent=2))
        elif args.command == "ingest":
            if not args.report.is_file():
                raise SystemExit(f"report not found: {args.report}")
            project = session.scalar(select(Project).where(Project.slug == args.project)) or create_project(
                session,
                args.project,
                args.project,
            )
            max_bytes = settings.max_bundle_bytes if args.report.suffix.lower() == ".zip" else settings.max_file_bytes
            if args.report.stat().st_size > max_bytes:
                raise SystemExit(f"report exceeds configured {max_bytes}-byte limit")
            content = args.report.read_bytes()
            media_type = {
                ".xml": "application/xml",
                ".json": "application/json",
                ".zip": "application/zip",
            }.get(args.report.suffix.lower(), "application/octet-stream")
            from .retention import lock_project
            lock_project(session, project.id)
            stored = store_bytes(
                content,
                root=settings.artifact_root,
                project_id=project.id,
                filename=args.report.name,
                media_type=media_type,
                max_bytes=max_bytes,
            )
            metadata = RunMetadata(
                external_id=args.external_id,
                attempt=args.attempt,
                repository=args.repository,
                commit_sha=args.commit_sha,
                base_sha=args.base_sha,
                branch=args.branch,
                framework=args.format,
                run_scope=args.run_scope,
                comparison_trust=args.comparison_trust,
                environment=args.environment,
                timezone=args.timezone,
                worker_count=args.worker_count,
                shard_count=args.shard_count,
                expected_inputs=args.expected_inputs,
                source_metadata={"transport": "cli"},
            )
            ingestion = enqueue_artifact_ingestion(
                session,
                project,
                metadata,
                stored,
                source_format=args.format,
                settings=settings,
            )
            if args.process and ingestion.run_id is None:
                worker_id = f"cli-{socket.gethostname()}-{int(time.time())}"
                for _ in range(1000):
                    ingestion = session.get(Ingestion, ingestion.id) or ingestion
                    if ingestion.run_id is not None or ingestion.state.value in {
                        "failed",
                        "cancelled",
                        "dead_lettered",
                    }:
                        break
                    if not process_next(session, worker_id, settings=settings):
                        break
                    session.expire_all()
                ingestion = session.get(Ingestion, ingestion.id) or ingestion
            print(
                json.dumps(
                    {
                        "ingestion_id": ingestion.id,
                        "job_id": ingestion.job_id,
                        "state": ingestion.state.value,
                        "run_id": ingestion.run_id,
                        "error_code": ingestion.error_code,
                    }
                )
            )
            if args.process and ingestion.run_id is None:
                raise SystemExit(2)
        elif args.command == "ingestion-status":
            ingestion = session.get(Ingestion, args.ingestion)
            if not ingestion:
                raise SystemExit("ingestion not found")
            print(
                json.dumps(
                    {
                        "ingestion_id": ingestion.id,
                        "state": ingestion.state.value,
                        "run_id": ingestion.run_id,
                        "job_id": ingestion.job_id,
                        "error_code": ingestion.error_code,
                        "error_message": ingestion.error_message,
                    },
                    indent=2,
                )
            )
        elif args.command == "analyze":
            failures = session.scalars(select(Failure).where(Failure.run_id == args.run)).all()
            results = [analyze_and_persist(session, failure) for failure in failures]
            print(json.dumps({"analyzed": len(results), "analysis_ids": [item.id for item in results]}))
        elif args.command == "impact":
            project = session.scalar(select(Project).where(Project.slug == args.project))
            if project is None:
                raise SystemExit("project not found")
            try:
                recommendation = create_impact_recommendation(
                    session,
                    project,
                    ImpactRecommendationCreate(
                        run_id=args.run,
                        mapping_snapshot_id=args.mapping_snapshot,
                        changed_input_id=args.changed_input,
                    ),
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            print(
                impact_recommendation_to_schema(recommendation).model_dump_json(
                    indent=2
                )
            )
        elif args.command == "infrastructure-event":
            project = session.scalar(select(Project).where(Project.slug == args.project))
            if project is None:
                raise SystemExit("project not found")
            if not args.event.is_file():
                raise SystemExit(f"event file not found: {args.event}")
            try:
                request = InfrastructureEventCreate.model_validate_json(
                    args.event.read_text(encoding="utf-8")
                )
                event = create_infrastructure_event(session, project, request)
            except (OSError, ValueError) as exc:
                raise SystemExit(str(exc)) from exc
            print(
                json.dumps(
                    infrastructure_event_to_schema(event),
                    indent=2,
                    default=str,
                )
            )
        elif args.command == "infrastructure-correlate":
            execution = session.scalar(
                select(TestExecution)
                .where(TestExecution.id == args.execution)
                .options(
                    selectinload(TestExecution.run),
                    selectinload(TestExecution.failure),
                )
            )
            if execution is None:
                raise SystemExit("test execution not found")
            run = execution.run
            try:
                result = build_infrastructure_correlation(
                    session,
                    selected_execution=execution,
                    selected_run=run,
                    cutoff=run.started_at or run.created_at,
                    timezone_name=run.timezone or "UTC",
                    exclude_run_id=run.id,
                    strict_fingerprint=(
                        execution.failure.strict_fingerprint
                        if execution.failure is not None
                        else None
                    ),
                    event_kind=args.event_kind,
                    window_seconds=args.window_seconds,
                    minimum_support=args.minimum_support,
                    persist=True,
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            print(json.dumps(result, indent=2, default=str))
        elif args.command == "performance":
            run = session.get(Run, args.run)
            if run is None:
                raise SystemExit("run not found")
            project = session.get(Project, run.project_id)
            if project is None:
                raise SystemExit("project not found")
            if args.policy:
                policy = session.get(PerformancePolicy, args.policy)
                if policy is None or policy.project_id != project.id:
                    raise SystemExit("performance policy not found in project")
            else:
                policy = ensure_default_performance_policy(session, project)
            try:
                comparisons = create_run_performance_comparisons(
                    session,
                    run,
                    policy,
                    observation_ids=args.observation,
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            print(
                json.dumps(
                    [
                        performance_comparison_to_schema(item).model_dump(mode="json")
                        for item in comparisons
                    ],
                    indent=2,
                    default=str,
                )
            )
        elif args.command == "publish-github":
            run = session.get(Run, args.run)
            if not run or run.repository != args.repository:
                raise SystemExit("run not found or repository does not match trusted destination")
            project = session.get(Project, run.project_id)
            analyses = list(session.scalars(select(Analysis).join(Failure).where(Failure.run_id == run.id)).all())
            publisher = None
            try:
                publisher = GitHubPublisher(os.environ.get("FAILURELENS_GITHUB_TOKEN", ""), bot_login=args.bot_login)
                receipt = publisher.publish(repository=args.repository, pull_number=args.pull_number,
                    project=project.slug, tested_head=run.commit_sha, report=report_snapshot(session, run)["markdown"])
                print(json.dumps(asdict(receipt)))
            except PublicationError as exc:
                raise SystemExit(str(exc)) from None
            finally:
                if publisher:
                    publisher.close()
        elif args.command == "report":
            run = session.get(Run, args.run)
            if not run:
                raise SystemExit("run not found")
            snapshot = report_snapshot(session, run)
            if args.format == "markdown":
                print(snapshot["markdown"], end="")
            else:
                print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()
