"""A recovered ingestion claim must fence the previous processing attempt."""

from datetime import UTC, datetime, timedelta

import pytest
from failurelens import jobs, service
from failurelens.config import get_settings
from failurelens.job_leases import ClaimGuard, LeaseLost, active_guard, claimed_identity
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
from sqlalchemy import func, select


def _enqueue(session, *, failed=False):
    settings = get_settings()
    project = service.create_project(session, "claim-fencing", "Claim fencing")
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
        RunMetadata(external_id="claim-fencing", expected_inputs=1),
        stored,
        settings=settings,
    )


def _assert_completed(factory, ingestion_id, job_id, *, attempts, analyses=0):
    with factory() as check:
        job = check.get(Job, job_id)
        ingestion = check.get(Ingestion, ingestion_id)
        assert job.state is JobState.succeeded
        assert job.lease_owner is None
        assert job.attempts == attempts
        assert ingestion.state is IngestionState.succeeded
        assert ingestion.run_id is not None
        assert check.scalar(select(func.count(Run.id))) == 1
        assert check.scalar(select(func.count(Execution.id))) == 1
        assert check.scalar(select(func.count(ArtifactDerivative.id))) == 1
        assert check.scalar(select(func.count(Analysis.id))) == analyses


@pytest.mark.parametrize("failed", [False, True])
def test_current_ingestion_owner_can_finish(session_factory, failed):
    with session_factory() as session:
        ingestion = _enqueue(session, failed=failed)
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        assert jobs.process_next(session, "worker-current", settings=get_settings())
    _assert_completed(
        session_factory, ingestion_id, job_id, attempts=1, analyses=int(failed)
    )


def test_recovered_ingestion_owner_can_finish(session_factory):
    with session_factory() as first, session_factory() as successor:
        ingestion = _enqueue(first)
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        original_claim = jobs.claim_next(first, "worker-original", 30)
        assert original_claim.id == job_id
        original_claim.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        first.commit()
        recovered = jobs.claim_next(successor, "worker-successor", 30)
        assert recovered.id == job_id
        assert recovered.attempts == 2
        jobs.process_claimed(successor, recovered, "worker-successor", get_settings())
    _assert_completed(session_factory, ingestion_id, job_id, attempts=2)


def _recover(session, job_id, owner="worker-successor"):
    previous = session.get(Job, job_id)
    previous.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    recovered = jobs.claim_next(session, owner, 30)
    assert recovered.id == job_id
    assert recovered.attempts == 2
    return recovered


def test_stale_attempt_cannot_start_or_reset_ingestion(session_factory):
    with session_factory() as original, session_factory() as successor:
        ingestion = _enqueue(original)
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        stale = jobs.claim_next(original, "worker-original", 30)
        recovered = _recover(successor, job_id)
        jobs.process_claimed(original, stale, "worker-original", get_settings())
        with session_factory() as check:
            current = check.get(Ingestion, ingestion_id)
            assert current.state is IngestionState.queued
            assert current.started_at is None
            assert current.diagnostics == [{"phase": "accepted", "status": "complete"}]
            assert check.get(Job, job_id).lease_owner == "worker-successor"
            assert check.scalar(select(func.count(Run.id))) == 0
        jobs.process_claimed(successor, recovered, "worker-successor", get_settings())
    _assert_completed(session_factory, ingestion_id, job_id, attempts=2)


@pytest.mark.parametrize("phase", ["source", "analysis", "exception"])
def test_recovery_stops_uncommitted_source_analysis_and_error_writes(
    session_factory, monkeypatch, phase
):
    with session_factory() as original, session_factory() as successor:
        ingestion = _enqueue(original, failed=phase == "analysis")
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        settings = get_settings()
        source = settings.artifact_root / ingestion.storage_path
        original_source = source.read_bytes()
        recovered = []
        function_name = (
            "analyze_failure" if phase == "analysis" else "ingest_parsed_report"
        )
        original_function = getattr(service, function_name)

        def interrupt(*args, **kwargs):
            decision = (
                original_function(*args, **kwargs) if phase == "analysis" else None
            )
            # Reusing the worker ID must not let the old attempt's exception
            # handler requeue, fail, or otherwise overwrite the newer attempt.
            recovered.append(_recover(successor, job_id, "worker-original"))
            if phase == "exception":
                raise RuntimeError("synthetic failure after recovery")
            return (
                decision if phase == "analysis" else original_function(*args, **kwargs)
            )

        with monkeypatch.context() as patch:
            patch.setattr(service, function_name, interrupt)
            assert jobs.process_next(original, "worker-original", settings=settings)
        with session_factory() as check:
            current_job = check.get(Job, job_id)
            current = check.get(Ingestion, ingestion_id)
            assert current_job.state is JobState.running
            assert current_job.attempts == 2
            assert current_job.lease_owner == "worker-original"
            assert current_job.last_error is None
            assert current.state is IngestionState.running
            assert current.error_code is None
            assert current.run_id is None
            assert check.scalar(select(func.count(Analysis.id))) == 0
            assert check.scalar(select(func.count(Run.id))) == int(phase == "analysis")
            assert check.scalar(select(func.count(ArtifactDerivative.id))) == int(
                phase == "analysis"
            )
        assert source.read_bytes() == original_source
        if phase != "analysis":
            # Storage initializes the empty derivatives directory at upload.
            assert not any(
                path.is_file()
                for path in (settings.artifact_root / "derivatives").rglob("*")
            )
        jobs.process_claimed(successor, recovered[0], "worker-original", settings)
    _assert_completed(
        session_factory,
        ingestion_id,
        job_id,
        attempts=2,
        analyses=int(phase == "analysis"),
    )


@pytest.mark.parametrize("cancel", [False, True])
def test_cleanup_runs_only_after_owned_completion_outside_the_claim_guard(
    session_factory, monkeypatch, cancel
):
    from failurelens import retention

    with session_factory() as original, session_factory() as canceller:
        ingestion = _enqueue(original)
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        original_ingest = service.ingest_parsed_report
        original_cleanup = retention.flush_deletions
        cleanup_states = []

        def after_run(*args, **kwargs):
            run = original_ingest(*args, **kwargs)
            if cancel:
                service.cancel_ingestion(
                    canceller, canceller.get(Ingestion, ingestion_id)
                )
            return run

        def cleanup(session, *args, **kwargs):
            assert active_guard(session) is None
            cleanup_states.append(session.get(Job, job_id).state)
            return original_cleanup(session, *args, **kwargs)

        monkeypatch.setattr(service, "ingest_parsed_report", after_run)
        monkeypatch.setattr(retention, "flush_deletions", cleanup)
        assert jobs.process_next(original, "worker-original", settings=get_settings())
    if cancel:
        assert cleanup_states == []
        with session_factory() as check:
            current = check.get(Ingestion, ingestion_id)
            job = check.get(Job, job_id)
            assert current.state is IngestionState.cancelled
            assert current.run_id is None
            assert current.error_code is None
            assert job.state is JobState.cancelled
            assert job.lease_owner is None
            assert job.last_error is None
    else:
        assert cleanup_states == [JobState.succeeded]
        _assert_completed(session_factory, ingestion_id, job_id, attempts=1)


@pytest.mark.parametrize("changed_field", ["kind", "project_id"])
def test_refreshed_job_cannot_change_the_original_claim_scope(
    session_factory, changed_field
):
    with session_factory() as original, session_factory() as mutator:
        ingestion = _enqueue(original)
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        claimed = jobs.claim_next(original, "worker-original", 30)
        other = service.create_project(mutator, "other-scope", "Other scope")
        changed = mutator.get(Job, job_id)
        before = getattr(changed, changed_field)
        setattr(changed, changed_field, "noop" if changed_field == "kind" else other.id)
        mutator.commit()
        original.refresh(claimed)
        jobs.process_claimed(original, claimed, "worker-original", get_settings())
        with session_factory() as check:
            assert check.get(Ingestion, ingestion_id).state is IngestionState.queued
            assert check.get(Job, job_id).state is JobState.running
            assert check.scalar(select(func.count(Run.id))) == 0
        setattr(changed, changed_field, before)
        mutator.commit()
        original.refresh(claimed)
        jobs.process_claimed(original, claimed, "worker-original", get_settings())
    _assert_completed(session_factory, ingestion_id, job_id, attempts=1)


def test_stale_sqlite_admission_cannot_reuse_a_claim_generation(
    session_factory, monkeypatch
):
    with session_factory() as first, session_factory() as second:
        ingestion = _enqueue(first)
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        original_scalar = first.scalar
        winners = []

        def claim_after_selection(statement, *args, **kwargs):
            result = original_scalar(statement, *args, **kwargs)
            if isinstance(result, Job) and not winners:
                winners.append(jobs.claim_next(second, "reused-worker", 30))
            return result

        with monkeypatch.context() as patch:
            patch.setattr(first, "scalar", claim_after_selection)
            assert jobs.claim_next(first, "reused-worker", 30) is None
        assert len(winners) == 1
        assert winners[0].id == job_id
        assert winners[0].attempts == 1
        jobs.process_claimed(second, winners[0], "reused-worker", get_settings())
    _assert_completed(session_factory, ingestion_id, job_id, attempts=1)


def test_fence_preserves_timestamp_and_expired_heartbeat_cannot_revive_lease(
    session_factory, monkeypatch
):
    from failurelens import job_leases

    with session_factory() as session:
        ingestion = _enqueue(session)
        job_id = ingestion.job_id
        claimed = jobs.claim_next(session, "worker-current", 30)
        before_updated, before_expiry = claimed.updated_at, claimed.lease_expires_at
        claim = claimed_identity(claimed, "worker-current")
        with ClaimGuard(session, claim) as guard:
            guard.check()
            session.commit()
        session.refresh(claimed)
        assert claimed.updated_at == before_updated
        assert claimed.lease_expires_at == before_expiry
        with ClaimGuard(session, claim) as guard:
            guard.check()

            class ExpiredClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return before_expiry.replace(tzinfo=UTC) + timedelta(seconds=1)

            monkeypatch.setattr(job_leases, "datetime", ExpiredClock)
            with pytest.raises(LeaseLost):
                jobs.heartbeat(session, claimed, "worker-current", 30)
            session.rollback()
        with session_factory() as check:
            current = check.get(Job, job_id)
            assert current.lease_expires_at == before_expiry
            assert current.attempts == 1


@pytest.mark.parametrize("scope", ["missing", "foreign-project", "replaced-job"])
def test_current_owner_invalid_scope_has_terminal_diagnostics_without_foreign_writes(
    session_factory, scope
):
    with session_factory() as session:
        ingestion = _enqueue(session)
        job = session.get(Job, ingestion.job_id)
        ingestion_id, job_id = ingestion.id, job.id
        if scope == "missing":
            job.payload = {**job.payload, "ingestion_id": "missing-ingestion"}
        elif scope == "foreign-project":
            other = service.create_project(
                session, "foreign-project", "Foreign project"
            )
            job.project_id = other.id
        else:
            replacement = Job(
                project_id=ingestion.project_id,
                kind="model_provider_fixture",
                payload={},
                state=JobState.queued,
            )
            session.add(replacement)
            session.flush()
            ingestion.job_id = replacement.id
        session.commit()
        before = {
            "state": ingestion.state,
            "job_id": ingestion.job_id,
            "diagnostics": ingestion.diagnostics,
            "started_at": ingestion.started_at,
            "run_id": ingestion.run_id,
        }
        assert jobs.process_next(session, "worker-current", settings=get_settings())
    with session_factory() as check:
        current_job = check.get(Job, job_id)
        current = check.get(Ingestion, ingestion_id)
        assert current_job.state is JobState.dead_lettered
        assert current_job.lease_owner is None
        assert (
            current_job.last_error == "Job references a missing or mismatched ingestion"
        )
        assert current_job.attempts == 1
        assert {key: getattr(current, key) for key in before} == before
        assert check.scalar(select(func.count(Run.id))) == 0


@pytest.mark.parametrize("expired", [False, True])
def test_abandoned_final_attempt_is_terminalized_without_reprocessing(
    session_factory, expired
):
    with session_factory() as owner, session_factory() as recovery:
        ingestion = _enqueue(owner)
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        job = owner.get(Job, job_id)
        job.max_attempts = 1
        owner.commit()
        claimed = jobs.claim_next(owner, "final-worker", 30)
        ingestion.state = IngestionState.running
        claimed.lease_expires_at = datetime.now(UTC) + timedelta(
            seconds=-1 if expired else 30
        )
        owner.commit()
        assert jobs.claim_next(recovery, "recovery-worker", 30) is None
    with session_factory() as check:
        job = check.get(Job, job_id)
        current = check.get(Ingestion, ingestion_id)
        assert job.attempts == job.max_attempts == 1
        assert job.state is (JobState.dead_lettered if expired else JobState.running)
        assert current.state is (
            IngestionState.dead_lettered if expired else IngestionState.running
        )
        assert current.error_code == ("lease_exhausted" if expired else None)
        assert job.lease_owner == (None if expired else "final-worker")
        assert check.scalar(select(func.count(Run.id))) == 0


def test_abandoned_final_completion_keeps_its_committed_success(session_factory):
    with session_factory() as owner, session_factory() as recovery:
        ingestion = _enqueue(owner)
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        job = owner.get(Job, job_id)
        job.max_attempts = 1
        owner.commit()
        assert jobs.process_next(owner, "final-worker", settings=get_settings())
        # Model a crash after the ingestion transaction committed but before
        # the separate job-completion transaction became durable.
        job.state = JobState.running
        job.lease_owner = "final-worker"
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        owner.commit()
        assert jobs.claim_next(recovery, "recovery-worker", 30) is None
    _assert_completed(session_factory, ingestion_id, job_id, attempts=1)


@pytest.mark.parametrize("kind", ["model_provider_v1", "retention_cleanup_v1"])
def test_exhausted_ingestion_sweep_does_not_touch_other_workers(session_factory, kind):
    with session_factory() as session:
        project = service.create_project(
            session, "independent-jobs", "Independent jobs"
        )
        job = Job(
            project_id=project.id,
            kind=kind,
            payload={},
            state=JobState.running,
            lease_owner="other-worker",
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            attempts=1,
            max_attempts=1,
        )
        session.add(job)
        session.commit()
        job_id = job.id
        assert jobs.claim_next(session, "ingestion-worker", 30) is None
    with session_factory() as check:
        current = check.get(Job, job_id)
        assert current.state is JobState.running
        assert current.lease_owner == "other-worker"
        assert current.attempts == 1
        assert current.last_error is None


@pytest.mark.parametrize("action", ["heartbeat", "complete", "fail"])
def test_direct_ingestion_job_helpers_reject_refreshed_stale_generations(
    session_factory, action
):
    with session_factory() as original, session_factory() as successor:
        ingestion = _enqueue(original)
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        stale = jobs.claim_next(original, "reused-worker", 30)
        recovered = _recover(successor, job_id, "reused-worker")
        original.refresh(stale)
        with pytest.raises(LeaseLost):
            if action == "heartbeat":
                jobs.heartbeat(original, stale, "reused-worker", 30)
            elif action == "complete":
                jobs.complete(original, stale)
            else:
                jobs.fail(original, stale, "old generation error")
        with session_factory() as check:
            current = check.get(Job, job_id)
            assert current.state is JobState.running
            assert current.attempts == 2
            assert current.lease_owner == "reused-worker"
            assert current.last_error is None
            assert check.get(Ingestion, ingestion_id).state is IngestionState.queued
        jobs.process_claimed(successor, recovered, "reused-worker", get_settings())
    _assert_completed(session_factory, ingestion_id, job_id, attempts=2)


@pytest.mark.parametrize("action", ["heartbeat", "complete", "fail"])
def test_active_ingestion_guard_cannot_authorize_another_job(session_factory, action):
    with session_factory() as session:
        ingestion = _enqueue(session)
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        claimed = jobs.claim_next(session, "worker-current", 30)
        other = service.create_project(session, "foreign-job", "Foreign job")
        target = Job(
            project_id=other.id,
            kind="noop",
            payload={},
            state=JobState.running,
            lease_owner="foreign-worker",
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=30),
            attempts=1,
        )
        session.add(target)
        session.commit()
        target_id = target.id
        with ClaimGuard(
            session, claimed_identity(claimed, "worker-current"), require_scope=False
        ):
            with pytest.raises(LeaseLost):
                if action == "heartbeat":
                    jobs.heartbeat(session, target, "foreign-worker", 30)
                elif action == "complete":
                    jobs.complete(session, target)
                else:
                    jobs.fail(session, target, "cross-job error")
            session.commit()
        with session_factory() as check:
            current = check.get(Job, target_id)
            assert current.state is JobState.running
            assert current.lease_owner == "foreign-worker"
            assert current.last_error is None
            assert current.attempts == 1
        jobs.process_claimed(session, claimed, "worker-current", get_settings())
    _assert_completed(session_factory, ingestion_id, job_id, attempts=1)


def test_fence_rejects_a_lease_that_expires_while_its_update_waits(
    session_factory, monkeypatch
):
    from failurelens import job_leases

    with session_factory() as session:
        ingestion = _enqueue(session)
        claimed = jobs.claim_next(session, "worker-current", 30)
        before_expiry = claimed.lease_expires_at
        connection = session.connection()
        original_execute = connection.execute

        class AfterWaitClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return before_expiry.replace(tzinfo=UTC) + timedelta(seconds=1)

        def finish_wait(*args, **kwargs):
            result = original_execute(*args, **kwargs)
            monkeypatch.setattr(job_leases, "datetime", AfterWaitClock)
            return result

        monkeypatch.setattr(connection, "execute", finish_wait)
        with (
            pytest.raises(LeaseLost),
            ClaimGuard(session, claimed_identity(claimed, "worker-current")) as guard,
        ):
            guard.check()
        with session_factory() as check:
            current = check.get(Ingestion, ingestion.id)
            assert current.state is IngestionState.queued
            assert current.started_at is None
            assert check.scalar(select(func.count(Run.id))) == 0


@pytest.mark.parametrize("successor_owner", ["worker-successor", "worker-original"])
def test_previous_attempt_cannot_finalize_a_reclaimed_ingestion(
    session_factory, monkeypatch, successor_owner
):
    # All-passing reports have no analysis-loop heartbeat. Pause at the real
    # persisted Run boundary, after its transaction and clustering have committed.
    # A distinct Session then recovers the expired claim through the real API.
    with session_factory() as original, session_factory() as successor:
        ingestion = _enqueue(original)
        ingestion_id, job_id = ingestion.id, ingestion.job_id
        original_ingest = service.ingest_parsed_report
        recovered_claims = []

        def reclaim_after_run(*args, **kwargs):
            run = original_ingest(*args, **kwargs)
            previous = successor.get(Job, job_id)
            assert previous.state is JobState.running
            assert previous.lease_owner == "worker-original"
            previous.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            successor.commit()
            recovered = jobs.claim_next(successor, successor_owner, 30)
            assert recovered.id == job_id
            assert recovered.attempts == 2
            recovered_claims.append(recovered)
            return run

        with monkeypatch.context() as patch:
            patch.setattr(service, "ingest_parsed_report", reclaim_after_run)
            assert jobs.process_next(
                original, "worker-original", settings=get_settings()
            )

        # The predecessor may leave its already committed idempotent Run, but
        # must not publish success, clear the successor's lease, or add errors.
        assert len(recovered_claims) == 1
        with session_factory() as check:
            current_job = check.get(Job, job_id)
            current_ingestion = check.get(Ingestion, ingestion_id)
            assert current_job.state is JobState.running
            assert current_job.lease_owner == successor_owner
            assert current_job.attempts == 2
            assert current_job.last_error is None
            assert current_ingestion.state is IngestionState.running
            assert current_ingestion.run_id is None
            assert current_ingestion.error_code is None
            assert current_ingestion.completed_at is None

        # Genuine recovery still finishes, reusing the committed Run and its
        # immutable derivative rather than duplicating observations.
        jobs.process_claimed(
            successor, recovered_claims[0], successor_owner, get_settings()
        )
    _assert_completed(session_factory, ingestion_id, job_id, attempts=2)
