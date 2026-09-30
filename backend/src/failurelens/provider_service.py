"""Database-to-provider bridge: only revalidated safe derivatives may leave."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, inspect, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from . import models as m
from .evidence_validation import persisted_analysis_is_publication_validated
from .models import Analysis
from .providers import (
    PROMPT_VERSION,
    HTTPModelProvider,
    ProviderBoundaryError,
    ProviderResult,
    RunBudget,
    prepare_request,
    validate_proposal,
)
from .publication_validity import PublicationContext
from .service import select_failure_evidence


def propose_for_analysis(
    session: Session,
    analysis: Analysis,
    provider: HTTPModelProvider,
    *,
    budget: RunBudget,
    cancel=None,
) -> dict:
    """Compatibility helper with in-process accounting; use durable_propose_for_analysis for workers."""
    category = analysis.category.value
    if not session.autoflush:
        return asdict(
            ProviderResult(
                "fallback", category, reason="unsupported_session_configuration"
            )
        )
    failure = analysis.failure
    scope = {
        "project_id": failure.project_id,
        "run_id": failure.run_id,
        "analysis_id": analysis.id,
    }
    try:
        snapshot = _snapshot(session, **scope)
    except (ProviderBoundaryError, ProviderScopeError) as exc:
        return asdict(
            ProviderResult(
                "fallback",
                category,
                reason=str(exc)
                if isinstance(exc, ProviderBoundaryError)
                else "scope_changed",
            )
        )
    checked_budget = _LegacySnapshotBudget(
        session=session, expected=snapshot, budget=budget, **scope
    )
    result = provider.propose(
        deterministic_category=snapshot.category,
        evidence=snapshot.evidence,
        budget=checked_budget,
        cancel=cancel,
    )
    if result.status == "proposed":
        try:
            checked_budget.validate()
        except ProviderBoundaryError as exc:
            result = replace(result, status="fallback", proposal=None, reason=str(exc))
    # The deterministic row is intentionally never overwritten or reclassified.
    return asdict(result)


# The legacy bridge above remains an in-process library helper. Application workers
# must use the factory-based boundary below: it never commits a caller's work and
# never holds a database transaction across transport.
class ProviderScopeError(ValueError):
    """The requested resource does not exist in the explicitly supplied scope."""


class ProviderIdempotencyConflict(ValueError):
    """An idempotency identity cannot be reused for a different request."""


def _canonical(value):
    def encode(item):
        if isinstance(item, datetime):
            return _aware(item).isoformat()
        raise TypeError("unsupported fingerprint value")

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=encode,
    )


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _provider_digest(config):
    # Credentials are intentionally absent: rotation cannot reset a logical request.
    return _digest(
        {
            field.name: getattr(config, field.name)
            for field in fields(config)
            if field.name not in {"token", "enabled"}
            # Preserve existing direct-transport invocation identities on upgrade.
            and not (field.name == "proxy" and config.proxy is None)
        }
    )


def _lock_scope(session, project_id, run_id):
    # A write, rather than SELECT FOR UPDATE alone, also serializes SQLite writers.
    # The same project row is locked by retention on PostgreSQL. This is always
    # the first statement in our own fresh transaction, avoiding SQLite upgrades.
    changed = session.execute(
        update(m.Project).where(m.Project.id == project_id).values(id=m.Project.id)
    )
    if changed.rowcount != 1:
        raise ProviderScopeError("requested provider scope not found")
    run = session.scalar(
        select(m.Run).where(m.Run.id == run_id, m.Run.project_id == project_id)
    )
    if run is None:
        raise ProviderScopeError("requested provider scope not found")
    return run


def _analysis(session, project_id, run_id, analysis_id):
    analysis = session.scalar(
        select(m.Analysis)
        .join(m.Failure)
        .where(
            m.Analysis.id == analysis_id,
            m.Failure.project_id == project_id,
            m.Failure.run_id == run_id,
        )
        .options(
            selectinload(m.Analysis.failure).selectinload(m.Failure.run),
            selectinload(m.Analysis.failure).selectinload(m.Failure.execution),
        )
        .execution_options(populate_existing=True)
    )
    if analysis is None or analysis.failure.run.project_id != project_id:
        raise ProviderScopeError("requested provider scope not found")
    if analysis.failure.execution.run_id != run_id:
        raise ProviderScopeError("requested provider scope not found")
    return analysis


@dataclass(frozen=True)
class _Snapshot:
    category: str
    revision: int
    analysis_digest: str
    evidence_digest: str
    evidence: list[dict]


@dataclass
class _LegacySnapshotBudget:
    """Revalidate on the owning thread; late accounting never touches its Session."""

    session: Session
    expected: _Snapshot
    budget: RunBudget
    project_id: str
    run_id: str
    analysis_id: str

    def validate(self):
        # populate_existing relies on normal autoflush to preserve pending writes.
        # Never change caller configuration or discard its unflushed attributes.
        if not self.session.autoflush:
            raise ProviderBoundaryError("unsupported_session_configuration")
        try:
            current = _snapshot(
                self.session, self.project_id, self.run_id, self.analysis_id
            )
        except ProviderScopeError:
            raise ProviderBoundaryError("scope_changed") from None
        if current != self.expected:
            raise ProviderBoundaryError("immutable_input_changed")

    def reserve(self, config, reserved_tokens):
        self.validate()
        return self.budget.reserve(config, reserved_tokens)

    def complete(self, number, result, *, sent, http_status, transport_terminated=True):
        self.budget.complete(
            number,
            result,
            sent=sent,
            http_status=http_status,
            transport_terminated=transport_terminated,
        )


def _snapshot(session, project_id, run_id, analysis_id):
    analysis = _analysis(session, project_id, run_id, analysis_id)
    if analysis.failure.run.evidence_expired_at is not None:
        raise ProviderBoundaryError("evidence_expired")
    if not persisted_analysis_is_publication_validated(analysis):
        raise ProviderBoundaryError("unvalidated_deterministic_analysis")
    if not analysis.input_digest:
        raise ProviderBoundaryError("missing_analysis_digest")
    context = PublicationContext(session)
    rows = select_failure_evidence(session, analysis.failure)
    accepted = set(context.failure_evidence(analysis.failure, rows).accepted_ids)
    permitted = set(
        analysis.supporting_evidence_ids + analysis.contradictory_evidence_ids
    )
    if not permitted or not permitted.issubset(accepted):
        raise ProviderBoundaryError("evidence_not_available")
    validity = context.analysis(analysis)
    if not validity.valid:
        raise ProviderBoundaryError(
            "historical_support_unavailable"
            if "historical_support_unavailable" in validity.reasons
            else "evidence_not_available"
        )
    rows = [row for row in rows if row.id in permitted]
    evidence = [
        {"id": row.id, "excerpt": row.excerpt, "approved": True} for row in rows
    ]
    analysis_digest = _digest(
        {
            column.key: getattr(analysis, column.key)
            for column in inspect(m.Analysis).column_attrs
        }
    )
    evidence_digest_rows = []
    for row in rows:
        derivative = row.derivative
        if derivative is None:
            raise ProviderBoundaryError("evidence_not_available")
        evidence_digest_rows.append(
            {
                "id": row.id,
                "project_id": row.project_id,
                "run_id": row.run_id,
                "execution_id": row.execution_id,
                "derivative_id": row.derivative_id,
                "content_digest": row.content_digest,
                "derivative_digest": derivative.digest,
                "source_digest": derivative.source_digest,
                "excerpt": row.excerpt,
            }
        )
    evidence_digest = _digest(evidence_digest_rows)
    return _Snapshot(
        analysis.category.value,
        analysis.revision,
        analysis_digest,
        evidence_digest,
        evidence,
    )


def _match_snapshot(invocation, snapshot):
    if (
        snapshot.analysis_digest != invocation.analysis_digest
        or snapshot.evidence_digest != invocation.evidence_digest
        or snapshot.revision != invocation.analysis_revision
        or snapshot.category != invocation.deterministic_category
    ):
        raise ProviderBoundaryError("immutable_input_changed")


def _owned(invocation, owner, now=None):
    if (
        invocation is None
        or invocation.status != "running"
        or invocation.owner_token != owner
        or invocation.cancel_requested_at is not None
    ):
        raise ProviderBoundaryError("invocation_interrupted")
    if _aware(invocation.lease_expires_at) <= (now or m.utcnow()):
        raise ProviderBoundaryError("invocation_lease_expired")


def _lease_duration(config):
    return timedelta(
        seconds=max(
            60,
            config.timeout_seconds * (config.max_attempts + 1)
            + config.max_attempts * (config.min_interval_seconds + 4)
            + 30,
        )
    )


class _DurableAttemptBudget:
    def __init__(self, factory, invocation_id, project_id, run_id, owner, config):
        self.factory, self.invocation_id = factory, invocation_id
        self.project_id, self.run_id, self.owner, self.config = (
            project_id,
            run_id,
            owner,
            config,
        )

    def _admit(self, session, invocation, config):
        return None

    def _now(self, session):
        return m.utcnow()

    def _settle(self, session, attempt, result, *, terminated, late, sent):
        if terminated:
            attempt.transport_terminated_at = m.utcnow()

    def reserve(self, config, reserved_tokens):
        with self.factory.begin() as session:
            _lock_scope(session, self.project_id, self.run_id)
            invocation = session.get(m.ModelInvocation, self.invocation_id)
            _owned(invocation, self.owner, self._now(session))
            if _provider_digest(config) != invocation.provider_digest:
                raise ProviderBoundaryError("provider_configuration_changed")
            snapshot = _snapshot(
                session, self.project_id, self.run_id, invocation.analysis_id
            )
            _match_snapshot(invocation, snapshot)
            prepared = prepare_request(config, snapshot.category, snapshot.evidence)
            if (
                isinstance(prepared, ProviderResult)
                or _digest(prepared.payload) != invocation.request_digest
            ):
                raise ProviderBoundaryError("immutable_input_changed")
            if reserved_tokens != prepared.reserved_tokens:
                raise ProviderBoundaryError("reservation_mismatch")
            budget = session.get(m.ModelRunBudget, self.run_id)
            # Persist stricter limits; no provider recreation can raise the ceiling.
            budget.max_requests = min(budget.max_requests, config.max_run_requests)
            budget.max_reserved_tokens = min(
                budget.max_reserved_tokens, config.max_run_reserved_tokens
            )
            session.flush()
            changed = session.execute(
                update(m.ModelRunBudget)
                .where(
                    m.ModelRunBudget.run_id == self.run_id,
                    m.ModelRunBudget.project_id == self.project_id,
                    m.ModelRunBudget.requests < m.ModelRunBudget.max_requests,
                    m.ModelRunBudget.reserved_tokens + reserved_tokens
                    <= m.ModelRunBudget.max_reserved_tokens,
                )
                .values(
                    requests=m.ModelRunBudget.requests + 1,
                    reserved_tokens=m.ModelRunBudget.reserved_tokens + reserved_tokens,
                )
            )
            if changed.rowcount != 1:
                return None
            admission_id = self._admit(session, invocation, config)
            number = (
                session.scalar(
                    select(func.count())
                    .select_from(m.ModelAttempt)
                    .where(m.ModelAttempt.invocation_id == invocation.id)
                )
                + 1
            )
            session.add(
                m.ModelAttempt(
                    invocation_id=invocation.id,
                    owner_token=self.owner,
                    admission_id=admission_id,
                    number=number,
                    reserved_tokens=reserved_tokens,
                    accounted_tokens=reserved_tokens,
                    input_price_per_million=config.input_price_per_million,
                    output_price_per_million=config.output_price_per_million,
                    pricing_source=config.pricing_source,
                    pricing_date=config.pricing_date,
                    currency=config.currency,
                )
            )
            invocation.lease_expires_at = self._now(session) + _lease_duration(config)
        # Exit/commit must succeed before a transport is permitted to run.
        return number

    def complete(self, number, result, *, sent, http_status, transport_terminated=True):
        with self.factory.begin() as session:
            _lock_scope(session, self.project_id, self.run_id)
            invocation = session.get(m.ModelInvocation, self.invocation_id)
            if invocation is None:
                raise ProviderBoundaryError("invocation_interrupted")
            attempt = session.scalar(
                select(m.ModelAttempt).where(
                    m.ModelAttempt.invocation_id == invocation.id,
                    m.ModelAttempt.number == number,
                )
            )
            if (
                attempt is None
                or attempt.owner_token != self.owner
                or attempt.status not in {"reserved", "uncertain"}
            ):
                raise ProviderBoundaryError("attempt_already_completed")
            # The fenced owner may reconcile only its own numeric attempt result.
            # It can never restore invocation ownership, publish, or reserve again.
            late = (
                invocation.status != "running"
                or invocation.owner_token != self.owner
                or _aware(invocation.lease_expires_at) <= self._now(session)
            )
            attempt.status = (
                "uncertain"
                if not transport_terminated
                else "reserved"
                if not late
                and invocation.job_id is None
                and result.reason == "transport_unexpected_error"
                else "reconciled"
                if late
                else result.status
            )
            attempt.reason = result.reason or (
                "late_response_after_recovery" if late else None
            )
            attempt.http_status, attempt.completed_at = http_status, self._now(session)
            attempt.spend_status = (
                "not_sent"
                if not sent
                else "reported"
                if result.usage is not None
                else "unknown"
            )
            if result.usage is not None:
                attempt.prompt_tokens, attempt.completion_tokens = (
                    result.usage["prompt_tokens"],
                    result.usage["completion_tokens"],
                )
                total = attempt.prompt_tokens + attempt.completion_tokens
                # Provider-reported overruns must block subsequent reservations,
                # never be hidden by the estimate or treated as a refund.
                overage = max(0, total - attempt.accounted_tokens)
                attempt.accounted_tokens += overage
                if overage:
                    session.execute(
                        update(m.ModelRunBudget)
                        .where(m.ModelRunBudget.run_id == self.run_id)
                        .values(
                            reserved_tokens=m.ModelRunBudget.reserved_tokens + overage
                        )
                    )
            attempt.estimated_cost, attempt.cost_status = (
                result.estimated_cost,
                result.cost_status,
            )
            self._settle(
                session,
                attempt,
                result,
                terminated=transport_terminated,
                late=late,
                sent=sent,
            )


def _attempt_projection(attempt):
    usage = (
        None
        if attempt.prompt_tokens is None
        else {
            "prompt_tokens": attempt.prompt_tokens,
            "completion_tokens": attempt.completion_tokens,
        }
    )
    return {
        "number": attempt.number,
        "status": attempt.status,
        "reason": attempt.reason,
        "http_status": attempt.http_status,
        "reserved_tokens": attempt.reserved_tokens,
        "accounted_tokens": attempt.accounted_tokens,
        "spend_status": attempt.spend_status,
        "usage": usage,
        "estimated_cost": attempt.estimated_cost,
        "cost_status": attempt.cost_status,
        "transport_terminated": attempt.transport_terminated_at is not None,
        "pricing": {
            "input_price_per_million": attempt.input_price_per_million,
            "output_price_per_million": attempt.output_price_per_million,
            "source": attempt.pricing_source,
            "date": attempt.pricing_date,
            "currency": attempt.currency,
        },
    }


def _project_invocation(session, invocation):
    # Only the requested exact scope reaches this function. No secrets, raw
    # provider IDs, owner tokens, prompts or response bodies enter the projection.
    result = ProviderResult(
        "fallback",
        invocation.deterministic_category,
        reason=invocation.reason or "invocation_in_progress",
    )
    if (
        invocation.status == "running"
        and _aware(invocation.lease_expires_at) <= m.utcnow()
    ):
        result = replace(result, reason="invocation_lease_expired")
    try:
        snapshot = _snapshot(
            session, invocation.project_id, invocation.run_id, invocation.analysis_id
        )
        _match_snapshot(invocation, snapshot)
        if invocation.status == "proposed":
            result = validate_proposal(
                invocation.proposal_json,
                snapshot.category,
                {row["id"] for row in snapshot.evidence},
            )
        elif invocation.status == "uncertain":
            result = replace(result, reason="invocation_interrupted")
    except (ProviderBoundaryError, ProviderScopeError) as exc:
        result = replace(
            result,
            reason=str(exc)
            if isinstance(exc, ProviderBoundaryError)
            else "scope_changed",
        )
    attempts = list(
        session.scalars(
            select(m.ModelAttempt)
            .where(m.ModelAttempt.invocation_id == invocation.id)
            .order_by(m.ModelAttempt.number)
        )
    )
    projections = [_attempt_projection(attempt) for attempt in attempts]
    known = [item["usage"] for item in projections if item["usage"] is not None]
    usage = (
        {
            key: sum(item[key] for item in known)
            for key in ("prompt_tokens", "completion_tokens")
        }
        if known
        else None
    )
    complete = bool(attempts) and all(
        item["spend_status"] in {"reported", "not_sent"} for item in projections
    )
    costs = [
        item.estimated_cost for item in attempts if item.estimated_cost is not None
    ]
    currencies = {item.currency for item in attempts if item.estimated_cost is not None}
    full_estimate = (
        bool(attempts) and len(costs) == len(attempts) and len(currencies) == 1
    )
    result = replace(
        result,
        usage=usage,
        estimated_cost=sum(costs) if full_estimate else None,
        cost_status="estimated" if full_estimate else "unknown",
        prompt_version=invocation.prompt_version,
    )
    budget = session.get(m.ModelRunBudget, invocation.run_id)
    return asdict(result) | {
        "invocation_id": invocation.id,
        "invocation_state": invocation.status,
        "usage_complete": complete,
        "attempts": projections,
        "budget": {
            "requests": budget.requests,
            "reserved_tokens": budget.reserved_tokens,
            "max_requests": budget.max_requests,
            "max_reserved_tokens": budget.max_reserved_tokens,
        },
    }


def get_model_invocation(
    factory, *, project_id: str, run_id: str, analysis_id: str, invocation_id: str
) -> dict:
    """Safe scoped projection for an already-authorized caller; never invokes HTTP."""
    with factory.begin() as session:
        _lock_scope(session, project_id, run_id)
        _analysis(session, project_id, run_id, analysis_id)
        invocation = session.scalar(
            select(m.ModelInvocation).where(
                m.ModelInvocation.id == invocation_id,
                m.ModelInvocation.project_id == project_id,
                m.ModelInvocation.run_id == run_id,
                m.ModelInvocation.analysis_id == analysis_id,
            )
        )
        if invocation is None:
            raise ProviderScopeError("requested provider scope not found")
        return _project_invocation(session, invocation)


def recover_model_invocations(factory, *, project_id: str, run_id: str) -> int:
    """Fence expired owners. Never replay an uncertain request or refund its budget."""
    with factory.begin() as session:
        _lock_scope(session, project_id, run_id)
        now = m.utcnow()
        invocations = list(
            session.scalars(
                select(m.ModelInvocation).where(
                    m.ModelInvocation.project_id == project_id,
                    m.ModelInvocation.run_id == run_id,
                    m.ModelInvocation.status == "running",
                    m.ModelInvocation.job_id.is_(None),
                    m.ModelInvocation.lease_expires_at <= now,
                )
            )
        )
        for invocation in invocations:
            invocation.status, invocation.reason = "uncertain", "invocation_interrupted"
            (
                invocation.owner_token,
                invocation.proposal_json,
                invocation.completed_at,
            ) = None, None, now
            session.execute(
                update(m.ModelAttempt)
                .where(
                    m.ModelAttempt.invocation_id == invocation.id,
                    m.ModelAttempt.status == "reserved",
                )
                .values(
                    status="uncertain",
                    reason="invocation_interrupted",
                    completed_at=now,
                )
            )
        return len(invocations)


def durable_propose_for_analysis(
    factory,
    provider: HTTPModelProvider,
    *,
    project_id: str,
    run_id: str,
    analysis_id: str,
    idempotency_key: str,
    cancel=None,
) -> dict:
    """Opt-in, restart-safe provider boundary; factory must create fresh Sessions.

    Project authorization belongs to the caller, as with other internal services.
    Scope, immutable inputs and publication safety are independently revalidated.
    No request is replayed after an uncertain interruption. No real provider is
    enabled by startup or by constructing this durable bookkeeping foundation.
    """
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 200:
        raise ValueError("a bounded idempotency key is required")
    config = provider.config
    key_digest = _digest(idempotency_key)
    owner = m.new_id()
    with factory.begin() as session:
        _lock_scope(session, project_id, run_id)
        analysis = _analysis(session, project_id, run_id, analysis_id)
        category = analysis.category.value
        if not config.enabled:
            return asdict(ProviderResult("fallback", category, reason="disabled"))
        existing = session.scalar(
            select(m.ModelInvocation).where(
                m.ModelInvocation.project_id == project_id,
                m.ModelInvocation.idempotency_digest == key_digest,
            )
        )
        # Scope/config conflicts are checked even if evidence has since expired.
        if existing and (
            existing.run_id != run_id
            or existing.analysis_id != analysis_id
            or existing.provider_digest != _provider_digest(config)
        ):
            raise ProviderIdempotencyConflict(
                "idempotency key conflicts with an existing request"
            )
        try:
            snapshot = _snapshot(session, project_id, run_id, analysis_id)
        except ProviderBoundaryError as exc:
            if existing:
                return _project_invocation(session, existing)
            return asdict(ProviderResult("fallback", category, reason=str(exc)))
        prepared = prepare_request(config, snapshot.category, snapshot.evidence)
        if isinstance(prepared, ProviderResult):
            return asdict(prepared)
        request_digest = _digest(prepared.payload)
        if existing:
            if (
                existing.analysis_digest != snapshot.analysis_digest
                or existing.evidence_digest != snapshot.evidence_digest
                or existing.request_digest != request_digest
            ):
                raise ProviderIdempotencyConflict(
                    "idempotency key conflicts with an existing request"
                )
            return _project_invocation(session, existing)
        budget = session.get(m.ModelRunBudget, run_id)
        if budget is None:
            session.add(
                m.ModelRunBudget(
                    run_id=run_id,
                    project_id=project_id,
                    max_requests=config.max_run_requests,
                    max_reserved_tokens=config.max_run_reserved_tokens,
                )
            )
            session.flush()
        invocation = m.ModelInvocation(
            project_id=project_id,
            run_id=run_id,
            analysis_id=analysis_id,
            analysis_revision=snapshot.revision,
            analysis_digest=snapshot.analysis_digest,
            evidence_digest=snapshot.evidence_digest,
            request_digest=request_digest,
            provider_digest=_provider_digest(config),
            idempotency_digest=key_digest,
            deterministic_category=snapshot.category,
            prompt_version=PROMPT_VERSION,
            owner_token=owner,
            lease_expires_at=m.utcnow() + _lease_duration(config),
        )
        session.add(invocation)
        session.flush()
        invocation_id = invocation.id
    budget = _DurableAttemptBudget(
        factory, invocation_id, project_id, run_id, owner, config
    )
    try:
        result = provider.propose(
            deterministic_category=snapshot.category,
            evidence=snapshot.evidence,
            budget=budget,
            cancel=cancel,
        )
    except ProviderScopeError:
        return asdict(ProviderResult("fallback", category, reason="scope_changed")) | {
            "invocation_id": invocation_id
        }
    except SQLAlchemyError:
        # An uncertain commit must never authorize another call. Recovery, not an
        # automatic transport retry, resolves the persisted active state later.
        return asdict(
            ProviderResult("fallback", category, reason="ledger_unavailable")
        ) | {"invocation_id": invocation_id}
    with factory.begin() as session:
        _lock_scope(session, project_id, run_id)
        invocation = session.get(m.ModelInvocation, invocation_id)
        if invocation is None:
            return asdict(
                ProviderResult("fallback", category, reason="invocation_interrupted")
            ) | {"invocation_id": invocation_id}
        try:
            _owned(invocation, owner)
        except ProviderBoundaryError:
            return _project_invocation(session, invocation)
        try:
            current = _snapshot(session, project_id, run_id, analysis_id)
            _match_snapshot(invocation, current)
            if cancel is not None and cancel.is_set():
                result = replace(
                    result, status="fallback", proposal=None, reason="cancelled"
                )
        except (ProviderBoundaryError, ProviderScopeError) as exc:
            result = ProviderResult(
                "fallback",
                category,
                reason=str(exc)
                if isinstance(exc, ProviderBoundaryError)
                else "scope_changed",
            )
        invocation.status, invocation.reason, invocation.proposal_json = (
            result.status,
            result.reason,
            result.proposal,
        )
        invocation.completed_at, invocation.owner_token = m.utcnow(), None
        session.flush()
        return _project_invocation(session, invocation)
