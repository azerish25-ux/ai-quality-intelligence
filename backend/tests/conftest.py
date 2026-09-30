from __future__ import annotations

import os

os.environ.setdefault("FAILURELENS_DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("FAILURELENS_ARTIFACT_ROOT", "/tmp/failurelens-test-artifacts")
os.environ.setdefault("FAILURELENS_DEMO_MODE", "true")

import pytest
from failurelens.api import app
from failurelens.config import get_settings
from failurelens.db import Base, create_database_engine, get_session
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def session(tmp_path, monkeypatch) -> Session:
    monkeypatch.setenv("FAILURELENS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    get_settings.cache_clear()
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as value:
        yield value
    Base.metadata.drop_all(engine)
    engine.dispose()
    get_settings.cache_clear()


@pytest.fixture
def client(session: Session) -> TestClient:
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as value:
        yield value
    app.dependency_overrides.clear()
