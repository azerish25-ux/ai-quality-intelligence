"""Actual cleanup queue must not wait for optional provider execution."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from failurelens import models as m
from failurelens import retention
from failurelens.jobs import claim_next
from failurelens.provider_jobs import (
    ApplicationAttemptBudget,
    claim_provider_job,
    recover_provider_jobs,
    run_provider_once,
)
from failurelens.provider_service import _digest
from failurelens.providers import prepare_request
from failurelens.service import INGEST_JOB_KIND
from sqlalchemy import select
from test_provider_ledger import good_response
from test_provider_workflow import expire_claim, fixture_provider, read, submit

pytest_plugins = ("test_provider_workflow",)


def cleanup_via_queue(factory, scope, principal, settings):
    with factory.begin() as session:
        session.get(m.Run, scope["run_id"]).created_at = m.utcnow() - timedelta(
            days=100
        )
    with factory() as session:
        proof = retention.preview(session, scope["project_id"])
        assert proof.evidence_runs == 1 and not proof.blocked_by_ingestion
        cleanup = retention.enqueue(session, scope["project_id"], proof, principal)
        claimed = claim_next(session, "provider-retention-test", 60)
        assert claimed and claimed.id == cleanup.id
        retention.process_cleanup(session, claimed, "provider-retention-test", settings)
        session.refresh(cleanup)
        assert cleanup.state == m.JobState.succeeded
        assert session.get(m.Run, scope["run_id"]).evidence_expired_at is not None
        assert (
            session.scalar(
                select(m.StorageDeletion.id).where(
                    m.StorageDeletion.project_id == scope["project_id"],
                    m.StorageDeletion.state == "pending",
                )
            )
            is None
        )
        for derivative in session.scalars(
            select(m.ArtifactDerivative).where(
                m.ArtifactDerivative.run_id == scope["run_id"]
            )
        ):
            assert derivative.retention_state == "expired"
            if not derivative.storage_path.startswith("db://"):
                assert not (settings.artifact_root / derivative.storage_path).exists()


@pytest.mark.parametrize(
    "state", ["queued", "future_provider_kind", "recovery_required"]
)
def test_queued_or_uncertain_provider_cannot_block_actual_retention(workflow, state):
    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)
    if state == "future_provider_kind":
        with factory.begin() as session:
            invocation = session.get(m.ModelInvocation, invocation_id)
            session.get(m.Job, invocation.job_id).kind = "model_provider_future_v2"
    if state == "recovery_required":
        submit(factory, scope, principal, settings, "second-queued")
        claimed = claim_provider_job(factory, settings)
        assert claimed and claimed[0] == invocation_id
        config, snapshot = claimed[4:]
        budget = ApplicationAttemptBudget(
            factory,
            invocation_id,
            scope["project_id"],
            scope["run_id"],
            claimed[3],
            config,
            settings=settings,
        )
        assert (
            budget.reserve(
                config,
                prepare_request(
                    config, snapshot.category, snapshot.evidence
                ).reserved_tokens,
            )
            == 1
        )
        expire_claim(factory, invocation_id)
        assert recover_provider_jobs(factory) == 1
        assert run_provider_once(
            factory,
            settings,
            provider_factory=fixture_provider(
                lambda _: pytest.fail("uncertain replay")
            ),
        )
    cleanup_via_queue(factory, scope, principal, settings)
    result = read(factory, settings, invocation_id)
    assert result["proposal"] is None and result["reason"] == "evidence_expired"
    if state == "recovery_required":
        assert result["recovery_required"] and result["budget"]["requests"] == 1
        with factory() as session:
            assert (
                session.get(
                    m.ModelProviderAdmission, _digest(settings.provider_id)
                ).active_permits
                == 1
            )
    elif state == "queued":
        assert not run_provider_once(
            factory,
            settings,
            provider_factory=lambda _: pytest.fail("expired queued evidence sent"),
        )
        assert read(factory, settings, invocation_id)["attempts"] == []


def test_inflight_provider_cannot_block_actual_cleanup_or_republish_expired_evidence(
    workflow,
):
    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    invocation_id, _ = submit(factory, scope, principal, settings)
    entered, release = Event(), Event()

    def handler(request):
        entered.set()
        assert release.wait(10)
        return good_response(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        worker = executor.submit(
            run_provider_once,
            factory,
            settings,
            provider_factory=fixture_provider(handler),
        )
        try:
            assert entered.wait(5)
            executor.submit(
                cleanup_via_queue, factory, scope, principal, settings
            ).result(timeout=5)
            with factory() as session:
                assert (
                    session.get(
                        m.ModelProviderAdmission, _digest(settings.provider_id)
                    ).active_permits
                    == 1
                )
                assert (
                    session.get(m.ModelInvocation, invocation_id).proposal_json is None
                )
        finally:
            release.set()
        assert worker.result(timeout=5)
    result = read(factory, settings, invocation_id)
    assert result["proposal"] is None and result["reason"] == "evidence_expired"
    assert result["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}
    assert result["budget"]["requests"] == 1 and not result["recovery_required"]


@pytest.mark.parametrize("state", [m.JobState.queued, m.JobState.running])
def test_real_ingestion_still_defers_actual_cleanup_with_provider_queued(
    workflow, state
):
    factory, scope, principal, settings, _api_settings, _client, _base = workflow
    submit(factory, scope, principal, settings)
    with factory.begin() as session:
        session.get(m.Run, scope["run_id"]).created_at = m.utcnow() - timedelta(
            days=100
        )
        session.add(
            m.Job(
                project_id=scope["project_id"],
                kind=INGEST_JOB_KIND,
                payload={"ingestion_id": m.new_id()},
                state=state,
                available_at=m.utcnow() + timedelta(days=1),
                lease_expires_at=m.utcnow() + timedelta(minutes=5),
                lease_owner="ingestion-worker" if state == m.JobState.running else None,
            )
        )
    with factory() as session:
        proof = retention.preview(session, scope["project_id"])
        assert proof.evidence_runs == 1 and proof.blocked_by_ingestion
        cleanup = retention.enqueue(session, scope["project_id"], proof, principal)
        claimed = claim_next(session, "retention-worker", 60)
        assert claimed and claimed.id == cleanup.id
        retention.process_cleanup(session, claimed, "retention-worker", settings)
        session.refresh(cleanup)
        assert cleanup.state == m.JobState.queued and cleanup.attempts == 0
        assert session.get(m.Run, scope["run_id"]).evidence_expired_at is None
