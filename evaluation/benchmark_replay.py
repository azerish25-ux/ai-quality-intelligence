"""Replay public benchmark inputs through the actual API, worker and publication gate.

No labels, family IDs, splits, generator or scoring modules are imported. Prior
reviews are explicit synthetic historical events submitted through the real API.
The chronology test uses actual ingestion ordering, not fabricated past timestamps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend/src"))
from evaluation.benchmark_contract import load_inputs, read_input
from evaluation.replay import install_label_read_guard

SUBSTANTIVE = (
    "category",
    "severity",
    "confidence",
    "summary",
    "claims",
    "policy_flags",
    "abstention_reason",
    "supporting_evidence_ids",
    "contradictory_evidence_ids",
)


def substantive_hash(value):
    return hashlib.sha256(
        json.dumps({k: value[k] for k in SUBSTANTIVE}, sort_keys=True).encode()
    ).hexdigest()


def replay(inputs: Path, output: Path, *, case_ids: set[str] | None = None, repeats=5):
    inputs, output = inputs.resolve(), output.resolve()
    if repeats != 5:
        raise ValueError("The frozen benchmark contract requires five repetitions")
    if output.exists() or output.is_relative_to(inputs.parent):
        raise ValueError("Replay output must be new and outside the corpus")
    manifest = load_inputs(inputs)
    if case_ids and not case_ids <= {c.case_id for c in manifest.cases}:
        raise ValueError("Requested case is absent from the public manifest")
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT,
            text=True,
        ).strip()
    )
    install_label_read_guard(inputs)
    from failurelens import models as m
    from failurelens.analysis import analyze_failure
    from failurelens.api import app
    from failurelens.config import get_settings
    from failurelens.db import SessionLocal, engine, initialize_database
    from failurelens.evidence_validation import (
        validate_evidence_records,
        validated_evidence_views,
    )
    from failurelens.github_report import render_markdown
    from failurelens.history import history_context_for_failure
    from failurelens.jobs import process_next
    from failurelens.service import select_failure_evidence
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    settings = get_settings()
    if not settings.demo_mode:
        raise ValueError(
            "Replay requires an explicit disposable synthetic-demo environment"
        )
    initialize_database()
    with SessionLocal() as session:
        if session.scalar(select(func.count()).select_from(m.Project)):
            raise ValueError(
                "Existing projects are never overwritten by benchmark replay"
            )
    output.mkdir(parents=True)
    rows = []
    started = time.perf_counter()
    network_attempts = []
    # Preserve PostgreSQL transport where configured. A complete OS-level network
    # sandbox is not claimed; SQLite replay can deny all socket connects.
    original_connect = socket.socket.connect

    def deny_connect(sock, address):
        network_attempts.append(str(address))
        raise PermissionError("Benchmark inference network egress is disabled")

    network_denied = engine.dialect.name == "sqlite"
    if network_denied:
        socket.socket.connect = deny_connect
    try:
        with TestClient(app) as client:

            def request(method, path, status=200, **kwargs):
                response = client.request(method, path, **kwargs)
                if response.status_code != status:
                    raise RuntimeError(
                        f"{method} {path}: expected {status}, got {response.status_code}: {response.text[:500]}"
                    )
                return response

            for case in manifest.cases:
                if case_ids and case.case_id not in case_ids:
                    continue
                begin = time.perf_counter()
                project = request(
                    "POST",
                    "/api/v1/projects",
                    201,
                    json={
                        "slug": "bench-" + case.case_id,
                        "name": "Controlled benchmark observations",
                    },
                ).json()
                ingestions = []

                def ingest(ref, *, case=case, project=project, ingestions=ingestions):
                    ingestion_started = time.perf_counter()
                    data = read_input(inputs, ref)
                    params = {
                        "external_id": ref.path,
                        "filename": "bundle.zip"
                        if ref.source_format == "failurelens-bundle-v2"
                        else "report.xml",
                        "repository": case.repository,
                        "commit_sha": case.source_revision,
                        "branch": "evaluation",
                        "run_scope": "full_suite",
                        "expected_inputs": ref.expected_inputs,
                        "source_format": ref.source_format,
                        "environment": "controlled-benchmark",
                        "timezone": "UTC",
                    }
                    route = f"/api/v1/projects/{project['id']}/ingestions"
                    headers = {
                        "content-type": "application/zip"
                        if ref.source_format == "failurelens-bundle-v2"
                        else "application/xml"
                    }
                    queued = request(
                        "POST", route, 202, params=params, content=data, headers=headers
                    ).json()
                    with SessionLocal() as worker:
                        if not process_next(
                            worker, "benchmark-worker", settings=settings
                        ):
                            raise RuntimeError("Durable ingestion was not claimed")
                    state = request("GET", "/api/v1/ingestions/" + queued["id"]).json()
                    if state["state"] != "succeeded":
                        raise RuntimeError(f"Ingestion did not succeed: {state}")
                    duplicate = request(
                        "POST", route, 202, params=params, content=data, headers=headers
                    ).json()
                    if duplicate["id"] != queued["id"]:
                        raise RuntimeError("Replay was not idempotent")
                    failures = request(
                        "GET", f"/api/v1/runs/{state['run_id']}/failures"
                    ).json()
                    ingestions.append(
                        {
                            "path": ref.path,
                            "sha256": ref.sha256,
                            "run_id": state["run_id"],
                            "idempotent": True,
                            "failure_count": len(failures),
                            "wall_seconds": time.perf_counter() - ingestion_started,
                        }
                    )
                    return state["run_id"], failures

                prior_events = []
                for prior in case.prior:
                    run_id, failures = ingest(prior.artifact)
                    if prior.review_reason:
                        if len(failures) != 1:
                            raise RuntimeError(
                                "A prior review must refer to one actual prior failure"
                            )
                        analysis_id = failures[0]["latest_analysis"]["analysis_id"]
                        event = request(
                            "POST",
                            f"/api/v1/analyses/{analysis_id}/reviews",
                            201,
                            json={
                                "decision": "category_correction",
                                "proposed_category": "known_flake",
                                "reason": prior.review_reason,
                                "expected_version": 0,
                            },
                        ).json()
                        prior_events.append(event)
                run_id, failures = ingest(case.current)
                if len(failures) != 1:
                    raise RuntimeError(
                        "Each current benchmark input must contain one failed observation"
                    )
                failure = failures[0]
                published = request(
                    "GET",
                    "/api/v1/analyses/" + failure["latest_analysis"]["analysis_id"],
                ).json()
                hashes = [substantive_hash(published)]
                for _ in range(repeats - 1):
                    again = request(
                        "POST", f"/api/v1/failures/{failure['id']}/analyses", 201
                    ).json()
                    hashes.append(substantive_hash(again))
                if len(set(hashes)) != 1:
                    raise RuntimeError(
                        "Substantive deterministic results changed across repetitions"
                    )
                evidence = []
                with SessionLocal() as session:
                    row = session.get(m.Failure, failure["id"])
                    erows = select_failure_evidence(session, row)
                    checks = validate_evidence_records(row, erows, settings=settings)
                    views = validated_evidence_views(erows, checks)
                    history = history_context_for_failure(session, row)
                    details = {
                        **row.execution.details,
                        "retry_recovered": row.execution.retry_recovered,
                        "incomplete_run": row.run.completeness != "complete",
                    }
                    modes = {}
                    attempted = {}
                    for mode, context in (
                        ("rules_only", {}),
                        ("rules_with_history", history),
                    ):
                        decision = analyze_failure(
                            message=row.message,
                            exception_type=row.exception_type,
                            details=details,
                            evidence=views,
                            historical=context,
                        )
                        modes[mode] = decision.category.value
                        attempted[mode] = {
                            "category": decision.category.value,
                            "claims": list(decision.claims),
                            "policy_flags": list(decision.policy_flags),
                        }
                    modes["full_deterministic"] = published["category"]
                    # Precommitted transparent baseline, not derived from current labels.
                    modes["constant_product_baseline"] = "product_defect"
                    for ev in erows:
                        if ev.id not in checks.accepted_ids:
                            continue
                        data = request(
                            "GET",
                            f"/api/v1/artifact-derivatives/{ev.derivative_id}/content",
                        ).content
                        if hashlib.sha256(data).hexdigest() != ev.content_digest:
                            raise RuntimeError("Authorized derivative digest mismatch")
                        path = (
                            output / "safe-evidence" / case.case_id / (ev.id + ".json")
                        )
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(data)
                        evidence.append(
                            {
                                "id": ev.id,
                                "project_id": ev.project_id,
                                "run_id": ev.run_id,
                                "execution_id": ev.execution_id,
                                "artifact_digest": ev.artifact.digest,
                                "kind": ev.kind,
                                "path": str(path.relative_to(output)),
                                "sha256": ev.content_digest,
                                "excerpt": ev.excerpt,
                                "locator": ev.locator,
                            }
                        )
                    analysis_rows = list(
                        session.scalars(
                            select(m.Analysis).where(m.Analysis.failure_id == row.id)
                        )
                    )
                    report = render_markdown(row.run, analysis_rows)
                    target = output / "reports" / (case.case_id + ".md")
                    target.parent.mkdir(exist_ok=True)
                    target.write_text(report)
                    history_before = history.get("history_input_digest")
                    execution_id = row.execution_id
                control_failures = None
                if case.control:
                    _, controls = ingest(case.control)
                    control_failures = len(controls)
                if case.later:
                    ingest(case.later)
                with SessionLocal() as session:
                    after = history_context_for_failure(
                        session, session.get(m.Failure, failure["id"])
                    )
                temporal_unchanged = after.get("history_input_digest") == history_before
                if not temporal_unchanged:
                    raise RuntimeError(
                        "Later observations leaked into prior-only context"
                    )
                post_later = request(
                    "POST", f"/api/v1/failures/{failure['id']}/analyses", 201
                ).json()
                if substantive_hash(post_later) != hashes[0]:
                    raise RuntimeError("Later runs changed a historical investigation")
                rows.append(
                    {
                        "case_id": case.case_id,
                        "project_id": project["id"],
                        "run_id": run_id,
                        "execution_id": execution_id,
                        "ingestions": ingestions,
                        "prior_reviews": prior_events,
                        "control_failures": control_failures,
                        "published": published,
                        "modes": modes,
                        "attempted": attempted,
                        "repeat_digests": hashes,
                        "evidence": evidence,
                        "integrity": checks.as_dict(),
                        "history": history,
                        "temporal_unchanged": temporal_unchanged,
                        "later_probe": case.later is not None,
                        "advisory_hold": "HOLD_FOR_REVIEW" in report,
                        "report": str(target.relative_to(output)),
                        "seconds": time.perf_counter() - begin,
                    }
                )
                print(
                    json.dumps({"completed": len(rows), "case_id": case.case_id}),
                    flush=True,
                )
    finally:
        if network_denied:
            socket.socket.connect = original_connect
    result = {
        "schema_version": "benchmark-replay-v1",
        "source_revision": revision,
        "source_dirty": dirty,
        "input_manifest_sha256": hashlib.sha256(
            (inputs / "manifest.json").read_bytes()
        ).hexdigest(),
        "database_dialect": engine.dialect.name,
        "repeats": repeats,
        "case_count": len(rows),
        "cases": rows,
        "wall_seconds": time.perf_counter() - started,
        "external_model_requests": 0,
        "compute_cost": None,
        "network_connect_denied": network_denied,
        "network_attempt_count": len(network_attempts),
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if sys.platform == "darwin" else 1024),
        "isolation": "Process-local label-read guard; SQLite socket-connect denial where available; not an OS sandbox.",
        "temporal_scope": "Real ingestion/review ordering with later-run exclusion; not a historical calendar-time production backtest.",
    }
    (output / "predictions.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--case-ids",
        default="",
        help="Optional comma-separated opaque IDs supplied by a separate evaluation driver",
    )
    parser.add_argument(
        "--confirm-disposable-database", action="store_true", required=True
    )
    args = parser.parse_args()
    result = replay(
        args.inputs,
        args.output,
        case_ids=set(filter(None, args.case_ids.split(","))) or None,
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "case_count",
                    "database_dialect",
                    "source_revision",
                    "wall_seconds",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
