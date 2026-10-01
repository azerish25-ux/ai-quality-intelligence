"""Rejected credentials and account commands preserve the durable account state."""

from dataclasses import replace
from datetime import timedelta

import pytest
from failurelens import accounts
from failurelens import models as m
from failurelens.auth import (
    DEMO_PRINCIPAL,
    Principal,
    as_utc,
    create_auth_session,
    create_project_ingestion_token,
    create_user,
    current_principal,
    ensure_bootstrap_administrator,
    hash_password,
    require_project_role,
    token_digest,
    verify_password,
)
from failurelens.config import Settings, get_settings
from fastapi import HTTPException, Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

PASSWORD = "synthetic-boundary-password"


def account_state(factory):
    """Read persisted values, including hashes, revocation and recovery timestamps."""
    with factory() as session:
        return {
            model.__tablename__: list(
                session.execute(select(model.__table__).order_by(model.id))
            )
            for model in (m.User, m.AuthSession, m.AccountRecovery, m.AuditEvent)
        }


def seed_user(session, username="boundary-user", *, administrator=False):
    user = create_user(
        session,
        username=username,
        display_name="Boundary User",
        password=PASSWORD,
        system_admin=administrator,
    )
    credential, raw = create_auth_session(session, user)
    principal = Principal(
        kind="user",
        actor_id=user.id,
        display_name=user.display_name,
        user_id=user.id,
        session_id=credential.id,
        system_admin=administrator,
    )
    return user, credential, raw, principal


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("username", " \t ", "username must contain"),
        ("username", "x" * 241, "username must contain"),
        ("username", "ß" * 240, "username must contain"),
        ("username", " BOUNDARY-USER ", "username already exists"),
        ("display_name", " \t ", "display name must contain"),
        ("display_name", "x" * 241, "display name must contain"),
        ("password", "x" * 11, "at least 12 characters"),
        ("password", "x" * 1025, "password is too long"),
    ],
)
def test_rejected_user_creation_preserves_existing_account(
    session_factory, field, value, message
):
    with session_factory.begin() as setup:
        seed_user(setup)
    before = account_state(session_factory)
    fields = {
        "username": "new-boundary-user",
        "display_name": "New Boundary User",
        "password": PASSWORD,
        field: value,
    }
    with session_factory() as session:
        with pytest.raises(ValueError, match=message):
            create_user(session, **fields)
        # Even a caller that commits after validation failure cannot persist a partial user.
        session.commit()
    assert account_state(session_factory) == before


@pytest.mark.parametrize("length", [12, 1024])
def test_password_length_boundaries_remain_usable(length):
    password = "x" * length
    encoded = hash_password(password)
    assert verify_password(password, encoded)
    assert not verify_password(password + "y", encoded)


@pytest.mark.parametrize(
    "encoded",
    [
        "sha256$16384$8$1$00$00",
        "scrypt$not-an-integer$8$1$00$00",
        "scrypt$18446744073709551616$8$1$00$00",
        "scrypt$16384$8$1$not-hex$00",
        "scrypt$16384$8$1$00$not-hex",
        "scrypt$16384$8$1$00$",
    ],
)
def test_malformed_stored_password_denies_login_without_creating_session(
    request_client, session_factory, encoded
):
    with session_factory.begin() as setup:
        user, _, _, _ = seed_user(setup)
        user.password_hash = encoded
        user_id = user.id
    before = account_state(session_factory)
    response = request_client.post(
        "/api/v1/auth/login",
        json={"username": "boundary-user", "password": PASSWORD},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid username or password"}
    assert "set-cookie" not in response.headers
    after = account_state(session_factory)
    assert after["users"] == before["users"]
    assert after["auth_sessions"] == before["auth_sessions"]
    with session_factory() as observer:
        assert observer.get(m.User, user_id).last_login_at is None
        audit = observer.scalar(select(m.AuditEvent))
        assert audit.action == "auth.login_denied" and audit.outcome == "denied"
        assert PASSWORD not in response.text + str(audit.details) + str(audit.reason)


@pytest.mark.parametrize("name", [" \t ", "x" * 241])
def test_invalid_ingestion_token_name_cannot_create_credential(session_factory, name):
    with session_factory.begin() as setup:
        project = m.Project(slug="name-boundary", name="Name Boundary")
        setup.add(project)
        setup.flush()
        project_id = project.id
    with session_factory() as session:
        with pytest.raises(ValueError, match="token name must contain"):
            create_project_ingestion_token(
                session, project_id=project_id, name=name, created_by_user_id=None
            )
        session.commit()
    with session_factory() as observer:
        assert observer.scalar(select(m.IngestionToken)) is None
        assert observer.get(m.Project, project_id).name == "Name Boundary"
    with session_factory.begin() as session:
        credential, raw = create_project_ingestion_token(
            session,
            project_id=project_id,
            name=" " + "x" * 240 + " ",
            created_by_user_id=None,
        )
        assert credential.name == "x" * 240
        assert credential.token_hash == token_digest(raw)


@pytest.mark.parametrize("header", ["Basic invalid", "Bearer", "Bearer   "])
def test_malformed_authorization_does_not_fall_back_to_valid_cookie(
    request_client, session_factory, header
):
    with session_factory.begin() as setup:
        _, credential, raw, _ = seed_user(setup)
        credential.last_used_at = m.utcnow() - timedelta(hours=1)
    before = account_state(session_factory)
    request_client.cookies.set(get_settings().session_cookie_name, raw)
    response = request_client.get("/api/v1/auth/me", headers={"Authorization": header})
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid authorization header"}
    assert account_state(session_factory) == before
    assert request_client.get("/api/v1/auth/me").status_code == 200


@pytest.mark.parametrize("kind", ["session", "ingestion", "unknown"])
def test_unprefixed_credentials_are_validated_and_unknown_values_never_become_demo(
    request_client, session_factory, kind
):
    raw = "legacy-synthetic-boundary-credential"
    old = m.utcnow() - timedelta(hours=1)
    with session_factory.begin() as setup:
        _, credential, _, _ = seed_user(setup)
        if kind == "ingestion":
            project = m.Project(slug="legacy-token", name="Legacy Token")
            setup.add(project)
            setup.flush()
            credential, _ = create_project_ingestion_token(
                setup, project_id=project.id, name="Legacy", created_by_user_id=None
            )
        if kind != "unknown":
            credential.token_hash = token_digest(raw)
        credential.last_used_at = old
        credential_id = credential.id
    response = request_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {raw}"}
    )
    assert (
        response.status_code == {"session": 200, "ingestion": 403, "unknown": 401}[kind]
    )
    if kind == "session":
        assert response.json()["kind"] == "user"
    model = m.IngestionToken if kind == "ingestion" else m.AuthSession
    with session_factory() as observer:
        touched = as_utc(observer.get(model, credential_id).last_used_at)
        assert touched == old if kind == "unknown" else touched > old


@pytest.mark.parametrize(
    ("invalidity", "status"),
    [
        ("demo", 403),
        ("ingestion_token", 403),
        ("system", 403),
        ("missing-user-id", 403),
        ("unknown-user", 404),
        ("missing-session-id", 401),
        ("unknown-session", 401),
        ("other-users-session", 401),
        ("inactive-user", 401),
        ("expired-session", 401),
    ],
)
def test_account_operations_require_a_current_matching_human_session(
    session_factory, invalidity, status
):
    with session_factory.begin() as setup:
        user, credential, _, principal = seed_user(setup)
        _, other_session, _, _ = seed_user(setup, "other-boundary-user")
        if invalidity in {"demo", "ingestion_token", "system"}:
            principal = replace(principal, kind=invalidity)
        elif invalidity == "missing-user-id":
            principal = replace(principal, user_id=None)
        elif invalidity == "unknown-user":
            principal = replace(principal, user_id=m.new_id())
        elif invalidity == "missing-session-id":
            principal = replace(principal, session_id=None)
        elif invalidity == "unknown-session":
            principal = replace(principal, session_id=m.new_id())
        elif invalidity == "other-users-session":
            principal = replace(principal, session_id=other_session.id)
        elif invalidity == "inactive-user":
            user.is_active = False
        else:
            credential.expires_at = m.utcnow() - timedelta(seconds=1)
    before = account_state(session_factory)
    with session_factory() as session:
        with pytest.raises(HTTPException) as error:
            accounts.verify_actor(session, principal, PASSWORD)
        assert error.value.status_code == status
        session.commit()
    assert account_state(session_factory) == before


@pytest.mark.parametrize("operation", ["change", "recovery"])
def test_cached_administrator_claim_cannot_authorize_after_demotion(
    session_factory, operation
):
    with session_factory.begin() as setup:
        admin, _, _, principal = seed_user(setup, administrator=True)
        target, _, _, _ = seed_user(setup, "target-account")
        admin_id, target_id = admin.id, target.id
    with session_factory() as session:
        cached_admin = session.get(m.User, admin_id)
        assert cached_admin.is_system_admin
        with session_factory.begin() as concurrent:
            concurrent.get(m.User, admin_id).is_system_admin = False
        assert cached_admin.is_system_admin
        before = account_state(session_factory)
        with pytest.raises(HTTPException) as error:
            command = (
                accounts.change_account
                if operation == "change"
                else accounts.issue_recovery
            )
            command(
                session,
                principal,
                target_id,
                password=PASSWORD,
                expected_version=0,
                reason="Synthetic administrative request",
                **({"active": False} if operation == "change" else {}),
            )
        assert error.value.status_code == 403
        assert error.value.detail == "system administrator role required"
        assert not cached_admin.is_system_admin
        session.commit()
    assert account_state(session_factory) == before


@pytest.mark.parametrize("rejection", ["stale-version", "inactive-account"])
def test_recovery_issue_rejection_preserves_password_sessions_and_pending_recovery(
    request_client, session_factory, rejection
):
    with session_factory.begin() as setup:
        user, _, _, _ = seed_user(setup)
        user.lifecycle_version = 3
        user.is_active = rejection != "inactive-account"
        setup.add(
            m.AccountRecovery(
                user_id=user.id,
                token_hash=token_digest("existing-synthetic-recovery"),
                expires_at=m.utcnow() + timedelta(minutes=10),
            )
        )
        user_id = user.id
    before = account_state(session_factory)
    response = request_client.post(
        f"/api/v1/users/{user_id}/recovery",
        json={
            "expected_version": 2 if rejection == "stale-version" else 3,
            "reason": "Synthetic recovery request",
        },
    )
    assert response.status_code == 409
    assert account_state(session_factory) == before


def test_operator_recovery_cannot_create_missing_user_and_preserves_active_role(
    session_factory,
):
    with session_factory.begin() as setup:
        user, _, _, _ = seed_user(setup)
        user_id = user.id
    before = account_state(session_factory)
    with session_factory() as session:
        with pytest.raises(ValueError, match="cannot create an account"):
            accounts.operator_recovery(
                session, "missing-user", reason="Synthetic request"
            )
        session.commit()
    assert account_state(session_factory) == before
    with session_factory() as session:
        user, recovery, raw = accounts.operator_recovery(
            session, " BOUNDARY-USER ", reason="Synthetic verified operator request"
        )
        assert user.id == user_id and user.is_active and not user.is_system_admin
        assert user.lifecycle_version == 1
        assert not verify_password(PASSWORD, user.password_hash)
        assert recovery.token_hash == token_digest(raw)
    with session_factory() as observer:
        assert all(row.revoked_at for row in observer.scalars(select(m.AuthSession)))
        event = observer.scalar(select(m.AuditEvent))
        assert event.action == "auth.operator_recovery_issued"
        assert event.actor_kind == "system" and event.actor_user_id is None
        assert event.details["activated_explicitly"] is False


def test_account_activation_invalidates_old_sessions_and_recovery_without_changing_password(
    request_client, session_factory
):
    with session_factory.begin() as setup:
        user, credential, _, _ = seed_user(setup, administrator=True)
        user.is_active = False
        user.lifecycle_version = 3
        recovery = m.AccountRecovery(
            user_id=user.id,
            token_hash=token_digest("pending-synthetic-recovery"),
            expires_at=m.utcnow() + timedelta(minutes=10),
        )
        setup.add(recovery)
        setup.flush()
        user_id, credential_id, recovery_id = user.id, credential.id, recovery.id
        password_hash = user.password_hash
    response = request_client.patch(
        f"/api/v1/users/{user_id}",
        json={
            "is_active": True,
            "expected_version": 3,
            "reason": "Explicit activation",
        },
    )
    assert response.status_code == 200
    assert response.json()["is_active"] and response.json()["lifecycle_version"] == 4
    with session_factory() as observer:
        user = observer.get(m.User, user_id)
        assert user.password_hash == password_hash and user.is_system_admin
        assert observer.get(m.AuthSession, credential_id).revoked_at is not None
        assert observer.get(m.AccountRecovery, recovery_id).consumed_at is not None
        assert observer.scalar(select(m.AuditEvent.action)) == "auth.account_activated"
    before = account_state(session_factory)
    stale = request_client.patch(
        f"/api/v1/users/{user_id}",
        json={"is_active": False, "expected_version": 3, "reason": "Stale update"},
    )
    assert stale.status_code == 409
    assert account_state(session_factory) == before


def test_demo_bootstrap_never_creates_or_modifies_accounts(session_factory):
    with session_factory.begin() as setup:
        seed_user(setup)
    before = account_state(session_factory)
    with session_factory() as session:
        assert ensure_bootstrap_administrator(session, Settings(demo_mode=True)) is None
        session.commit()
    assert account_state(session_factory) == before


def test_user_principal_without_identity_has_no_project_membership(session_factory):
    with session_factory.begin() as setup:
        project = m.Project(slug="identity-boundary", name="Identity Boundary")
        setup.add(project)
        setup.flush()
        project_id = project.id
    principal = Principal(kind="user", actor_id=None, display_name="Missing identity")
    with session_factory() as session:
        with pytest.raises(HTTPException) as error:
            require_project_role(session, principal, project_id)
        assert error.value.status_code == 404
        assert (
            require_project_role(session, DEMO_PRINCIPAL, project_id)
            == m.ProjectRole.administrator
        )


def test_unsupported_database_backend_is_rejected_before_connecting():
    class UnusedDBAPI:
        paramstyle = "pyformat"

        @staticmethod
        def connect(*args, **kwargs):
            pytest.fail("authentication opened an unsupported database connection")

    engine = create_engine("mysql+pymysql://", module=UnusedDBAPI, poolclass=QueuePool)
    factory = sessionmaker(bind=engine)
    request = Request(
        {"type": "http", "headers": [(b"authorization", b"Bearer fls_synthetic")]}
    )
    try:
        with pytest.raises(RuntimeError, match="file-backed SQLite or PostgreSQL"):
            current_principal(request, factory)
        assert not hasattr(request.state, "principal")
    finally:
        engine.dispose()


@pytest.mark.parametrize("detail", [False, True])
def test_publication_history_requires_an_existing_project_even_for_administrators(
    request_client, session_factory, detail
):
    with session_factory.begin() as setup:
        project = m.Project(slug="empty-history", name="Empty History")
        setup.add(project)
        setup.flush()
        project_id = project.id
    before = account_state(session_factory)
    suffix = "/" + m.new_id() if detail else ""
    response = request_client.get(
        f"/api/v1/projects/{m.new_id()}/github-publications{suffix}"
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "project not found"}
    control = request_client.get(f"/api/v1/projects/{project_id}/github-publications")
    assert control.status_code == 200 and control.json()["items"] == []
    assert account_state(session_factory) == before
