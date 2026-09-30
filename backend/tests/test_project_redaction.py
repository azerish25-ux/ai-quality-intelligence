"""Synthetic privacy/correlation regressions; no real credentials or provider calls."""
from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import threading
import zipfile

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from failurelens.config import Settings, get_settings
from failurelens.evidence_validation import validate_evidence_records
from failurelens.ingestion import _safe_json_value, parse_artifact
from failurelens.jobs import process_next
from failurelens.models import Artifact, ArtifactDerivative, Evidence, Failure, Ingestion, RunInput
from failurelens.redaction import (
    REDACTION_VERSION, RedactionContext, current_redaction_context, redact_sensitive_field,
    redact_text, redaction_provenance, redaction_scope,
)
from failurelens.redaction_keys import (
    KEY_FILE, MARKER_FILE, PRIVATE_DIRECTORY, KeyMaterial, RedactionKeyError, load_key,
)
from failurelens.schemas import IngestionRequest, RunMetadata, TestObservation as Observation
from failurelens.service import (
    create_project, enqueue_artifact_ingestion, ingest_normalized, process_artifact_ingestion,
    select_failure_evidence,
)
from failurelens.storage import StorageError, read_stored_bytes, store_bytes

EMAIL = "synthetic.person@example.invalid"


def context(project="project-a", material=b"synthetic-test-key-32-bytes-only!!", reference="test-v1"):
    return RedactionContext.from_key(project, KeyMaterial(reference, "operator", material))


def settings_for(root, *, active=None, keys=None):
    return Settings(artifact_root=root, redaction_active_key_ref=active,
                    redaction_keyring=SecretStr(json.dumps({k: base64.b64encode(v).decode()
                                                           for k, v in keys.items()})) if keys else None)


def _ingest(session, project, external_id, *, message=None, details=None, source_metadata=None):
    run = ingest_normalized(session, project, IngestionRequest(
        external_id=external_id, source_metadata=source_metadata or {},
        observations=[Observation(test_identity="synthetic::case", outcome="failed",
                                  message=message or f"assertion failed; contact {EMAIL}",
                                  details=details or {})]))
    evidence = session.scalar(select(Evidence).where(Evidence.run_id == run.id))
    return run, evidence


def test_project_keyed_values_are_deterministic_distinct_and_not_plain_hashes():
    values = []
    for ctx in [context(), context(), context("project-b"), context(material=b"x"*32), context(reference="test-v2")]:
        with redaction_scope(ctx):
            token = redact_text(EMAIL).text
            assert redact_sensitive_field("customer_email", EMAIL).text == token
            assert redact_text(token).text == token
            assert redaction_provenance()["preexisting_markers"] is False
            values.append(token)
    assert values[0] == values[1]
    assert len(set(values)) == 4
    assert hashlib.sha256(EMAIL.encode()).hexdigest()[:10] not in values[0]
    assert EMAIL not in values[0] and ":hmac-v3:" in values[0]


def test_direct_no_context_parsing_suppresses_without_a_sensitive_value_digest(tmp_path):
    assert current_redaction_context() is None
    safe = redact_text(EMAIL).text
    assert safe == "[REDACTED:email:unscoped]"
    assert hashlib.sha256(EMAIL.encode()).hexdigest()[:10] not in safe
    xml = f'<testsuite><testcase name="case"><failure message="{EMAIL}"/></testcase></testsuite>'.encode()
    parsed = parse_artifact(xml, "report.xml", settings_for(tmp_path))
    assert EMAIL not in parsed.observations[0].evidence_excerpt
    assert parsed.inputs[0].metadata["redaction_policy"]["correlation_scope"] == "none"
    assert not (tmp_path / PRIVATE_DIRECTORY).exists()


def test_legacy_and_preexisting_markers_are_preserved_and_labeled():
    legacy = "[REDACTED:email:0123456789]"
    with redaction_scope(context()):
        assert redact_text(legacy).text == legacy
        assert redact_sensitive_field("customer_email", legacy).text == legacy
        assert redaction_provenance()["legacy_unscoped_markers"] is True
        assert redaction_provenance()["preexisting_markers"] is True
    with redaction_scope(context()):
        generated = redact_text(EMAIL).text
    with redaction_scope(context("project-b")):
        assert redact_text(generated).text == generated
        assert redaction_provenance()["preexisting_markers"] is True
        assert redaction_provenance()["legacy_unscoped_markers"] is False


def test_transactions_amounts_and_statuses_remain_distinct():
    with redaction_scope(context()):
        first = redact_sensitive_field("transaction_id", "1234567890").text
        second = redact_sensitive_field("transaction_id", "1234567891").text
        assert first != second
        safe = redact_text("transaction_id=1234567890; transaction_id=1234567891; amount=1000000000; expected_amount=1000000001; status=409").text
        assert first in safe and second in safe
        assert "amount=1000000000" in safe and "expected_amount=1000000001" in safe
        assert "status=409" in safe
        structured = _safe_json_value({"amount": "1000000000", "response_status": 409,
                                      "phone": "1234567890", "customer_email": EMAIL})
        assert structured["amount"] == "1000000000" and structured["response_status"] == 409
        assert structured["phone"] != "1234567890" and EMAIL not in structured["customer_email"]


def test_sensitive_long_values_do_not_collapse_shared_prefix():
    with redaction_scope(context()):
        first = redact_sensitive_field("session_id", "a"*5000 + "1").text
        second = redact_sensitive_field("session_id", "a"*5000 + "2").text
        assert first != second


def test_thread_nested_and_exception_context_isolation():
    barrier = threading.Barrier(2)
    def run(project):
        with redaction_scope(context(project)):
            barrier.wait()
            value = redact_text(EMAIL).text
            with pytest.raises(RuntimeError):
                with redaction_scope(context("nested")):
                    assert redact_text(EMAIL).text != value
                    raise RuntimeError("synthetic")
            assert redact_text(EMAIL).text == value
        assert current_redaction_context() is None
        return value
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, project) for project in ("one", "two")]
        assert futures[0].result() != futures[1].result()
    assert current_redaction_context() is None


def test_local_key_concurrent_creation_permissions_and_restart(tmp_path):
    settings = settings_for(tmp_path / "artifacts")
    with ThreadPoolExecutor(max_workers=6) as pool:
        values = list(pool.map(lambda _: load_key(settings, allow_local_create=True), range(12)))
    assert len({key.reference for key in values}) == 1
    assert all(key.material == values[0].material for key in values)
    directory = settings.artifact_root / PRIVATE_DIRECTORY
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE((directory / KEY_FILE).stat().st_mode) == 0o600
    assert sorted(p.name for p in directory.iterdir()) == sorted([KEY_FILE, MARKER_FILE])
    with redaction_scope(RedactionContext.from_key("same-project", values[0])):
        expected = redact_text(EMAIL).text
    script = '''from pathlib import Path
import sys
from failurelens.config import Settings
from failurelens.redaction import RedactionContext, redaction_scope, redact_text
from failurelens.redaction_keys import load_key
with redaction_scope(RedactionContext.from_key("same-project", load_key(Settings(artifact_root=Path(sys.argv[1]))))):
 print(redact_text("synthetic.person@example.invalid").text)
'''
    completed = subprocess.run([sys.executable, "-c", script, str(settings.artifact_root)],
                               capture_output=True, text=True, check=True)
    assert completed.stdout.strip() == expected


@pytest.mark.parametrize("mutation", ["mode", "symlink", "oversize", "malformed", "marker", "missing"])
def test_private_key_storage_fails_closed(tmp_path, mutation):
    settings = settings_for(tmp_path / "artifacts")
    load_key(settings, allow_local_create=True)
    key_file = settings.artifact_root / PRIVATE_DIRECTORY / KEY_FILE
    if mutation == "mode":
        key_file.chmod(0o644)
    elif mutation == "symlink":
        other = tmp_path / "other"; key_file.rename(other); key_file.symlink_to(other)
    elif mutation == "oversize":
        key_file.write_bytes(b"x"*8193)
    elif mutation == "malformed":
        key_file.write_text("malformed synthetic key record")
    elif mutation == "marker":
        (key_file.parent / MARKER_FILE).write_text("mismatched-reference\n")
    else:
        key_file.unlink()
    with pytest.raises(RedactionKeyError):
        load_key(settings, allow_local_create=True)


def test_private_directory_symlink_and_unsafe_parent_fail_closed(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    other = tmp_path / "other"; other.mkdir(mode=0o700)
    (root / PRIVATE_DIRECTORY).symlink_to(other, target_is_directory=True)
    with pytest.raises(RedactionKeyError):
        load_key(settings_for(root), allow_local_create=True)
    (root / PRIVATE_DIRECTORY).unlink(); root.chmod(0o777)
    with pytest.raises(RedactionKeyError, match="permissions_unsafe"):
        load_key(settings_for(root), allow_local_create=True)


def test_keyring_secrets_excluded_and_retired_reference_never_falls_back(tmp_path):
    settings = settings_for(tmp_path, active="second", keys={"first": b"a"*32, "second": b"b"*32})
    assert load_key(settings).reference == "second"
    assert load_key(settings, expected_reference="first").reference == "first"
    assert "redaction_keyring" not in settings.model_dump()
    assert "redaction_keyring" not in repr(settings)
    assert base64.b64encode(b"b"*32).decode() not in repr(load_key(settings))
    with pytest.raises(RedactionKeyError, match="redaction_key_missing"):
        load_key(settings, expected_reference="retired", allow_local_create=True)
    assert not (tmp_path / PRIVATE_DIRECTORY).exists()


def test_private_state_is_not_readable_as_evidence_even_through_symlink(tmp_path):
    settings = settings_for(tmp_path / "artifacts")
    load_key(settings, allow_local_create=True)
    directory = settings.artifact_root / PRIVATE_DIRECTORY
    source_dir = settings.artifact_root / "sources"; source_dir.mkdir()
    (source_dir / "alias").symlink_to(directory / KEY_FILE)
    for relative in [f"{PRIVATE_DIRECTORY}/{KEY_FILE}", "sources/alias"]:
        with pytest.raises(StorageError, match="Private operational state"):
            read_stored_bytes(root=settings.artifact_root, relative_path=relative,
                              expected_digest="0"*64, expected_size=0, max_bytes=8192)


def test_normalized_determinism_project_isolation_and_provenance(session):
    a = create_project(session, "redaction-a", "Synthetic A")
    b = create_project(session, "redaction-b", "Synthetic B")
    run1, first = _ingest(session, a, "one", details={"customer_email": EMAIL, "amount": "1000000000"})
    _, second = _ingest(session, a, "two", details={"customer_email": EMAIL, "amount": "1000000000"})
    _, foreign = _ingest(session, b, "one")
    assert first.excerpt == second.excerpt and first.excerpt != foreign.excerpt
    assert first.observation["details"]["amount"] == "1000000000"
    assert first.observation["details"]["customer_email"] in first.excerpt
    content = (get_settings().artifact_root / first.derivative.storage_path).read_bytes()
    payload = json.loads(content)
    assert payload["redaction"] == first.derivative.metadata_json["redaction"]
    assert payload["redaction"]["project_id"] == a.id
    assert payload["redaction"]["key_ref"] == run1.source_metadata["redaction_policy"]["key_ref"]
    assert EMAIL.encode() not in content
    assert not any(key in payload["redaction"] for key in ("key", "material", "secret"))


def test_client_metadata_cannot_select_key_or_claim_project_provenance(session):
    project = create_project(session, "untrusted-policy", "Synthetic")
    forged = {"version": REDACTION_VERSION, "key_ref": "attacker", "project_id": "elsewhere"}
    run, evidence = _ingest(session, project, "normalized", source_metadata={"redaction_policy": forged})
    assert run.source_metadata["redaction_policy"]["key_ref"] != "attacker"
    assert evidence.derivative.metadata_json["redaction"]["project_id"] == project.id
    settings = get_settings()
    source = b'<testsuite><testcase name="case"/></testsuite>'
    stored = store_bytes(source, root=settings.artifact_root, project_id=project.id,
                         filename="report.xml", max_bytes=4096)
    queued = enqueue_artifact_ingestion(session, project, RunMetadata(
        external_id="raw", source_metadata={"redaction_policy": forged}), stored, settings=settings)
    assert queued.source_metadata["redaction_policy"]["key_ref"] != "attacker"
    assert queued.source_metadata["redaction_policy"]["project_id"] == project.id


def test_whole_directory_loss_and_db_only_restore_do_not_regenerate(session, monkeypatch, tmp_path):
    project = create_project(session, "lost-key", "Synthetic")
    _, evidence = _ingest(session, project, "before")
    path = get_settings().artifact_root / PRIVATE_DIRECTORY
    shutil.rmtree(path)
    with pytest.raises(RedactionKeyError, match="restore_required"):
        _ingest(session, project, "after")
    assert not path.exists()
    # Existing immutable evidence remains verifiable without any secret key.
    failure = session.scalar(select(Failure).where(Failure.run_id == evidence.run_id))
    assert validate_evidence_records(failure, [evidence]).accepted_ids == (evidence.id,)
    monkeypatch.setenv("FAILURELENS_ARTIFACT_ROOT", str(tmp_path / "db-only-restore"))
    get_settings.cache_clear()
    with pytest.raises(RedactionKeyError, match="restore_required"):
        _ingest(session, project, "restored")
    assert not (get_settings().artifact_root / PRIVATE_DIRECTORY).exists()


def test_rotation_pins_queued_work_and_old_citations_survive_retirement(session, monkeypatch):
    project = create_project(session, "rotation", "Synthetic")
    keys = {"first": base64.b64encode(b"a"*32).decode(), "second": base64.b64encode(b"b"*32).decode()}
    monkeypatch.setenv("FAILURELENS_REDACTION_KEYRING", json.dumps(keys))
    monkeypatch.setenv("FAILURELENS_REDACTION_ACTIVE_KEY_REF", "first"); get_settings.cache_clear()
    _, old = _ingest(session, project, "old")
    old_bytes = (get_settings().artifact_root / old.derivative.storage_path).read_bytes()
    xml = f'<testsuite><testcase name="case"><failure message="contact {EMAIL}"/></testcase></testsuite>'.encode()
    stored = store_bytes(xml, root=get_settings().artifact_root, project_id=project.id,
                         filename="report.xml", max_bytes=4096)
    queued = enqueue_artifact_ingestion(session, project, RunMetadata(external_id="queued"), stored)
    assert queued.source_metadata["redaction_policy"]["key_ref"] == "first"
    monkeypatch.setenv("FAILURELENS_REDACTION_ACTIVE_KEY_REF", "second"); get_settings.cache_clear()
    processed = process_artifact_ingestion(session, queued)
    processed_evidence = session.scalar(select(Evidence).where(Evidence.run_id == processed.id))
    assert processed_evidence.derivative.metadata_json["redaction"]["key_ref"] == "first"
    _, new = _ingest(session, project, "new")
    assert old.excerpt != new.excerpt
    assert new.derivative.metadata_json["redaction"]["key_ref"] == "second"
    monkeypatch.setenv("FAILURELENS_REDACTION_KEYRING", json.dumps({"second": keys["second"]})); get_settings.cache_clear()
    failure = session.scalar(select(Failure).where(Failure.run_id == old.run_id))
    assert validate_evidence_records(failure, [old]).accepted_ids == (old.id,)
    assert (get_settings().artifact_root / old.derivative.storage_path).read_bytes() == old_bytes
    with pytest.raises(RedactionKeyError, match="redaction_key_missing"):
        process_artifact_ingestion(session, queued)


def test_provenance_tampering_rejected_without_needing_old_key(session):
    project = create_project(session, "provenance", "Synthetic")
    _, evidence = _ingest(session, project, "one")
    failure = session.scalar(select(Failure).where(Failure.run_id == evidence.run_id))
    evidence.derivative.metadata_json = {**evidence.derivative.metadata_json,
        "redaction": {**evidence.derivative.metadata_json["redaction"], "key_ref": "forged"}}
    session.commit()
    result = validate_evidence_records(failure, [evidence])
    assert result.accepted_ids == ()
    assert "redaction_provenance_mismatch" in result.checks[0].reasons


def test_worker_parser_and_trace_share_project_context(client, session):
    project = client.post("/api/v1/projects", json={"slug": "parser-context", "name": "Synthetic"}).json()
    xml = f'<testsuite><testcase name="case"><failure message="contact {EMAIL}"/></testcase></testsuite>'.encode()
    trace = io.BytesIO()
    with zipfile.ZipFile(trace, "w") as archive:
        archive.writestr("trace.trace", "\n".join(json.dumps(item) for item in [
            {"type": "context-options", "version": 9, "playwrightVersion": "1.63.0"},
            {"type": "console", "text": f"contact {EMAIL}", "messageType": "error"}]))
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"schema_version": "2.0", "inputs": [
            {"id": "report", "path": "report.xml", "kind": "junit-xml", "required": True},
            {"id": "trace", "path": "trace.zip", "kind": "playwright-trace", "required": False}]}))
        archive.writestr("report.xml", xml); archive.writestr("trace.zip", trace.getvalue())
    response = client.post(f"/api/v1/projects/{project['id']}/ingestions",
        params={"external_id": "raw", "filename": "bundle.zip"}, content=bundle.getvalue(),
        headers={"content-type": "application/zip"})
    assert response.status_code == 202, response.text
    assert process_next(session, "privacy-worker", settings=get_settings())
    queued = session.get(Ingestion, response.json()["id"])
    assert queued.state.value == "succeeded", queued.error_message
    evidence = list(session.scalars(select(Evidence).where(Evidence.run_id == queued.run_id)))
    primary = next(e for e in evidence if e.kind == "current_run_observation")
    trace_event = next(e for e in evidence if e.kind == "trace_event")
    token = primary.excerpt.removeprefix("contact ")
    assert ":hmac-v3:" in token and token in trace_event.excerpt
    for row in session.scalars(select(ArtifactDerivative).where(ArtifactDerivative.run_id == queued.run_id)):
        content = (get_settings().artifact_root / row.storage_path).read_text()
        assert EMAIL not in content
        assert row.metadata_json["redaction"]["project_id"] == project["id"]
    for item in session.scalars(select(RunInput).where(RunInput.run_id == queued.run_id)):
        assert item.metadata_json["redaction_policy"]["key_ref"] == queued.source_metadata["redaction_policy"]["key_ref"]


def test_local_key_creation_is_atomic_across_processes(tmp_path):
    root = tmp_path / "shared-root"
    script = '''from pathlib import Path
import sys
from failurelens.config import Settings
from failurelens.redaction_keys import load_key
print(load_key(Settings(artifact_root=Path(sys.argv[1])), allow_local_create=True).reference)
'''
    processes = [subprocess.Popen([sys.executable, "-c", script, str(root)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(4)]
    outputs = []
    for process in processes:
        output, error = process.communicate(timeout=30)
        assert process.returncode == 0, error
        outputs.append(output.strip())
    assert len(set(outputs)) == 1


def test_normalized_source_metadata_and_manifest_metadata_are_redacted(session):
    project = create_project(session, "metadata-privacy", "Synthetic")
    run, _ = _ingest(session, project, "metadata", source_metadata={"customer_email": EMAIL, "password": "synthetic-secret"})
    assert EMAIL not in json.dumps(run.source_metadata)
    assert "synthetic-secret" not in json.dumps(run.source_metadata)
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"schema_version": "2.0", "inputs": [{
            "id": "report", "path": "report.xml", "kind": "junit-xml", "required": True,
            "metadata": {"customer_email": EMAIL, "password": "synthetic-secret"}}]}))
        archive.writestr("report.xml", b'<testsuite><testcase name="case"/></testsuite>')
    with redaction_scope(context(project.id)):
        parsed = parse_artifact(bundle.getvalue(), "bundle.zip", get_settings())
        metadata = parsed.inputs[0].metadata
        assert EMAIL not in json.dumps(metadata) and "synthetic-secret" not in json.dumps(metadata)
        assert ":hmac-v3:" in metadata["customer_email"]


def test_legacy_queue_client_policy_is_replaced_by_server_pin(session):
    project = create_project(session, "legacy-queue", "Synthetic")
    settings = get_settings()
    xml = b'<testsuite><testcase name="case"/></testsuite>'
    stored = store_bytes(xml, root=settings.artifact_root, project_id=project.id,
                         filename="report.xml", max_bytes=4096)
    queued = enqueue_artifact_ingestion(session, project, RunMetadata(external_id="legacy"), stored)
    queued.policy_version = "artifact-policy-v1"
    queued.source_metadata = {**queued.source_metadata, "redaction_policy": {
        **queued.source_metadata["redaction_policy"], "key_ref": "client-forged"}}
    session.commit()
    process_artifact_ingestion(session, queued)
    assert queued.policy_version == "artifact-policy-v2"
    assert queued.source_metadata["redaction_policy"]["key_ref"] != "client-forged"


def test_old_policy_derivative_remains_byte_compatible_and_verifiable(session):
    project = create_project(session, "legacy-citation", "Synthetic")
    _, evidence = _ingest(session, project, "current")
    derivative = evidence.derivative
    path = get_settings().artifact_root / derivative.storage_path
    payload = json.loads(path.read_bytes())
    payload["redaction"] = {"version": "redaction-v2", "classes": ["email"]}
    content = (json.dumps(payload, sort_keys=True) + "\n").encode()
    # A synthetic historical v2 record, never modification of an evaluation file.
    path.write_bytes(content)
    derivative.digest = evidence.content_digest = hashlib.sha256(content).hexdigest()
    derivative.size_bytes = len(content)
    derivative.redaction_version = evidence.redaction_version = "redaction-v2"
    derivative.metadata_json = {"redaction_classes": ["email"]}
    session.commit()
    failure = session.scalar(select(Failure).where(Failure.run_id == evidence.run_id))
    assert validate_evidence_records(failure, [evidence]).accepted_ids == (evidence.id,)
    assert path.read_bytes() == content


@pytest.mark.parametrize("raw,active", [
    ('not-json', 'one'),
    ('[]', 'one'),
    ('{"one":"x","one":"y"}', 'one'),
    (json.dumps({"one": "not base64"}), 'one'),
    (json.dumps({"one": base64.b64encode(b"short").decode()}), 'one'),
    (json.dumps({"one": base64.b64encode(b"a"*32).decode()}), 'absent'),
    (json.dumps({"local-v1-forged": base64.b64encode(b"a"*32).decode()}), 'local-v1-forged'),
])
def test_invalid_operator_keyring_errors_are_fixed_and_secret_free(tmp_path, raw, active):
    settings = Settings(artifact_root=tmp_path, redaction_keyring=SecretStr(raw), redaction_active_key_ref=active)
    with pytest.raises(RedactionKeyError) as error:
        load_key(settings, allow_local_create=True)
    assert str(error.value).startswith("redaction_")
    assert raw not in str(error.value)
    assert not (tmp_path / PRIVATE_DIRECTORY).exists()


def test_short_sensitive_fields_and_unicode_do_not_collapse():
    with redaction_scope(context()):
        assert "password=x" not in redact_text("password=x; status=409").text
        assert redact_text("session_id=1").text != redact_text("session_id=2").text
        assert redact_sensitive_field("session_id", "\ud800").text != redact_sensitive_field("session_id", "\ud801").text


def test_approved_content_endpoint_cannot_serve_private_key_path(client, session):
    project = create_project(session, "private-serving", "Synthetic")
    _, evidence = _ingest(session, project, "one")
    evidence.derivative.storage_path = f"{PRIVATE_DIRECTORY}/{KEY_FILE}"
    session.commit()
    response = client.get(f"/api/v1/artifact-derivatives/{evidence.derivative.id}/content")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "artifact_integrity_failed"
    assert "key_ref" not in response.text and "installation-key-v1" not in response.text


def test_new_queue_missing_or_forged_pin_fails_closed(session):
    project = create_project(session, "missing-pin", "Synthetic")
    settings = get_settings()
    source = b'<testsuite><testcase name="case"/></testsuite>'
    stored = store_bytes(source, root=settings.artifact_root, project_id=project.id,
                         filename="report.xml", max_bytes=4096)
    queued = enqueue_artifact_ingestion(session, project, RunMetadata(external_id="one"), stored)
    queued.source_metadata = {}
    session.commit()
    with pytest.raises(RedactionKeyError, match="pin_invalid"):
        process_artifact_ingestion(session, queued)


def test_database_and_full_artifact_backup_restore_preserves_correlation(session, monkeypatch, tmp_path):
    project = create_project(session, "backup-continuity", "Synthetic")
    _, original = _ingest(session, project, "before-backup")
    original_root = get_settings().artifact_root
    restored_root = tmp_path / "restored-artifacts"
    shutil.copytree(original_root, restored_root)
    monkeypatch.setenv("FAILURELENS_ARTIFACT_ROOT", str(restored_root)); get_settings.cache_clear()
    _, after = _ingest(session, project, "after-restore")
    assert after.excerpt == original.excerpt
    assert after.derivative.metadata_json["redaction"]["key_ref"] == original.derivative.metadata_json["redaction"]["key_ref"]
    failure = session.scalar(select(Failure).where(Failure.run_id == original.run_id))
    assert validate_evidence_records(failure, [original]).accepted_ids == (original.id,)
    assert stat.S_IMODE((restored_root / PRIVATE_DIRECTORY / KEY_FILE).stat().st_mode) == 0o600


def test_key_material_is_absent_from_evidence_and_api_serialization(client, session):
    project = create_project(session, "no-key-export", "Synthetic")
    _, evidence = _ingest(session, project, "one")
    key = load_key(get_settings())
    replies = [client.get(f"/api/v1/evidence/{evidence.id}"),
               client.get(f"/api/v1/artifact-derivatives/{evidence.derivative.id}/content"),
               client.get(f"/api/v1/runs/{evidence.run_id}")]
    assert all(reply.status_code == 200 for reply in replies)
    serialized = b"\n".join(reply.content for reply in replies)
    # Never put material in assertion messages, logs, or test artifacts.
    assert not any(value in serialized for value in (
        key.material, base64.b64encode(key.material), key.material.hex().encode()))


def test_preparsed_unscoped_tokens_are_not_claimed_as_upgraded_correlation(session):
    from failurelens.service import ingest_parsed_report
    project = create_project(session, "preparsed", "Synthetic")
    source = f'<testsuite><testcase name="case"><failure message="{EMAIL}"/></testcase></testsuite>'.encode()
    parsed = parse_artifact(source, "report.xml", get_settings())
    unscoped = parsed.observations[0].evidence_excerpt
    run = ingest_parsed_report(session, project, RunMetadata(external_id="one"), parsed.observations,
        source_name="report.xml", source_digest=hashlib.sha256(source).hexdigest(),
        source_size_bytes=len(source), storage_path="db://synthetic-preparsed", media_type="application/xml",
        source_format=parsed.source_format, parser_version=parsed.parser_version, input_records=parsed.inputs)
    evidence = session.scalar(select(Evidence).where(Evidence.run_id == run.id))
    item = session.scalar(select(RunInput).where(RunInput.run_id == run.id))
    assert evidence.excerpt == unscoped
    assert evidence.derivative.metadata_json["redaction"]["legacy_unscoped_markers"] is True
    assert item.metadata_json["redaction_policy"]["legacy_unscoped_markers"] is True


@pytest.mark.parametrize("source,canary", [
    ("[REDACTED:email:person@example.invalid]", "person@example.invalid"),
    ("[REDACTED:api_key:private-secret-canary]", "private-secret-canary"),
    ("[REDACTED:email:opaque-sensitive-canary]", "opaque-sensitive-canary"),
    ("[REDACTED:session:truncated-canary", "truncated-canary"),
    ("[redacted:phone:wrapped-canary]", "wrapped-canary"),
    ("[REDACTED:api_key:[nested]nested-secret-canary]", "nested-secret-canary"),
])
def test_malformed_marker_wrappers_never_bypass_redaction(session, source, canary):
    assert canary not in redact_text(source).text
    assert canary not in redact_sensitive_field("customer_email", source).text
    with redaction_scope(context()):
        assert canary not in redact_text(source).text
        assert canary not in redact_sensitive_field("access_token", source).text
    project = create_project(session, "marker-bypass", "Synthetic")
    _, evidence = _ingest(session, project, "one", message=source, details={"customer_email": source})
    content = (get_settings().artifact_root / evidence.derivative.storage_path).read_text()
    assert canary not in content
    assert "[REDACTED:" in evidence.excerpt


def test_key_lock_wait_is_bounded_with_real_holder_process(tmp_path, monkeypatch):
    import time
    import failurelens.redaction_keys as key_module
    settings = settings_for(tmp_path / "artifacts")
    load_key(settings, allow_local_create=True)
    directory = settings.artifact_root / PRIVATE_DIRECTORY
    script = '''import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY)
fcntl.flock(fd, fcntl.LOCK_EX)
print("locked", flush=True)
sys.stdin.readline()
os.close(fd)
'''
    holder = subprocess.Popen([sys.executable, "-c", script, str(directory)], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "locked"
        monkeypatch.setattr(key_module, "KEY_LOCK_TIMEOUT_SECONDS", 0.1)
        started = time.monotonic()
        with pytest.raises(RedactionKeyError, match="redaction_key_storage_busy"):
            load_key(settings)
        assert time.monotonic() - started < 2
    finally:
        holder.communicate("release\n", timeout=5)
    assert holder.returncode == 0
    assert load_key(settings).source == "local"


def test_crash_after_atomic_link_is_fail_closed_without_regeneration(tmp_path):
    settings = settings_for(tmp_path / "artifacts")
    script = '''import os, sys
from pathlib import Path
from failurelens.config import Settings
from failurelens.redaction_keys import load_key
# Simulate process death after complete key publication but before temp unlink.
def interrupted_unlink(*args, **kwargs):
 os._exit(23)
os.unlink = interrupted_unlink
load_key(Settings(artifact_root=Path(sys.argv[1])), allow_local_create=True)
'''
    result = subprocess.run([sys.executable, "-c", script, str(settings.artifact_root)],
                            capture_output=True, timeout=30)
    assert result.returncode == 23
    key_file = settings.artifact_root / PRIVATE_DIRECTORY / KEY_FILE
    before = key_file.stat()
    assert before.st_nlink == 2
    with pytest.raises(RedactionKeyError, match="redaction_key_permissions_unsafe"):
        load_key(settings, allow_local_create=True)
    after = key_file.stat()
    assert after.st_ino == before.st_ino and after.st_nlink == 2
    assert not (key_file.parent / MARKER_FILE).exists()
