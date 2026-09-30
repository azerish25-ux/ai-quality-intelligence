"""Real PostgreSQL races; skip explicitly without the real PostgreSQL lane."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier, Event, Lock

import pytest
from sqlalchemy import func, select

from failurelens import models as m
from failurelens.config import get_settings
from failurelens.provider_service import recover_model_invocations
from test_operations_postgres import pg_factory
from test_provider_ledger import CONFIG, good_response, invoke, reservation_size, seed_scope


@pytest.fixture
def pg_ledger(pg_factory, monkeypatch):
    factory, settings = pg_factory
    monkeypatch.setenv("FAILURELENS_ARTIFACT_ROOT", str(settings.artifact_root))
    get_settings.cache_clear()
    yield factory
    get_settings.cache_clear()


@pytest.mark.parametrize("dimension", ["requests", "tokens", "idempotency"])
def test_postgres_workers_cannot_double_reserve_or_duplicate_transport(pg_ledger, dimension):
    scope = seed_scope(pg_ledger)
    config = replace(CONFIG, max_run_requests=1) if dimension == "requests" else replace(CONFIG, max_run_reserved_tokens=reservation_size(pg_ledger, scope))
    barrier, guard, calls = Barrier(2), Lock(), []
    def handler(request):
        with guard:
            calls.append(request)
        return good_response(request)
    def worker(number):
        barrier.wait(timeout=10)
        return invoke(pg_ledger, scope, key="same-key" if dimension == "idempotency" else str(number), config=config, handler=handler)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, number) for number in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert len(calls) == 1
    assert any(result["status"] == "proposed" for result in results)
    if dimension == "idempotency":
        assert len({result["invocation_id"] for result in results}) == 1
    else:
        assert sum(result.get("reason") == "run_budget_exhausted" for result in results) == 1
    with pg_ledger() as session:
        budget = session.get(m.ModelRunBudget, scope["run_id"])
        assert budget.requests == 1 and budget.reserved_tokens <= budget.max_reserved_tokens
        assert session.scalar(select(func.count()).select_from(m.ModelAttempt)) == 1


def test_postgres_recovered_owner_reconciles_usage_without_overwriting_successor(pg_ledger):
    scope = seed_scope(pg_ledger)
    entered, release = Event(), Event()
    def handler(request):
        entered.set()
        assert release.wait(10)
        return good_response(request)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(invoke, pg_ledger, scope, handler=handler)
        assert entered.wait(10)
        # This independent write must proceed while the network request is open.
        with pg_ledger.begin() as session:
            invocation = session.scalar(select(m.ModelInvocation))
            invocation.lease_expires_at = m.utcnow() - timedelta(seconds=1)
        assert recover_model_invocations(pg_ledger, project_id=scope["project_id"], run_id=scope["run_id"]) == 1
        successor = invoke(pg_ledger, scope, key="explicit-new-request")
        assert successor["status"] == "proposed"
        release.set()
        original = first.result(timeout=15)
    assert original["invocation_state"] == "uncertain" and original["proposal"] is None
    assert original["attempts"][0]["status"] == "reconciled"
    assert original["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
    with pg_ledger() as session:
        assert session.get(m.ModelRunBudget, scope["run_id"]).requests == 2
        assert session.get(m.ModelInvocation, successor["invocation_id"]).status == "proposed"


def test_postgres_retention_during_transport_cannot_republish_proposal(pg_ledger):
    from failurelens.retention import _scrub_run, lock_project
    scope = seed_scope(pg_ledger)
    entered, release = Event(), Event()
    def handler(request):
        entered.set()
        assert release.wait(10)
        return good_response(request)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(invoke, pg_ledger, scope, handler=handler)
        assert entered.wait(10)
        with pg_ledger.begin() as session:
            lock_project(session, scope["project_id"])
            _scrub_run(session, session.get(m.Run, scope["run_id"]), 1)
        release.set()
        result = future.result(timeout=15)
    assert result["reason"] == "evidence_expired" and result["proposal"] is None
    assert result["usage"]["prompt_tokens"] == 100
    with pg_ledger() as session:
        assert session.get(m.ModelInvocation, result["invocation_id"]).proposal_json is None
        assert session.get(m.ModelRunBudget, scope["run_id"]).requests == 1
