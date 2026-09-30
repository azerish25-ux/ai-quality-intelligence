"""Actual API/PostgreSQL/fixture-worker assertions for disposable Docker CI."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from functools import partial
from typing import Any

import httpx
from failurelens.auth import create_user
from failurelens.config import get_settings
from failurelens.db import SessionLocal
from failurelens.models import (
    Analysis,
    Category,
    Failure,
    ModelAttempt,
    ModelInvocation,
    Project,
)
from failurelens.schemas import IngestionRequest
from failurelens.service import analyze_and_persist, ingest_normalized
from sqlalchemy import func, select

PROJECT = "provider-smoke-project"
PASSWORD = "disposable-fixture-only-593"
PRIVATE = "synthetic-evidence-canary-935"


def eventually(check: Callable[[], Any], predicate: Callable[[Any], bool]) -> Any:
    deadline = time.monotonic() + 45
    while True:
        result = check()
        if predicate(result):
            return result
        assert time.monotonic() < deadline, "bounded fixture wait expired"
        time.sleep(0.1)


def fetch(client: httpx.Client, path: str) -> Any:
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def seed() -> dict[str, dict[str, str]]:
    settings = get_settings()
    assert not settings.demo_mode and settings.session_cookie_secure
    assert settings.provider_token is None
    settings.validate_security()
    assert (
        settings.provider_endpoint
        == "https://provider.fixture.invalid/v1/chat/completions"
    )
    fixtures: dict[str, dict[str, str]] = {}
    with SessionLocal() as session:
        assert session.get(Project, PROJECT) is None, "refuse nonempty fixture scope"
        project = Project(
            id=PROJECT, slug=PROJECT, name="Disposable synthetic provider checks"
        )
        session.add(project)
        create_user(
            session,
            username="provider-fixture@example.test",
            display_name="Fixture administrator",
            password=PASSWORD,
            system_admin=True,
        )
        session.commit()
        for scenario in ("success", "outage"):
            marker = (
                "synthetic_outage_marker_706"
                if scenario == "outage"
                else "synthetic_success_marker_735"
            )
            run = ingest_normalized(
                session,
                project,
                IngestionRequest.model_validate(
                    {
                        "external_id": "provider-fixture-" + scenario,
                        "observations": [
                            {
                                "test_identity": "synthetic-duplicate-" + scenario,
                                "outcome": "failed",
                                "message": "balance invariant violated: duplicate committed transfer "
                                + marker
                                + " token="
                                + PRIVATE,
                                "details": {"data_integrity_violation": True},
                            }
                        ],
                    }
                ),
            )
            failure = session.scalar(select(Failure).where(Failure.run_id == run.id))
            assert failure is not None
            analyze_and_persist(session, failure)
            analysis = session.scalar(
                select(Analysis).where(Analysis.failure_id == failure.id)
            )
            assert analysis is not None and analysis.category == Category.product_defect
            fixtures[scenario] = {"run_id": run.id, "analysis_id": analysis.id}
    return fixtures


def verify(fixtures: dict[str, dict[str, str]], client: httpx.Client) -> dict[str, Any]:
    results: dict[str, Any] = {}
    # Production authentication must close the demo privilege-minting route.
    anonymous = client.post(
        "/api/v1/users",
        json={
            "username": "untrusted-fixture@example.test",
            "display_name": "Untrusted fixture",
            "password": PASSWORD,
            "system_admin": True,
        },
    )
    assert anonymous.status_code == 401
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "provider-fixture@example.test", "password": PASSWORD},
    )
    login.raise_for_status()
    assert login.json()["principal"]["demo_mode"] is False
    token = login.json()["access_token"]
    client.headers["Authorization"] = "Bearer " + token
    status_url = f"/api/v1/projects/{PROJECT}/provider/status"
    state = eventually(
        lambda: client.get(status_url).json(),
        lambda body: body.get("availability") == "ready",
    )
    assert state["can_submit"] and state["admission"]["worker_available"]
    assert state["cost_status"] == "unknown"
    assert state["destination"]["endpoint"] == "https://provider.fixture.invalid"
    for scenario, fixture in fixtures.items():
        base = f"/api/v1/projects/{PROJECT}/runs/{fixture['run_id']}/analyses/{fixture['analysis_id']}/provider"
        preview = eventually(
            partial(fetch, client, base + "/preview"),
            lambda body: body.get("can_submit") is True,
        )
        assert preview["evidence"] and PRIVATE not in json.dumps(preview)
        body = {
            key: preview[key]
            for key in (
                "analysis_revision",
                "configuration_digest",
                "preview_digest",
            )
        }
        body["idempotency_key"] = "provider-fixture-" + scenario
        submitted = client.post(base + "/invocations", json=body)
        assert submitted.status_code == 202
        invocation_id = submitted.json()["invocation_id"]
        endpoint = base + "/invocations/" + invocation_id
        result = eventually(
            partial(fetch, client, endpoint),
            lambda item: item.get("invocation_state") not in {"queued", "running"},
        )
        expected = "proposed" if scenario == "success" else "fallback"
        assert result["status"] == expected, "unexpected fixture terminal state"
        assert result["validation_status"] == "unverified_hypotheses_only"
        assert result["deterministic_category"] == "product_defect"
        assert result["budget"]["requests"] == 1 and len(result["attempts"]) == 1
        assert result["attempts"][0]["transport_terminated"] is True
        assert result["cost_status"] == "unknown"
        assert not any(
            canary in json.dumps(result)
            for canary in (
                PRIVATE,
                token,
                PASSWORD,
                "synthetic-worker-only-canary-534",
                "synthetic-transport-canary-716",
            )
        )
        if scenario == "success":
            assert result["proposal"] and result["usage"] == {
                "prompt_tokens": 100,
                "completion_tokens": 50,
            }
        else:
            assert result["proposal"] is None and result["usage"] is None
        duplicate = client.post(base + "/invocations", json=body)
        assert (
            duplicate.status_code == 202
            and duplicate.json()["invocation_id"] == invocation_id
        )
        with SessionLocal() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ModelAttempt)
                    .where(ModelAttempt.invocation_id == invocation_id)
                )
                == 1
            )
            persisted = session.get(ModelInvocation, invocation_id)
            assert persisted is not None and persisted.status == expected
            original = session.get(Analysis, fixture["analysis_id"])
            assert original is not None and original.category == Category.product_defect
        results[scenario] = {
            "status": result["status"],
            "attempts": 1,
            "cost_status": result["cost_status"],
        }
    overview = client.get("/api/v1/overview")
    overview.raise_for_status()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-disposable-stack", action="store_true", required=True
    )
    parser.parse_args()
    assert SessionLocal.kw["bind"].dialect.name == "postgresql", (
        "this gate requires real PostgreSQL"
    )
    fixtures = seed()
    with httpx.Client(
        base_url="http://127.0.0.1:8000", timeout=5, trust_env=False
    ) as client:
        results = verify(fixtures, client)
    print(
        json.dumps(
            {
                "status": "passed",
                "scope": "synthetic_actual_api_postgresql_fixture_worker",
                "real_model_connectivity_tested": False,
                "metadata_readiness_only": True,
                "sensitive_canaries_absent": True,
                "results": results,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
