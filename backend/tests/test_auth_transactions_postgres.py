"""Real PostgreSQL authentication ownership; SQLite is never a substitute."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Annotated

import pytest
from failurelens.api import app
from failurelens.auth import Principal, as_utc, current_principal
from failurelens.config import get_settings
from failurelens.db import get_authentication_session_factory, get_session
from failurelens.models import AuthSession, Project
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session, sessionmaker
from test_auth_transactions import seed_credential

pytest_plugins = ("test_operations_postgres",)


@pytest.fixture
def postgres_authentication(pg_factory):
    factory, _ = pg_factory
    authentication_factory = sessionmaker(
        bind=factory.kw["bind"], expire_on_commit=False
    )
    authentication_pids, handler_pids = [], []

    @event.listens_for(authentication_factory, "after_begin")
    def authentication_started(_session, _transaction, connection):
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(text("SET LOCAL statement_timeout = '8s'"))
        authentication_pids.append(connection.scalar(text("SELECT pg_backend_pid()")))

    def handler_sessions():
        with factory() as session:
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            session.execute(text("SET LOCAL statement_timeout = '8s'"))
            handler_pids.append(session.scalar(text("SELECT pg_backend_pid()")))
            yield session

    overrides = {
        get_session: handler_sessions,
        get_authentication_session_factory: lambda: authentication_factory,
    }
    try:
        yield factory, overrides, authentication_pids, handler_pids
    finally:
        event.remove(authentication_factory, "after_begin", authentication_started)


@contextmanager
def request_client(application, overrides):
    previous = application.dependency_overrides.copy()
    application.dependency_overrides.update(overrides)
    # pg_factory owns the migrated test schema. Do not run application startup
    # against the separate global database configured for the surrounding suite.
    client = TestClient(application)
    try:
        yield client
    finally:
        client.close()
        application.dependency_overrides.clear()
        application.dependency_overrides.update(previous)


@pytest.mark.parametrize("credential_source", ["bearer", "cookie"])
def test_postgres_read_only_me_persists_last_used(
    postgres_authentication, credential_source
):
    factory, overrides, authentication_pids, handler_pids = postgres_authentication
    row_id, raw, old = seed_credential(factory)
    with request_client(app, overrides) as client:
        if credential_source == "cookie":
            client.cookies.set(get_settings().session_cookie_name, raw)
            headers = {}
        else:
            headers = {"Authorization": f"Bearer {raw}"}
        response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["kind"] == "user"
    assert len(authentication_pids) == len(handler_pids) == 1
    with factory() as observer:
        assert as_utc(observer.get(AuthSession, row_id).last_used_at) > old


def test_postgres_authentication_commit_cannot_commit_failed_handler_write(
    postgres_authentication,
):
    factory, overrides, authentication_pids, handler_pids = postgres_authentication
    row_id, raw, old = seed_credential(factory)
    application = FastAPI()
    flushed_ids = []

    @application.post("/fail-after-write")
    def fail_after_write(
        # Keep a handler connection checked out before authentication so these
        # transactions must use different live PostgreSQL backend connections.
        session: Annotated[Session, Depends(get_session)],
        principal: Annotated[Principal, Depends(current_principal)],
    ):
        assert principal.session_id == row_id
        assert len(authentication_pids) == len(handler_pids) == 1
        assert authentication_pids[0] != handler_pids[0]
        business = Project(slug="failed-handler-business", name="Uncommitted")
        session.add(business)
        session.flush()
        flushed_ids.append(business.id)
        raise HTTPException(409, "handler failed after its business INSERT")

    with request_client(application, overrides) as client:
        response = client.post(
            "/fail-after-write", headers={"Authorization": f"Bearer {raw}"}
        )
    assert response.status_code == 409, response.text
    assert len(flushed_ids) == 1
    with factory() as observer:
        assert as_utc(observer.get(AuthSession, row_id).last_used_at) > old
        assert observer.get(Project, flushed_ids[0]) is None
        assert observer.scalar(select(Project.id)) is None
