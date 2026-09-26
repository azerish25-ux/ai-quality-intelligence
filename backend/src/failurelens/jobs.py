from __future__ import annotations

import argparse
import socket
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SessionLocal, initialize_database
from .models import Job, JobState


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


def complete(session: Session, job: Job) -> None:
    job.state = JobState.succeeded
    job.lease_owner = None
    job.lease_expires_at = None
    session.commit()


def fail(session: Session, job: Job, error: str) -> None:
    job.last_error = error[:4000]
    job.lease_owner = None
    job.lease_expires_at = None
    job.state = JobState.dead_lettered if job.attempts >= job.max_attempts else JobState.queued
    job.available_at = datetime.now(UTC) + timedelta(seconds=min(60, 2 ** job.attempts))
    session.commit()


def run_once(worker_id: str) -> bool:
    settings = get_settings()
    with SessionLocal() as session:
        job = claim_next(session, worker_id, settings.job_lease_seconds)
        if not job:
            return False
        try:
            if job.kind == "noop":
                complete(session, job)
            else:
                raise RuntimeError(f"Unsupported job kind: {job.kind}")
        except Exception as exc:  # worker boundary
            fail(session, job, str(exc))
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="FailureLens durable worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    initialize_database()
    worker_id = f"{socket.gethostname()}-{int(time.time())}"
    while True:
        worked = run_once(worker_id)
        if args.once:
            return
        if not worked:
            time.sleep(max(0.1, args.poll_seconds))
