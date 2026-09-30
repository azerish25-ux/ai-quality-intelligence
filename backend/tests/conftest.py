from __future__ import annotations

import os

os.environ.setdefault("FAILURELENS_DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("FAILURELENS_ARTIFACT_ROOT", "/tmp/failurelens-test-artifacts")
os.environ.setdefault("FAILURELENS_DEMO_MODE", "true")

import pytest
from failurelens.api import app
from failurelens.config import get_settings
from failurelens.db import (
    Base,
    create_database_engine,
    get_authentication_session_factory,
    get_session,
)
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("FAILURELENS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    get_settings.cache_clear()
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'application.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()
    get_settings.cache_clear()


@pytest.fixture
def session(session_factory) -> Session:
    with session_factory() as value:
        yield value


@pytest.fixture
def client(session: Session, session_factory) -> TestClient:
    """Legacy shared handler Session; setup commits remain explicit in each test."""

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_authentication_session_factory] = lambda: (
        session_factory
    )
    with TestClient(app) as value:
        yield value
    app.dependency_overrides.clear()


@pytest.fixture
def request_client(session_factory) -> TestClient:
    """Match production transaction lifetime: one handler Session per request."""

    def override_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_authentication_session_factory] = lambda: (
        session_factory
    )
    with TestClient(app) as value:
        yield value
    app.dependency_overrides.clear()
