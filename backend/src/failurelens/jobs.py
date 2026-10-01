from __future__ import annotations

import argparse
import logging
import signal
import socket
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import SessionLocal, initialize_database
from .ingestion import IngestionError
from .job_leases import (
    ClaimGuard,
    ClaimScopeInvalid,
    LeaseLost,
    active_guard,
    bind_claim,
    bound_claim,
    capture_claim,
    claimed_identity,
)
from .models import Ingestion, IngestionState, Job, JobState
from .service import INGEST_JOB_KIND, process_artifact_ingestion
from .storage import StorageError
from .telemetry import (
    SpanKind,
    configure_telemetry,
    observe_result,
    shutdown_telemetry,
    stage,
)

logger = logging.getLogger(__name__)

PERMANENT_INGESTION_ERRORS = {
    "unsupported_trace_version",
    "unsupported_trace_producer",
    "unsupported_image_frames",
    "image_processing_failed",
    "image_processing_timeout",
    "ambiguous_bundle",
    "digest_mismatch",
    "empty_report",
    "empty_upload",
    "limit_exceeded",
    "malformed_report",
    "missing_attachment",
    "storage_collision",
    "storage_missing",
    "storage_size_mismatch",
    "unsafe_archive",
    "unsafe_filename",
    "unsafe_storage_path",
    "unsafe_xml",
    "unsupported_format",
    "unsupported_schema",
}


def _expire_exhausted_ingestion(session: Session, now: datetime) -> None:
    """Close at most one abandoned final ingestion attempt without replaying it."""
    job = session.scalar(
        select(Job)
        .where(
            Job.kind == INGEST_JOB_KIND,
            Job.state == JobState.running,
            Job.lease_expires_at <= now,
            Job.attempts >= Job.max_attempts,
        )
        .order_by(Job.lease_expires_at, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return
    changed = (
        session.connection()
        .execute(
            update(Job)
            .where(
                Job.id == job.id,
                Job.project_id == job.project_id,
                Job.kind == INGEST_JOB_KIND,
                Job.state == JobState.running,
                Job.attempts == job.attempts,
                Job.attempts >= Job.max_attempts,
                Job.lease_owner == job.lease_owner,
                Job.lease_expires_at <= now,
            )
            .values(lease_owner=Job.lease_owner, updated_at=Job.updated_at)
        )
        .rowcount
    )
    if changed != 1:
        session.rollback()
        return
    # Read completion only after the conditional lock. A worker can have
    # committed its final owned transaction while this acquisition was waiting.
    session.refresh(job)
    ingestion = _linked_ingestion(session, job)
    if ingestion is not None:
        session.refresh(ingestion)
    completed = {
        IngestionState.succeeded: JobState.succeeded,
        IngestionState.partial: JobState.partial,
        IngestionState.cancelled: JobState.cancelled,
    }
    state = completed.get(ingestion.state) if ingestion is not None else None
    job.state = state or JobState.dead_lettered
    job.lease_owner = None
    job.lease_expires_at = None
    job.last_error = None if state else "ingestion final attempt lease expired"
    if ingestion is not None and state is None:
        ingestion.state = IngestionState.dead_lettered
        ingestion.error_code = "lease_exhausted"
        ingestion.error_message = "ingestion final attempt lease expired"
        ingestion.completed_at = now
        ingestion.diagnostics = [
            *ingestion.diagnostics,
            {
                "phase": "worker",
                "status": "failed",
                "code": "lease_exhausted",
                "attempt": job.attempts,
            },
        ]
    session.commit()


def claim_next(session: Session, worker_id: str, lease_seconds: int) -> Job | None:
    now = datetime.now(UTC)
    _expire_exhausted_ingestion(session, now)
    query = (
        select(Job)
        .where(
            or_(
                Job.state == JobState.queued,
                (Job.state == JobState.running) & (Job.lease_expires_at < now),
            ),
            Job.available_at <= now,
            Job.attempts < Job.max_attempts,
            # Provider attempts have irreversible external spend. Only their
            # dedicated fenced worker may claim or recover these jobs.
            ~Job.kind.startswith("model_provider"),
        )
        .order_by(Job.available_at, Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = session.scalar(query)
    if not job:
        return None
    recovered_lease = job.state is JobState.running
    # SQLite ignores SELECT FOR UPDATE. Repeat admission atomically so a stale
    # queued/expired read cannot steal a claim or reuse its attempt generation.
    generation = (
        session.connection()
        .execute(
            update(Job)
            .where(
                Job.id == job.id,
                Job.project_id == job.project_id,
                Job.kind == job.kind,
                Job.attempts == job.attempts,
                Job.attempts < Job.max_attempts,
                Job.available_at <= now,
                or_(
                    Job.state == JobState.queued,
                    (Job.state == JobState.running) & (Job.lease_expires_at < now),
                ),
            )
            .values(
                state=JobState.running,
                lease_owner=worker_id,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                attempts=Job.attempts + 1,
            )
            .returning(Job.attempts)
        )
        .scalar_one_or_none()
    )
    if generation is None:
        session.rollback()
        return None
    session.refresh(job)
    # Preserve this generation before commit/refresh can expose a newer claim.
    claim = capture_claim(job, worker_id)
    session.commit()
    session.refresh(job)
    bind_claim(job, claim)
    if recovered_lease:
        with stage("job") as span:
            span.set_attribute("job.event", "recovered_lease")
            observe_result("worker_events", "recovered_lease")
    return job


def heartbeat(session: Session, job: Job, worker_id: str, lease_seconds: int) -> None:
    guard = active_guard(session)
    if guard is not None:
        guard.renew(job, worker_id, lease_seconds)
        session.commit()
        return
    claim = bound_claim(job)
    if (claim and claim.kind == INGEST_JOB_KIND) or job.kind == INGEST_JOB_KIND:
        claim = claimed_identity(job, worker_id)
        with ClaimGuard(session, claim):
            heartbeat(session, job, worker_id, lease_seconds)
        return
    session.refresh(job)
    if job.state is not JobState.running or job.lease_owner != worker_id:
        raise RuntimeError("job lease is no longer owned by this worker")
    job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
    session.commit()


def complete(session: Session, job: Job, *, partial: bool = False) -> None:
    guard = active_guard(session)
    if guard is not None:
        guard.check_target(job)
    claim = bound_claim(job)
    if active_guard(session) is None and (
        (claim and claim.kind == INGEST_JOB_KIND) or job.kind == INGEST_JOB_KIND
    ):
        if claim is None:
            raise LeaseLost()
        try:
            with ClaimGuard(session, claim):
                complete(session, job, partial=partial)
        except LeaseLost:
            session.rollback()
            session.refresh(job)
            if job.state is not JobState.cancelled:
                raise
        return
    session.refresh(job)
    if job.state is JobState.cancelled:
        job.lease_owner = None
        job.lease_expires_at = None
        session.commit()
        return
    job.state = JobState.partial if partial else JobState.succeeded
    job.lease_owner = None
    job.lease_expires_at = None
    job.last_error = None
    session.commit()


def _linked_ingestion(session: Session, job: Job) -> Ingestion | None:
    ingestion_id = (
        job.payload.get("ingestion_id") if isinstance(job.payload, dict) else None
    )
    if not isinstance(ingestion_id, str):
        return None
    claim = bound_claim(job)
    if (
        claim is not None
        and claim.kind == INGEST_JOB_KIND
        and (claim.ingestion_id != ingestion_id)
    ):
        return None
    ingestion = session.get(Ingestion, ingestion_id)
    if ingestion is not None and (
        ingestion.project_id != job.project_id or ingestion.job_id != job.id
    ):
        return None
    return ingestion


def fail(
    session: Session,
    job: Job,
    error: str,
    *,
    error_code: str = "worker_error",
    permanent: bool = False,
) -> None:
    guard = active_guard(session)
    if guard is not None:
        guard.check_target(job)
    claim = bound_claim(job)
    if active_guard(session) is None and (
        (claim and claim.kind == INGEST_JOB_KIND) or job.kind == INGEST_JOB_KIND
    ):
        if claim is None:
            raise LeaseLost()
        try:
            with ClaimGuard(session, claim, require_scope=False):
                fail(session, job, error, error_code=error_code, permanent=permanent)
        except LeaseLost:
            session.rollback()
            session.refresh(job)
            if job.state is not JobState.cancelled:
                raise
        return
    # A cancellation may race with worker failure handling. Never resurrect a
    # cancelled job or ingestion as queued merely because the worker observed
    # that it lost its lease.
    if job.state is JobState.cancelled:
        job.lease_owner = None
        job.lease_expires_at = None
        session.commit()
        return

    job.last_error = error[:4000]
    job.lease_owner = None
    job.lease_expires_at = None
    terminal = permanent or job.attempts >= job.max_attempts
    job.state = JobState.dead_lettered if terminal else JobState.queued
    if not terminal:
        job.available_at = datetime.now(UTC) + timedelta(
            seconds=min(60, 2**job.attempts)
        )

    ingestion = _linked_ingestion(session, job)
    if ingestion and ingestion.state is not IngestionState.cancelled:
        ingestion.error_code = error_code
        ingestion.error_message = error[:4000]
        ingestion.completed_at = datetime.now(UTC) if terminal else None
        if permanent:
            ingestion.state = IngestionState.failed
        elif terminal:
            ingestion.state = IngestionState.dead_lettered
        else:
            ingestion.state = IngestionState.queued
        ingestion.diagnostics = [
            *ingestion.diagnostics,
            {
                "phase": "worker",
                "status": "failed" if terminal else "retry_queued",
                "code": error_code,
                "attempt": job.attempts,
            },
        ]
    session.commit()


def _process_claimed(
    session: Session,
    job: Job,
    worker_id: str,
    settings: Settings,
) -> str | None:
    from .retention import RETENTION_JOB_KIND, process_cleanup

    if job.kind == RETENTION_JOB_KIND:
        process_cleanup(session, job, worker_id, settings)
        return None
    if job.kind == "noop":
        complete(session, job)
        return None
    if job.kind != INGEST_JOB_KIND:
        raise RuntimeError(f"Unsupported job kind: {job.kind}")

    ingestion = _linked_ingestion(session, job)
    if ingestion is None:
        raise IngestionError("missing_ingestion", "Job references a missing ingestion")
    if ingestion.state is IngestionState.cancelled:
        job.state = JobState.cancelled
        job.lease_owner = None
        job.lease_expires_at = None
        session.commit()
        return None

    ingestion.state = IngestionState.running
    ingestion.started_at = ingestion.started_at or datetime.now(UTC)
    ingestion.error_code = None
    ingestion.error_message = None
    ingestion.diagnostics = [
        *ingestion.diagnostics,
        {"phase": "worker", "status": "running", "attempt": job.attempts},
    ]
    session.commit()

    def pulse() -> None:
        heartbeat(session, job, worker_id, settings.job_lease_seconds)

    run = process_artifact_ingestion(
        session,
        ingestion,
        settings=settings,
        heartbeat=pulse,
    )
    session.refresh(job)
    session.refresh(ingestion)
    if job.state is JobState.cancelled or ingestion.state is IngestionState.cancelled:
        job.state = JobState.cancelled
        job.lease_owner = None
        job.lease_expires_at = None
        ingestion.state = IngestionState.cancelled
        ingestion.completed_at = ingestion.completed_at or datetime.now(UTC)
        session.commit()
        return None
    complete(session, job, partial=run.completeness != "complete")
    return ingestion.project_id


def process_claimed(
    session: Session, job: Job, worker_id: str, settings: Settings
) -> None:
    try:
        claim = claimed_identity(job, worker_id)
    except LeaseLost:
        session.rollback()
        return
    parent = job.payload.get("traceparent") if isinstance(job.payload, dict) else None
    with stage("job", parent=parent, kind=SpanKind.CONSUMER) as span:
        span.set_attribute(
            "job.kind",
            job.kind
            if job.kind in {INGEST_JOB_KIND, "retention_cleanup_v1", "noop"}
            else "unsupported",
        )
        span.set_attribute("job.attempt", max(0, min(20, job.attempts)))
        created = (
            job.created_at.replace(tzinfo=UTC)
            if job.created_at.tzinfo is None
            else job.created_at
        )
        span.set_attribute(
            "job.queue_delay_ms",
            max(0, (datetime.now(UTC) - created).total_seconds() * 1000),
        )
        if claim.kind == INGEST_JOB_KIND:
            try:
                with ClaimGuard(session, claim) as guard:
                    guard.check()
                    cleanup_project = _process_claimed(
                        session, job, worker_id, settings
                    )
            except ClaimScopeInvalid as exc:
                raise IngestionError(
                    "missing_ingestion",
                    "Job references a missing or mismatched ingestion",
                ) from exc
            except LeaseLost:
                session.rollback()
                return
            # Deletion outbox processing has its own project/live-reference
            # locks. A completed job no longer has a running ingestion claim.
            if cleanup_project is not None:
                from .retention import flush_deletions

                flush_deletions(session, cleanup_project, settings)
        else:
            _process_claimed(session, job, worker_id, settings)


def process_next(
    session: Session,
    worker_id: str,
    *,
    settings: Settings | None = None,
) -> bool:
    settings = settings or get_settings()
    job = claim_next(session, worker_id, settings.job_lease_seconds)
    if not job:
        return False
    claim = claimed_identity(job, worker_id)

    def record_failure(current, message, **kwargs):
        if claim.kind != INGEST_JOB_KIND:
            fail(session, current, message, **kwargs)
            return
        try:
            # Only the claimed generation may record an error. In particular,
            # worker IDs can be reused by a successor and are not a fence.
            with ClaimGuard(session, claim, require_scope=False):
                fail(session, current, message, **kwargs)
        except LeaseLost:
            session.rollback()

    try:
        process_claimed(session, job, worker_id, settings)
    except (IngestionError, StorageError) as exc:
        session.rollback()
        current = session.get(Job, job.id)
        if current is not None and (
            current.lease_owner == worker_id or current.state == JobState.cancelled
        ):
            record_failure(
                current,
                exc.code if current.kind == "retention_cleanup_v1" else str(exc),
                error_code=exc.code,
                permanent=exc.code in PERMANENT_INGESTION_ERRORS
                or exc.code == "missing_ingestion",
            )
    except Exception as exc:  # worker boundary
        logger.exception("worker_boundary_error", exc_info=False)
        session.rollback()
        current = session.get(Job, job.id)
        if current is not None and (
            current.lease_owner == worker_id or current.state == JobState.cancelled
        ):
            message = (
                "retention_worker_error"
                if current.kind == "retention_cleanup_v1"
                else str(exc)
            )
            record_failure(current, message)
    return True


def run_once(
    worker_id: str,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
    settings: Settings | None = None,
) -> bool:
    with session_factory() as session:
        return process_next(session, worker_id, settings=settings)


def main() -> None:
    parser = argparse.ArgumentParser(description="FailureLens durable worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    initialize_database()
    configure_telemetry()
    stopped = threading.Event()
    previous_handlers = {}

    def request_stop(signum, frame):
        # Finish the currently claimed job, then drain telemetry before exit.
        stopped.set()

    try:
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous_handlers[signum] = signal.signal(signum, request_stop)
        worker_id = f"{socket.gethostname()}-{int(time.time())}"
        next_retention_sweep = 0.0
        while not stopped.is_set():
            if time.monotonic() >= next_retention_sweep:
                from .retention import schedule_due

                with SessionLocal() as maintenance_session:
                    schedule_due(maintenance_session)
                next_retention_sweep = time.monotonic() + 60
            if stopped.is_set():
                break
            worked = run_once(worker_id)
            if args.once:
                return
            if not worked:
                stopped.wait(max(0.1, args.poll_seconds))
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        shutdown_telemetry()


if __name__ == "__main__":
    main()
