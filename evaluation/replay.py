"""Replay only public artifacts through the real API, leased worker and publication validator.

Run in an explicit disposable database. Never import the generator or open labels.
The calling evaluator scores the resulting predictions in a separate process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT))
from evaluation.artifact_contract import load_manifest, read_artifact


def install_label_read_guard(inputs: Path) -> None:
    """A process-local tripwire against accidental label loading; not an OS sandbox."""
    corpus_root = inputs.resolve().parent

    def audit(event: str, args: tuple) -> None:
        if event != "open" or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(args[0])).resolve()
        if path.is_relative_to(corpus_root) and not path.is_relative_to(
            inputs.resolve()
        ):
            raise PermissionError(
                "Inference may read only the public input view, never evaluation labels/provenance"
            )

    sys.addaudithook(audit)


def replay(inputs: Path, output: Path, repeats: int = 5) -> dict:
    if not 1 <= repeats <= 10:
        raise ValueError("repeats outside resource policy")
    inputs, output = inputs.resolve(), output.resolve()
    if output.is_relative_to(inputs.parent):
        raise ValueError("prediction output must be outside the label/corpus directory")
    if output.exists() and any(output.iterdir()):
        raise ValueError("refusing to replace previous predictions")
    manifest = load_manifest(inputs)
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
            "replay requires an isolated, explicitly enabled synthetic-demo database"
        )
    initialize_database()
    with SessionLocal() as session:
        if session.scalar(select(func.count()).select_from(m.Project)):
            raise ValueError(
                "replay requires an empty disposable database; existing projects are never overwritten"
            )
    output.mkdir(parents=True, exist_ok=True)
    predictions = []
    begin = time.perf_counter()
    with TestClient(app) as client:

        def request(method: str, url: str, status: int = 200, **kwargs):
            response = client.request(method, url, **kwargs)
            if response.status_code != status:
                raise RuntimeError(
                    f"API {method} {url} returned {response.status_code}, expected {status}: {response.text[:1000]}"
                )
            return response

        for case in manifest.cases:
            started = time.perf_counter()
            project = request(
                "POST",
                "/api/v1/projects",
                201,
                json={
                    "slug": "eval-" + case.case_id,
                    "name": "Controlled artifact replay",
                },
            ).json()
            result = {
                "case_id": case.case_id,
                "inputs": [],
                "analyses": [],
                "evidence": [],
                "ablation_categories": {},
            }
            if manifest.schema_version == "artifact-replay-v2":
                result["role_analyses"] = {}
                result["run_links"] = {}
                result["repeat_digests"] = {}
            for ordinal, artifact in enumerate(case.inputs):
                content = read_artifact(inputs, artifact)
                params = {
                    "external_id": case.case_id + "-" + str(ordinal),
                    "filename": "bundle.zip"
                    if artifact.source_format == "failurelens-bundle-v2"
                    else "report.xml",
                    "repository": case.repository,
                    "commit_sha": case.source_revision,
                    "branch": "evaluation",
                    "run_scope": "full_suite",
                    "expected_inputs": artifact.expected_inputs,
                    "source_format": artifact.source_format,
                    "environment": "controlled-http-database-measurement"
                    if manifest.schema_version == "artifact-replay-v2"
                    else "controlled-component-measurement",
                }
                path = f"/api/v1/projects/{project['id']}/ingestions"
                queued = request(
                    "POST",
                    path,
                    202,
                    params=params,
                    content=content,
                    headers={
                        "content-type": "application/zip"
                        if artifact.source_format == "failurelens-bundle-v2"
                        else "application/xml"
                    },
                ).json()
                with SessionLocal() as worker:
                    if not process_next(
                        worker, "artifact-replay-worker", settings=settings
                    ):
                        raise RuntimeError("ingestion job was not claimed")
                state = request("GET", f"/api/v1/ingestions/{queued['id']}").json()
                if state["state"] != "succeeded":
                    raise RuntimeError(
                        f"artifact ingestion did not complete: {state['state']}"
                    )
                duplicate = request(
                    "POST",
                    path,
                    202,
                    params=params,
                    content=content,
                    headers={
                        "content-type": "application/zip"
                        if artifact.source_format == "failurelens-bundle-v2"
                        else "application/xml"
                    },
                ).json()
                if duplicate["id"] != queued["id"]:
                    raise RuntimeError("identical ingestion was not idempotent")
                run_id = state["run_id"]
                failures = request("GET", f"/api/v1/runs/{run_id}/failures").json()
                if manifest.schema_version == "artifact-replay-v2":
                    run = request("GET", f"/api/v1/runs/{run_id}").json()["run"]
                    if (
                        run["completeness"] != "complete"
                        or run["received_inputs"] != artifact.expected_inputs
                    ):
                        raise RuntimeError("multi-artifact run is incomplete")
                    result["role_analyses"][artifact.role] = []
                    result["run_links"][artifact.role] = run_id
                result["inputs"].append(
                    {
                        "role": artifact.role,
                        "sha256": artifact.sha256,
                        "state": state["state"],
                        "failure_count": len(failures),
                        "idempotent_replay": True,
                    }
                )
                for failure in failures:
                    published = request(
                        "GET",
                        "/api/v1/analyses/" + failure["latest_analysis"]["analysis_id"],
                    ).json()
                    substantive = {
                        k: published[k]
                        for k in (
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
                    }
                    repetition_hashes = [
                        hashlib.sha256(
                            json.dumps(substantive, sort_keys=True).encode()
                        ).hexdigest()
                    ]
                    for _ in range(repeats - 1):
                        again = request(
                            "POST", f"/api/v1/failures/{failure['id']}/analyses", 201
                        ).json()
                        if {k: again[k] for k in substantive} != substantive:
                            raise RuntimeError(
                                "substantive deterministic analysis changed during replay"
                            )
                        repetition_hashes.append(
                            hashlib.sha256(
                                json.dumps(
                                    {k: again[k] for k in substantive}, sort_keys=True
                                ).encode()
                            ).hexdigest()
                        )
                    result["analyses"].append(published)
                    if manifest.schema_version == "artifact-replay-v2":
                        result["role_analyses"][artifact.role].append(published)
                        result["repeat_digests"].setdefault(artifact.role, []).append(
                            repetition_hashes
                        )
                    with SessionLocal() as session:
                        row = session.get(m.Failure, failure["id"])
                        evidence_rows = select_failure_evidence(session, row)
                        checked = validate_evidence_records(
                            row, evidence_rows, settings=settings
                        )
                        views = validated_evidence_views(evidence_rows, checked)
                        details = {
                            **row.execution.details,
                            "retry_recovered": row.execution.retry_recovered,
                            "incomplete_run": row.run.completeness != "complete",
                        }
                        for mode, historical in (
                            ("rules_only", {}),
                            (
                                "rules_with_history",
                                history_context_for_failure(session, row),
                            ),
                        ):
                            decision = analyze_failure(
                                message=row.message,
                                exception_type=row.exception_type,
                                details=details,
                                evidence=views,
                                historical=historical,
                            )
                            result["ablation_categories"][mode] = (
                                decision.category.value
                            )
                        result["ablation_categories"]["full_deterministic"] = published[
                            "category"
                        ]
                        result["integrity_checks"] = checked.as_dict()
                        for ev in evidence_rows:
                            if ev.id not in checked.accepted_ids:
                                continue
                            safe = request("GET", f"/api/v1/evidence/{ev.id}").json()
                            derivative = request(
                                "GET",
                                f"/api/v1/artifact-derivatives/{ev.derivative_id}/content",
                            ).content
                            if (
                                hashlib.sha256(derivative).hexdigest()
                                != ev.content_digest
                            ):
                                raise RuntimeError(
                                    "authorized downloaded derivative digest mismatch"
                                )
                            target = (
                                output
                                / "safe-evidence"
                                / case.case_id
                                / (ev.id + ".json")
                            )
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(derivative)
                            result["evidence"].append(
                                {
                                    "id": ev.id,
                                    "path": str(target.relative_to(output)),
                                    "sha256": ev.content_digest,
                                    "excerpt": safe["excerpt"],
                                    "locator": safe["locator"],
                                }
                            )
                        analyses = list(
                            session.scalars(
                                select(m.Analysis).where(
                                    m.Analysis.failure_id == row.id
                                )
                            )
                        )
                        markdown = render_markdown(row.run, analyses)
                        report = (
                            output
                            / "reports"
                            / (
                                case.case_id
                                + (
                                    "-" + artifact.role
                                    if manifest.schema_version == "artifact-replay-v2"
                                    else ""
                                )
                                + ".md"
                            )
                        )
                        report.parent.mkdir(parents=True, exist_ok=True)
                        report.write_text(markdown)
                        result["report"] = str(report.relative_to(output))
                        result["advisory_hold"] = "HOLD_FOR_REVIEW" in markdown
            result["repeat_count"] = repeats
            result["seconds"] = time.perf_counter() - started
            predictions.append(result)
    value = {
        "schema_version": "artifact-replay-result-v1",
        "database_dialect": engine.dialect.name,
        "repeats": repeats,
        "input_manifest_sha256": hashlib.sha256(
            (inputs / "manifest.json").read_bytes()
        ).hexdigest(),
        "case_count": len(predictions),
        "wall_seconds": time.perf_counter() - begin,
        "inference_view": "strict public artifact manifest; process-local label-read tripwire; no generator imports",
        "label_guard_scope": "Python open audit tripwire, not an OS sandbox",
        "cases": predictions,
    }
    (output / "predictions.json").write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n"
    )
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--confirm-disposable-database", action="store_true", required=True
    )
    args = parser.parse_args()
    result = replay(args.inputs, args.output, args.repeats)
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("case_count", "database_dialect", "repeats", "wall_seconds")
            }
        )
    )


if __name__ == "__main__":
    main()
