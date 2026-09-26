from __future__ import annotations

import os

os.environ.setdefault("FAILURELENS_DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("FAILURELENS_ARTIFACT_ROOT", "/tmp/failurelens-test-artifacts")
os.environ.setdefault("FAILURELENS_DEMO_MODE", "true")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from failurelens.api import app
from failurelens.db import Base, create_database_engine, get_session


@pytest.fixture
def session() -> Session:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as value:
        yield value
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(session: Session) -> TestClient:
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as value:
        yield value
    app.dependency_overrides.clear()
