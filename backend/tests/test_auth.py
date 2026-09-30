from __future__ import annotations

from datetime import timedelta

import pytest
from failurelens.auth import (
    create_user,
    hash_password,
    token_digest,
    verify_password,
)
from failurelens.config import Settings
from failurelens.models import (
    AuditEvent,
    Failure,
    IngestionToken,
    ProjectMembership,
    ProjectRole,
    ReviewEvent,
    utcnow,
)
from failurelens.schemas import IngestionRequest
from failurelens.service import analyze_and_persist, create_project, ingest_normalized
from sqlalchemy import select


def _user(
    session,
    *,
    username: str,
    display_name: str,
    password: str = "correct-horse-battery-staple",
    system_admin: bool = False,
):
    row = create_user(
        session,
        username=username,
        display_name=display_name,
        password=password,
        system_admin=system_admin,
    )
    session.commit()
    session.refresh(row)
    return row


def _membership(session, project_id: str, user_id: str, role: ProjectRole):
    row = ProjectMembership(project_id=project_id, user_id=user_id, role=role)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _login(
    client, username: str, password: str = "correct-horse-battery-staple"
) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _run_with_analysis(session, project, *, external_id: str):
    run = ingest_normalized(
        session,
        project,
        IngestionRequest.model_validate(
            {
                "external_id": external_id,
                "observations": [
                    {
                        "test_identity": "payments::duplicate",
                        "outcome": "failed",
                        "message": "duplicate transfer committed and ledger became unbalanced",
                        "details": {"data_integrity_violation": True},
                    }
                ],
            }
        ),
    )
    failure = session.scalar(select(Failure).where(Failure.run_id == run.id))
    assert failure is not None
    analysis = analyze_and_persist(session, failure)
    return run, failure, analysis


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("correct-horse-battery-staple")
    second = hash_password("correct-horse-battery-staple")
    assert first != second
    assert verify_password("correct-horse-battery-staple", first) is True
    assert verify_password("wrong-password", first) is False
    assert (
        verify_password("correct-horse-battery-staple", "not-a-password-hash") is False
    )


def test_production_security_configuration_refuses_unsafe_defaults(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="BOOTSTRAP_ADMIN_USERNAME"):
        Settings(
            demo_mode=False,
            artifact_root=tmp_path / "missing-user",
            bootstrap_admin_password="very-long-production-password",
        ).validate_security()
    with pytest.raises(RuntimeError, match="at least 14 characters"):
        Settings(
            demo_mode=False,
            artifact_root=tmp_path / "weak-password",
            bootstrap_admin_username="admin",
            bootstrap_admin_password="too-short",
        ).validate_security()
    with pytest.raises(RuntimeError, match="SESSION_COOKIE_SECURE"):
        Settings(
            demo_mode=False,
            artifact_root=tmp_path / "insecure-cookie",
            bootstrap_admin_username="admin",
            bootstrap_admin_password="very-long-production-password",
        ).validate_security()
    with pytest.raises(RuntimeError, match="deprecated global credential"):
        Settings(
            demo_mode=False,
            artifact_root=tmp_path / "legacy-token",
            bootstrap_admin_username="admin",
            bootstrap_admin_password="very-long-production-password",
            session_cookie_secure=True,
            ingestion_token="global-secret-is-not-project-scoped",
        ).validate_security()


def test_login_me_logout_and_invalid_credentials_are_audited(client, session) -> None:
    user = _user(
        session, username="reviewer@example.test", display_name="Verified Reviewer"
    )
    project = create_project(session, "auth-login", "Auth Login")
    _membership(session, project.id, user.id, ProjectRole.reviewer)

    denied = client.post(
        "/api/v1/auth/login",
        json={"username": user.username, "password": "wrong-password"},
    )
    assert denied.status_code == 401

    token = _login(client, user.username)
    me = client.get("/api/v1/auth/me", headers=_headers(token))
    assert me.status_code == 200
    assert me.json()["display_name"] == "Verified Reviewer"
    assert me.json()["memberships"] == [
        {
            "project_id": project.id,
            "project_slug": project.slug,
            "project_name": project.name,
            "role": "reviewer",
        }
    ]

    logout = client.post("/api/v1/auth/logout", headers=_headers(token))
    assert logout.status_code == 204
    revoked = client.get("/api/v1/auth/me", headers=_headers(token))
    assert revoked.status_code == 401

    actions = list(session.scalars(select(AuditEvent.action)).all())
    assert "auth.login_denied" in actions
    assert "auth.login_succeeded" in actions
    assert "auth.logout" in actions


def test_viewer_is_project_scoped_and_cannot_mutate_reviews(client, session) -> None:
    viewer = _user(
        session, username="viewer@example.test", display_name="Project A Viewer"
    )
    project_a = create_project(session, "project-a", "Project A")
    project_b = create_project(session, "project-b", "Project B")
    _membership(session, project_a.id, viewer.id, ProjectRole.viewer)
    run_a, _, analysis_a = _run_with_analysis(session, project_a, external_id="run-a")
    run_b, _, _ = _run_with_analysis(session, project_b, external_id="run-b")
    token = _login(client, viewer.username)

    projects = client.get("/api/v1/projects", headers=_headers(token))
    assert projects.status_code == 200
    assert [item["id"] for item in projects.json()] == [project_a.id]
    assert (
        client.get(f"/api/v1/runs/{run_a.id}", headers=_headers(token)).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/runs/{run_b.id}", headers=_headers(token)).status_code
        == 404
    )

    review = client.post(
        f"/api/v1/analyses/{analysis_a.id}/reviews",
        headers=_headers(token),
        json={
            "decision": "accept",
            "reason": "The evidence is internally consistent.",
            "expected_version": 0,
        },
    )
    assert review.status_code == 403
    assert (
        client.get(
            f"/api/v1/projects/{project_a.id}/members", headers=_headers(token)
        ).status_code
        == 403
    )


def test_reviewer_identity_is_server_derived_and_audited(client, session) -> None:
    reviewer = _user(
        session,
        username="trusted-reviewer@example.test",
        display_name="Trusted Reviewer",
    )
    project = create_project(session, "review-identity", "Review Identity")
    _membership(session, project.id, reviewer.id, ProjectRole.reviewer)
    _, _, analysis = _run_with_analysis(session, project, external_id="review-run")
    token = _login(client, reviewer.username)

    spoofed = client.post(
        f"/api/v1/analyses/{analysis.id}/reviews",
        headers=_headers(token),
        json={
            "actor": "spoofed@example.test",
            "decision": "accept",
            "reason": "Attempted actor spoofing must not be accepted.",
            "expected_version": 0,
        },
    )
    assert spoofed.status_code == 422

    response = client.post(
        f"/api/v1/analyses/{analysis.id}/reviews",
        headers=_headers(token),
        json={
            "decision": "needs_more_evidence",
            "reason": "The current report does not include the required service trace.",
            "expected_version": 0,
            "investigation_outcome": "Trace collection requested from the owning team.",
            "release_advice": "INVESTIGATE",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["actor"] == "Trusted Reviewer"
    assert payload["actor_user_id"] == reviewer.id
    assert payload["actor_kind"] == "user"

    event = session.scalar(select(ReviewEvent).where(ReviewEvent.id == payload["id"]))
    assert event is not None
    assert event.actor_user_id == reviewer.id
    audit = session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "analysis.review_created",
            AuditEvent.resource_id == event.id,
        )
    )
    assert audit is not None
    assert audit.actor_user_id == reviewer.id
    assert audit.project_id == project.id


def test_project_admin_manages_members_and_single_use_token_secret(
    client, session
) -> None:
    admin = _user(
        session, username="admin@example.test", display_name="Project Administrator"
    )
    viewer = _user(
        session, username="new-viewer@example.test", display_name="New Viewer"
    )
    project = create_project(session, "admin-project", "Admin Project")
    _membership(session, project.id, admin.id, ProjectRole.administrator)
    token = _login(client, admin.username)

    membership = client.post(
        f"/api/v1/projects/{project.id}/members",
        headers=_headers(token),
        json={"username": viewer.username, "role": "viewer"},
    )
    assert membership.status_code == 201, membership.text
    assert membership.json()["display_name"] == "New Viewer"

    created = client.post(
        f"/api/v1/projects/{project.id}/ingestion-tokens",
        headers=_headers(token),
        json={"name": "CI upload"},
    )
    assert created.status_code == 201, created.text
    raw_token = created.json()["token"]
    assert raw_token.startswith("fli_")
    listed = client.get(
        f"/api/v1/projects/{project.id}/ingestion-tokens", headers=_headers(token)
    )
    assert listed.status_code == 200
    assert "token" not in listed.json()[0]
    persisted = session.get(IngestionToken, created.json()["id"])
    assert persisted is not None
    assert persisted.token_hash != raw_token
    assert raw_token not in persisted.token_hash


def test_ingestion_token_is_project_bound_non_reading_and_revocable(
    client, session
) -> None:
    admin = _user(
        session, username="token-admin@example.test", display_name="Token Admin"
    )
    project_a = create_project(session, "token-a", "Token A")
    project_b = create_project(session, "token-b", "Token B")
    _membership(session, project_a.id, admin.id, ProjectRole.administrator)
    token = _login(client, admin.username)
    created = client.post(
        f"/api/v1/projects/{project_a.id}/ingestion-tokens",
        headers=_headers(token),
        json={"name": "Action uploader"},
    ).json()
    ingestion_headers = {"X-FailureLens-Token": created["token"]}
    payload = {
        "external_id": "token-run",
        "observations": [
            {
                "test_identity": "auth::token",
                "outcome": "passed",
            }
        ],
    }

    accepted = client.post(
        f"/api/v1/projects/{project_a.id}/ingestions",
        headers=ingestion_headers,
        json=payload,
    )
    assert accepted.status_code == 202, accepted.text
    assert client.get("/api/v1/projects", headers=ingestion_headers).status_code == 403
    assert (
        client.post(
            f"/api/v1/projects/{project_b.id}/ingestions",
            headers=ingestion_headers,
            json={**payload, "external_id": "cross-project"},
        ).status_code
        == 404
    )

    revoked = client.post(
        f"/api/v1/projects/{project_a.id}/ingestion-tokens/{created['id']}/revoke",
        headers=_headers(token),
    )
    assert revoked.status_code == 200
    rejected = client.post(
        f"/api/v1/projects/{project_a.id}/ingestions",
        headers=ingestion_headers,
        json={**payload, "external_id": "after-revoke"},
    )
    assert rejected.status_code == 401


def test_expired_ingestion_token_is_rejected(client, session) -> None:
    project = create_project(session, "expired-token", "Expired Token")
    raw_token = "fli_expired-but-correctly-hashed"
    row = IngestionToken(
        project_id=project.id,
        name="Expired",
        token_prefix="fli_expired",
        token_hash=token_digest(raw_token),
        scopes=["ingestion:create"],
        expires_at=utcnow() - timedelta(minutes=1),
    )
    session.add(row)
    session.commit()
    # A malformed/unknown credential and an expired credential are both deliberately
    # indistinguishable to callers.
    response = client.get(
        "/api/v1/projects",
        headers={"X-FailureLens-Token": raw_token},
    )
    assert response.status_code == 401
