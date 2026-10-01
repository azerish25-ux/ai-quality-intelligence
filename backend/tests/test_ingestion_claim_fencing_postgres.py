"""Actual PostgreSQL claim fencing; SQLite cannot prove these lock interleavings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from failurelens import job_leases, jobs, service
from failurelens.config import get_settings
from failurelens.job_leases import ClaimGuard, LeaseLost, claimed_identity
from failurelens.models import (
    Analysis,
    ArtifactDerivative,
    Ingestion,
    IngestionState,
    Job,
    JobState,
    Run,
)
from failurelens.models import (
    TestExecution as Execution,
)
from failurelens.schemas import RunMetadata
from failurelens.storage import store_bytes
from sqlalchemy import event, func, select, text, update

pytest_plugins = ("test_operations_postgres",)


@pytest.fixture
def pg_ingestion(pg_factory, monkeypatch):
    # pg_factory creates and drops an isolated disposable PostgreSQL schema.
    # Every session/transaction below is bounded, including post-commit refreshes.
    factory, settings = pg_factory
    monkeypatch.setenv("FAILURELENS_ARTIFACT_ROOT", str(settings.artifact_root))
    get_settings.cache_clear()

    @event.listens_for(factory, "after_begin")
    def set_timeouts(_session, _transaction, connection):
        connection.execute(text("SET LOCAL lock_timeout = '2s'"))
        connection.execute(text("SET LOCAL statement_timeout = '5s'"))

    try:
        yield factory, settings
    finally:
        event.remove(factory, "after_begin", set_timeouts)
        get_settings.cache_clear()


@pytest.fixture
def claim_clock(monkeypatch):
    class Clock(datetime):
        # Queue/model defaults use the real clock; put this clock just ahead so
        # newly enqueued jobs are immediately eligible without any sleep.
        current = datetime.now(UTC) + timedelta(minutes=1)

        @classmethod
        def now(cls, tz=None):
            return (
                cls.current.astimezone(tz)
                if tz is not None
                else cls.current.replace(tzinfo=None)
            )

        @classmethod
        def expire(cls, job):
            cls.current = job.lease_expires_at + timedelta(seconds=1)

    monkeypatch.setattr(jobs, "datetime", Clock)
    monkeypatch.setattr(job_leases, "datetime", Clock)
    return Clock


def _enqueue(session, settings, *, failed=False):
    project = service.create_project(session, "pg-claim-fencing", "Claim fencing")
    failure = (
        '<failure type="Error">duplicate committed ledger unbalanced</failure>'
        if failed
        else ""
    )
    stored = store_bytes(
        f'<testsuite><testcase name="transfer">{failure}</testcase></testsuite>'.encode(),
        root=settings.artifact_root,
        project_id=project.id,
        filename="junit.xml",
        media_type="application/xml",
        max_bytes=settings.max_file_bytes,
    )
    return service.enqueue_artifact_ingestion(
        session,
        project,
        RunMetadata(external_id="pg-claim-fencing", expected_inputs=1),
        stored,
        settings=settings,
    )


def _assert_completed(factory, ingestion_id, job_id, *, attempts, analyses=0):
    with factory() as check:
        job = check.get(Job, job_id)
        ingestion = check.get(Ingestion, ingestion_id)
        assert job.state is JobState.succeeded
        assert job.attempts == attempts
        assert job.lease_owner is None
        assert job.lease_expires_at is None
        assert job.last_error is None
        assert ingestion.state is IngestionState.succeeded
        assert ingestion.run_id is not None
        assert ingestion.error_code is None
        assert ingestion.error_message is None
        assert check.scalar(select(func.count(Run.id))) == 1
        assert check.scalar(select(func.count(Execution.id))) == 1
        assert check.scalar(select(func.count(ArtifactDerivative.id))) == 1
        assert check.scalar(select(func.count(Analysis.id))) == analyses


@pytest.mark.parametrize("failed", [False, True])
def test_postgres_current_ingestion_owner_can_finish(pg_ingestion, failed):
    factory, settings = pg_ingestion
    with factory() as session:
        ingestion = _enqueue(session, settings, failed=failed)
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        assert jobs.process_next(session, "worker-current", settings=settings)
    _assert_completed(factory, ingestion_id, job_id, attempts=1, analyses=int(failed))


@pytest.mark.parametrize("successor_owner", ["worker-successor", "worker-original"])
@pytest.mark.parametrize("write_boundary", ["flush", "commit", "dml"])
def test_postgres_locked_transaction_finishes_then_fences_stale_generation(
    pg_ingestion, claim_clock, successor_owner, write_boundary
):
    factory, settings = pg_ingestion
    with factory() as original, factory() as successor:
        ingestion = _enqueue(original, settings)
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        previous = jobs.claim_next(original, "worker-original", 30)
        assert previous.id == job_id
        claim = claimed_identity(previous, "worker-original")

        # These sessions retain different live PostgreSQL connections. Sequential
        # orchestration of overlapping transactions is sufficient to prove the
        # lock interleaving; no thread scheduling or wall-clock sleep is needed.
        with ClaimGuard(original, claim) as guard:
            guard.check()
            original_pid = original.scalar(text("SELECT pg_backend_pid()"))
            successor_pid = successor.scalar(text("SELECT pg_backend_pid()"))
            assert original_pid != successor_pid
            claim_clock.expire(previous)
            assert successor.scalar(
                select(Job.lease_expires_at).where(Job.id == job_id)
            ) < claim_clock.now(UTC)
            assert jobs.claim_next(successor, successor_owner, 30) is None
            successor.rollback()

            # The lock permits finishing this transaction after expiry, but an
            # explicit heartbeat must never revive its already expired lease.
            deadline = previous.lease_expires_at
            with pytest.raises(LeaseLost):
                guard.renew(previous, "worker-original", 30)
            assert previous.lease_expires_at == deadline
            ingestion.error_message = "committed while the original lock was held"
            original.flush()
            original.commit()

            recovered = jobs.claim_next(successor, successor_owner, 30)
            assert recovered.id == job_id
            assert recovered.attempts == 2
            assert successor.get(Ingestion, ingestion_id).error_message == (
                "committed while the original lock was held"
            )
            # Refresh deliberately overwrites mutable ORM attempts/owner fields;
            # the identity captured at claim time must still name generation 1.
            original.refresh(previous)
            assert previous.attempts == 2
            assert claimed_identity(previous, "worker-original") == claim
            assert claim.attempts == 1

            with pytest.raises(LeaseLost):
                if write_boundary == "dml":
                    original.execute(
                        update(Ingestion)
                        .where(Ingestion.id == ingestion_id)
                        .values(error_message="forbidden stale write")
                    )
                else:
                    ingestion.error_message = "forbidden stale write"
                    getattr(original, write_boundary)()
            original.rollback()

        with factory() as check:
            current = check.get(Job, job_id)
            assert current.state is JobState.running
            assert current.lease_owner == successor_owner
            assert current.attempts == 2
            assert check.get(Ingestion, ingestion_id).error_message == (
                "committed while the original lock was held"
            )
        jobs.process_claimed(successor, recovered, successor_owner, settings)
    _assert_completed(factory, ingestion_id, job_id, attempts=2)


@pytest.mark.parametrize("successor_owner", ["worker-successor", "worker-original"])
def test_postgres_savepoint_rollback_releases_and_invalidates_claim_fence(
    pg_ingestion, claim_clock, successor_owner
):
    factory, settings = pg_ingestion
    with factory() as original, factory() as successor:
        ingestion = _enqueue(original, settings)
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        previous = jobs.claim_next(original, "worker-original", 30)
        claim = claimed_identity(previous, "worker-original")
        with ClaimGuard(original, claim) as guard:
            nested = original.begin_nested()
            guard.check()
            claim_clock.expire(previous)
            assert jobs.claim_next(successor, successor_owner, 30) is None
            successor.rollback()

            # PostgreSQL releases a row lock first acquired inside the rolled
            # back savepoint even though the outer transaction remains open.
            nested.rollback()
            assert original.in_transaction()
            recovered = jobs.claim_next(successor, successor_owner, 30)
            assert recovered.id == job_id
            assert recovered.attempts == 2
            with pytest.raises(LeaseLost):
                original.execute(
                    update(Ingestion.__table__)
                    .where(Ingestion.id == ingestion_id)
                    .values(error_message="forbidden savepoint survivor")
                )
            original.rollback()

        with factory() as check:
            assert check.get(Ingestion, ingestion_id).error_message is None
            assert check.get(Job, job_id).lease_owner == successor_owner
        jobs.process_claimed(successor, recovered, successor_owner, settings)
    _assert_completed(factory, ingestion_id, job_id, attempts=2)


@pytest.mark.parametrize("successor_owner", ["worker-successor", "worker-original"])
def test_postgres_predecessor_cannot_finalize_after_committed_run_is_reclaimed(
    pg_ingestion, claim_clock, monkeypatch, successor_owner
):
    factory, settings = pg_ingestion
    with factory() as original, factory() as successor:
        ingestion = _enqueue(original, settings)
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        ingest_parsed_report = service.ingest_parsed_report
        recovered_claims = []

        def reclaim_after_committed_run(*args, **kwargs):
            run = ingest_parsed_report(*args, **kwargs)
            previous = successor.get(Job, job_id)
            assert previous.state is JobState.running
            assert previous.lease_owner == "worker-original"
            claim_clock.expire(previous)
            recovered = jobs.claim_next(successor, successor_owner, 30)
            assert recovered.id == job_id
            assert recovered.attempts == 2
            recovered_claims.append(recovered)
            return run

        with monkeypatch.context() as patch:
            patch.setattr(service, "ingest_parsed_report", reclaim_after_committed_run)
            assert jobs.process_next(original, "worker-original", settings=settings)

        assert len(recovered_claims) == 1
        with factory() as check:
            current_job = check.get(Job, job_id)
            current_ingestion = check.get(Ingestion, ingestion_id)
            assert current_job.state is JobState.running
            assert current_job.lease_owner == successor_owner
            assert current_job.attempts == 2
            assert current_job.last_error is None
            assert current_ingestion.state is IngestionState.running
            assert current_ingestion.run_id is None
            assert current_ingestion.completed_at is None
            assert current_ingestion.error_code is None
            assert current_ingestion.error_message is None
            assert check.scalar(select(func.count(Run.id))) == 1
            assert check.scalar(select(func.count(Execution.id))) == 1
            assert check.scalar(select(func.count(ArtifactDerivative.id))) == 1

        jobs.process_claimed(successor, recovered_claims[0], successor_owner, settings)
    _assert_completed(factory, ingestion_id, job_id, attempts=2)
