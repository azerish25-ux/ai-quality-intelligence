from __future__ import annotations

import argparse
import socket
import time
from datetime import UTC, datetime, timedelta
from typing import Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import SessionLocal, initialize_database
from .ingestion import IngestionError
from .models import Ingestion, IngestionState, Job, JobState
from .service import INGEST_JOB_KIND, process_artifact_ingestion
from .storage import StorageError


PERMANENT_INGESTION_ERRORS = {
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


def claim_next(session: Session, worker_id: str, lease_seconds: int) -> Job | None:
    now = datetime.now(UTC)
    query = (
        select(Job)
        .where(
            or_(
                Job.state == JobState.queued,
                (Job.state == JobState.running) & (Job.lease_expires_at < now),
            ),
            Job.available_at <= now,
            Job.attempts < Job.max_attempts,
        )
        .order_by(Job.available_at, Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = session.scalar(query)
    if not job:
        return None
    job.state = JobState.running
    job.lease_owner = worker_id
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.attempts += 1
    session.commit()
    session.refresh(job)
    return job


def heartbeat(session: Session, job: Job, worker_id: str, lease_seconds: int) -> None:
    session.refresh(job)
    if job.state is not JobState.running or job.lease_owner != worker_id:
        raise RuntimeError("job lease is no longer owned by this worker")
    job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
    session.commit()


def complete(session: Session, job: Job, *, partial: bool = False) -> None:
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
    ingestion_id = job.payload.get("ingestion_id") if isinstance(job.payload, dict) else None
    if not isinstance(ingestion_id, str):
        return None
    return session.get(Ingestion, ingestion_id)


def fail(
    session: Session,
    job: Job,
    error: str,
    *,
    error_code: str = "worker_error",
    permanent: bool = False,
) -> None:
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
        job.available_at = datetime.now(UTC) + timedelta(seconds=min(60, 2 ** job.attempts))

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


def process_claimed(
    session: Session,
    job: Job,
    worker_id: str,
    settings: Settings,
) -> None:
    from .retention import RETENTION_JOB_KIND, process_cleanup
    if job.kind == RETENTION_JOB_KIND:
        process_cleanup(session, job, worker_id, settings)
        return
    if job.kind == "noop":
        complete(session, job)
        return
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
        return

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
        return
    complete(session, job, partial=run.completeness != "complete")


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
    try:
        process_claimed(session, job, worker_id, settings)
    except (IngestionError, StorageError) as exc:
        session.rollback()
        current = session.get(Job, job.id)
        if current is not None and (current.lease_owner == worker_id or current.state == JobState.cancelled):
            fail(
                session,
                current,
                exc.code if current.kind == "retention_cleanup_v1" else str(exc),
                error_code=exc.code,
                permanent=exc.code in PERMANENT_INGESTION_ERRORS or exc.code == "missing_ingestion",
            )
    except Exception as exc:  # worker boundary
        session.rollback()
        current = session.get(Job, job.id)
        if current is not None and (current.lease_owner == worker_id or current.state == JobState.cancelled):
            message = "retention_worker_error" if current.kind == "retention_cleanup_v1" else str(exc)
            fail(session, current, message)
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
    worker_id = f"{socket.gethostname()}-{int(time.time())}"
    next_retention_sweep = 0.0
    while True:
        if time.monotonic() >= next_retention_sweep:
            from .retention import schedule_due
            with SessionLocal() as maintenance_session:
                schedule_due(maintenance_session)
            next_retention_sweep = time.monotonic() + 60
        worked = run_once(worker_id)
        if args.once:
            return
        if not worked:
            time.sleep(max(0.1, args.poll_seconds))


if __name__ == "__main__":
    main()
