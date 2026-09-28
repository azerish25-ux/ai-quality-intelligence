"""Unit/security fixtures are synthetic, not executed-producer provenance."""
from __future__ import annotations

import hashlib
import io
import json
import struct
import zipfile
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin
from sqlalchemy import select

from failurelens import models as m
from failurelens.auth import create_user, create_auth_session, DEMO_PRINCIPAL
from failurelens.binary_api import _range
from failurelens.config import Settings, get_settings
from failurelens.image_codec import ImageCodecError, decode_image
from failurelens.ingestion import IngestionError, parse_artifact
from failurelens.jobs import process_next
from failurelens.retention import _scrub_run, flush_deletions


def image_bytes(size=(32, 24), fmt="PNG", *, orientation=None):
    image = Image.new("RGB", size, (231, 173, 97))
    image.putpixel((size[0] - 1, size[1] - 1), (10, 90, 255))
    out = io.BytesIO()
    kwargs = {}
    if fmt == "PNG":
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Comment", "private-person@example.com metadata must be discarded")
        kwargs["pnginfo"] = metadata
    if orientation is not None:
        exif = Image.Exif()
        exif[274] = orientation
        kwargs["exif"] = exif
    image.save(out, format=fmt, **kwargs)
    return out.getvalue()


def trace_bytes(*, version=9, producer="1.63.0", extra=None, count=1):
    rows = [{"type": "context-options", "version": version, "playwrightVersion": producer}]
    rows.extend({"type": "before", "callId": f"call@{i}", "apiName": "page.click", "startTime": i,
                 "params": {"expression": "document.cookie", "password": "NEVER_COPY_SCRIPT"}} for i in range(count))
    rows.append({"type": "console", "messageType": "error", "text": "contact private-person@example.com"})
    rows.append({"type": "after", "callId": "call@0", "error": {"message": "selector failed"}})
    rows.extend(extra or [])
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("trace.trace", "\n".join(json.dumps(row) for row in rows) + "\n")
        archive.writestr("trace.network", json.dumps({"type": "resource-snapshot", "snapshot": {
            "request": {"method": "GET", "url": "https://user:password@example.com/route?token=NEVER_COPY_TOKEN",
                        "headers": [{"name": "Cookie", "value": "NEVER_COPY_COOKIE"}]},
            "response": {"status": 503, "content": {"text": "NEVER_COPY_BODY"}}, "time": 42}}) + "\n")
        archive.writestr("resources/private.html", "<script>NEVER_COPY_SCRIPT</script>")
    return out.getvalue()


def bundle_bytes(*, trace=True, missing=False, metadata=None, ambiguous=False):
    shots = {"expected.png": image_bytes(), "actual.png": image_bytes()}
    attachments = [{"name": path, "path": path, "contentType": "image/png"} for path in shots]
    if trace:
        shots["trace.zip"] = trace_bytes()
        attachments.append({"name": "trace", "path": "trace.zip", "contentType": "application/zip"})
    test = {"testId": "checkout", "projectName": "chromium", "results": [{"status": "failed", "retry": 0,
        "duration": 15, "error": {"name": "Error", "message": "selector missing"}, "attachments": attachments}]}
    tests = [test] if not ambiguous else [test, {**test, "testId": "other-checkout"}]
    report = {"suites": [{"title": "checkout", "specs": [{"title": "checkout", "file": "checkout.spec.ts", "tests": tests}]}]}
    context = {"browser": "chromium", "os": "linux", "viewport_width": 32, "viewport_height": 24,
               "device_scale_factor": 1, "comparison_group": "checkout-first-attempt"}
    inputs = [{"id": "report", "path": "report.json", "kind": "playwright-json", "required": True}]
    for path in shots:
        details = {"relationship": "expected" if path == "expected.png" else "actual", "comparison_context": context}
        details.update(metadata or {})
        inputs.append({"id": path, "path": path, "kind": "playwright-trace" if path.endswith("zip") else "screenshot",
                       "required": True, "metadata": details})
    if missing:
        inputs.append({"id": "missing", "path": "missing.png", "kind": "screenshot", "required": True,
                       "metadata": {"relationship": [], "width": {"bad": True}, "height": [], "coordinate_system": 3}})
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", json.dumps({"schema_version": "2.0", "inputs": inputs}))
        archive.writestr("report.json", json.dumps(report))
        for path, content in shots.items():
            archive.writestr(path, content)
    return out.getvalue(), shots


def ingest(client, session, **kwargs):
    project = client.post("/api/v1/projects", json={"slug": "binary", "name": "Binary evidence"})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    bundle, shots = bundle_bytes(**kwargs)
    response = client.post(f"/api/v1/projects/{project_id}/ingestions",
        params={"external_id": "binary-test", "filename": "evidence.zip"}, content=bundle,
        headers={"content-type": "application/zip"})
    assert response.status_code == 202, response.text
    assert process_next(session, "binary-worker", settings=get_settings())
    finished = client.get(f"/api/v1/ingestions/{response.json()['id']}").json()
    assert finished["state"] == "partial", finished
    run_id = finished["run_id"]
    response = client.get(f"/api/v1/runs/{run_id}/binary-evidence")
    assert response.status_code == 200, response.text
    items = {item["manifest_input_id"]: item for item in response.json()["items"]}
    return project_id, run_id, items, shots


def review(client, item, content, *, version=None, masks=None, headers=None):
    options = {"expected_version": item["version"] if version is None else version,
               "confirm_safe": True, "reason": "Verified and masked sensitive pixels", "masks": masks or []}
    return client.post(f"/api/v1/binary-evidence/{item['input_id']}/screenshot-reviews",
        content=json.dumps(options).encode() + b"\n" + content,
        headers={"content-type": "application/vnd.failurelens.image-review", **(headers or {})})


def user_headers(session, project_id=None, role=m.ProjectRole.viewer, username="test-viewer"):
    user = create_user(session, username=username, display_name=username,
                       password="correct-horse-battery-staple")
    if project_id:
        session.add(m.ProjectMembership(project_id=project_id, user_id=user.id, role=role))
    _, token = create_auth_session(session, user, settings=get_settings())
    session.commit()
    return {"Authorization": f"Bearer {token}"}


def test_actual_pixels_masked_metadata_removed_and_original_never_published(client, session):
    project_id, run_id, items, shots = ingest(client, session)
    actual = items["actual.png"]
    assert actual["state"] == "restricted" and actual["derivative"] is None
    assert actual["execution_id"] and actual["correlation"] == "report_attachment"
    response = review(client, actual, shots["actual.png"], masks=[{"x": 0, "y": 0, "width": 16, "height": 12}])
    assert response.status_code == 201, response.text
    approved = response.json()
    assert approved["version"] == 1 and approved["source_status"] == "restricted"
    assert approved["decisions"][0]["actor_display"] == "Synthetic demo administrator"
    derivative = approved["derivative"]
    content = client.get(f"/api/v1/artifact-derivatives/{derivative['id']}/content")
    assert content.status_code == 200, content.text
    assert content.headers["x-content-type-options"] == "nosniff"
    assert set(content.headers["cache-control"].split(", ")) == {"private", "no-store"}
    assert hashlib.sha256(content.content).hexdigest() == derivative["digest"]
    with Image.open(io.BytesIO(content.content)) as masked:
        assert masked.getpixel((0, 0)) == (0, 0, 0)
        assert masked.getpixel((15, 11)) == (0, 0, 0)
        assert masked.getpixel((16, 12)) == (231, 173, 97)
        assert not masked.info
    assert b"private-person" not in content.content
    source = session.scalar(select(m.Ingestion).where(m.Ingestion.run_id == run_id))
    assert source.source_expired_at is not None
    assert not (get_settings().artifact_root / source.storage_path).exists()
    assert session.get(m.Run, run_id).completeness == "partial"
    artifact = session.get(m.Artifact, session.get(m.ArtifactDerivative, derivative["id"]).artifact_id)
    assert artifact.restricted is True
    assert "storage_path" not in json.dumps(approved)


def test_trace_index_precise_safe_paginated_and_not_classifier_outcome(client, session):
    _, run_id, items, _ = ingest(client, session)
    item = items["trace.zip"]
    assert item["state"] == "safe_index_available"
    response = client.get(f"/api/v1/binary-evidence/{item['input_id']}/trace-events?limit=1&offset=1")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["total"] == 4 and len(result["events"]) == 1
    event = result["events"][0]
    assert event["index"] == 1 and event["pointer"] == "/events/1"
    assert event["source_locator"]["line"] == 3
    assert len(event["source_locator"]["entry_digest"]) == 64
    assert event["source_locator"]["source_digest"] == item["source_digest"]
    assert event["evidence_id"] and event["evidence_digest"]
    entire = client.get(f"/api/v1/artifact-derivatives/{item['derivative']['id']}/content").text
    for private in ("NEVER_COPY", "private-person", "document.cookie", "user:password"):
        assert private not in entire
    source_input = session.get(m.RunInput, item["input_id"])
    assert "events" not in source_input.metadata_json
    from failurelens.service import select_failure_evidence
    failure = session.scalar(select(m.Failure).where(m.Failure.run_id == run_id))
    assert all(e.provenance_kind != "supplemental_trace" for e in select_failure_evidence(session, failure))


def test_reviews_are_versioned_digest_bound_and_revocation_closes_old_urls(client, session):
    _, _, items, shots = ingest(client, session, trace=False)
    item = items["actual.png"]
    wrong = review(client, item, image_bytes((31, 24)))
    assert wrong.status_code == 409 and wrong.json()["detail"]["code"] == "source_digest_mismatch"
    first = review(client, item, shots["actual.png"])
    assert first.status_code == 201, first.text
    approved = first.json()
    assert review(client, item, shots["actual.png"]).status_code == 409
    second = review(client, approved, shots["actual.png"], masks=[{"x": 0, "y": 0, "width": 1, "height": 1}])
    assert second.status_code == 201, second.text
    assert second.json()["derivative"]["id"] != approved["derivative"]["id"]
    original_derivative = session.get(m.ArtifactDerivative, approved["derivative"]["id"])
    assert original_derivative.source_map["masks"] == []
    decision = client.post(f"/api/v1/binary-evidence/{item['input_id']}/decisions",
        json={"expected_version": 2, "decision": "revoke", "reason": "Found an unmasked sensitive field"})
    assert decision.status_code == 200, decision.text
    for derivative in (approved["derivative"], second.json()["derivative"]):
        assert client.get(f"/api/v1/artifact-derivatives/{derivative['id']}/content").status_code == 403
    third = review(client, decision.json(), shots["actual.png"])
    assert third.status_code == 201, third.text
    assert third.json()["derivative"]["id"] not in {approved["derivative"]["id"], second.json()["derivative"]["id"]}
    assert client.get(f"/api/v1/artifact-derivatives/{approved['derivative']['id']}/content").status_code == 403
    assert third.json()["decisions_total"] == 4


def test_authorization_on_read_upload_decision_and_trace_guessed_ids(client, session):
    project_id, run_id, items, shots = ingest(client, session)
    item = items["actual.png"]
    approved = review(client, item, shots["actual.png"]).json()
    viewer = user_headers(session, project_id)
    outsider = user_headers(session, username="outsider")
    urls = [f"/api/v1/runs/{run_id}/binary-evidence", f"/api/v1/binary-evidence/{item['input_id']}",
            f"/api/v1/artifact-derivatives/{approved['derivative']['id']}/content",
            f"/api/v1/binary-evidence/{items['trace.zip']['input_id']}/trace-events"]
    for url in urls:
        assert client.get(url, headers=viewer).status_code == 200
        assert client.get(url, headers=outsider).status_code == 404
    assert review(client, item, shots["actual.png"], headers=viewer).status_code == 403
    assert review(client, item, shots["actual.png"], headers=outsider).status_code == 404
    assert client.post(f"/api/v1/binary-evidence/{item['input_id']}/decisions", headers=viewer,
        json={"decision": "revoke", "expected_version": 1, "reason": "Viewer must not make decisions"}).status_code == 403


def test_missing_input_review_cannot_revoke_sibling_text_evidence(client, session):
    _, run_id, items, shots = ingest(client, session, missing=True)
    assert items["missing"]["state"] == "missing" and items["missing"]["width"] is None
    before = list(session.scalars(select(m.ArtifactDerivative).where(m.ArtifactDerivative.run_id == run_id)))
    assert before and all(row.approved for row in before)
    missing_id = items["missing"]["input_id"]
    assert client.post(f"/api/v1/binary-evidence/{missing_id}/decisions", json={"decision": "revoke",
        "expected_version": 0, "reason": "Missing input cannot revoke its parent"}).status_code == 409
    assert all(row.approved for row in before)
    assert review(client, items["missing"], shots["actual.png"]).status_code == 409


def test_integrity_scope_expiry_and_content_ranges(client, session):
    _, run_id, items, shots = ingest(client, session, trace=False)
    approved = review(client, items["actual.png"], shots["actual.png"]).json()
    derivative = session.get(m.ArtifactDerivative, approved["derivative"]["id"])
    url = f"/api/v1/artifact-derivatives/{derivative.id}/content"
    full = client.get(url).content
    partial = client.get(url, headers={"Range": "bytes=0-7"})
    assert partial.status_code == 206 and partial.content == full[:8]
    assert partial.headers["content-range"] == f"bytes 0-7/{len(full)}"
    assert client.get(url, headers={"Range": "bytes=-8"}).content == full[-8:]
    assert client.get(url, headers={"Range": "bytes=0-1,5-9"}).status_code == 416
    assert client.get(url, headers={"Range": "bytes=" + "9" * 5000 + "-"}).status_code == 416
    assert client.get(url + "?preview=true").headers["content-type"] == "image/png"
    assert "attachment" in client.get(url + "?download=true").headers["content-disposition"]
    original_path = derivative.storage_path
    derivative.storage_path = original_path.replace(derivative.project_id, "other-project")
    session.commit()
    assert client.get(url).status_code == 409
    derivative.storage_path = original_path
    session.commit()
    path = get_settings().artifact_root / original_path
    path.write_bytes(b"x" * len(full))
    assert client.get(url).status_code == 409
    path.write_bytes(full)
    run = session.get(m.Run, run_id)
    _scrub_run(session, run, 1)
    session.commit()
    flush_deletions(session, run.project_id, get_settings())
    assert client.get(url).status_code == 410
    assert client.get(f"/api/v1/binary-evidence/{items['actual.png']['input_id']}").status_code == 410
    listing = client.get(f"/api/v1/runs/{run_id}/binary-evidence").json()
    assert all(item["state"] == "expired" for item in listing["items"])
    assert not path.exists()
    decision = session.scalar(select(m.BinaryEvidenceDecision))
    assert not decision.masks and "Verified and masked" not in decision.reason


def test_comparison_requires_same_approved_execution_and_compatible_environment(client, session):
    _, _, items, shots = ingest(client, session, trace=False)
    approved = {name: review(client, item, shots[name]).json() for name, item in items.items()}
    request = {"expected_derivative_id": approved["expected.png"]["derivative"]["id"],
               "actual_derivative_id": approved["actual.png"]["derivative"]["id"]}
    response = client.post("/api/v1/image-comparisons", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "COMPARABLE"
    assert response.json()["similarity"] == 1 and response.json()["hamming_distance"] == 0
    item = session.get(m.RunInput, items["actual.png"]["input_id"])
    item.metadata_json = {**item.metadata_json, "comparison_context": {**item.metadata_json["comparison_context"], "browser": "firefox"}}
    session.commit()
    assert client.post("/api/v1/image-comparisons", json=request).json()["status"] == "INCOMPATIBLE"
    item.metadata_json = {**item.metadata_json, "comparison_context": {}}
    session.commit()
    result = client.post("/api/v1/image-comparisons", json=request).json()
    assert result["status"] == "INSUFFICIENT_CONTEXT" and result["similarity"] is None


def test_ambiguous_attachment_is_not_assigned_to_arbitrary_execution(client, session):
    _, _, items, _ = ingest(client, session, trace=False, ambiguous=True)
    assert all(item["execution_id"] is None and item["correlation"] == "ambiguous" for item in items.values())


@pytest.mark.parametrize("content", [b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 2, 2),
    b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x02\x00\x02\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"])
def test_header_only_rasters_are_rejected(content):
    with pytest.raises(IngestionError) as error:
        parse_artifact(content, "image.png", get_settings(), source_format="screenshot")
    assert error.value.code == "malformed_report"


def test_decode_bounds_orientation_alpha_and_mask_validation():
    with pytest.raises(ImageCodecError, match="limit_exceeded"):
        decode_image(image_bytes(), Settings(max_image_pixels=100))
    metadata, encoded = decode_image(image_bytes((8, 4), "JPEG", orientation=6), get_settings(), encode=True)
    assert metadata["width"] == 4 and metadata["height"] == 8
    with Image.open(io.BytesIO(encoded)) as output:
        assert not output.getexif() and output.size == (4, 8)
    with pytest.raises(ImageCodecError, match="invalid_mask"):
        decode_image(image_bytes(), get_settings(), encode=True, masks=[{"x": 31, "y": 0, "width": 2, "height": 1}])
    hidden = Image.new("RGBA", (2, 2), (231, 3, 100, 0))
    buffer = io.BytesIO()
    hidden.save(buffer, format="PNG")
    _, flattened = decode_image(buffer.getvalue(), get_settings(), encode=True)
    with Image.open(io.BytesIO(flattened)) as output:
        assert output.mode == "RGB" and output.getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("version,producer,code", [(999999, "1.63.0", "unsupported_trace_version"),
    (True, "1.63.0", "unsupported_trace_version"), (9, "invented", "unsupported_trace_producer"),
    (9, {}, "unsupported_trace_producer")])
def test_trace_declared_version_rejected_explicitly(version, producer, code):
    with pytest.raises(IngestionError) as error:
        parse_artifact(trace_bytes(version=version, producer=producer), "trace.zip", get_settings(), source_format="playwright-trace")
    assert error.value.code == code


def test_trace_bounded_index_counts_omitted_events_without_hiding_errors():
    parsed = parse_artifact(trace_bytes(count=300), "trace.zip", get_settings(), source_format="playwright-trace")
    metadata = parsed.inputs[0].metadata
    assert metadata["indexed_events"] == 256 and metadata["omitted_index_events"] == 47
    assert metadata["error_event_count"] == 2
    assert metadata["event_count"] == 304 and metadata["truncated"] is True
    assert "trace_index_truncated" in parsed.inputs[0].warnings


@pytest.mark.parametrize("range_value,expected", [("bytes=0-2", (0, 2)), ("bytes=5-", (5, 9)),
    ("bytes=-2", (8, 9)), ("bytes=1-100", (1, 9))])
def test_single_byte_ranges(range_value, expected):
    assert _range(range_value, 10) == expected


def test_http_replay_of_discarded_binary_original_is_idempotent_and_conflicts_still_clean_up(client, session):
    project_id, _, _, _ = ingest(client, session)
    bundle, _ = bundle_bytes()
    # Source bytes are intentionally not retained. Capture a new external-ID
    # upload and replay that same buffer after durable processing.
    url = f"/api/v1/projects/{project_id}/ingestions"
    params = {"external_id": "replay-binary", "filename": "replay.zip"}
    queued = client.post(url, params=params, content=bundle, headers={"content-type": "application/zip"})
    assert queued.status_code == 202
    assert process_next(session, "replay-worker", settings=get_settings())
    result = queued.json()
    source = session.get(m.Ingestion, result["id"])
    assert source.source_expired_at is not None
    source_path = get_settings().artifact_root/source.storage_path
    assert not source_path.exists()
    replay = client.post(url, params=params, content=bundle, headers={"content-type": "application/zip"})
    assert replay.status_code == 202, replay.text
    assert replay.json()["id"] == result["id"] and replay.json()["state"] == "partial"
    assert not source_path.exists()
    conflict = client.post(url, params={**params, "branch": "changed"}, content=bundle,
                           headers={"content-type": "application/zip"})
    assert conflict.status_code == 409 and not source_path.exists()
    run = session.get(m.Run, source.run_id)
    _scrub_run(session, run, m.utcnow()); session.commit()
    expired = client.post(url, params=params, content=bundle, headers={"content-type": "application/zip"})
    assert expired.status_code == 409 and not source_path.exists()
