"""Mandatory CI conformance against actual executed producer output (not synthetic gold labels)."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

import pytest
from failurelens import models as m
from failurelens.config import get_settings
from failurelens.ingestion import parse_artifact
from failurelens.jobs import process_next
from sqlalchemy import select


def fixture_root() -> Path:
    path = Path(
        os.environ.get(
            "FAILURELENS_PRODUCER_FIXTURES",
            Path(__file__).parent / "fixtures/producers",
        )
    )
    assert (path / "provenance.json").is_file(), (
        "Generate the pinned fixtures with integrations/producer-fixtures/run.py or download the matching CI producer artifact; these tests must not silently skip."
    )
    return path


def test_executed_producer_provenance_has_verified_exits_oracles_and_digests():
    root = fixture_root()
    manifest = json.loads((root / "provenance.json").read_text())
    assert (
        manifest["source_kind"] == "other_executed"
        and manifest["ledgerguard_executions"] == 0
    )
    assert manifest["scope"] == "browser-python-java-k6"
    assert len(manifest["source_revision"]) == 40
    assert manifest["versions"]["playwright"] == "1.63.0"
    assert manifest["versions"]["pytest-json-report"] == "1.5.0"
    assert manifest["versions"]["rest-assured"] == "6.0.0"
    assert manifest["versions"]["k6_image"][0].startswith("grafana/k6@sha256:")
    for name, info in manifest["files"].items():
        file = root / name
        assert file.resolve().is_relative_to(root.resolve())
        assert file.stat().st_size == info["bytes"]
        assert hashlib.sha256(file.read_bytes()).hexdigest() == info["sha256"], name
    assert all(
        command["exit_code"] in command["expected_exit_codes"]
        for command in manifest["commands"]
    )
    assert manifest["oracles"]["playwright"]["unexpected"] == 1
    assert manifest["oracles"]["pytest"]["failed"] == 1


@pytest.mark.parametrize(
    "name,kind",
    [
        ("playwright.json", "playwright-json"),
        ("playwright.junit.xml", "junit-xml"),
        ("pytest.json", "pytest-json"),
        ("pytest.junit.xml", "junit-xml"),
        ("rest-assured.junit.xml", "junit-xml"),
        ("rest-assured.json", "rest-assured-evidence"),
        ("k6.json", "k6-summary"),
        ("console.txt", "console-text"),
        ("console.jsonl", "console-jsonl"),
        ("network.har", "har"),
        ("network.jsonl", "network-jsonl"),
        ("github.json", "github-metadata"),
        ("changes.json", "changed-files"),
    ],
)
def test_actual_pinned_export_is_accepted(name, kind):
    content = (fixture_root() / name).read_bytes()
    parsed = parse_artifact(content, name, get_settings(), source_format=kind)
    assert parsed.received_inputs == 1
    assert parsed.inputs[0].status == "accepted"
    if name in {
        "playwright.json",
        "playwright.junit.xml",
        "pytest.json",
        "pytest.junit.xml",
        "rest-assured.junit.xml",
    }:
        assert any(
            observation.outcome == "failed" for observation in parsed.observations
        )
        assert any(
            observation.outcome == "passed" for observation in parsed.observations
        )
    if name == "rest-assured.json":
        assert parsed.inputs[0].metadata["exchange_count"] == 2
        assert "503" in parsed.inputs[0].metadata["safe_preview"]
    if name == "k6.json":
        assert any(
            observation.details.get("threshold_name") == "rate==0"
            or "rate==0" in observation.test_identity
            for observation in parsed.observations
        )


def test_actual_playwright_binary_bundle_preserves_attempts_and_safe_event_locators():
    root = fixture_root()
    content = (root / "failurelens-bundle.zip").read_bytes()
    parsed = parse_artifact(content, "failurelens-bundle.zip", get_settings())
    assert parsed.completeness == "partial"
    assert not [
        item for item in parsed.inputs if item.status not in {"accepted", "restricted"}
    ], [(i.input_id, i.warnings) for i in parsed.inputs]
    screenshots = [item for item in parsed.inputs if item.kind == "screenshot"]
    traces = [item for item in parsed.inputs if item.kind == "playwright-trace"]
    assert len(screenshots) >= 4 and len(traces) >= 3
    assert all(
        item.metadata["width"] == 640 and item.metadata["height"] == 480
        for item in screenshots
    )
    assert {item.metadata["relationship"] for item in screenshots} == {
        "expected",
        "actual",
    }
    assert all(item.metadata["schema_versions"] == [9] for item in traces)
    assert any(item.metadata["error_event_count"] > 0 for item in traces)
    assert {observation.attempt for observation in parsed.observations} >= {0, 1}
    with zipfile.ZipFile(root / "failurelens-bundle.zip") as bundle:
        for item in traces:
            with zipfile.ZipFile(
                __import__("io").BytesIO(bundle.read(item.path))
            ) as trace:
                for event in item.metadata["events"]:
                    locator = event["source_locator"]
                    source = trace.read(trace.infolist()[locator["entry_index"]])
                    assert hashlib.sha256(source).hexdigest() == locator["entry_digest"]
                    assert locator["line"] <= len(source.splitlines())


def test_actual_producer_bundle_real_worker_review_trace_and_idempotent_replay(
    client, session
):
    root = fixture_root()
    project = client.post(
        "/api/v1/projects", json={"slug": "producer", "name": "Executed producers"}
    ).json()
    content = (root / "failurelens-bundle.zip").read_bytes()
    url = f"/api/v1/projects/{project['id']}/ingestions"
    params = {"external_id": "producer-regression", "filename": "producer.zip"}
    queued = client.post(
        url, params=params, content=content, headers={"content-type": "application/zip"}
    )
    assert queued.status_code == 202, queued.text
    assert process_next(session, "producer-worker", settings=get_settings())
    finished = client.get(f"/api/v1/ingestions/{queued.json()['id']}").json()
    assert finished["state"] == "partial", finished
    items = client.get(
        f"/api/v1/runs/{finished['run_id']}/binary-evidence?limit=100"
    ).json()["items"]
    assert all(
        item["execution_id"] and item["correlation"] == "report_attachment"
        for item in items
    )
    shot = next(
        item
        for item in items
        if item["kind"] == "screenshot" and item["relationship"] == "actual"
    )
    with zipfile.ZipFile(root / "failurelens-bundle.zip") as bundle:
        image = bundle.read(shot["path"])
    header = {
        "expected_version": 0,
        "confirm_safe": True,
        "reason": "Executed fixture privacy mask reviewed",
        "masks": [{"x": 0, "y": 0, "width": 640, "height": 130}],
    }
    approved = client.post(
        f"/api/v1/binary-evidence/{shot['input_id']}/screenshot-reviews",
        content=json.dumps(header).encode() + b"\n" + image,
        headers={"content-type": "application/vnd.failurelens.image-review"},
    )
    assert approved.status_code == 201, approved.text
    derivative = approved.json()["derivative"]
    assert (
        client.get(
            f"/api/v1/artifact-derivatives/{derivative['id']}/content"
        ).status_code
        == 200
    )
    trace = next(item for item in items if item["kind"] == "playwright-trace")
    assert client.get(
        f"/api/v1/binary-evidence/{trace['input_id']}/trace-events"
    ).json()["events"]
    duplicate = client.post(
        url, params=params, content=content, headers={"content-type": "application/zip"}
    )
    assert (
        duplicate.status_code == 202 and duplicate.json()["id"] == queued.json()["id"]
    )
    assert (
        len(
            list(
                session.scalars(select(m.Run).where(m.Run.project_id == project["id"]))
            )
        )
        == 1
    )
    ingestion = session.get(m.Ingestion, queued.json()["id"])
    assert not (get_settings().artifact_root / ingestion.storage_path).exists()
