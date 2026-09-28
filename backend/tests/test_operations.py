from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from failurelens import models as m, retention
from failurelens.auth import DEMO_PRINCIPAL, ensure_bootstrap_administrator, token_digest, verify_password
from failurelens.config import Settings, get_settings
from failurelens.governance import review_queue_page
from failurelens.github_report import render_markdown
from failurelens.jobs import claim_next, process_next
from failurelens.schemas import IngestionRequest, ReviewCreate
from failurelens.service import add_review, analyze_and_persist, create_project, ingest_normalized, retry_ingestion
from test_auth import _headers, _login, _membership, _run_with_analysis, _user

PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "new-strong-account-password"


def test_two_sessions_revoke_only_one_and_hide_hashes(client, session):
    user = _user(session, username="sessions", display_name="Session User")
    first, second = _login(client, user.username), _login(client, user.username)
    listed = client.get("/api/v1/auth/sessions", headers=_headers(first))
    assert listed.status_code == 200
    assert len(listed.json()) == 2
    current = next(row for row in listed.json() if row["current"])
    assert "token" not in listed.text and "hash" not in listed.text
    assert "no-store" in listed.headers["cache-control"]
    assert client.post(f"/api/v1/auth/sessions/{current['id']}/revoke", headers=_headers(first)).status_code == 204
    assert client.get("/api/v1/auth/me", headers=_headers(first)).status_code == 401
    assert client.get("/api/v1/auth/me", headers=_headers(second)).status_code == 200


def test_session_owner_is_enforced(client, session):
    alice = _user(session, username="alice", display_name="Alice")
    bob = _user(session, username="bob", display_name="Bob")
    alice_token = _login(client, alice.username)
    alice_session = session.scalar(select(m.AuthSession).where(m.AuthSession.user_id == alice.id))
    bob_token = _login(client, bob.username)
    assert client.post(f"/api/v1/auth/sessions/{alice_session.id}/revoke", headers=_headers(bob_token)).status_code == 404
    assert client.get(f"/api/v1/users/{alice.id}/sessions", headers=_headers(bob_token)).status_code == 403
    assert client.get("/api/v1/auth/me", headers=_headers(alice_token)).status_code == 200


def test_password_change_reauthenticates_rotates_and_revokes(client, session):
    user = _user(session, username="change", display_name="Password User")
    first, second = _login(client, user.username), _login(client, user.username)
    wrong = client.post("/api/v1/auth/password", headers=_headers(second),
        json={"current_password": "wrong", "new_password": NEW_PASSWORD})
    assert wrong.status_code == 401
    good = client.post("/api/v1/auth/password", headers=_headers(second),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert good.status_code == 204
    assert "HttpOnly" in good.headers["set-cookie"]
    assert client.get("/api/v1/auth/me", headers=_headers(first)).status_code == 401
    assert client.get("/api/v1/auth/me", headers=_headers(second)).status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 200  # rotated cookie
    assert client.post("/api/v1/auth/login", json={"username": user.username, "password": PASSWORD}).status_code == 401
    assert _login(client, user.username, NEW_PASSWORD)
    assert session.get(m.User, user.id).lifecycle_version == 1
    assert all(NEW_PASSWORD not in str(row.details) for row in session.scalars(select(m.AuditEvent)))


def test_recovery_is_one_time_hashed_expires_and_revokes_old_password(client, session):
    admin = _user(session, username="admin", display_name="Admin", system_admin=True)
    user = _user(session, username="recover", display_name="Recover")
    old = _login(client, user.username)
    admin_token = _login(client, admin.username)
    issued = client.post(f"/api/v1/users/{user.id}/recovery", headers=_headers(admin_token),
        json={"current_password": PASSWORD, "expected_version": 0, "reason": "Verified identity offline"})
    assert issued.status_code == 201, issued.text
    raw = issued.json()["token"]
    stored = session.scalar(select(m.AccountRecovery))
    assert stored.token_hash == token_digest(raw) and stored.token_hash != raw
    assert client.get("/api/v1/auth/me", headers=_headers(old)).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": user.username, "password": PASSWORD}).status_code == 401
    assert client.post("/api/v1/auth/recovery", json={"token": raw, "new_password": NEW_PASSWORD}).status_code == 204
    assert client.post("/api/v1/auth/recovery", json={"token": raw, "new_password": NEW_PASSWORD}).status_code == 400
    assert _login(client, user.username, NEW_PASSWORD)
    assert raw not in "".join(str(row.details) + str(row.reason) for row in session.scalars(select(m.AuditEvent)))
    # A new issued recovery invalidates the old one and cannot be used after expiry.
    second = client.post(f"/api/v1/users/{user.id}/recovery", headers=_headers(admin_token),
        json={"current_password": PASSWORD, "expected_version": 2, "reason": "Second verified request"})
    assert second.status_code == 201
    token = second.json()["token"]
    row = session.scalar(select(m.AccountRecovery).where(m.AccountRecovery.token_hash == token_digest(token)))
    row.expires_at = m.utcnow() - timedelta(seconds=1)
    session.commit()
    assert client.post("/api/v1/auth/recovery", json={"token": token, "new_password": NEW_PASSWORD}).status_code == 400


def test_deactivation_survives_bootstrap_restart_and_preserves_attribution(client, session):
    admin = _user(session, username="operator", display_name="Operator", system_admin=True)
    user = _user(session, username="configured-admin", display_name="Disabled Admin", system_admin=True)
    token = _login(client, user.username)
    admin_token = _login(client, admin.username)
    body = {"current_password": PASSWORD, "expected_version": 0, "reason": "Account disabled", "is_active": False}
    changed = client.patch(f"/api/v1/users/{user.id}", headers=_headers(admin_token), json=body)
    assert changed.status_code == 200 and not changed.json()["is_active"]
    assert client.get("/api/v1/auth/me", headers=_headers(token)).status_code == 401
    settings = Settings(demo_mode=False, bootstrap_admin_username=user.username, bootstrap_admin_password=PASSWORD, session_cookie_secure=True)
    ensure_bootstrap_administrator(session, settings)
    session.refresh(user)
    assert not user.is_active and user.display_name == "Disabled Admin"
    assert client.patch(f"/api/v1/users/{user.id}", headers=_headers(admin_token), json=body).status_code == 409
    last = {**body, "expected_version": 0}
    assert client.patch(f"/api/v1/users/{admin.id}", headers=_headers(admin_token), json=last).status_code == 409
    # Changing the bootstrap environment cannot create an escalation path later.
    ensure_bootstrap_administrator(session, Settings(bootstrap_admin_username="other-bootstrap", bootstrap_admin_password=PASSWORD))
    assert session.scalar(select(m.User).where(m.User.username == "other-bootstrap")) is None


def test_project_admin_cannot_administer_global_accounts(client, session):
    user = _user(session, username="project-admin", display_name="Project Admin")
    project = create_project(session, "ops-isolation", "Ops")
    _membership(session, project.id, user.id, m.ProjectRole.administrator)
    token = _login(client, user.username)
    assert client.patch(f"/api/v1/users/{user.id}", headers=_headers(token), json={
        "current_password": PASSWORD, "reason": "not allowed", "expected_version": 0, "is_active": False}).status_code == 403
    assert client.post(f"/api/v1/users/{user.id}/recovery", headers=_headers(token), json={
        "current_password": PASSWORD, "reason": "not allowed", "expected_version": 0}).status_code == 403


def _old_run(session, project, *, external_id="old", message="duplicate transfer committed and ledger became unbalanced"):
    run = ingest_normalized(session, project, IngestionRequest.model_validate({"external_id": external_id,
        "observations": [{"test_identity": "payment-invariant", "outcome": "failed", "message": message,
                          "details": {"data_integrity_violation": True}}]}))
    failure = session.scalar(select(m.Failure).where(m.Failure.run_id == run.id))
    analysis = analyze_and_persist(session, failure)
    run.created_at = m.utcnow() - timedelta(days=100)
    session.commit()
    return run, failure, analysis


def _cleanup(session, project):
    proof = retention.preview(session, project.id)
    job = retention.enqueue(session, project.id, proof, DEMO_PRINCIPAL)
    for _ in range(20):
        process_next(session, "ops-test", settings=get_settings())
        session.refresh(job)
        if job.state not in {m.JobState.queued, m.JobState.running}:
            break
    assert job.state == m.JobState.succeeded, (job.state, job.last_error)
    return job


def test_retention_policy_preview_conflicts_limits_and_authorization(client, session):
    project = create_project(session, "policy", "Policy")
    run, _, _ = _old_run(session, project)
    base = f"/api/v1/projects/{project.id}/retention"
    policy = client.get(base).json()
    assert policy["version"] == 1
    body = {"expected_version": 1, "source_days": 2, "evidence_days": 30, "audit_days": 60,
            "export_enabled": False, "export_max_rows": 10, "reason": "Documented shorter retention"}
    proposed = client.post(base + "/preview", json=body)
    assert proposed.status_code == 200 and proposed.json()["evidence_runs"] == 1
    assert client.get(base).json()["version"] == 1
    saved = client.put(base, json=body)
    assert saved.status_code == 200 and saved.json()["version"] == 2
    assert client.put(base, json=body).status_code == 409
    assert client.put(base, json={**body, "expected_version": 2, "source_days": 31}).status_code == 422
    viewer = _user(session, username="viewer", display_name="Viewer")
    _membership(session, project.id, viewer.id, m.ProjectRole.viewer)
    token = _login(client, viewer.username)
    assert client.get(base, headers=_headers(token)).status_code == 200
    assert client.get(base + "/preview", headers=_headers(token)).status_code == 403
    other = create_project(session, "other-policy", "Other")
    assert client.get(f"/api/v1/projects/{other.id}/retention", headers=_headers(token)).status_code == 404


def test_retention_candidate_preview_is_exact_not_count_only(client, session):
    project = create_project(session, "proof", "Proof")
    run, _, _ = _old_run(session, project)
    base = f"/api/v1/projects/{project.id}/retention"
    proof = client.get(base + "/preview").json()
    body = {"expected_version": proof["policy_version"], "as_of": proof["as_of"], "confirmation_digest": proof["confirmation_digest"]}
    run.created_at = m.utcnow()
    session.commit()
    assert client.post(base + "/cleanup", json=body).status_code == 409
    fresh = client.get(base + "/preview").json()
    accepted = client.post(base + "/cleanup", json={"expected_version": fresh["policy_version"],
        "as_of": fresh["as_of"], "confirmation_digest": fresh["confirmation_digest"]})
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["job_id"]
    assert client.get(base + f"/jobs/{job_id}").status_code == 200
    future = {**body, "as_of": (m.utcnow() + timedelta(days=1)).isoformat()}
    assert client.post(base + "/cleanup", json=future).status_code == 422


def test_expiry_clears_bytes_copied_excerpts_and_returns_gone(client, session):
    project = create_project(session, "expired", "Expired")
    canary = "RETENTION_CANARY_PRIVATE_EXCERPT"
    run, failure, analysis = _old_run(session, project, message=f"duplicate transfer ledger unbalanced {canary}")
    review = add_review(session, analysis, ReviewCreate(decision="needs_more_evidence", expected_version=0,
        reason=f"Review quoted {canary}", investigation_outcome=canary), principal=DEMO_PRINCIPAL)
    evidence = session.scalar(select(m.Evidence).where(m.Evidence.run_id == run.id))
    paths = [get_settings().artifact_root / row.storage_path for row in session.scalars(
        select(m.ArtifactDerivative).where(m.ArtifactDerivative.run_id == run.id))]
    assert any(path.exists() for path in paths)
    job = _cleanup(session, project)
    assert job.payload["progress"]["evidence_runs"] == 1
    assert all(not path.exists() for path in paths)
    gone = client.get(f"/api/v1/evidence/{evidence.id}")
    assert gone.status_code == 410 and "no-store" in gone.headers["cache-control"]
    result = client.get(f"/api/v1/analyses/{analysis.id}")
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["evidence_state"] == "expired" and data["category"] == "insufficient_evidence"
    assert data["recorded_category"] == "product_defect" and data["claims"] == []
    for endpoint in (f"/runs/{run.id}/failures", f"/analyses/{analysis.id}/reviews",
                     f"/projects/{project.id}/review-queue/page?status=all", f"/projects/{project.id}/audit-events/page"):
        response = client.get("/api/v1" + endpoint)
        assert response.status_code == 200, response.text
        assert canary not in response.text
    session.refresh(review)
    assert review.actor == DEMO_PRINCIPAL.display_name and review.version == 1
    assert review.reason == retention.EXPIRED and review.investigation_outcome is None
    assert client.post(f"/api/v1/failures/{failure.id}/analyses").status_code == 410
    assert "HOLD_FOR_REVIEW" in render_markdown(run, [analysis])
    assert "HOLD_FOR_REVIEW" in render_markdown(run, [])
    tombstone_count = session.scalar(select(func.count()).select_from(m.RetentionTombstone))
    _cleanup(session, project)
    assert session.scalar(select(func.count()).select_from(m.RetentionTombstone)) == tombstone_count


def test_cleanup_does_not_expire_another_project_or_recent_run(session):
    first = create_project(session, "one", "One")
    second = create_project(session, "two", "Two")
    old, _, _ = _old_run(session, first)
    recent, _, _ = _run_with_analysis(session, first, external_id="recent")
    other, _, _ = _old_run(session, second)
    _cleanup(session, first)
    session.refresh(recent); session.refresh(other)
    assert old.evidence_expired_at is not None
    assert recent.evidence_expired_at is None and other.evidence_expired_at is None


def test_cleanup_crash_after_logical_expiry_resumes_idempotently(session, monkeypatch):
    project = create_project(session, "crash", "Crash")
    run, _, _ = _old_run(session, project)
    job = retention.enqueue(session, project.id, retention.preview(session, project.id), DEMO_PRINCIPAL)
    real = retention.flush_deletions
    def crash(*args, **kwargs):
        raise OSError("simulated crash before unlink")
    monkeypatch.setattr(retention, "flush_deletions", crash)
    assert process_next(session, "crash-worker")
    session.refresh(run); session.refresh(job)
    assert run.evidence_expired_at is not None and job.state == m.JobState.queued
    assert session.scalar(select(m.StorageDeletion.id).where(m.StorageDeletion.state == "pending"))
    monkeypatch.setattr(retention, "flush_deletions", real)
    job.available_at = m.utcnow() - timedelta(seconds=1)
    session.commit()
    assert process_next(session, "retry-worker")
    session.refresh(job)
    assert job.state == m.JobState.succeeded, job.last_error
    assert session.scalar(select(m.StorageDeletion.id).where(m.StorageDeletion.state == "pending")) is None


def test_cleanup_policy_change_cancels_stale_work(session):
    project = create_project(session, "policy-race", "Policy Race")
    run, _, _ = _old_run(session, project)
    job = retention.enqueue(session, project.id, retention.preview(session, project.id), DEMO_PRINCIPAL)
    policy = retention.policy_for(session, project.id)
    policy.version += 1
    session.commit()
    assert process_next(session, "worker")
    session.refresh(job); session.refresh(run)
    assert job.state == m.JobState.cancelled and job.last_error == "policy_version_changed"
    assert run.evidence_expired_at is None


def test_pending_ingestion_defers_cleanup_without_retry_exhaustion(session):
    project = create_project(session, "busy", "Busy")
    run, _, _ = _old_run(session, project)
    cleanup = retention.enqueue(session, project.id, retention.preview(session, project.id), DEMO_PRINCIPAL)
    busy = m.Job(project_id=project.id, kind="noop", state=m.JobState.queued, payload={},
                 available_at=m.utcnow()+timedelta(days=1))
    session.add(busy); session.commit()
    assert process_next(session, "worker")
    session.refresh(cleanup); session.refresh(run)
    assert cleanup.state == m.JobState.queued and cleanup.attempts == 0 and run.evidence_expired_at is None


def test_file_deletion_protects_shared_reference_and_rejects_unsafe_paths(session, tmp_path):
    project = create_project(session, "paths", "Paths")
    run, _, _ = _old_run(session, project)
    derivative = session.scalar(select(m.ArtifactDerivative).where(m.ArtifactDerivative.run_id == run.id))
    source = get_settings().artifact_root / derivative.storage_path
    retention._delete_later(session, project.id, derivative.storage_path)
    unsafe = m.StorageDeletion(project_id=project.id, storage_path="../other/project-secret")
    session.add(unsafe); session.commit()
    assert retention.flush_deletions(session, project.id, get_settings()) == 0
    assert source.exists()
    row = session.scalar(select(m.StorageDeletion).where(m.StorageDeletion.storage_path == derivative.storage_path))
    assert row.state == "retained_reference"
    assert unsafe.state == "blocked"


def test_review_queue_filters_before_pagination_beyond_500(session, client):
    project = create_project(session, "large-queue", "Large Queue")
    # One real ingestion with many independent failures avoids test-only SQL shapes.
    observations = [{"test_identity": f"test-{i:04}", "outcome": "failed", "message": "unknown failure"} for i in range(505)]
    run = ingest_normalized(session, project, IngestionRequest.model_validate({"external_id": "large", "observations": observations}))
    failures = list(session.scalars(select(m.Failure).where(m.Failure.run_id == run.id).order_by(m.Failure.id)))
    for i, failure in enumerate(failures):
        session.add(m.Analysis(failure_id=failure.id, revision=1, analysis_version="test-fixture", input_digest=f"{i:064x}",
            category=m.Category.insufficient_evidence, severity="medium", confidence_kind="unavailable",
            confidence_explanation="test fixture", evidence_completeness="complete", summary="needle-original" if i == 0 else "newer",
            created_at=m.utcnow()-timedelta(days=1 if i == 0 else 0)))
    session.commit()
    result = client.get(f"/api/v1/projects/{project.id}/review-queue/page?status=all&search=needle-original&limit=10")
    assert result.status_code == 200, result.text
    assert result.json()["total"] == 1 and len(result.json()["items"]) == 1
    last = client.get(f"/api/v1/projects/{project.id}/review-queue/page?status=all&offset=500&limit=10").json()
    assert last["total"] == 505 and len(last["items"]) == 5
    assert any(row["summary"] == "needle-original" for row in last["items"])
    literal = review_queue_page(session, project.id, status="all", search="%")
    assert literal.total == 0


def test_review_queue_uses_latest_revision_and_latest_decision(client, session):
    project = create_project(session, "decisions", "Decisions")
    _, _, analysis = _run_with_analysis(session, project, external_id="review")
    add_review(session, analysis, ReviewCreate(decision="accept", expected_version=0, reason="Reviewed evidence"), principal=DEMO_PRINCIPAL)
    prefix = f"/api/v1/projects/{project.id}/review-queue/page"
    assert client.get(prefix).json()["total"] == 0
    assert client.get(prefix + "?status=reviewed").json()["total"] == 1
    add_review(session, analysis, ReviewCreate(decision="needs_more_evidence", expected_version=1, reason="New uncertainty"), principal=DEMO_PRINCIPAL)
    data = client.get(prefix).json()
    assert data["total"] == 1 and data["items"][0]["latest_review_version"] == 2
    assert client.get(prefix + "?status=needs_more_evidence").json()["total"] == 1


def test_audit_export_is_server_authorized_bounded_and_formula_safe(client, session):
    project = create_project(session, "export", "Export")
    for i in range(4):
        session.add(m.AuditEvent(project_id=project.id, actor_kind="demo", actor_display="Admin", action="example",
            outcome="success", resource_type="fixture", resource_id=str(i), reason=" \t=HYPERLINK(\"danger\")" if i == 0 else f"item {i}"))
    session.commit()
    base = f"/api/v1/projects/{project.id}"
    response = client.post(base + "/audit-events/export", json={"action": "example"})
    assert response.status_code == 200, response.text
    assert "' \t=HYPERLINK" in response.text and "no-store" in response.headers["cache-control"]
    event = session.scalar(select(m.AuditEvent).where(m.AuditEvent.action == "audit.exported"))
    assert event.details["rows"] == 4
    page = client.get(base + "/audit-events/page?search=item%203").json()
    assert page["total"] == 1 and len(page["items"]) == 1
    policy = retention.policy_for(session, project.id)
    policy.export_max_rows = 2; session.commit()
    assert client.post(base + "/audit-events/export", json={"action": "example"}).status_code == 413
    policy.export_enabled = False; session.commit()
    assert client.post(base + "/audit-events/export", json={"action": "example"}).status_code == 403
    reviewer = _user(session, username="audit-reader", display_name="Reviewer")
    _membership(session, project.id, reviewer.id, m.ProjectRole.reviewer)
    token = _login(client, reviewer.username)
    assert client.get(base + "/audit-events/page", headers=_headers(token)).status_code == 200
    assert client.post(base + "/audit-events/export", headers=_headers(token), json={}).status_code == 403


def test_audit_expiration_leaves_minimal_tombstone(session):
    project = create_project(session, "audit-expired", "Audit")
    event = m.AuditEvent(project_id=project.id, actor_kind="demo", actor_display="Sensitive name", action="example",
        outcome="success", resource_type="fixture", reason="old private reason", created_at=m.utcnow()-timedelta(days=400))
    session.add(event); session.commit()
    ident = event.id
    _cleanup(session, project)
    assert session.get(m.AuditEvent, ident) is None
    tombstone = session.scalar(select(m.RetentionTombstone).where(m.RetentionTombstone.resource_id == ident))
    assert tombstone.resource_type == "audit_event"
    assert "private" not in str(tombstone.__dict__) and "Sensitive name" not in str(tombstone.__dict__)


def test_original_expiry_replay_does_not_resurrect_files(client, session):
    project = create_project(session, "raw-expiry", "Raw Expiry")
    report = b'<testsuite><testcase name="sample"><failure>unknown failure</failure></testcase></testsuite>'
    url = f"/api/v1/projects/{project.id}/ingestions?external_id=old-raw&filename=report.xml"
    uploaded = client.post(url, content=report, headers={"Content-Type": "application/xml"})
    assert uploaded.status_code == 202
    assert process_next(session, "ingester")
    ingestion = session.get(m.Ingestion, uploaded.json()["id"])
    run = session.get(m.Run, ingestion.run_id)
    ingestion.created_at = run.created_at = m.utcnow() - timedelta(days=10)
    session.commit()
    path = get_settings().artifact_root / ingestion.storage_path
    _cleanup(session, project)
    session.refresh(ingestion); session.refresh(run)
    assert not path.exists() and run.evidence_expired_at is None
    assert ingestion.source_expired_at is not None
    replay = client.post(url, content=report, headers={"Content-Type": "application/xml"})
    assert replay.status_code == 409 and not path.exists()
    ingestion.state = m.IngestionState.failed
    session.commit()
    with pytest.raises(ValueError, match="source expired"):
        retry_ingestion(session, ingestion)


def test_original_cleanup_preserves_bytes_shared_by_recent_upload(client, session):
    project = create_project(session, "shared-source", "Shared Source")
    content = b'<testsuite><testcase name="same"/></testsuite>'
    url = f"/api/v1/projects/{project.id}/ingestions?filename=same.xml&external_id="
    first = client.post(url + "first", content=content, headers={"Content-Type": "application/xml"}).json()
    process_next(session, "ingester")
    old = session.get(m.Ingestion, first["id"])
    old.created_at = m.utcnow()-timedelta(days=10)
    session.get(m.Run, old.run_id).created_at = old.created_at
    session.commit()
    second = client.post(url + "second", content=content, headers={"Content-Type": "application/xml"}).json()
    process_next(session, "ingester")
    recent = session.get(m.Ingestion, second["id"])
    assert old.storage_path == recent.storage_path
    path = get_settings().artifact_root / old.storage_path
    _cleanup(session, project)
    session.refresh(old); session.refresh(recent)
    assert old.source_expired_at is not None and recent.source_expired_at is None and path.exists()
    recent.created_at = m.utcnow()-timedelta(days=10)
    session.get(m.Run, recent.run_id).created_at = recent.created_at
    session.commit()
    _cleanup(session, project)
    assert not path.exists()


def test_scheduler_records_empty_scan_without_noop_job_growth(session):
    project = create_project(session, "empty-sweep", "Empty Sweep")
    retention.schedule_due(session)
    policy = retention.policy_for(session, project.id)
    assert policy.last_scanned_at is not None
    retention.schedule_due(session)
    assert session.scalar(select(func.count()).select_from(m.Job)) == 0
    run, _, _ = _old_run(session, project)
    policy.last_scanned_at = m.utcnow()-timedelta(minutes=6)
    session.commit()
    retention.schedule_due(session)
    assert session.scalar(select(func.count()).select_from(m.Job)) == 1


def test_unlink_then_crash_recovers_when_bytes_already_gone(session, monkeypatch):
    project = create_project(session, "unlink-crash", "Unlink Crash")
    run, _, _ = _old_run(session, project)
    job = retention.enqueue(session, project.id, retention.preview(session, project.id), DEMO_PRINCIPAL)
    real_unlink = Path.unlink
    crashed = False
    def unlink_once(path, *args, **kwargs):
        nonlocal crashed
        real_unlink(path, *args, **kwargs)
        if not crashed:
            crashed = True
            raise OSError("simulated crash after unlink before commit")
    monkeypatch.setattr(Path, "unlink", unlink_once)
    process_next(session, "worker")
    session.refresh(job)
    assert job.state == m.JobState.queued and job.last_error == "retention_worker_error"
    monkeypatch.setattr(Path, "unlink", real_unlink)
    job.available_at = m.utcnow()-timedelta(seconds=1)
    session.commit()
    process_next(session, "worker-2")
    session.refresh(job)
    assert job.state == m.JobState.succeeded


def test_validation_never_echoes_credentials(client):
    marker = "PRIVATE_PASSWORD_CANARY"
    response = client.post("/api/v1/auth/recovery", json={"token": marker, "new_password": {"secret": marker}})
    assert response.status_code == 422 and marker not in response.text
    assert "no-store" in response.headers["cache-control"]


def test_expired_session_and_blank_recovery_do_not_authenticate(client, session):
    user = _user(session, username="expired-session", display_name="Expired")
    token = _login(client, user.username)
    row = session.scalar(select(m.AuthSession).where(m.AuthSession.token_hash == token_digest(token)))
    row.expires_at = m.utcnow()-timedelta(seconds=1); session.commit()
    assert client.get("/api/v1/auth/sessions", headers=_headers(token)).status_code == 401
    assert client.post("/api/v1/auth/recovery", json={"token": "x"*40, "new_password": NEW_PASSWORD}).status_code == 400


def test_operator_recovery_is_explicit_and_does_not_promote_accounts(session):
    from failurelens.accounts import operator_recovery, redeem_recovery
    user = _user(session, username="operator-recover", display_name="Inactive")
    user.is_active = False; session.commit()
    with pytest.raises(ValueError, match="explicit --activate"):
        operator_recovery(session, user.username, reason="Verified operator request")
    restored, recovery, token = operator_recovery(session, user.username, reason="Verified operator request", activate=True)
    assert restored.is_active and not restored.is_system_admin
    assert session.scalar(select(m.AuditEvent).where(m.AuditEvent.action == "auth.operator_recovery_issued"))
    redeem_recovery(session, token, NEW_PASSWORD)
    assert verify_password(NEW_PASSWORD, session.get(m.User, user.id).password_hash)


def test_stale_principal_is_rechecked_under_the_account_lock(session):
    from failurelens.accounts import active_actor
    from failurelens.auth import Principal, create_auth_session
    user = _user(session, username="stale-principal", display_name="Stale Principal")
    row, _ = create_auth_session(session, user, settings=Settings(demo_mode=True))
    session.commit()
    principal = Principal(kind="user", actor_id=user.id, user_id=user.id,
                          session_id=row.id, display_name=user.display_name)
    row.revoked_at = m.utcnow()
    session.commit()
    with pytest.raises(HTTPException) as error:
        active_actor(session, principal)
    assert error.value.status_code == 401
