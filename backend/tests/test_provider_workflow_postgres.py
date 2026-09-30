"""Real PostgreSQL provider-queue races; fixture transports never reach a network."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from threading import Barrier, Event, Lock

import httpx
import pytest
from failurelens import models as m
from failurelens.demo import seed_demo
from failurelens.provider_jobs import (
    PROVIDER_JOB_KIND,
    ApplicationAttemptBudget,
    cancel_model_invocation,
    claim_provider_job,
    database_now,
    heartbeat_provider_worker,
    provider_preview,
    provider_status,
    recover_provider_jobs,
    run_provider_once,
    submit_model_invocation,
)
from failurelens.provider_schemas import ProviderSubmit
from failurelens.provider_service import _digest
from failurelens.providers import ProviderBoundaryError, ProviderResult, prepare_request
from pydantic import SecretStr
from sqlalchemy import func, select
from test_provider_ledger import good_response
from test_provider_retention import cleanup_via_queue
from test_provider_workflow import (
    application_scope,
    expire_claim,
    fixture_provider,
    read,
    submit,
)

pytest_plugins = ("test_operations_postgres", "test_provider_ledger_postgres")


def independent_scopes(factory):
    """Give two real projects their own run, evidence, analysis and run budget."""
    first, principal, _, settings = application_scope(factory)
    with factory.begin() as session:
        session.get(m.Project, first["project_id"]).slug = "first-provider-project"
    with factory() as session:
        second = seed_demo(session)
        analysis = session.scalar(
            select(m.Analysis)
            .join(m.Failure)
            .where(
                m.Failure.run_id == second["run_id"],
                m.Analysis.category == m.Category.product_defect,
            )
            .order_by(m.Analysis.id)
        )
        second["analysis_id"] = analysis.id
        session.add(
            m.ProjectMembership(
                project_id=second["project_id"],
                user_id=principal.user_id,
                role=m.ProjectRole.administrator,
            )
        )
        session.commit()
    settings.provider_allowed_project_ids = ",".join(
        (first["project_id"], second["project_id"])
    )
    assert first["project_id"] != second["project_id"]
    assert first["run_id"] != second["run_id"]
    assert first["analysis_id"] != second["analysis_id"]
    return first, second, principal, settings


def make_available(factory, invocation_id):
    """Advance only the queue fixture, never the durable admission deadline."""
    with factory.begin() as session:
        invocation = session.get(m.ModelInvocation, invocation_id)
        session.get(m.Job, invocation.job_id).available_at = database_now(session)


def test_postgres_simultaneous_enqueue_has_one_invocation_job_and_audit(pg_ledger):
    scope, principal, _, settings = application_scope(pg_ledger)
    heartbeat_provider_worker(pg_ledger, settings)
    with pg_ledger() as session:
        preview = provider_preview(session, settings, principal, **scope)
    request = ProviderSubmit(
        analysis_revision=preview["analysis_revision"],
        preview_digest=preview["preview_digest"],
        configuration_digest=preview["configuration_digest"],
        idempotency_key="simultaneous-application-enqueue",
    )
    barrier = Barrier(2)

    def enqueue():
        with pg_ledger.begin() as session:
            # Both transactions own independent live connections before contention.
            session.connection()
            barrier.wait(timeout=10)
            invocation = submit_model_invocation(
                session, settings, principal, **scope, request=request
            )
            return invocation.id, invocation.job_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(enqueue) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert results[0] == results[1]
    invocation_id, job_id = results[0]
    with pg_ledger() as session:
        assert session.scalar(select(func.count()).select_from(m.ModelInvocation)) == 1
        jobs = list(
            session.scalars(select(m.Job).where(m.Job.kind == PROVIDER_JOB_KIND))
        )
        assert len(jobs) == 1 and jobs[0].id == job_id
        assert jobs[0].payload == {
            "schema_version": "1.0",
            "invocation_id": invocation_id,
        }
        audits = list(
            session.scalars(
                select(m.AuditEvent).where(m.AuditEvent.action == "provider.submitted")
            )
        )
        assert len(audits) == 1
        assert audits[0].resource_id == invocation_id
        assert audits[0].actor_user_id == principal.user_id
        assert session.scalar(select(func.count()).select_from(m.ModelAttempt)) == 0
        assert session.get(m.ModelRunBudget, scope["run_id"]).requests == 0


def test_postgres_cross_project_workers_share_one_service_permit(pg_ledger):
    first, second, principal, settings = independent_scopes(pg_ledger)
    settings.provider_concurrency = "1"
    ids = [
        submit(pg_ledger, scope, principal, settings, "per-project-key")[0]
        for scope in (first, second)
    ]
    entered, release, barrier, guard = Event(), Event(), Barrier(2), Lock()
    calls = []

    def handler(request):
        with guard:
            calls.append(request)
        entered.set()
        assert release.wait(20)
        return good_response(request)

    def worker():
        barrier.wait(timeout=10)
        return run_provider_once(
            pg_ledger, settings, provider_factory=fixture_provider(handler)
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        try:
            assert entered.wait(10)
            done, pending = wait(futures, timeout=10, return_when=FIRST_COMPLETED)
            assert len(done) == len(pending) == 1
            assert next(iter(done)).result()
            results = [read(pg_ledger, settings, value) for value in ids]
            assert sorted(row["invocation_state"] for row in results) == [
                "queued",
                "running",
            ]
            queued = next(row for row in results if row["invocation_state"] == "queued")
            assert queued["reason"] == "concurrency_limited"
            assert queued["attempts"] == [] and queued["budget"]["requests"] == 0
            with pg_ledger() as session:
                admissions = list(session.scalars(select(m.ModelProviderAdmission)))
                assert len(admissions) == 1
                assert admissions[0].id == _digest(settings.provider_id)
                assert admissions[0].active_permits == 1
                assert (
                    session.scalar(select(func.count()).select_from(m.ModelAttempt))
                    == 1
                )
            assert len(calls) == 1
        finally:
            release.set()
        assert all(future.result(timeout=10) for future in futures)
    make_available(pg_ledger, queued["invocation_id"])
    assert run_provider_once(pg_ledger, settings, provider_factory=fixture_provider())
    assert all(
        read(pg_ledger, settings, value)["invocation_state"] == "proposed"
        for value in ids
    )
    with pg_ledger() as session:
        assert (
            session.get(
                m.ModelProviderAdmission, _digest(settings.provider_id)
            ).active_permits
            == 0
        )
        assert session.scalar(select(func.count()).select_from(m.ModelAttempt)) == 2


@pytest.mark.parametrize("operation", ["cancel", "retention"])
def test_postgres_cancel_or_retention_commits_while_transport_is_blocked(
    pg_ledger, operation, monkeypatch
):
    scope, principal, _, settings = application_scope(pg_ledger)
    invocation_id, _ = submit(pg_ledger, scope, principal, settings)
    entered, release, settled = Event(), Event(), Event()
    original_complete = ApplicationAttemptBudget.complete

    def observe_settlement(budget, *args, **kwargs):
        result = original_complete(budget, *args, **kwargs)
        if kwargs.get("transport_terminated", True):
            settled.set()
        return result

    monkeypatch.setattr(ApplicationAttemptBudget, "complete", observe_settlement)

    def handler(request):
        entered.set()
        assert release.wait(20)
        return good_response(request)

    def mutate():
        if operation == "retention":
            cleanup_via_queue(pg_ledger, scope, principal, settings)
            return
        with pg_ledger.begin() as session:
            cancel_model_invocation(
                session, settings, principal, **scope, invocation_id=invocation_id
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        worker = executor.submit(
            run_provider_once,
            pg_ledger,
            settings,
            provider_factory=fixture_provider(handler),
        )
        try:
            assert entered.wait(10)
            # Completion before release proves HTTP does not retain the project lock.
            executor.submit(mutate).result(timeout=10)
            with pg_ledger() as session:
                invocation = session.get(m.ModelInvocation, invocation_id)
                assert invocation.proposal_json is None
                assert session.get(m.ModelRunBudget, scope["run_id"]).requests == 1
                admission = session.get(
                    m.ModelProviderAdmission, _digest(settings.provider_id)
                )
                assert admission.active_permits == 1
                attempt = session.scalar(select(m.ModelAttempt))
                assert attempt.transport_terminated_at is None
                if operation == "cancel":
                    assert invocation.status == "cancelled"
                    assert invocation.cancel_requested_at is not None
                    assert (
                        session.get(m.Job, invocation.job_id).state
                        == m.JobState.cancelled
                    )
                else:
                    assert (
                        session.get(m.Run, scope["run_id"]).evidence_expired_at
                        is not None
                    )
        finally:
            release.set()
        assert worker.result(timeout=10)
        # Cancellation may detach HTTP; wait for its committed late settlement
        # before the PostgreSQL fixture can drop this test's private schema.
        assert settled.wait(10)
    result = read(pg_ledger, settings, invocation_id)
    assert result["proposal"] is None and result["budget"]["requests"] == 1
    if operation == "cancel":
        assert result["invocation_state"] == "cancelled"
    else:
        assert result["reason"] == "evidence_expired"
        assert result["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
    with pg_ledger() as session:
        assert session.get(m.ModelInvocation, invocation_id).proposal_json is None
        assert (
            session.get(
                m.ModelProviderAdmission, _digest(settings.provider_id)
            ).active_permits
            == 0
        )
        assert (
            session.scalar(select(m.ModelAttempt)).transport_terminated_at is not None
        )


def test_postgres_recovery_fences_owners_and_retains_permit_until_reconciliation(
    pg_ledger,
):
    first, second, principal, settings = independent_scopes(pg_ledger)
    settings.provider_concurrency = "1"
    invocation_id, _ = submit(pg_ledger, first, principal, settings, "recover-first")
    with ThreadPoolExecutor(max_workers=2) as executor:
        original = executor.submit(claim_provider_job, pg_ledger, settings).result(
            timeout=10
        )
        assert original and original[0] == invocation_id
        expire_claim(pg_ledger, invocation_id)
        assert executor.submit(recover_provider_jobs, pg_ledger).result(timeout=10) == 1
        assert read(pg_ledger, settings, invocation_id)["invocation_state"] == "queued"
        with pg_ledger() as session:
            assert session.scalar(select(func.count()).select_from(m.ModelAttempt)) == 0
            assert (
                session.get(
                    m.ModelProviderAdmission, _digest(settings.provider_id)
                ).active_permits
                == 0
            )
        successor = executor.submit(claim_provider_job, pg_ledger, settings).result(
            timeout=10
        )
        assert (
            successor and successor[0] == invocation_id and successor[3] != original[3]
        )
        config, snapshot = successor[4:]
        reserved_tokens = prepare_request(
            config, snapshot.category, snapshot.evidence
        ).reserved_tokens
        stale_budget = ApplicationAttemptBudget(
            pg_ledger,
            invocation_id,
            first["project_id"],
            first["run_id"],
            original[3],
            original[4],
            settings=settings,
        )
        with pytest.raises(ProviderBoundaryError, match="invocation_interrupted"):
            executor.submit(stale_budget.reserve, original[4], reserved_tokens).result(
                timeout=10
            )
        budget = ApplicationAttemptBudget(
            pg_ledger,
            invocation_id,
            first["project_id"],
            first["run_id"],
            successor[3],
            config,
            settings=settings,
        )
        # Queue an independent project before the reservation closes admission.
        waiting_id, _ = submit(
            pg_ledger, second, principal, settings, "waiting-project"
        )
        number = executor.submit(budget.reserve, config, reserved_tokens).result(
            timeout=10
        )
        assert number == 1
        expire_claim(pg_ledger, invocation_id)
        assert executor.submit(recover_provider_jobs, pg_ledger).result(timeout=10) == 1
        assert executor.submit(recover_provider_jobs, pg_ledger).result(timeout=10) == 0
        assert executor.submit(
            run_provider_once,
            pg_ledger,
            settings,
            provider_factory=fixture_provider(
                lambda _: pytest.fail("uncertain request was resent")
            ),
        ).result(timeout=10)
        blocked = read(pg_ledger, settings, waiting_id)
        assert blocked["invocation_state"] == "queued"
        assert blocked["reason"] == "recovery_required" and blocked["attempts"] == []
        result = read(pg_ledger, settings, invocation_id)
        assert result["invocation_state"] == "uncertain" and result["recovery_required"]
        assert result["budget"]["requests"] == 1
        with pg_ledger() as session:
            admission = session.get(
                m.ModelProviderAdmission, _digest(settings.provider_id)
            )
            assert admission.active_permits == 1
            assert (
                provider_status(session, settings, principal, second["project_id"])[
                    "availability"
                ]
                == "recovery_required"
            )
        late_result = ProviderResult(
            "proposed",
            "product_defect",
            usage={"prompt_tokens": 8, "completion_tokens": 2},
        )
        executor.submit(
            budget.complete, number, late_result, sent=True, http_status=200
        ).result(timeout=10)
        with pytest.raises(ProviderBoundaryError, match="attempt_already_completed"):
            executor.submit(
                budget.complete, number, late_result, sent=True, http_status=200
            ).result(timeout=10)
        with pytest.raises(ProviderBoundaryError, match="invocation_interrupted"):
            executor.submit(budget.reserve, config, reserved_tokens).result(timeout=10)
    result = read(pg_ledger, settings, invocation_id)
    assert result["invocation_state"] == "uncertain" and result["proposal"] is None
    assert not result["recovery_required"]
    assert result["attempts"][0]["status"] == "reconciled"
    assert result["attempts"][0]["transport_terminated"]
    assert result["usage"] == {"prompt_tokens": 8, "completion_tokens": 2}
    assert (
        result["budget"]["requests"] == 1
        and result["budget"]["reserved_tokens"] == reserved_tokens
    )
    with pg_ledger() as session:
        assert (
            session.get(
                m.ModelProviderAdmission, _digest(settings.provider_id)
            ).active_permits
            == 0
        )
    make_available(pg_ledger, waiting_id)
    assert run_provider_once(pg_ledger, settings, provider_factory=fixture_provider())
    assert read(pg_ledger, settings, waiting_id)["invocation_state"] == "proposed"
    assert read(pg_ledger, settings, invocation_id)["invocation_state"] == "uncertain"


@pytest.mark.parametrize("gate", ["rate_limited", "circuit_open"])
def test_postgres_admission_survives_new_adapter_token_and_configuration(
    pg_ledger, gate
):
    first, second, principal, settings = independent_scopes(pg_ledger)
    settings.provider_min_interval_seconds = "60"
    settings.provider_failure_threshold = "1"
    settings.provider_cooldown_seconds = "300"
    first_id, _ = submit(pg_ledger, first, principal, settings, "service-state")
    waiting_id, _ = submit(pg_ledger, second, principal, settings, "other-project")
    handler = good_response if gate == "rate_limited" else lambda _: httpx.Response(503)
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(
            run_provider_once,
            pg_ledger,
            settings,
            provider_factory=fixture_provider(handler),
        ).result(timeout=10)
    with pg_ledger() as session:
        admission = session.get(m.ModelProviderAdmission, _digest(settings.provider_id))
        prior = (admission.next_allowed_at, admission.open_until, admission.failures)
        assert (
            provider_status(session, settings, principal, second["project_id"])[
                "availability"
            ]
            == gate
        )
    rotated = settings.model_copy(
        update={"provider_token": SecretStr("rotated-fixture-credential")}
    )
    adapters = []

    def fresh_adapter(config):
        adapters.append(config)
        return fixture_provider(
            lambda _: pytest.fail("persisted admission was bypassed")
        )(config)

    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(
            run_provider_once, pg_ledger, rotated, provider_factory=fresh_adapter
        ).result(timeout=10)
    assert len(adapters) == 1
    result = read(pg_ledger, rotated, waiting_id)
    assert result["invocation_state"] == "queued" and result["reason"] == gate
    assert result["attempts"] == [] and result["budget"]["requests"] == 0
    changed = rotated.model_copy(
        update={
            "provider_model": "different-fixture-model",
            "provider_endpoint": "https://different-provider.example/v1/chat/completions",
            "provider_min_interval_seconds": "0",
            "provider_failure_threshold": "5",
        }
    )
    heartbeat_provider_worker(pg_ledger, changed)
    with pg_ledger.begin() as session:
        preview = provider_preview(session, changed, principal, **second)
        assert preview["availability"] == gate and not preview["can_submit"]
        assert preview["configuration_digest"] != result["configuration_digest"]
        request = ProviderSubmit(
            analysis_revision=preview["analysis_revision"],
            preview_digest=preview["preview_digest"],
            configuration_digest=preview["configuration_digest"],
            idempotency_key="changed-config-still-blocked",
        )
        with pytest.raises(ProviderBoundaryError, match=gate):
            submit_model_invocation(
                session, changed, principal, **second, request=request
            )
    with pg_ledger() as session:
        admissions = list(session.scalars(select(m.ModelProviderAdmission)))
        assert len(admissions) == 1 and admissions[0].id == _digest(
            settings.provider_id
        )
        admission = admissions[0]
        assert (
            admission.next_allowed_at,
            admission.open_until,
            admission.failures,
        ) == prior
        assert admission.active_permits == 0
        assert session.scalar(select(func.count()).select_from(m.ModelAttempt)) == 1
    assert read(pg_ledger, settings, first_id)["budget"]["requests"] == 1
