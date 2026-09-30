"""Fenced optional-provider application queue. Ordinary workers never claim it.

Lock order is project -> service admission. HTTP always happens after commit.
A reservation can consume spend: recovery after one never resends or refunds it.
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from . import models as m
from .auth import record_audit_event, require_project_role
from .config import get_settings
from .provider_service import (
    ProviderIdempotencyConflict,
    ProviderScopeError,
    _analysis,
    _aware,
    _digest,
    _DurableAttemptBudget,
    _lease_duration,
    _lock_scope,
    _match_snapshot,
    _owned,
    _project_invocation,
    _provider_digest,
    _snapshot,
)
from .providers import (
    PROMPT_VERSION,
    HTTPModelProvider,
    ProviderBoundaryError,
    ProviderResult,
    prepare_request,
)
from .telemetry import SpanKind, stage, trace_context

PROVIDER_JOB_KIND = "model_provider_proposal_v1"
NOTICE = (
    "Explicit submission sends only the selected approved evidence to the operator-configured "
    "provider. Hypotheses remain unverified and do not change deterministic analysis or reviews. "
    "Reservations are conservative token estimates, not a currency spending cap. "
    "Cancellation cannot undo a transmitted request; unreported usage and charges remain unknown."
)
logger = logging.getLogger(__name__)


def database_now(session):
    if session.get_bind().dialect.name == "postgresql":
        return _aware(session.scalar(select(func.clock_timestamp())))
    value = session.scalar(select(func.strftime("%Y-%m-%d %H:%M:%f", "now")))
    return _aware(datetime.fromisoformat(value))


def _identity(settings):
    return _digest(settings.provider_id)


def _application_gate(settings):
    if settings.demo_mode:
        return "demo_mode_enabled"
    if not settings.session_cookie_secure:
        return "insecure_authentication"
    return None


def require_provider_admin(session, principal, project_id):
    require_project_role(session, principal, project_id, m.ProjectRole.administrator)
    if principal.kind != "user" or not principal.user_id or not principal.session_id:
        raise HTTPException(403, "authenticated project administrator required")
    _active_requester(session, principal.user_id, principal.session_id, project_id)


def _active_requester(session, user_id, session_id, project_id):
    user = session.get(m.User, user_id) if user_id else None
    auth = session.get(m.AuthSession, session_id) if session_id else None
    if (
        user is None
        or not user.is_active
        or auth is None
        or auth.user_id != user.id
        or auth.revoked_at is not None
        or _aware(auth.expires_at) <= database_now(session)
    ):
        raise ProviderBoundaryError("requester_authorization_revoked")
    member = session.scalar(
        select(m.ProjectMembership).where(
            m.ProjectMembership.project_id == project_id,
            m.ProjectMembership.user_id == user.id,
        )
    )
    if not user.is_system_admin and (
        member is None or member.role != m.ProjectRole.administrator
    ):
        raise ProviderBoundaryError("requester_authorization_revoked")


def _current_config(session, settings, invocation, *, credential=True):
    gate = _application_gate(settings)
    if gate:
        raise ProviderBoundaryError(gate)
    config, state = settings.provider_configuration(require_credential=credential)
    if config is None:
        raise ProviderBoundaryError(state)
    if invocation.project_id not in settings.provider_project_ids():
        raise ProviderBoundaryError("project_not_allowed")
    if (
        _provider_digest(config) != invocation.provider_digest
        or _identity(settings) != invocation.provider_identity_digest
    ):
        raise ProviderBoundaryError("provider_configuration_changed")
    _active_requester(
        session,
        invocation.requester_user_id,
        invocation.requester_session_id,
        invocation.project_id,
    )
    return config


def _lock_admission(session, identity, now):
    # Upsert then row lock: works for independent projects/processes, including
    # first use. Never delete/reset this row on token/configuration rotation.
    insert = (
        pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    )
    session.execute(
        insert(m.ModelProviderAdmission)
        .values(
            id=identity,
            active_permits=0,
            failures=0,
            next_allowed_at=now,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    return session.scalar(
        select(m.ModelProviderAdmission)
        .where(m.ModelProviderAdmission.id == identity)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def heartbeat_provider_worker(factory, settings):
    if _application_gate(settings):
        return False
    config, _ = settings.provider_configuration()
    if config is None:
        return False
    with factory.begin() as session:
        now = database_now(session)
        admission = _lock_admission(session, _identity(settings), now)
        admission.worker_seen_at = database_now(session)
        admission.worker_configuration_digest = _provider_digest(config)
    return True


def _admission_status(session, settings, config):
    now = database_now(session)
    row = session.get(m.ModelProviderAdmission, _identity(settings))
    available = bool(
        row
        and row.worker_seen_at
        and _aware(row.worker_seen_at) > now - timedelta(seconds=90)
        and row.worker_configuration_digest == _provider_digest(config)
    )
    recovery = bool(
        session.scalar(
            select(m.ModelAttempt.id)
            .join(m.ModelInvocation)
            .where(
                m.ModelAttempt.admission_id == _identity(settings),
                m.ModelAttempt.transport_terminated_at.is_(None),
                or_(
                    m.ModelAttempt.status == "uncertain",
                    m.ModelInvocation.status != "running",
                    m.ModelInvocation.lease_expires_at <= now,
                ),
            )
            .limit(1)
        )
    )
    projection = {
        "active_permits": row.active_permits if row else 0,
        "concurrency": config.concurrency,
        "next_allowed_at": _aware(row.next_allowed_at) if row else None,
        "circuit_open_until": _aware(row.open_until)
        if row and row.open_until
        else None,
        "recovery_required": recovery,
        "worker_available": available,
    }
    if recovery:
        return "recovery_required", projection
    if not available:
        return "worker_unavailable", projection
    if row.open_until and _aware(row.open_until) > now:
        return "circuit_open", projection
    if row.active_permits >= config.concurrency:
        return "concurrency_limited", projection
    if _aware(row.next_allowed_at) > now:
        return "rate_limited", projection
    return "ready", projection


def provider_status(session, settings, principal, project_id):
    require_project_role(session, principal, project_id)
    config, state = settings.provider_configuration(require_credential=False)
    admin = False
    if principal.kind == "user":
        try:
            require_provider_admin(session, principal, project_id)
            admin = True
        except (HTTPException, ProviderBoundaryError):
            pass
    result = {
        "schema_version": "1.0",
        "project_id": project_id,
        "availability": state,
        "reason": None if state == "ready" else state,
        "can_submit": False,
        "configuration_digest": None,
        "destination": None,
        "limits": None,
        "pricing": None,
        "cost_status": "unknown",
        "notice": NOTICE,
        "admission": None,
    }
    gate = _application_gate(settings)
    if gate:
        return result | {"availability": "disabled", "reason": gate}
    if config is None:
        return result
    if project_id not in settings.provider_project_ids():
        return result | {
            "availability": "project_not_allowed",
            "reason": "project_not_allowed",
        }
    origin = urlsplit(config.endpoint)
    state, admission = _admission_status(session, settings, config)
    return result | {
        "availability": state,
        "reason": None if state == "ready" else state,
        "can_submit": admin and state == "ready",
        "configuration_digest": _provider_digest(config),
        "destination": {
            "provider_identity": settings.provider_id,
            "endpoint": f"{origin.scheme}://{origin.netloc}",
            "model": config.model,
        },
        "limits": {
            key: getattr(config, key)
            for key in (
                "max_attempts",
                "max_output_tokens",
                "max_context_bytes",
                "max_response_bytes",
                "max_run_requests",
                "max_run_reserved_tokens",
                "concurrency",
                "min_interval_seconds",
                "timeout_seconds",
            )
        },
        "pricing": {
            "input_price_per_million": config.input_price_per_million,
            "output_price_per_million": config.output_price_per_million,
            "source": config.pricing_source,
            "date": config.pricing_date,
            "currency": config.currency,
        },
        "cost_status": "estimate_available"
        if config.input_price_per_million is not None
        else "unknown",
        "admission": admission,
    }


def provider_preview(session, settings, principal, project_id, run_id, analysis_id):
    analysis = _analysis(session, project_id, run_id, analysis_id)
    status = provider_status(session, settings, principal, project_id)
    result = status | {
        "project_id": project_id,
        "run_id": run_id,
        "analysis_id": analysis_id,
        "analysis_revision": analysis.revision,
        "analysis_digest": None,
        "evidence_digest": None,
        "preview_digest": None,
        "prompt_version": PROMPT_VERSION,
        "evidence": [],
        "reserved_tokens_per_attempt": None,
        "budget": None,
    }
    config, _ = settings.provider_configuration(require_credential=False)
    if (
        config is None
        or project_id not in settings.provider_project_ids()
        or _application_gate(settings)
    ):
        return result
    try:
        snapshot = _snapshot(session, project_id, run_id, analysis_id)
        prepared = prepare_request(config, snapshot.category, snapshot.evidence)
        if isinstance(prepared, ProviderResult):
            raise ProviderBoundaryError(prepared.reason or "evidence_unavailable")
    except ProviderBoundaryError as exc:
        return result | {
            "availability": "evidence_unavailable",
            "reason": str(exc),
            "can_submit": False,
        }
    preview_digest = _digest(
        {
            "project_id": project_id,
            "run_id": run_id,
            "analysis_id": analysis_id,
            "analysis_digest": snapshot.analysis_digest,
            "evidence_digest": snapshot.evidence_digest,
            "configuration_digest": _provider_digest(config),
            "provider_identity": _identity(settings),
            "request_digest": _digest(prepared.payload),
            "prompt_version": PROMPT_VERSION,
        }
    )
    budget = session.get(m.ModelRunBudget, run_id)
    budget_projection = {
        "requests": budget.requests if budget else 0,
        "reserved_tokens": budget.reserved_tokens if budget else 0,
        "max_requests": min(budget.max_requests, config.max_run_requests)
        if budget
        else config.max_run_requests,
        "max_reserved_tokens": min(
            budget.max_reserved_tokens, config.max_run_reserved_tokens
        )
        if budget
        else config.max_run_reserved_tokens,
    }
    result["budget"] = budget_projection
    result["limits"] = result["limits"] | {
        "max_run_requests": budget_projection["max_requests"],
        "max_run_reserved_tokens": budget_projection["max_reserved_tokens"],
    }
    if (
        budget_projection["requests"] >= budget_projection["max_requests"]
        or budget_projection["reserved_tokens"] + prepared.reserved_tokens
        > budget_projection["max_reserved_tokens"]
    ):
        result.update(
            availability="run_budget_exhausted",
            reason="run_budget_exhausted",
            can_submit=False,
        )
    return result | {
        "analysis_digest": snapshot.analysis_digest,
        "evidence_digest": snapshot.evidence_digest,
        "preview_digest": preview_digest,
        # Show the exact approved/redacted content the adapter prepared. The
        # entire serialized context is already bounded by max_context_bytes.
        "evidence": json.loads(prepared.payload["messages"][1]["content"])["evidence"],
        "reserved_tokens_per_attempt": prepared.reserved_tokens,
    }


def project_invocation(session, settings, invocation):
    result = _project_invocation(session, invocation)
    try:
        _current_config(session, settings, invocation, credential=False)
    except ProviderBoundaryError as exc:
        result.update(status="fallback", proposal=None, reason=str(exc))
    attempts = list(
        session.scalars(
            select(m.ModelAttempt).where(m.ModelAttempt.invocation_id == invocation.id)
        )
    )
    open_permit = any(
        a.admission_id and a.transport_terminated_at is None for a in attempts
    )
    costs = [a.estimated_cost for a in attempts if a.estimated_cost is not None]
    currencies = {a.currency for a in attempts if a.estimated_cost is not None}
    return result | {
        "schema_version": "1.0",
        "project_id": invocation.project_id,
        "run_id": invocation.run_id,
        "analysis_id": invocation.analysis_id,
        "job_id": invocation.job_id,
        "analysis_revision": invocation.analysis_revision,
        "analysis_digest": invocation.analysis_digest,
        "evidence_digest": invocation.evidence_digest,
        "configuration_digest": invocation.provider_digest,
        "preview_digest": invocation.preview_digest,
        "created_at": _aware(invocation.created_at),
        "completed_at": _aware(invocation.completed_at)
        if invocation.completed_at
        else None,
        "cancel_requested_at": _aware(invocation.cancel_requested_at)
        if invocation.cancel_requested_at
        else None,
        "recovery_required": bool(
            open_permit
            and (
                any(a.status == "uncertain" for a in attempts)
                or invocation.status != "running"
                or _aware(invocation.lease_expires_at) <= database_now(session)
            )
        ),
        "known_estimated_cost": sum(costs) if costs and len(currencies) == 1 else None,
        "cost_complete": result["cost_status"] == "estimated",
    }


def scoped_invocation(session, project_id, run_id, analysis_id, invocation_id):
    _analysis(session, project_id, run_id, analysis_id)
    invocation = session.scalar(
        select(m.ModelInvocation).where(
            m.ModelInvocation.id == invocation_id,
            m.ModelInvocation.project_id == project_id,
            m.ModelInvocation.run_id == run_id,
            m.ModelInvocation.analysis_id == analysis_id,
            m.ModelInvocation.job_id.is_not(None),
        )
    )
    if invocation is None:
        raise ProviderScopeError("requested provider scope not found")
    return invocation


def submit_model_invocation(
    session, settings, principal, project_id, run_id, analysis_id, request
):
    _lock_scope(session, project_id, run_id)
    require_provider_admin(session, principal, project_id)
    _analysis(session, project_id, run_id, analysis_id)
    existing = session.scalar(
        select(m.ModelInvocation).where(
            m.ModelInvocation.project_id == project_id,
            m.ModelInvocation.idempotency_digest == _digest(request.idempotency_key),
        )
    )
    if existing:
        if (
            existing.run_id != run_id
            or existing.analysis_id != analysis_id
            or existing.analysis_revision != request.analysis_revision
            or existing.preview_digest != request.preview_digest
            or existing.provider_digest != request.configuration_digest
            or existing.job_id is None
        ):
            raise ProviderIdempotencyConflict(
                "idempotency key conflicts with an existing request"
            )
        return existing
    preview = provider_preview(
        session, settings, principal, project_id, run_id, analysis_id
    )
    if not preview["can_submit"]:
        raise ProviderBoundaryError(preview["reason"] or "provider_unavailable")
    if (
        request.analysis_revision != preview["analysis_revision"]
        or request.preview_digest != preview["preview_digest"]
        or request.configuration_digest != preview["configuration_digest"]
    ):
        raise ProviderBoundaryError("preview_changed")
    config, _ = settings.provider_configuration(require_credential=False)
    snapshot = _snapshot(session, project_id, run_id, analysis_id)
    prepared = prepare_request(config, snapshot.category, snapshot.evidence)
    if isinstance(prepared, ProviderResult):
        raise ProviderBoundaryError(prepared.reason or "evidence_unavailable")
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
    now = database_now(session)
    job = m.Job(
        project_id=project_id,
        kind=PROVIDER_JOB_KIND,
        payload={"schema_version": "1.0"},
        max_attempts=1,
        available_at=now,
    )
    session.add(job)
    session.flush()
    invocation = m.ModelInvocation(
        project_id=project_id,
        run_id=run_id,
        analysis_id=analysis_id,
        analysis_revision=snapshot.revision,
        analysis_digest=snapshot.analysis_digest,
        evidence_digest=snapshot.evidence_digest,
        request_digest=_digest(prepared.payload),
        provider_digest=_provider_digest(config),
        provider_identity_digest=_identity(settings),
        preview_digest=preview["preview_digest"],
        idempotency_digest=_digest(request.idempotency_key),
        deterministic_category=snapshot.category,
        prompt_version=PROMPT_VERSION,
        status="queued",
        lease_expires_at=now,
        job_id=job.id,
        requester_user_id=principal.user_id,
        requester_session_id=principal.session_id,
    )
    session.add(invocation)
    session.flush()
    job.payload = {
        "schema_version": "1.0",
        "invocation_id": invocation.id,
        **trace_context(),
    }
    record_audit_event(
        session,
        principal,
        action="provider.submitted",
        resource_type="model_invocation",
        resource_id=invocation.id,
        project_id=project_id,
        details={
            "analysis_id": analysis_id,
            "analysis_revision": snapshot.revision,
            "preview_digest": preview["preview_digest"],
            "job_id": job.id,
        },
    )
    return invocation


def cancel_model_invocation(
    session, settings, principal, project_id, run_id, analysis_id, invocation_id
):
    _lock_scope(session, project_id, run_id)
    require_provider_admin(session, principal, project_id)
    invocation = scoped_invocation(
        session, project_id, run_id, analysis_id, invocation_id
    )
    if invocation.cancel_requested_at is None and invocation.status in {
        "queued",
        "running",
    }:
        now = database_now(session)
        invocation.cancel_requested_at = now
        invocation.status, invocation.reason, invocation.proposal_json = (
            "cancelled",
            "cancelled",
            None,
        )
        invocation.owner_token, invocation.completed_at = None, now
        job = session.get(m.Job, invocation.job_id)
        if job:
            job.state, job.lease_owner, job.lease_expires_at = (
                m.JobState.cancelled,
                None,
                None,
            )
        record_audit_event(
            session,
            principal,
            action="provider.cancelled",
            resource_type="model_invocation",
            resource_id=invocation.id,
            project_id=project_id,
        )
    return invocation


class ApplicationAttemptBudget(_DurableAttemptBudget):
    def __init__(self, *args, settings):
        super().__init__(*args)
        self.settings = settings

    def _now(self, session):
        return database_now(session)

    def _admit(self, session, invocation, config):
        _current_config(session, self.settings, invocation)
        now = database_now(session)
        _owned(invocation, self.owner, now)
        row = _lock_admission(session, invocation.provider_identity_digest, now)
        now = database_now(session)
        _owned(invocation, self.owner, now)
        # Any stranded permit blocks the whole stable provider identity. A new
        # adapter, job owner, token or configuration cannot reset uncertainty.
        recovery = session.scalar(
            select(m.ModelAttempt.id)
            .join(m.ModelInvocation)
            .where(
                m.ModelAttempt.admission_id == row.id,
                m.ModelAttempt.transport_terminated_at.is_(None),
                or_(
                    m.ModelAttempt.status == "uncertain",
                    m.ModelInvocation.status != "running",
                    m.ModelInvocation.lease_expires_at <= now,
                ),
            )
            .limit(1)
        )
        if recovery:
            raise ProviderBoundaryError("recovery_required")
        if row.open_until and _aware(row.open_until) > now:
            raise ProviderBoundaryError("circuit_open")
        if row.active_permits >= config.concurrency:
            raise ProviderBoundaryError("concurrency_limited")
        if _aware(row.next_allowed_at) > now:
            raise ProviderBoundaryError("rate_limited")
        row.active_permits += 1
        row.next_allowed_at = now + timedelta(seconds=config.min_interval_seconds)
        invocation.lease_expires_at = now + _lease_duration(config)
        job = session.get(m.Job, invocation.job_id)
        if (
            job is None
            or job.kind != PROVIDER_JOB_KIND
            or job.state != m.JobState.running
            or job.lease_owner != self.owner
        ):
            raise ProviderBoundaryError("invocation_interrupted")
        job.lease_expires_at = invocation.lease_expires_at
        return row.id

    def _settle(self, session, attempt, result, *, terminated, late, sent):
        if not attempt.admission_id:
            return
        now = database_now(session)
        row = _lock_admission(session, attempt.admission_id, now)
        if terminated and attempt.transport_terminated_at is None:
            attempt.transport_terminated_at = now
            row.active_permits -= 1
        if attempt.circuit_accounted:
            return
        attempt.circuit_accounted = True
        # Circuit state describes one live provider attempt. Late cleanup can
        # reconcile numbers/permits only; user cancellation and local observer
        # failures are not evidence of a provider outage.
        if (
            late
            or not sent
            or result.reason in {"cancelled", "cancellation_observer_error"}
        ):
            return
        if result.status == "proposed" and terminated:
            row.failures = 0
        else:
            row.failures += 1
            if row.failures >= self.config.failure_threshold:
                row.open_until = now + timedelta(seconds=self.config.cooldown_seconds)


class _PersistedCancellation:
    def __init__(self, factory, invocation_id, owner):
        self.factory, self.invocation_id, self.owner = factory, invocation_id, owner

    def is_set(self):
        with self.factory() as session:
            row = session.get(m.ModelInvocation, self.invocation_id)
            return (
                row is None
                or row.cancel_requested_at is not None
                or row.status != "running"
                or row.owner_token != self.owner
            )

    def wait(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            if self.is_set():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            threading.Event().wait(min(0.05, remaining))


def _finish_job(session, invocation, result):
    now = database_now(session)
    open_permit = session.scalar(
        select(m.ModelAttempt.id)
        .where(
            m.ModelAttempt.invocation_id == invocation.id,
            m.ModelAttempt.admission_id.is_not(None),
            m.ModelAttempt.transport_terminated_at.is_(None),
        )
        .limit(1)
    )
    invocation.status = "uncertain" if open_permit else result.status
    invocation.reason, invocation.proposal_json = (
        result.reason,
        result.proposal if not open_permit else None,
    )
    invocation.owner_token, invocation.completed_at = None, now
    job = session.get(m.Job, invocation.job_id)
    if job:
        job.state = (
            m.JobState.succeeded
            if invocation.status == "proposed"
            else m.JobState.failed
        )
        job.lease_owner, job.lease_expires_at, job.last_error = (
            None,
            None,
            invocation.reason,
        )


def recover_provider_jobs(factory):
    with factory() as session:
        now = database_now(session)
        candidates = list(
            session.execute(
                select(
                    m.ModelInvocation.id,
                    m.ModelInvocation.project_id,
                    m.ModelInvocation.run_id,
                )
                .where(
                    m.ModelInvocation.job_id.is_not(None),
                    m.ModelInvocation.status == "running",
                    m.ModelInvocation.lease_expires_at <= now,
                )
                .limit(100)
            )
        )
    recovered = 0
    for invocation_id, project_id, run_id in candidates:
        with factory.begin() as session:
            _lock_scope(session, project_id, run_id)
            invocation = session.get(m.ModelInvocation, invocation_id)
            now = database_now(session)
            if (
                invocation is None
                or invocation.status != "running"
                or _aware(invocation.lease_expires_at) > now
            ):
                continue
            reserved = session.scalar(
                select(m.ModelAttempt.id)
                .where(m.ModelAttempt.invocation_id == invocation.id)
                .limit(1)
            )
            job = session.get(m.Job, invocation.job_id)
            invocation.owner_token = None
            if reserved:
                _finish_job(
                    session,
                    invocation,
                    ProviderResult(
                        "uncertain",
                        invocation.deterministic_category,
                        reason="invocation_interrupted",
                    ),
                )
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
            elif job:
                invocation.status, invocation.reason = (
                    "queued",
                    "recovered_before_reservation",
                )
                job.state, job.lease_owner, job.lease_expires_at = (
                    m.JobState.queued,
                    None,
                    None,
                )
                job.available_at = now
            recovered += 1
    return recovered


def claim_provider_job(factory, settings):
    with factory() as session:
        now = database_now(session)
        candidates = list(
            session.execute(
                select(
                    m.ModelInvocation.id,
                    m.ModelInvocation.project_id,
                    m.ModelInvocation.run_id,
                )
                .join(m.Job, m.ModelInvocation.job_id == m.Job.id)
                .where(
                    m.ModelInvocation.status == "queued",
                    m.Job.kind == PROVIDER_JOB_KIND,
                    m.Job.state == m.JobState.queued,
                    m.Job.available_at <= now,
                )
                .order_by(m.Job.available_at, m.Job.created_at)
                .limit(50)
            )
        )
    for invocation_id, project_id, run_id in candidates:
        with factory.begin() as session:
            _lock_scope(session, project_id, run_id)
            invocation = session.get(m.ModelInvocation, invocation_id)
            job = session.get(m.Job, invocation.job_id) if invocation else None
            if (
                invocation is None
                or invocation.status != "queued"
                or job is None
                or job.state != m.JobState.queued
            ):
                continue
            try:
                config = _current_config(session, settings, invocation)
                snapshot = _snapshot(
                    session, project_id, run_id, invocation.analysis_id
                )
                _match_snapshot(invocation, snapshot)
            except (ProviderBoundaryError, ProviderScopeError) as exc:
                _finish_job(
                    session,
                    invocation,
                    ProviderResult(
                        "fallback",
                        invocation.deterministic_category,
                        reason=str(exc)
                        if isinstance(exc, ProviderBoundaryError)
                        else "scope_changed",
                    ),
                )
                continue
            now, owner = database_now(session), m.new_id()
            invocation.status, invocation.reason, invocation.owner_token = (
                "running",
                None,
                owner,
            )
            invocation.lease_expires_at = now + _lease_duration(config)
            job.state, job.lease_owner, job.lease_expires_at = (
                m.JobState.running,
                owner,
                invocation.lease_expires_at,
            )
            job.attempts += 1
            return (
                invocation.id,
                invocation.project_id,
                invocation.run_id,
                owner,
                config,
                snapshot,
            )
    return None


def run_provider_once(factory, settings=None, *, provider_factory=HTTPModelProvider):
    settings = settings or get_settings()
    heartbeat_provider_worker(factory, settings)
    recover_provider_jobs(factory)
    claimed = claim_provider_job(factory, settings)
    if claimed is None:
        return False
    invocation_id, project_id, run_id, owner, config, snapshot = claimed
    budget = ApplicationAttemptBudget(
        factory, invocation_id, project_id, run_id, owner, config, settings=settings
    )
    provider = provider_factory(config)
    with factory() as session:
        job = session.scalar(
            select(m.Job)
            .join(m.ModelInvocation, m.ModelInvocation.job_id == m.Job.id)
            .where(m.ModelInvocation.id == invocation_id)
        )
        parent = job.payload.get("traceparent") if job else None
    try:
        with stage("job", parent=parent, kind=SpanKind.CONSUMER) as span:
            span.set_attribute("job.kind", PROVIDER_JOB_KIND)
            result = provider.propose(
                deterministic_category=snapshot.category,
                evidence=snapshot.evidence,
                budget=budget,
                cancel=_PersistedCancellation(factory, invocation_id, owner),
            )
    finally:
        provider.close()
    with factory.begin() as session:
        _lock_scope(session, project_id, run_id)
        invocation = session.get(m.ModelInvocation, invocation_id)
        try:
            _owned(invocation, owner, database_now(session))
        except ProviderBoundaryError:
            return True
        try:
            _current_config(session, settings, invocation)
            current = _snapshot(session, project_id, run_id, invocation.analysis_id)
            _match_snapshot(invocation, current)
        except (ProviderBoundaryError, ProviderScopeError) as exc:
            result = replace(
                result,
                status="fallback",
                proposal=None,
                reason=str(exc)
                if isinstance(exc, ProviderBoundaryError)
                else "scope_changed",
            )
        attempts = session.scalar(
            select(func.count())
            .select_from(m.ModelAttempt)
            .where(m.ModelAttempt.invocation_id == invocation.id)
        )
        if attempts == 0 and result.reason in {
            "rate_limited",
            "concurrency_limited",
            "circuit_open",
            "recovery_required",
        }:
            invocation.status, invocation.reason, invocation.owner_token = (
                "queued",
                result.reason,
                None,
            )
            job = session.get(m.Job, invocation.job_id)
            job.state, job.lease_owner, job.lease_expires_at = (
                m.JobState.queued,
                None,
                None,
            )
            job.available_at = database_now(session) + timedelta(seconds=1)
        else:
            _finish_job(session, invocation, result)
    return True


def main():
    from .db import SessionLocal, initialize_database
    from .telemetry import configure_telemetry, shutdown_telemetry

    parser = argparse.ArgumentParser(description="Dedicated opt-in provider worker")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    initialize_database()
    configure_telemetry()
    try:
        while True:
            try:
                worked = run_provider_once(SessionLocal)
            except Exception:
                # Never interpolate exceptions: transport/config/DB text is private.
                logger.exception("provider_worker_failed", exc_info=False)
                worked = False
            if args.once:
                return
            if not worked:
                time.sleep(1)
    finally:
        shutdown_telemetry()


if __name__ == "__main__":
    main()
