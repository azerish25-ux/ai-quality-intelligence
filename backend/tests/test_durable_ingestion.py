from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from failurelens.config import get_settings
from failurelens.jobs import claim_next, process_claimed, process_next
from failurelens.models import (
    Analysis,
    Artifact,
    Evidence,
    Ingestion,
    IngestionState,
    Job,
    JobState,
    Run,
    RunInput,
)
from failurelens.schemas import RunMetadata
from failurelens.service import create_project, enqueue_artifact_ingestion
from failurelens.storage import store_bytes


def _project(client) -> str:
    response = client.post(
        "/api/v1/projects",
        json={"slug": "durable-project", "name": "Durable Project"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_raw_junit_is_queued_processed_and_auto_analyzed(client, session) -> None:
    project_id = _project(client)
    junit = b'''<testsuite name="payments" tests="2"><testcase classname="Transfer" name="duplicate" time="0.03"><failure type="LedgerInvariantError" message="duplicate committed transfer">ledger unbalanced after double charge</failure></testcase><testcase classname="Health" name="ok" time="0.01"/></testsuite>'''
    response = client.post(
        f"/api/v1/projects/{project_id}/ingestions",
        params={
            "external_id": "gha-100",
            "filename": "junit.xml",
            "repository": "owner/repo",
            "commit_sha": "abcdef0",
            "expected_inputs": 1,
        },
        content=junit,
        headers={"content-type": "application/xml"},
    )
    assert response.status_code == 202, response.text
    queued = response.json()
    assert queued["state"] == "queued"
    assert queued["run_id"] is None

    assert process_next(session, "worker-a", settings=get_settings()) is True
    completed = client.get(f"/api/v1/ingestions/{queued['id']}").json()
    assert completed["state"] == "succeeded"
    assert completed["run_id"]
    assert completed["received_inputs"] == 1

    failures = client.get(f"/api/v1/runs/{completed['run_id']}/failures").json()
    assert len(failures) == 1
    assert failures[0]["latest_analysis"]["category"] == "product_defect"
    assert failures[0]["latest_analysis"]["supporting_evidence_ids"]

    artifact = session.scalar(select(Artifact).where(Artifact.run_id == completed["run_id"]))
    assert artifact is not None and artifact.restricted is True
    evidence = session.scalar(select(Evidence).where(Evidence.run_id == completed["run_id"]))
    assert evidence is not None and len(evidence.content_digest) == 64

    duplicate = client.post(
        f"/api/v1/projects/{project_id}/ingestions",
        params={
            "external_id": "gha-100",
            "filename": "junit.xml",
            "repository": "owner/repo",
            "commit_sha": "abcdef0",
            "expected_inputs": 1,
        },
        content=junit,
        headers={"content-type": "application/xml"},
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["id"] == queued["id"]
    assert session.scalar(select(func.count(Run.id))) == 1


def test_playwright_report_preserves_attempts_and_auto_analysis(client, session) -> None:
    project_id = _project(client)
    report = {
        "suites": [
            {
                "title": "checkout",
                "specs": [
                    {
                        "title": "creates one payment",
                        "file": "tests/checkout.spec.ts",
                        "tests": [
                            {
                                "projectName": "chromium",
                                "results": [
                                    {
                                        "status": "failed",
                                        "duration": 20,
                                        "error": {
                                            "name": "LedgerInvariantError",
                                            "message": "duplicate committed payment caused balance invariant violation",
                                        },
                                    },
                                    {"status": "passed", "duration": 8},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    response = client.post(
        f"/api/v1/projects/{project_id}/ingestions",
        params={"external_id": "pw-1", "filename": "playwright-report.json", "expected_inputs": 1},
        content=json.dumps(report).encode(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 202
    ingestion_id = response.json()["id"]
    process_next(session, "worker-pw", settings=get_settings())
    completed = client.get(f"/api/v1/ingestions/{ingestion_id}").json()
    assert completed["state"] == "succeeded"
    failures = client.get(f"/api/v1/runs/{completed['run_id']}/failures").json()
    assert failures[0]["latest_analysis"] is not None


def test_expired_lease_recovery_is_idempotent(session) -> None:
    settings = get_settings()
    project = create_project(session, "lease-project", "Lease Project")
    content = b'<testsuite><testcase name="duplicate"><failure type="Error">duplicate committed ledger unbalanced</failure></testcase></testsuite>'
    stored = store_bytes(
        content,
        root=settings.artifact_root,
        project_id=project.id,
        filename="lease.xml",
        media_type="application/xml",
        max_bytes=settings.max_file_bytes,
    )
    ingestion = enqueue_artifact_ingestion(
        session,
        project,
        RunMetadata(external_id="lease-1", expected_inputs=1),
        stored,
        settings=settings,
    )
    first = claim_next(session, "worker-dead", 30)
    assert first is not None
    first.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()

    recovered = claim_next(session, "worker-recovered", 30)
    assert recovered is not None and recovered.id == first.id and recovered.attempts == 2
    process_claimed(session, recovered, "worker-recovered", settings)
    session.refresh(ingestion)
    first_run_id = ingestion.run_id
    assert first_run_id
    assert session.scalar(select(func.count(Analysis.id))) == 1

    recovered.state = JobState.running
    recovered.lease_owner = "worker-died-after-publish"
    recovered.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    ingestion.state = IngestionState.running
    ingestion.completed_at = None
    session.commit()
    replay = claim_next(session, "worker-final", 30)
    assert replay is not None and replay.id == recovered.id
    process_claimed(session, replay, "worker-final", settings)
    session.refresh(ingestion)
    assert ingestion.run_id == first_run_id
    assert session.scalar(select(func.count(Run.id))) == 1
    assert session.scalar(select(func.count(Analysis.id))) == 1


def test_malformed_report_fails_permanently_with_diagnostics(client, session) -> None:
    project_id = _project(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/ingestions",
        params={"external_id": "bad-1", "filename": "report.json"},
        content=b'{"suites":',
        headers={"content-type": "application/json-report"},
    )
    ingestion_id = response.json()["id"]
    process_next(session, "worker-bad", settings=get_settings())
    result = client.get(f"/api/v1/ingestions/{ingestion_id}").json()
    assert result["state"] == "failed"
    assert result["error_code"] == "malformed_report"
    job = session.get(Job, result["job_id"])
    assert job is not None and job.state is JobState.dead_lettered
    assert result["run_id"] is None


def test_cancellation_is_terminal_and_worker_failure_cannot_resurrect_it(client, session) -> None:
    project_id = _project(client)
    response = client.post(
        f"/api/v1/projects/{project_id}/ingestions",
        params={"external_id": "cancel-1", "filename": "junit.xml"},
        content=b'<testsuite><testcase name="late"/></testsuite>',
        headers={"content-type": "application/xml"},
    )
    queued = response.json()
    claimed = claim_next(session, "worker-cancel", 30)
    assert claimed is not None

    cancelled = client.post(f"/api/v1/ingestions/{queued['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"

    from failurelens.jobs import fail

    current = session.get(Job, claimed.id)
    assert current is not None and current.state is JobState.cancelled
    fail(session, current, "job lease is no longer owned by this worker")
    session.refresh(current)
    ingestion = session.get(Ingestion, queued["id"])
    assert current.state is JobState.cancelled
    assert ingestion is not None and ingestion.state is IngestionState.cancelled
    assert ingestion.run_id is None


def test_duplicate_digest_with_conflicting_provenance_is_rejected(client) -> None:
    project_id = _project(client)
    content = b'<testsuite><testcase name="ok"/></testsuite>'
    first = client.post(
        f"/api/v1/projects/{project_id}/ingestions",
        params={
            "external_id": "same-run",
            "filename": "junit.xml",
            "commit_sha": "abcdef0",
        },
        content=content,
        headers={"content-type": "application/xml"},
    )
    assert first.status_code == 202
    conflict = client.post(
        f"/api/v1/projects/{project_id}/ingestions",
        params={
            "external_id": "same-run",
            "filename": "junit.xml",
            "commit_sha": "1234567",
        },
        content=content,
        headers={"content-type": "application/xml"},
    )
    assert conflict.status_code == 409
    assert "idempotency conflict" in conflict.text


def test_same_report_bytes_are_distinct_across_run_attempts(client) -> None:
    project_id = _project(client)
    content = b'<testsuite><testcase name="ok"/></testsuite>'
    ids = []
    for attempt in (1, 2):
        response = client.post(
            f"/api/v1/projects/{project_id}/ingestions",
            params={
                "external_id": "rerun",
                "attempt": attempt,
                "filename": "junit.xml",
            },
            content=content,
            headers={"content-type": "application/xml"},
        )
        assert response.status_code == 202
        ids.append(response.json()["id"])
    assert ids[0] != ids[1]



def test_manifest_v2_persists_input_scope_and_missing_required_artifacts(client, session) -> None:
    project_id = _project(client)
    manifest = {
        "schema_version": "2.0",
        "inputs": [
            {
                "id": "tests",
                "kind": "junit-xml",
                "path": "reports/junit.xml",
                "required": True,
                "role": "primary",
            },
            {
                "id": "changes",
                "kind": "changed-files",
                "path": "metadata/changes.json",
                "required": False,
            },
            {
                "id": "expected-screenshot",
                "kind": "screenshot",
                "path": "screenshots/expected.png",
                "required": True,
            },
        ],
    }
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr(
            "reports/junit.xml",
            '<testsuite><testcase name="duplicate"><failure type="LedgerInvariantError">ledger unbalanced after duplicate committed transfer</failure></testcase></testsuite>',
        )
        archive.writestr(
            "metadata/changes.json",
            json.dumps(
                {
                    "base_sha": "abcdef0",
                    "head_sha": "1234567",
                    "complete": True,
                    "files": [{"status": "modified", "path": "src/ledger.py"}],
                }
            ),
        )

    response = client.post(
        f"/api/v1/projects/{project_id}/ingestions",
        params={"external_id": "manifest-v2", "filename": "failurelens-bundle.zip"},
        content=bundle.getvalue(),
        headers={"content-type": "application/zip"},
    )
    assert response.status_code == 202, response.text
    ingestion_id = response.json()["id"]
    assert process_next(session, "worker-manifest", settings=get_settings()) is True

    completed = client.get(f"/api/v1/ingestions/{ingestion_id}").json()
    assert completed["state"] == "partial"
    assert completed["expected_inputs"] == 2
    assert completed["received_inputs"] == 1

    run = client.get(f"/api/v1/runs/{completed['run_id']}").json()["run"]
    assert run["completeness"] == "partial"
    assert run["source_metadata"]["observation_count"] == 1
    assert run["source_metadata"]["manifest_version"] == "2.0"

    inputs = client.get(f"/api/v1/runs/{completed['run_id']}/inputs").json()
    by_id = {item["input_id"]: item for item in inputs}
    assert by_id["tests"]["status"] == "accepted"
    assert by_id["changes"]["status"] == "accepted"
    assert by_id["expected-screenshot"]["status"] == "missing"
    assert by_id["expected-screenshot"]["warnings"] == ["missing_attachment"]
    assert session.scalar(select(func.count(RunInput.id))) == 3
