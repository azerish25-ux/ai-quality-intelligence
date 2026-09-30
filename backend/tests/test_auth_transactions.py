"""Authentication metadata has its own committed transaction, before handlers."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

import pytest
from failurelens import db
from failurelens.auth import (
    DEMO_PRINCIPAL,
    Principal,
    _authenticate_ingestion_token,
    _authenticate_session,
    as_utc,
    create_auth_session,
    create_project_ingestion_token,
    create_user,
    current_principal,
)
from failurelens.config import Settings, get_settings
from failurelens.db import Base, get_authentication_session_factory, get_session
from failurelens.models import AuthSession, IngestionToken, Project, User, utcnow
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool, SingletonThreadPool, StaticPool


def seed_credential(factory, *, kind="session"):
    with factory.begin() as session:
        user = create_user(
            session,
            username="transaction-user",
            display_name="Transaction User",
            password="transaction-test-password",
        )
        if kind == "session":
            row, raw = create_auth_session(session, user)
        else:
            project = Project(slug="auth-project", name="Authentication project")
            session.add(project)
            session.flush()
            row, raw = create_project_ingestion_token(
                session,
                project_id=project.id,
                name="Transaction ingestion",
                created_by_user_id=user.id,
            )
        old = utcnow() - timedelta(hours=1)
        row.last_used_at = old
        return row.id, raw, old


@pytest.mark.parametrize("credential_source", ["bearer", "cookie"])
def test_read_only_me_persists_last_used_in_fresh_session(
    request_client, session_factory, credential_source
):
    row_id, raw, old = seed_credential(session_factory)
    if credential_source == "cookie":
        request_client.cookies.set(get_settings().session_cookie_name, raw)
        headers = {}
    else:
        headers = {"Authorization": f"Bearer {raw}"}
    response = request_client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    with session_factory() as observer:
        assert as_utc(observer.get(AuthSession, row_id).last_used_at) > old


def request_for(raw=None):
    headers = [(b"authorization", f"Bearer {raw}".encode())] if raw else []
    return Request({"type": "http", "headers": headers})


@pytest.mark.parametrize("header", ["Authorization", "X-FailureLens-Token"])
def test_valid_ingestion_token_touch_survives_route_forbidden(
    request_client, session_factory, header
):
    row_id, raw, old = seed_credential(session_factory, kind="ingestion")
    response = request_client.get(
        "/api/v1/auth/me",
        headers={header: f"Bearer {raw}" if header == "Authorization" else raw},
    )
    assert response.status_code == 403
    with session_factory() as observer:
        assert as_utc(observer.get(IngestionToken, row_id).last_used_at) > old


@pytest.mark.parametrize(
    ("kind", "invalidity"),
    [
        ("session", "unknown"),
        ("session", "expired"),
        ("session", "revoked"),
        ("session", "inactive"),
        ("ingestion", "unknown"),
        ("ingestion", "expired"),
        ("ingestion", "revoked"),
    ],
)
def test_invalid_credentials_never_touch_last_used(
    request_client, session_factory, kind, invalidity
):
    row_id, raw, old = seed_credential(session_factory, kind=kind)
    model = AuthSession if kind == "session" else IngestionToken
    with session_factory.begin() as setup:
        row = setup.get(model, row_id)
        if invalidity == "expired":
            row.expires_at = old
        elif invalidity == "revoked":
            row.revoked_at = old
        elif invalidity == "inactive":
            setup.get(User, row.user_id).is_active = False
        else:
            raw += "-unknown"
    response = request_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {raw}"}
    )
    assert response.status_code == 401
    with session_factory() as observer:
        assert as_utc(observer.get(model, row_id).last_used_at) == old


@pytest.mark.parametrize("kind", ["session", "ingestion"])
def test_reusable_authentication_helpers_do_not_commit(session_factory, kind):
    row_id, raw, old = seed_credential(session_factory, kind=kind)
    model = AuthSession if kind == "session" else IngestionToken
    authenticate = (
        _authenticate_session if kind == "session" else _authenticate_ingestion_token
    )
    with session_factory() as session:
        assert authenticate(session, raw) is not None
        assert as_utc(session.get(model, row_id).last_used_at) > old
    with session_factory() as observer:
        assert as_utc(observer.get(model, row_id).last_used_at) == old


def test_handler_failure_rolls_back_flushed_business_write_only(
    session_factory, monkeypatch
):
    row_id, raw, old = seed_credential(session_factory)
    monkeypatch.setattr(db, "SessionLocal", session_factory)
    application = FastAPI()

    @application.post("/fail-after-write")
    def fail_after_write(
        principal: Annotated[Principal, Depends(current_principal)],
        session: Annotated[Session, Depends(get_session)],
    ):
        assert principal.kind == "user"
        session.add(Project(slug="rolled-back-business-write", name="Business"))
        session.flush()
        raise HTTPException(409, "handler failed after flush")

    with TestClient(application) as client:
        response = client.post(
            "/fail-after-write", headers={"Authorization": f"Bearer {raw}"}
        )
    assert response.status_code == 409
    with session_factory() as observer:
        assert as_utc(observer.get(AuthSession, row_id).last_used_at) > old
        assert observer.scalar(select(Project.id)) is None


def test_authentication_uses_distinct_connection_and_leaves_pending_handler_untouched(
    session_factory,
):
    row_id, raw, old = seed_credential(session_factory)
    engine = session_factory.kw["bind"]
    checked_out = []

    def checkout(connection, _record, _proxy):
        checked_out.append(connection)

    event.listen(engine, "checkout", checkout)
    try:
        with session_factory() as handler:
            handler.scalar(select(1))
            pending = Project(slug="pending-business-write", name="Pending")
            handler.add(pending)
            principal = current_principal(request_for(raw), session_factory)
            assert principal.session_id == row_id
            assert len(checked_out) == 2
            assert checked_out[0] is not checked_out[1]
            assert pending in handler.new
            assert pending.id is None
            with session_factory() as observer:
                assert observer.scalar(select(Project.id)) is None
                assert as_utc(observer.get(AuthSession, row_id).last_used_at) > old
    finally:
        event.remove(engine, "checkout", checkout)


def test_commit_failure_does_not_publish_principal_and_next_request_recovers(
    session_factory, monkeypatch
):
    row_id, raw, old = seed_credential(session_factory)
    monkeypatch.setattr(db, "SessionLocal", session_factory)
    lifecycle = []
    requests = []
    fail_once = True

    class AuthenticationSession(Session):
        def close(self):
            super().close()
            lifecycle.append("closed")

    factory = sessionmaker(
        bind=session_factory.kw["bind"],
        class_=AuthenticationSession,
        expire_on_commit=False,
    )

    @event.listens_for(AuthenticationSession, "before_commit")
    def fail_commit(_session):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise RuntimeError("injected authentication commit failure")

    @event.listens_for(AuthenticationSession, "after_commit")
    def committed(_session):
        lifecycle.append("committed")

    def authentication_factory(request: Request):
        requests.append(request)
        return factory

    application = FastAPI()
    application.dependency_overrides[get_authentication_session_factory] = (
        authentication_factory
    )

    @application.get("/protected")
    def protected(principal: Annotated[Principal, Depends(current_principal)]):
        assert lifecycle[-2:] == ["committed", "closed"]
        lifecycle.append("handler")
        return {"session_id": principal.session_id}

    with TestClient(application, raise_server_exceptions=False) as client:
        failed = client.get("/protected", headers={"Authorization": f"Bearer {raw}"})
        assert failed.status_code == 500
        assert lifecycle == ["closed"]
        assert not hasattr(requests[0].state, "principal")
        with session_factory() as observer:
            assert as_utc(observer.get(AuthSession, row_id).last_used_at) == old
        recovered = client.get("/protected", headers={"Authorization": f"Bearer {raw}"})
        assert recovered.status_code == 200
        assert recovered.json() == {"session_id": row_id}
    assert lifecycle == ["closed", "committed", "closed", "handler"]
    with session_factory() as observer:
        assert as_utc(observer.get(AuthSession, row_id).last_used_at) > old


@pytest.mark.parametrize("demo_mode", [True, False])
def test_credential_free_requests_never_open_authentication_session(
    monkeypatch, demo_mode
):
    import failurelens.auth as auth_module

    monkeypatch.setattr(
        auth_module, "get_settings", lambda: Settings(demo_mode=demo_mode)
    )

    class ForbiddenFactory:
        def begin(self):
            pytest.fail("credential-free request opened authentication storage")

    request = request_for()
    if demo_mode:
        assert current_principal(request, ForbiddenFactory()) == DEMO_PRINCIPAL
        assert request.state.principal == DEMO_PRINCIPAL
    else:
        with pytest.raises(HTTPException) as error:
            current_principal(request, ForbiddenFactory())
        assert error.value.status_code == 401
        assert not hasattr(request.state, "principal")


@pytest.mark.parametrize("poolclass", [StaticPool, SingletonThreadPool])
def test_shared_pool_rejected_without_committing_handler_writes(tmp_path, poolclass):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'unsafe-pool.db'}", poolclass=poolclass
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    row_id, raw, old = seed_credential(factory)
    statements = []
    commits = []
    try:
        with factory() as handler:
            handler.add(Project(slug="unsafe-pool-business", name="Uncommitted"))
            handler.flush()
            event.listen(
                engine, "before_cursor_execute", lambda *args: statements.append(True)
            )
            event.listen(engine, "commit", lambda *args: commits.append(True))
            request = request_for(raw)
            with pytest.raises(RuntimeError, match="engine-bound sessionmaker"):
                current_principal(request, factory)
            assert not hasattr(request.state, "principal")
            assert statements == commits == []
            handler.rollback()
        with factory() as observer:
            assert observer.scalar(select(Project.id)) is None
            assert as_utc(observer.get(AuthSession, row_id).last_used_at) == old
    finally:
        engine.dispose()


@pytest.mark.parametrize("binding", ["connection", "session", "per-model"])
def test_non_engine_factory_rejected_without_committing_handler_writes(
    session_factory, binding
):
    row_id, raw, old = seed_credential(session_factory)
    engine = session_factory.kw["bind"]
    with engine.connect() as connection, Session(bind=connection) as handler:
        handler.add(Project(slug="unsafe-binding-business", name="Uncommitted"))
        handler.flush()
        if binding == "connection":
            factory = sessionmaker(bind=connection)
        elif binding == "session":
            factory = handler
        else:
            factory = sessionmaker(bind=engine, binds={AuthSession: connection})
        statements = []
        commits = []
        event.listen(
            engine, "before_cursor_execute", lambda *args: statements.append(True)
        )
        event.listen(engine, "commit", lambda *args: commits.append(True))
        expected_error = TypeError if binding == "session" else RuntimeError
        with pytest.raises(expected_error, match="engine-bound sessionmaker"):
            current_principal(request_for(raw), factory)
        assert statements == commits == []
        handler.rollback()
    with session_factory() as observer:
        assert observer.scalar(select(Project.id)) is None
        assert as_utc(observer.get(AuthSession, row_id).last_used_at) == old


@pytest.mark.parametrize(
    "url",
    [
        "sqlite+pysqlite://",
        "sqlite+pysqlite:///:memory:",
        "sqlite+pysqlite:///file:auth-memory?mode=memory&cache=shared&uri=true",
        "sqlite+pysqlite:///file::memory:?uri=true",
    ],
)
def test_in_memory_storage_rejected_before_any_connection(url):
    engine = create_engine(url, poolclass=QueuePool)
    factory = sessionmaker(bind=engine)
    connections = []
    event.listen(engine, "connect", lambda *args: connections.append(True))
    try:
        with pytest.raises(RuntimeError, match="file-backed SQLite or PostgreSQL"):
            current_principal(request_for("fls_unknown"), factory)
        assert connections == []
    finally:
        engine.dispose()


def test_file_backed_null_pool_persists_authentication(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'independent-null-pool.db'}",
        poolclass=NullPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        row_id, raw, old = seed_credential(factory)
        assert current_principal(request_for(raw), factory).session_id == row_id
        with factory() as observer:
            assert as_utc(observer.get(AuthSession, row_id).last_used_at) > old
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "query",
    [
        "vfs=memdb&uri=true",
        "uri=true&x=%26mode%3Dmemory%26cache%3Dshared",
    ],
)
def test_sqlite_uri_storage_rejected_before_any_connection(tmp_path, query):
    engine = create_engine(
        f"sqlite+pysqlite:///file:{tmp_path / 'uri-authentication'}?{query}",
        poolclass=QueuePool,
    )
    factory = sessionmaker(bind=engine)
    connections = []
    event.listen(engine, "connect", lambda *args: connections.append(True))
    try:
        with pytest.raises(RuntimeError, match="file-backed SQLite or PostgreSQL"):
            current_principal(request_for("fls_unknown"), factory)
        assert connections == []
    finally:
        engine.dispose()
