"""Run the Docker fixture logic with SQLite; never count this as Docker/PostgreSQL."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from failurelens.api import app
from failurelens.config import get_settings
from failurelens.db import Base, get_session
from failurelens.provider_jobs import heartbeat_provider_worker, run_provider_once
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from integrations.provider import fixture_check, fixture_worker


def test_synthetic_fixture_seed_api_submission_worker_and_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = {
        "FAILURELENS_ARTIFACT_ROOT": str(tmp_path / "artifacts"),
        "FAILURELENS_DEMO_MODE": "false",
        "FAILURELENS_SESSION_COOKIE_SECURE": "true",
        "FAILURELENS_BOOTSTRAP_ADMIN_USERNAME": "provider-bootstrap@example.test",
        "FAILURELENS_BOOTSTRAP_ADMIN_PASSWORD": "synthetic-bootstrap-canary-592",
        "FAILURELENS_PROVIDER_ENABLED": "true",
        "FAILURELENS_PROVIDER_ID": "synthetic-provider-fixture",
        "FAILURELENS_PROVIDER_ALLOWED_PROJECT_IDS": fixture_check.PROJECT,
        "FAILURELENS_PROVIDER_ENDPOINT": fixture_worker.ENDPOINT,
        "FAILURELENS_PROVIDER_MODEL": "test-fixture-not-a-model",
        "FAILURELENS_PROVIDER_PROXY": "http://provider-proxy:8080",
        "FAILURELENS_PROVIDER_MAX_ATTEMPTS": "1",
        "FAILURELENS_PROVIDER_MIN_INTERVAL_SECONDS": "0",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("FAILURELENS_PROVIDER_TOKEN", raising=False)
    get_settings.cache_clear()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'deployment-fixture.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(fixture_check, "SessionLocal", factory)
    settings = get_settings().model_copy(
        update={"provider_token": SecretStr(fixture_worker.TOKEN)}
    )

    def sessions():
        with factory() as session:
            yield session

    def forbidden(*args, **kwargs):
        raise AssertionError("fixture attempted actual network")

    def tick(check, predicate):
        # Exercise the same durable worker and HTTP handlers using independent
        # SQLite sessions. Actual concurrent processes belong to Docker CI.
        run_provider_once(factory, settings, provider_factory=fixture_worker.provider)
        result = check()
        assert predicate(result), "fixture did not reach its expected state"
        return result

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(fixture_check, "eventually", tick)
    app.dependency_overrides[get_session] = sessions
    try:
        fixtures = fixture_check.seed()
        assert heartbeat_provider_worker(factory, settings)
        client = TestClient(app)
        try:
            result = fixture_check.verify(fixtures, client)
        finally:
            client.close()
        assert result == {
            "success": {"status": "proposed", "attempts": 1, "cost_status": "unknown"},
            "outage": {"status": "fallback", "attempts": 1, "cost_status": "unknown"},
        }
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        get_settings.cache_clear()


def test_deployment_fixture_rejects_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from failurelens.config import Settings

    monkeypatch.setattr(fixture_check, "get_settings", lambda: Settings(demo_mode=True))
    with pytest.raises(AssertionError):
        fixture_check.seed()


@pytest.mark.parametrize("service", ["api", "worker", "provider-worker"])
def test_optional_compose_overrides_every_application_database_url(
    service: str,
) -> None:
    """Static overlay contract; actual missing/empty expansion is a Docker CI gate."""
    import re

    import yaml

    root = Path(__file__).resolve().parents[2]
    base = yaml.safe_load((root / "compose.yaml").read_text())
    overlay = yaml.safe_load((root / "compose.provider.yaml").read_text())
    effective = {
        **base["services"].get(service, {}).get("environment", {}),
        **overlay["services"][service]["environment"],
    }
    value = effective["FAILURELENS_DATABASE_URL"]
    # ${name:?message} rejects both absent and empty values. A default, an
    # unqualified expansion, or accidentally inherited demo URL fails this test.
    assert re.fullmatch(r"\$\{FAILURELENS_PROVIDER_DATABASE_URL:\?[^{}]+\}", value)
    assert value != base["services"]["api"]["environment"]["FAILURELENS_DATABASE_URL"]


def test_optional_compose_database_password_is_required_and_scoped() -> None:
    import re

    import yaml

    root = Path(__file__).resolve().parents[2]
    base = yaml.safe_load((root / "compose.yaml").read_text())
    overlay = yaml.safe_load((root / "compose.provider.yaml").read_text())
    effective = {
        **base["services"]["db"]["environment"],
        **overlay["services"]["db"]["environment"],
    }
    value = effective["POSTGRES_PASSWORD"]
    assert re.fullmatch(r"\$\{FAILURELENS_PROVIDER_DATABASE_PASSWORD:\?[^{}]+\}", value)
    assert value != base["services"]["db"]["environment"]["POSTGRES_PASSWORD"]
    proxy = overlay["services"]["provider-proxy"]
    assert "FAILURELENS_DATABASE_URL" not in proxy["environment"]
    assert "POSTGRES_PASSWORD" not in proxy["environment"]
    assert "env_file" not in proxy
