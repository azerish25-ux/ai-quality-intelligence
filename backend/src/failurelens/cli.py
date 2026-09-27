from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path

from sqlalchemy import select

from .api import app  # noqa: F401
from .config import get_settings
from .db import SessionLocal, initialize_database
from .demo import seed_demo
from .github_report import render_markdown
from .impact import create_impact_recommendation, impact_recommendation_to_schema
from .jobs import process_next
from .models import Analysis, Failure, Ingestion, PerformancePolicy, Project, Run
from .performance import (
    create_run_performance_comparisons,
    ensure_default_performance_policy,
    performance_comparison_to_schema,
)
from .schemas import ImpactRecommendationCreate, RunMetadata
from .service import analyze_and_persist, create_project, enqueue_artifact_ingestion
from .storage import store_bytes


def main() -> None:
    parser = argparse.ArgumentParser(prog="failurelens")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("demo")

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

    args = parser.parse_args()
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
        elif args.command == "report":
            run = session.get(Run, args.run)
            if not run:
                raise SystemExit("run not found")
            analyses = session.scalars(select(Analysis).join(Failure).where(Failure.run_id == run.id)).all()
            if args.format == "markdown":
                print(render_markdown(run, list(analyses)), end="")
            else:
                print(
                    json.dumps(
                        {
                            "run_id": run.id,
                            "analyses": [
                                {
                                    "id": analysis.id,
                                    "category": analysis.category.value,
                                    "summary": analysis.summary,
                                }
                                for analysis in analyses
                            ],
                        },
                        indent=2,
                    )
                )


if __name__ == "__main__":
    main()
