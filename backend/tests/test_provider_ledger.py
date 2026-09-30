"""Network-free durable provider contracts, using independent database sessions."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import json
import threading

import httpx
import pytest
from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from failurelens import models as m
from failurelens.config import get_settings
from failurelens.db import Base
from failurelens.demo import seed_demo
from failurelens.provider_service import (
    ProviderIdempotencyConflict, ProviderScopeError, durable_propose_for_analysis,
    get_model_invocation, recover_model_invocations,
)
from failurelens.providers import HTTPModelProvider, ProviderConfig, prepare_request

CONFIG = ProviderConfig(endpoint="https://provider.example/v1/chat/completions",
    model="test-fixture-not-a-model", token="private-test-credential", enabled=True,
    min_interval_seconds=0, max_attempts=1, max_run_requests=5)


@pytest.fixture
def ledger_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("FAILURELENS_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    get_settings.cache_clear()
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'ledger.db'}", connect_args={"timeout": 10})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield factory
    engine.dispose()
    get_settings.cache_clear()


def seed_scope(factory):
    with factory() as session:
        scope = seed_demo(session)
        analysis = session.scalar(select(m.Analysis).where(m.Analysis.category == m.Category.product_defect).order_by(m.Analysis.id))
        return scope | {"analysis_id": analysis.id}


def reservation_size(factory, scope):
    from failurelens.service import select_failure_evidence
    with factory() as session:
        analysis = session.get(m.Analysis, scope["analysis_id"])
        allowed = set(analysis.supporting_evidence_ids + analysis.contradictory_evidence_ids)
        evidence = [{"id": row.id, "excerpt": row.excerpt, "approved": True}
                    for row in select_failure_evidence(session, analysis.failure) if row.id in allowed]
        return prepare_request(CONFIG, analysis.category.value, evidence).reserved_tokens


def good_response(request, *, usage=None, text="Inspect the measured effect", category="product_defect"):
    context = json.loads(json.loads(request.content)["messages"][1]["content"])
    proposal = {"category": category,
        "hypotheses": [{"text": text, "evidence_ids": [context["evidence"][0]["id"]]}],
        "contradictory_evidence_ids": [], "missing_evidence": []}
    return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(proposal)}}],
        "usage": usage if usage is not None else {"prompt_tokens": 100, "completion_tokens": 50}})


def invoke(factory, scope, *, key="request-one", config=CONFIG, handler=good_response, cancel=None):
    provider = HTTPModelProvider(config, transport=httpx.MockTransport(handler))
    try:
        return durable_propose_for_analysis(factory, provider, **scope, idempotency_key=key, cancel=cancel)
    finally:
        provider.close()


def fetch(factory, scope, result):
    return get_model_invocation(factory, **scope, invocation_id=result["invocation_id"])


def test_durable_success_commits_before_transport_and_replays_without_egress(ledger_factory):
    scope = seed_scope(ledger_factory)
    calls = []
    def handler(request):
        calls.append(request)
        # An independent writer proves the transport does not hold the project lock.
        with ledger_factory.begin() as session:
            session.execute(update(m.Project).where(m.Project.id == scope["project_id"]).values(name="Concurrent writer"))
            budget = session.get(m.ModelRunBudget, scope["run_id"])
            attempt = session.scalar(select(m.ModelAttempt))
            assert budget.requests == 1 and budget.reserved_tokens > 0
            assert attempt.status == "reserved" and attempt.spend_status == "unknown"
        return good_response(request)
    result = invoke(ledger_factory, scope, handler=handler)
    again = invoke(ledger_factory, scope, handler=lambda _: pytest.fail("duplicate transport"))
    assert result == again == fetch(ledger_factory, scope, result)
    assert result["status"] == "proposed" and result["usage_complete"]
    assert result["validation_status"] == "unverified_hypotheses_only"
    assert result["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
    assert result["attempts"][0]["spend_status"] == "reported"
    assert len(calls) == 1
    with ledger_factory() as session:
        assert session.get(m.Analysis, scope["analysis_id"]).category == m.Category.product_defect


def test_disabled_does_not_create_ledger_or_call_transport(ledger_factory):
    scope = seed_scope(ledger_factory)
    result = invoke(ledger_factory, scope, config=replace(CONFIG, enabled=False), handler=lambda _: pytest.fail("disabled egress"))
    assert result["reason"] == "disabled"
    with ledger_factory() as session:
        assert session.scalar(select(func.count()).select_from(m.ModelInvocation)) == 0
        assert session.scalar(select(func.count()).select_from(m.ModelRunBudget)) == 0


@pytest.mark.parametrize("kind", ["requests", "tokens"])
def test_restart_and_configuration_changes_cannot_reset_run_limits(ledger_factory, kind):
    scope = seed_scope(ledger_factory)
    config = replace(CONFIG, max_run_requests=1) if kind == "requests" else replace(CONFIG, max_run_reserved_tokens=reservation_size(ledger_factory, scope))
    result = invoke(ledger_factory, scope, config=config)
    assert result["status"] == "proposed"
    # A fresh provider instance plus larger limits cannot discard persisted ceilings.
    next_result = invoke(ledger_factory, scope, key="request-two",
        config=replace(CONFIG, max_run_requests=100, max_run_reserved_tokens=1_000_000),
        handler=lambda _: pytest.fail("persisted ceiling bypass"))
    assert next_result["reason"] == "run_budget_exhausted"
    assert next_result["budget"]["requests"] == 1
    assert next_result["budget"]["max_requests"] == config.max_run_requests
    assert next_result["budget"]["max_reserved_tokens"] == config.max_run_reserved_tokens


def test_stricter_limit_is_persisted_and_not_relaxed(ledger_factory):
    scope = seed_scope(ledger_factory)
    invoke(ledger_factory, scope)
    result = invoke(ledger_factory, scope, key="tight", config=replace(CONFIG, max_run_requests=1))
    assert result["reason"] == "run_budget_exhausted"
    result = invoke(ledger_factory, scope, key="loose", handler=lambda _: pytest.fail("limit reset"))
    assert result["reason"] == "run_budget_exhausted" and result["budget"]["max_requests"] == 1


def test_scope_idempotency_and_credential_rotation(ledger_factory):
    scope = seed_scope(ledger_factory)
    result = invoke(ledger_factory, scope)
    assert invoke(ledger_factory, scope, config=replace(CONFIG, token="rotated-test-credential")) == result
    for field in ("project_id", "run_id", "analysis_id"):
        with pytest.raises(ProviderScopeError):
            invoke(ledger_factory, scope | {field: m.new_id()})
        with pytest.raises(ProviderScopeError):
            fetch(ledger_factory, scope | {field: m.new_id()}, result)
    with ledger_factory() as session:
        other_analysis = session.scalar(select(m.Analysis.id).where(m.Analysis.id != scope["analysis_id"]))
    with pytest.raises(ProviderIdempotencyConflict):
        invoke(ledger_factory, scope | {"analysis_id": other_analysis})
    with pytest.raises(ProviderIdempotencyConflict):
        invoke(ledger_factory, scope, config=replace(CONFIG, model="changed-fixture-model"))


def test_mutated_analysis_and_cached_proposals_are_withheld(ledger_factory):
    scope = seed_scope(ledger_factory)
    result = invoke(ledger_factory, scope)
    with ledger_factory.begin() as session:
        invocation = session.get(m.ModelInvocation, result["invocation_id"])
        invocation.proposal_json = invocation.proposal_json | {"hypotheses": [{"text": "token=abcdef123456", "evidence_ids": []}]}
    assert fetch(ledger_factory, scope, result)["reason"] == "sensitive_output"
    with ledger_factory.begin() as session:
        session.get(m.Analysis, scope["analysis_id"]).summary = "Changed immutable analysis"
    assert fetch(ledger_factory, scope, result)["reason"] == "immutable_input_changed"
    with pytest.raises(ProviderIdempotencyConflict):
        invoke(ledger_factory, scope)


@pytest.mark.parametrize("change", ["restrict", "delete", "digest"])
def test_changed_derivative_is_never_replayed(ledger_factory, change):
    scope = seed_scope(ledger_factory)
    result = invoke(ledger_factory, scope)
    with ledger_factory.begin() as session:
        analysis = session.get(m.Analysis, scope["analysis_id"])
        evidence = session.get(m.Evidence, analysis.supporting_evidence_ids[0])
        if change == "restrict":
            evidence.derivative.restricted = True
        elif change == "digest":
            evidence.derivative.digest = "0" * 64
        else:
            from pathlib import Path
            (get_settings().artifact_root / evidence.derivative.storage_path).unlink()
    replay = invoke(ledger_factory, scope, handler=lambda _: pytest.fail("invalid replay"))
    assert replay["reason"] == "evidence_not_available" and replay["proposal"] is None
    assert replay["budget"]["requests"] == 1


def test_retention_during_transport_erases_proposal_but_preserves_usage(ledger_factory):
    from failurelens.retention import _scrub_run, lock_project
    scope = seed_scope(ledger_factory)
    def handler(request):
        response = good_response(request)
        with ledger_factory.begin() as session:
            lock_project(session, scope["project_id"])
            _scrub_run(session, session.get(m.Run, scope["run_id"]), 1)
        return response
    result = invoke(ledger_factory, scope, handler=handler)
    assert result["reason"] == "evidence_expired" and result["proposal"] is None
    assert result["usage"]["prompt_tokens"] == 100
    with ledger_factory() as session:
        assert session.get(m.ModelInvocation, result["invocation_id"]).proposal_json is None
        assert session.get(m.ModelRunBudget, scope["run_id"]).requests == 1


def test_completed_proposal_is_physically_scrubbed_on_retention(ledger_factory):
    from failurelens.retention import _scrub_run, lock_project
    scope = seed_scope(ledger_factory)
    result = invoke(ledger_factory, scope)
    with ledger_factory.begin() as session:
        lock_project(session, scope["project_id"])
        _scrub_run(session, session.get(m.Run, scope["run_id"]), 1)
    with ledger_factory() as session:
        assert session.get(m.ModelInvocation, result["invocation_id"]).proposal_json is None
        assert session.scalar(select(m.ModelAttempt.prompt_tokens)) == 100
    assert fetch(ledger_factory, scope, result)["reason"] == "evidence_expired"


def test_rejected_response_preserves_allowlisted_usage_and_pricing_without_secrets(ledger_factory):
    scope = seed_scope(ledger_factory)
    config = replace(CONFIG, input_price_per_million=2, output_price_per_million=4,
        pricing_source="Operator published fixture prices", pricing_date="2026-09-30", currency="USD")
    result = invoke(ledger_factory, scope, config=config, key="token=private-key-in-input",
        handler=lambda req: good_response(req, text="token=abcdef123456",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "private": "response-secret"}))
    assert result["reason"] == "sensitive_output" and result["proposal"] is None
    assert result["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
    assert result["estimated_cost"] == pytest.approx(.0004)
    assert result["attempts"][0]["pricing"]["source"] == config.pricing_source
    with ledger_factory() as session:
        records = [dict(row) for table in (m.ModelInvocation, m.ModelAttempt, m.ModelRunBudget)
                   for row in session.execute(select(table.__table__)).mappings()]
    serialized = str(records) + str(result)
    for secret in (config.token, config.endpoint, config.model, "abcdef123456", "response-secret", "private-key-in-input"):
        assert secret not in serialized
    assert "messages" not in serialized and "content" not in serialized


def test_usage_overrun_is_accounted_and_blocks_further_spend(ledger_factory):
    scope = seed_scope(ledger_factory)
    result = invoke(ledger_factory, scope,
        handler=lambda req: good_response(req, usage={"prompt_tokens": 30_000, "completion_tokens": 50}))
    assert result["budget"]["reserved_tokens"] == 30_050
    assert result["attempts"][0]["accounted_tokens"] == 30_050
    result = invoke(ledger_factory, scope, key="second", handler=lambda _: pytest.fail("overrun bypass"))
    assert result["reason"] == "run_budget_exhausted"


def test_retries_record_every_attempt_and_partial_usage_is_unknown_cost(ledger_factory):
    scope = seed_scope(ledger_factory)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503, text="private response") if len(calls) == 1 else good_response(request)
    result = invoke(ledger_factory, scope, config=replace(CONFIG, max_attempts=2), handler=handler)
    assert result["status"] == "proposed" and len(calls) == 2
    assert [a["reason"] for a in result["attempts"]] == ["http_503", None]
    assert result["budget"]["requests"] == 2 and not result["usage_complete"]
    assert result["cost_status"] == "unknown" and result["estimated_cost"] is None


def test_retries_revalidate_revoked_evidence(ledger_factory):
    scope = seed_scope(ledger_factory)
    calls = []
    def handler(request):
        calls.append(request)
        with ledger_factory.begin() as session:
            analysis = session.get(m.Analysis, scope["analysis_id"])
            session.get(m.Evidence, analysis.supporting_evidence_ids[0]).derivative.restricted = True
        return httpx.Response(503)
    result = invoke(ledger_factory, scope, config=replace(CONFIG, max_attempts=2), handler=handler)
    assert result["reason"] == "evidence_not_available" and len(calls) == 1
    assert result["budget"]["requests"] == 1


def test_timeout_and_cancellation_keep_unknown_reservations(ledger_factory):
    scope = seed_scope(ledger_factory)
    def timeout(request):
        raise httpx.ReadTimeout("private transport detail", request=request)
    result = invoke(ledger_factory, scope, handler=timeout)
    assert result["reason"] == "transport_or_response_error"
    assert result["attempts"][0]["spend_status"] == "unknown"
    cancelled = threading.Event()
    def cancel(request):
        cancelled.set()
        return good_response(request)
    result = invoke(ledger_factory, scope, key="cancel", handler=cancel, cancel=cancelled)
    assert result["reason"] == "cancelled" and result["proposal"] is None
    assert result["budget"]["requests"] == 2 and result["budget"]["reserved_tokens"] > 0


def test_crash_recovery_never_refunds_or_replays_and_fences_late_completion(ledger_factory):
    scope = seed_scope(ledger_factory)
    def crash(_):
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        invoke(ledger_factory, scope, config=replace(CONFIG, max_run_requests=1), handler=crash)
    duplicate = invoke(ledger_factory, scope, config=replace(CONFIG, max_run_requests=1), handler=lambda _: pytest.fail("crash replay"))
    assert duplicate["reason"] == "invocation_in_progress"
    assert duplicate["attempts"][0]["status"] == "reserved"
    assert recover_model_invocations(ledger_factory, project_id=scope["project_id"], run_id=scope["run_id"]) == 0
    with ledger_factory.begin() as session:
        session.get(m.ModelInvocation, duplicate["invocation_id"]).lease_expires_at = m.utcnow() - timedelta(seconds=1)
    assert recover_model_invocations(ledger_factory, project_id=scope["project_id"], run_id=scope["run_id"]) == 1
    recovered = invoke(ledger_factory, scope, config=replace(CONFIG, max_run_requests=1))
    assert recovered["reason"] == "invocation_interrupted"
    assert recovered["attempts"][0]["status"] == "uncertain"
    assert recovered["budget"] == duplicate["budget"]
    assert invoke(ledger_factory, scope, key="new")["reason"] == "run_budget_exhausted"


def test_recovery_while_transport_running_fences_late_result(ledger_factory):
    scope = seed_scope(ledger_factory)
    def handler(request):
        with ledger_factory.begin() as session:
            invocation = session.scalar(select(m.ModelInvocation))
            invocation.lease_expires_at = m.utcnow() - timedelta(seconds=1)
        assert recover_model_invocations(ledger_factory, project_id=scope["project_id"], run_id=scope["run_id"]) == 1
        return good_response(request)
    result = invoke(ledger_factory, scope, handler=handler)
    assert result["reason"] == "invocation_interrupted" and result["proposal"] is None
    assert result["invocation_state"] == "uncertain"
    assert result["attempts"][0]["spend_status"] == "reported"
    assert result["attempts"][0]["status"] == "reconciled"
    assert result["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}


def test_reservation_commit_failure_never_calls_transport(ledger_factory):
    scope = seed_scope(ledger_factory)
    @event.listens_for(Session, "before_commit")
    def reject_attempt_commit(session):
        if any(isinstance(row, m.ModelAttempt) for row in session.new):
            raise OperationalError("reservation failed", {}, Exception("private database detail"))
    try:
        result = invoke(ledger_factory, scope, handler=lambda _: pytest.fail("uncommitted reservation sent"))
    finally:
        event.remove(Session, "before_commit", reject_attempt_commit)
    assert result["reason"] == "ledger_unavailable"
    with ledger_factory() as session:
        assert session.get(m.ModelRunBudget, scope["run_id"]).requests == 0
        assert session.scalar(select(func.count()).select_from(m.ModelAttempt)) == 0


@pytest.mark.parametrize("dimension", ["requests", "tokens", "idempotency"])
def test_sqlite_independent_workers_share_reservations(ledger_factory, dimension):
    from concurrent.futures import ThreadPoolExecutor
    scope = seed_scope(ledger_factory)
    barrier, calls, guard = threading.Barrier(2), [], threading.Lock()
    config = replace(CONFIG, max_run_requests=1) if dimension == "requests" else replace(CONFIG, max_run_reserved_tokens=reservation_size(ledger_factory, scope))
    def handler(request):
        with guard:
            calls.append(request)
        return good_response(request)
    def worker(number):
        barrier.wait(timeout=5)
        return invoke(ledger_factory, scope, key="same" if dimension == "idempotency" else str(number), config=config, handler=handler)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, number) for number in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert len(calls) == 1
    if dimension == "idempotency":
        assert len({result["invocation_id"] for result in results}) == 1
    else:
        assert sorted(result["status"] for result in results) == ["fallback", "proposed"]
    with ledger_factory() as session:
        budget = session.get(m.ModelRunBudget, scope["run_id"])
        assert budget.requests == 1 and budget.reserved_tokens <= budget.max_reserved_tokens
        assert session.scalar(select(func.count()).select_from(m.ModelAttempt)) == 1


def test_partial_usage_is_rejected_by_database_constraint(ledger_factory):
    from sqlalchemy.exc import IntegrityError
    scope = seed_scope(ledger_factory)
    result = invoke(ledger_factory, scope)
    for prompt, completion in ((None, 1), (1, None), (-1, 1)):
        with pytest.raises(IntegrityError):
            with ledger_factory.begin() as session:
                session.add(m.ModelAttempt(invocation_id=result["invocation_id"], owner_token=m.new_id(), number=2,
                    reserved_tokens=100, accounted_tokens=100, prompt_tokens=prompt, completion_tokens=completion))


def test_missing_invocation_after_scoped_delete_fails_closed(ledger_factory):
    from sqlalchemy import delete
    scope = seed_scope(ledger_factory)
    def handler(request):
        with ledger_factory.begin() as session:
            session.execute(delete(m.ModelInvocation).where(m.ModelInvocation.run_id == scope["run_id"]))
        return good_response(request)
    result = invoke(ledger_factory, scope, handler=handler)
    assert result["status"] == "fallback" and result["proposal"] is None
    assert result["reason"] == "invocation_interrupted"


def test_migration_roundtrip_matches_ledger_models(tmp_path, monkeypatch):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    root = Path(__file__).resolve().parents[1]
    url = f"sqlite+pysqlite:///{tmp_path / 'migrated.db'}"
    monkeypatch.setenv("FAILURELENS_DATABASE_URL", url)
    get_settings.cache_clear()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    try:
        command.upgrade(cfg, "head")
        engine = create_engine(url)
        inspector = inspect(engine)
        for model in (m.ModelRunBudget, m.ModelInvocation, m.ModelAttempt):
            assert {col["name"] for col in inspector.get_columns(model.__tablename__)} == set(model.__table__.columns.keys())
        assert any(item["name"] == "ck_model_attempt_usage" for item in inspector.get_check_constraints("model_attempts"))
        engine.dispose()
        command.downgrade(cfg, "c8f2e6a9d410")
        command.upgrade(cfg, "head")
    finally:
        get_settings.cache_clear()


def test_total_deadline_preserves_uncertain_spend_and_never_replays(ledger_factory):
    import time
    scope = seed_scope(ledger_factory)
    release, finished = threading.Event(), threading.Event()
    config = replace(CONFIG, timeout_seconds=.08, max_attempts=3)
    def handler(request):
        try:
            assert release.wait(3)
            return good_response(request)
        finally:
            finished.set()
    try:
        start = time.monotonic()
        result = invoke(ledger_factory, scope, config=config, handler=handler)
        assert time.monotonic() - start < 1
        assert result["reason"] == "transport_deadline_exceeded"
        assert result["attempts"][0]["spend_status"] == "unknown"
        assert result["budget"]["requests"] == 1 and not result["usage_complete"]
    finally:
        release.set()
        assert finished.wait(3)
    replay = invoke(ledger_factory, scope, config=config, handler=lambda _: pytest.fail("deadline replay"))
    assert replay["reason"] == "transport_deadline_exceeded" and replay["proposal"] is None
    assert replay["budget"] == result["budget"]
