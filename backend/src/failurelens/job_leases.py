"""Transaction fences for durable ingestion, separate from provider/retention jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Self

from sqlalchemy import event, exists, select, update
from sqlalchemy.orm import Session

from .models import Ingestion, Job, JobState

_CLAIM_ATTRIBUTE = "_ingestion_claim"
_GUARD_KEY = "ingestion_claim_guard"


class LeaseLost(RuntimeError):
    def __init__(self) -> None:
        super().__init__("ingestion claim is no longer current")


class ClaimScopeInvalid(RuntimeError):
    def __init__(self) -> None:
        super().__init__("current ingestion job has invalid scope")


@dataclass(frozen=True)
class Claim:
    job_id: str
    project_id: str
    kind: str
    owner: str
    attempts: int
    ingestion_id: str | None


def capture_claim(job: Job, owner: str) -> Claim:
    payload = job.payload if isinstance(job.payload, dict) else {}
    ingestion_id = payload.get("ingestion_id")
    return Claim(
        job.id,
        job.project_id,
        job.kind,
        owner,
        job.attempts,
        ingestion_id if isinstance(ingestion_id, str) else None,
    )


def bind_claim(job: Job, claim: Claim) -> None:
    setattr(job, _CLAIM_ATTRIBUTE, claim)


def bound_claim(job: Job) -> Claim | None:
    claim = getattr(job, _CLAIM_ATTRIBUTE, None)
    return claim if isinstance(claim, Claim) and claim.job_id == job.id else None


def claimed_identity(job: Job, owner: str) -> Claim:
    claim = bound_claim(job)
    if claim is None or claim.owner != owner:
        raise LeaseLost()
    return claim


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def active_guard(session: Session) -> ClaimGuard | None:
    return session.info.get(_GUARD_KEY)


class ClaimGuard:
    """Fence each writing transaction, including helpers that commit internally.

    A conditional UPDATE both checks the immutable claim generation and acquires
    a write lock on SQLite/PostgreSQL. It preserves timestamps. Cached ownership
    belongs to the exact root/savepoint pair; rollback cannot preserve a lock
    acquired inside a discarded savepoint. An already-owned transaction may
    finish after expiry while its uninterrupted lock prevents recovery. The next
    transaction must recheck expiry; an expired lease can never be renewed.
    """

    def __init__(self, session: Session, claim: Claim, *, require_scope: bool = True):
        self.session = session
        self.claim = claim
        self.require_scope = require_scope
        self.locks: dict[tuple[object, object], datetime] = {}

    def _key(self) -> tuple[object, object]:
        return (self.session.get_transaction(), self.session.get_nested_transaction())

    def check(self) -> None:
        connection = self.session.connection()
        key = self._key()
        now = datetime.now(UTC)
        deadline = self.locks.get(key)
        if deadline is not None:
            return
        claim = self.claim
        statement = (
            update(Job)
            .where(
                Job.id == claim.job_id,
                Job.project_id == claim.project_id,
                Job.kind == claim.kind,
                Job.state == JobState.running,
                Job.lease_owner == claim.owner,
                Job.attempts == claim.attempts,
                Job.lease_expires_at > now,
            )
            .values(lease_owner=Job.lease_owner, updated_at=Job.updated_at)
            .returning(Job.lease_expires_at)
        )
        scoped_statement = statement
        if self.require_scope:
            scoped_statement = scoped_statement.where(
                exists(
                    select(Ingestion.id).where(
                        Ingestion.id == claim.ingestion_id,
                        Ingestion.project_id == claim.project_id,
                        Ingestion.job_id == claim.job_id,
                    )
                )
            )
        # Connection execution bypasses ORM autoflush and this guard's DML
        # listener. No pending business write can precede the fence.
        deadline = connection.execute(scoped_statement).scalar_one_or_none()
        if deadline is None:
            owned_deadline = (
                connection.execute(statement).scalar_one_or_none()
                if self.require_scope
                else None
            )
            if owned_deadline is not None and _utc(owned_deadline) > datetime.now(UTC):
                # Ownership is still ours, so malformed linkage is a permanent
                # job error. It must not be mistaken for a newer worker's claim.
                raise ClaimScopeInvalid()
            raise LeaseLost()
        # Acquiring an UPDATE lock may have waited. Eligibility at statement
        # submission is not proof that the lease is still live on acquisition.
        if _utc(deadline) <= datetime.now(UTC):
            raise LeaseLost()
        self.locks[key] = _utc(deadline)

    def renew(self, job: Job, owner: str, seconds: int) -> None:
        self.check_target(job)
        if owner != self.claim.owner:
            raise LeaseLost()
        self.check()
        if self.locks[self._key()] <= datetime.now(UTC):
            raise LeaseLost()
        self.session.refresh(job)
        deadline = datetime.now(UTC) + timedelta(seconds=seconds)
        job.lease_expires_at = deadline
        self.locks[self._key()] = deadline

    def check_target(self, job: Job) -> None:
        if (
            job.id != self.claim.job_id
            or job.project_id != self.claim.project_id
            or job.kind != self.claim.kind
            or job.attempts != self.claim.attempts
            or job.lease_owner != self.claim.owner
        ):
            raise LeaseLost()

    def _before_flush(self, _session, _context, _instances) -> None:
        self.check()

    def _before_commit(self, _session) -> None:
        self.check()

    def _before_execute(self, execute_state) -> None:
        if (
            execute_state.is_insert
            or execute_state.is_update
            or execute_state.is_delete
        ):
            self.check()

    def _transaction_ended(self, _session, transaction) -> None:
        self.locks = {
            key: deadline
            for key, deadline in self.locks.items()
            if transaction not in key
        }

    def __enter__(self) -> Self:
        if active_guard(self.session) is not None:
            raise RuntimeError("an ingestion claim guard is already active")
        self.session.info[_GUARD_KEY] = self
        for name, callback in self._listeners():
            event.listen(self.session, name, callback)
        return self

    def _listeners(self):
        return (
            ("before_flush", self._before_flush),
            ("before_commit", self._before_commit),
            ("do_orm_execute", self._before_execute),
            ("after_transaction_end", self._transaction_ended),
        )

    def __exit__(self, exc_type, _exc, _traceback) -> None:
        for name, callback in self._listeners():
            event.remove(self.session, name, callback)
        self.session.info.pop(_GUARD_KEY, None)
        self.locks.clear()
        if exc_type is not None:
            self.session.rollback()
