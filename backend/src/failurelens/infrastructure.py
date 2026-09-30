from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .history import build_test_history
from .models import (
    Evidence,
    InfrastructureCorrelationMember,
    InfrastructureCorrelationSnapshot,
    InfrastructureEvent,
    Outcome,
    Project,
    Run,
    TestExecution,
)
from .schemas import InfrastructureEventCreate

INFRASTRUCTURE_POLICY_VERSION = "infrastructure-correlation-policy-v1"
INFRASTRUCTURE_ENGINE_VERSION = "infrastructure-correlation-v1"
DEFAULT_WINDOW_SECONDS = 900
DEFAULT_MINIMUM_SUPPORT = 3
MAX_CORRELATION_EVENTS = 10_000
MAX_CORRELATION_RUNS = 20_000

TRUSTED_SOURCE_TRUST = {
    "authenticated_lookup",
    "trusted_workflow",
    "verified_monitor",
}
SUPPORTED_EVENT_KINDS = {
    "runner_terminated",
    "runner_unavailable",
    "service_outage",
    "database_connection_exhaustion",
    "dns_failure",
    "tls_failure",
    "network_degradation",
    "storage_exhaustion",
    "resource_contention",
    "deployment_event",
    "dependency_outage",
    "rate_limit_event",
    "unknown_infrastructure_event",
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _outcome_counts(values: list[str]) -> dict[str, int]:
    counter = Counter(values)
    return {outcome.value: counter.get(outcome.value, 0) for outcome in Outcome}


def _aggregate_outcome(values: list[str]) -> str:
    observed = set(values)
    for outcome in (
        Outcome.failed,
        Outcome.cancelled,
        Outcome.unknown,
        Outcome.passed,
        Outcome.skipped,
    ):
        if outcome.value in observed:
            return outcome.value
    return Outcome.unknown.value


def _wilson_interval(numerator: int, denominator: int) -> list[float] | None:
    if denominator <= 0:
        return None
    z = 1.959963984540054
    proportion = numerator / denominator
    z2 = z * z
    adjusted = 1 + z2 / denominator
    centre = proportion + z2 / (2 * denominator)
    margin = z * math.sqrt(
        (proportion * (1 - proportion) + z2 / (4 * denominator)) / denominator
    )
    return [
        round(max(0.0, (centre - margin) / adjusted), 6),
        round(min(1.0, (centre + margin) / adjusted), 6),
    ]


def _rate(numerator: int, denominator: int, *, minimum_support: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 6) if denominator else None,
        "interval_95": _wilson_interval(numerator, denominator),
        "status": (
            "available"
            if denominator >= minimum_support
            else "insufficient_data"
            if denominator
            else "unavailable"
        ),
        "minimum_support": minimum_support,
        "definition": (
            "Final failed outcomes divided by final pass/fail outcomes in the cohort. "
            "Retries and browsers are collapsed to one conservative result per independent run; "
            "skipped, cancelled and unknown outcomes remain visible outside the denominator."
        ),
    }


def _event_payload(project_id: str, request: InfrastructureEventCreate) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "repository": request.repository,
        "environment": request.environment,
        "producer": request.producer,
        "producer_event_id": request.producer_event_id,
        "event_kind": request.event_kind,
        "severity": request.severity,
        "status": request.status,
        "started_at": _as_utc(request.started_at).isoformat(),
        "ended_at": _as_utc(request.ended_at).isoformat() if request.ended_at else None,
        "recorded_at": _as_utc(request.recorded_at).isoformat(),
        "workflow_name": request.workflow_name,
        "workflow_run_id": request.workflow_run_id,
        "workflow_attempt": request.workflow_attempt,
        "runner_identity": request.runner_identity,
        "runner_group": request.runner_group,
        "region": request.region,
        "worker_count": request.worker_count,
        "shard_identity": request.shard_identity,
        "source_trust": request.source_trust,
        "evidence_id": request.evidence_id,
        "metadata": request.metadata,
    }


def create_infrastructure_event(
    session: Session,
    project: Project,
    request: InfrastructureEventCreate,
) -> InfrastructureEvent:
    if request.event_kind not in SUPPORTED_EVENT_KINDS:
        raise ValueError(f"unsupported infrastructure event kind: {request.event_kind}")
    started_at = _as_utc(request.started_at)
    ended_at = _as_utc(request.ended_at) if request.ended_at else None
    recorded_at = _as_utc(request.recorded_at)
    if ended_at is not None and ended_at < started_at:
        raise ValueError("ended_at must not be earlier than started_at")
    if recorded_at < started_at:
        raise ValueError("recorded_at must not be earlier than started_at")
    if ended_at is not None and recorded_at < ended_at:
        raise ValueError("recorded_at must not be earlier than ended_at for a resolved event")
    if request.evidence_id:
        evidence = session.get(Evidence, request.evidence_id)
        if evidence is None or evidence.project_id != project.id:
            raise ValueError("infrastructure event evidence not found in project")

    digest = _canonical_digest(_event_payload(project.id, request))
    existing = session.scalar(
        select(InfrastructureEvent).where(
            InfrastructureEvent.project_id == project.id,
            InfrastructureEvent.producer == request.producer,
            InfrastructureEvent.producer_event_id == request.producer_event_id,
        )
    )
    if existing is not None:
        if existing.source_digest != digest:
            raise ValueError(
                "infrastructure event identity already exists with different content"
            )
        return existing

    event = InfrastructureEvent(
        project_id=project.id,
        repository=request.repository,
        environment=request.environment,
        producer=request.producer,
        producer_event_id=request.producer_event_id,
        event_kind=request.event_kind,
        severity=request.severity,
        status=request.status,
        started_at=started_at,
        ended_at=ended_at,
        recorded_at=recorded_at,
        workflow_name=request.workflow_name,
        workflow_run_id=request.workflow_run_id,
        workflow_attempt=request.workflow_attempt,
        runner_identity=request.runner_identity,
        runner_group=request.runner_group,
        region=request.region,
        worker_count=request.worker_count,
        shard_identity=request.shard_identity,
        source_trust=request.source_trust,
        source_digest=digest,
        evidence_id=request.evidence_id,
        metadata_json=request.metadata,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def infrastructure_event_to_schema(event: InfrastructureEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "project_id": event.project_id,
        "repository": event.repository,
        "environment": event.environment,
        "producer": event.producer,
        "producer_event_id": event.producer_event_id,
        "event_kind": event.event_kind,
        "severity": event.severity,
        "status": event.status,
        "started_at": event.started_at,
        "ended_at": event.ended_at,
        "recorded_at": event.recorded_at,
        "workflow_name": event.workflow_name,
        "workflow_run_id": event.workflow_run_id,
        "workflow_attempt": event.workflow_attempt,
        "runner_identity": event.runner_identity,
        "runner_group": event.runner_group,
        "region": event.region,
        "worker_count": event.worker_count,
        "shard_identity": event.shard_identity,
        "source_trust": event.source_trust,
        "trusted_for_correlation": event.source_trust in TRUSTED_SOURCE_TRUST,
        "source_digest": event.source_digest,
        "evidence_id": event.evidence_id,
        "metadata": event.metadata_json,
        "created_at": event.created_at,
    }


def list_infrastructure_events(
    session: Session,
    project_id: str,
    *,
    event_kind: str | None = None,
    before: datetime | None = None,
    after: datetime | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[InfrastructureEvent]:
    query = select(InfrastructureEvent).where(
        InfrastructureEvent.project_id == project_id
    )
    if event_kind:
        query = query.where(InfrastructureEvent.event_kind == event_kind)
    if before:
        query = query.where(InfrastructureEvent.started_at < _as_utc(before))
    if after:
        query = query.where(
            InfrastructureEvent.started_at >= _as_utc(after)
            - timedelta(seconds=DEFAULT_WINDOW_SECONDS)
        )
    return list(
        session.scalars(
            query.order_by(
                InfrastructureEvent.started_at.desc(), InfrastructureEvent.id
            )
            .offset(offset)
            .limit(limit)
        ).all()
    )


def _collapse_history_observations(
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        grouped[str(observation["run_id"])].append(observation)

    collapsed: list[dict[str, Any]] = []
    for run_id, rows in grouped.items():
        ordered = sorted(rows, key=lambda item: (item.get("browser") or ""))
        representative = ordered[0]
        collapsed.append(
            {
                "run_id": run_id,
                "observed_at": representative["observed_at"],
                "outcome": _aggregate_outcome(
                    [str(item["final_outcome"]) for item in ordered]
                ),
                "execution_ids": [
                    execution_id
                    for item in ordered
                    for execution_id in item["execution_ids"]
                ],
            }
        )
    collapsed.sort(key=lambda item: (str(item["observed_at"]), item["run_id"]))
    return collapsed


def _run_context_rejection(event: InfrastructureEvent, run: Run) -> str | None:
    if event.repository != run.repository:
        return "repository_mismatch"
    if event.environment != run.environment:
        return "environment_mismatch"
    if event.worker_count is not None and event.worker_count != run.worker_count:
        return "worker_count_mismatch"

    source = run.source_metadata or {}
    if event.region is not None and source.get("region") != event.region:
        return "region_mismatch"
    if event.workflow_name is not None and source.get("workflow_name") not in {
        None,
        event.workflow_name,
    }:
        return "workflow_mismatch"
    if event.runner_identity is not None and source.get("runner_identity") not in {
        None,
        event.runner_identity,
    }:
        return "runner_mismatch"
    if event.runner_group is not None and source.get("runner_group") not in {
        None,
        event.runner_group,
    }:
        return "runner_group_mismatch"
    return None


def _temporally_overlaps(
    event: InfrastructureEvent,
    run: Run,
    *,
    window_seconds: int,
) -> bool:
    run_start = _as_utc(run.started_at or run.created_at)
    run_end = _as_utc(run.ended_at or run_start)
    event_start = _as_utc(event.started_at)
    event_end = _as_utc(event.ended_at or event.started_at)
    window = timedelta(seconds=window_seconds)
    return event_start <= run_end + window and event_end >= run_start - window


def _association_row(
    *,
    event_kind: str,
    members: list[dict[str, Any]],
    minimum_support: int,
) -> dict[str, Any]:
    exposed = [item for item in members if event_kind in item["event_kinds"]]
    unexposed = [item for item in members if event_kind not in item["event_kinds"]]
    exposed_counts = _outcome_counts([str(item["outcome"]) for item in exposed])
    unexposed_counts = _outcome_counts([str(item["outcome"]) for item in unexposed])
    exposed_denominator = (
        exposed_counts[Outcome.passed.value] + exposed_counts[Outcome.failed.value]
    )
    unexposed_denominator = (
        unexposed_counts[Outcome.passed.value]
        + unexposed_counts[Outcome.failed.value]
    )
    exposed_rate = _rate(
        exposed_counts[Outcome.failed.value],
        exposed_denominator,
        minimum_support=minimum_support,
    )
    unexposed_rate = _rate(
        unexposed_counts[Outcome.failed.value],
        unexposed_denominator,
        minimum_support=minimum_support,
    )
    absolute_difference = (
        round(float(exposed_rate["value"]) - float(unexposed_rate["value"]), 6)
        if exposed_rate["value"] is not None and unexposed_rate["value"] is not None
        else None
    )
    relative_risk = (
        round(float(exposed_rate["value"]) / float(unexposed_rate["value"]), 6)
        if exposed_rate["value"] is not None
        and unexposed_rate["value"] not in {None, 0}
        else None
    )
    status = (
        "AVAILABLE"
        if exposed_denominator >= minimum_support
        and unexposed_denominator >= minimum_support
        else "INSUFFICIENT_DATA"
    )
    return {
        "event_kind": event_kind,
        "status": status,
        "exposed_run_count": len(exposed),
        "unexposed_run_count": len(unexposed),
        "exposed_outcomes": exposed_counts,
        "unexposed_outcomes": unexposed_counts,
        "exposed_failure_rate": exposed_rate,
        "unexposed_failure_rate": unexposed_rate,
        "absolute_failure_rate_difference": absolute_difference,
        "relative_risk": relative_risk,
        "confounded_run_count": sum(
            len(item["event_kinds"]) > 1 for item in exposed
        ),
        "interpretation": (
            "Exploratory association only. Temporal overlap and rate differences do not "
            "establish that the infrastructure event caused a test outcome."
        ),
    }


def build_infrastructure_correlation(
    session: Session,
    *,
    selected_execution: TestExecution,
    selected_run: Run,
    cutoff: datetime,
    after: datetime | None = None,
    browser: str | None = None,
    match_browser: bool = False,
    branch: str | None = None,
    match_branch: bool = False,
    environment: str | None = None,
    match_environment: bool = False,
    run_scope: str | None = None,
    worker_count: int | None = None,
    match_worker_count: bool = False,
    shard_count: int | None = None,
    match_shard_count: bool = False,
    timezone_name: str = "UTC",
    exclude_run_id: str | None = None,
    strict_fingerprint: str | None = None,
    event_kind: str | None = None,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    minimum_support: int = DEFAULT_MINIMUM_SUPPORT,
    persist: bool = False,
    request_history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if window_seconds < 0 or window_seconds > 86_400:
        raise ValueError("window_seconds must be between 0 and 86400")
    if minimum_support < 1 or minimum_support > 10_000:
        raise ValueError("minimum_support must be between 1 and 10000")
    if event_kind is not None and event_kind not in SUPPORTED_EVENT_KINDS:
        raise ValueError(f"unsupported infrastructure event kind: {event_kind}")

    cutoff_utc = _as_utc(cutoff)
    after_utc = _as_utc(after) if after is not None else None
    # Reuse only a complete, same-scope history calculated inside this request.
    # This is not a cross-request cache and is never accepted from API input.
    if request_history is not None:
        logical = request_history.get("logical_test", {})
        window = request_history.get("window", {})
        filters = request_history.get("filters", {})
        expected_logical = {"project_id": selected_run.project_id,
            "repository": selected_run.repository, "framework": selected_run.framework,
            "test_identity": selected_execution.test_identity, "suite": selected_execution.suite,
            "source_path": selected_execution.source_path, "parameterization": selected_execution.parameterization}
        expected_filters = {"browser": browser if match_browser else None, "browser_match": match_browser,
            "branch": branch if match_branch else None, "branch_match": match_branch,
            "environment": environment if match_environment else None, "environment_match": match_environment,
            "run_scope": run_scope, "worker_count": worker_count if match_worker_count else None,
            "worker_count_match": match_worker_count, "shard_count": shard_count if match_shard_count else None,
            "shard_count_match": match_shard_count}
        pagination = request_history.get("pagination", {})
        observations = request_history.get("observations", [])
        if (any(logical.get(k) != v for k, v in expected_logical.items()) or
                any(filters.get(k) != v for k, v in expected_filters.items()) or
                window.get("before") != cutoff_utc.isoformat() or
                window.get("after") != (after_utc.isoformat() if after_utc else None) or
                window.get("timezone") != timezone_name or window.get("excluded_run_id") != exclude_run_id or
                pagination.get("offset") != 0 or pagination.get("limit", 0) < MAX_CORRELATION_RUNS or
                len(observations) != min(pagination.get("total", -1), MAX_CORRELATION_RUNS)):
            raise ValueError("request history scope or completeness mismatch")
        history = request_history
    else:
        history = build_test_history(
            session,
            selected_execution=selected_execution,
            selected_run=selected_run,
            cutoff=cutoff_utc,
            after=after_utc,
            browser=browser,
            match_browser=match_browser,
            branch=branch,
            match_branch=match_branch,
            environment=environment,
            match_environment=match_environment,
            run_scope=run_scope,
            worker_count=worker_count,
            match_worker_count=match_worker_count,
            shard_count=shard_count,
            match_shard_count=match_shard_count,
            timezone_name=timezone_name,
            exclude_run_id=exclude_run_id,
            strict_fingerprint=strict_fingerprint,
            observation_limit=MAX_CORRELATION_RUNS,
            observation_offset=0,
        )
    history_members = _collapse_history_observations(history["observations"])
    run_ids = [str(item["run_id"]) for item in history_members]
    runs = {
        run.id: run
        for run in session.scalars(select(Run).where(Run.id.in_(run_ids))).all()
    } if run_ids else {}

    events_query = select(InfrastructureEvent).where(
        InfrastructureEvent.project_id == selected_run.project_id,
        InfrastructureEvent.started_at < cutoff_utc,
        InfrastructureEvent.recorded_at < cutoff_utc,
    )
    if after_utc is not None:
        events_query = events_query.where(
            InfrastructureEvent.started_at
            >= after_utc - timedelta(seconds=window_seconds)
        )
    if event_kind is not None:
        events_query = events_query.where(InfrastructureEvent.event_kind == event_kind)
    raw_events = list(
        session.scalars(
            events_query.order_by(
                InfrastructureEvent.started_at, InfrastructureEvent.id
            ).limit(MAX_CORRELATION_EVENTS + 1)
        ).all()
    )
    truncated = len(raw_events) > MAX_CORRELATION_EVENTS
    events = raw_events[:MAX_CORRELATION_EVENTS]

    accepted_event_ids: set[str] = set()
    rejection_reasons: dict[str, set[str]] = defaultdict(set)
    correlated_members: list[dict[str, Any]] = []
    event_by_id = {event.id: event for event in events}

    for member in history_members:
        run = runs.get(str(member["run_id"]))
        if run is None:
            continue
        matched: list[InfrastructureEvent] = []
        for event in events:
            if event.source_trust not in TRUSTED_SOURCE_TRUST:
                rejection_reasons[event.id].add("untrusted_event_source")
                continue
            context_rejection = _run_context_rejection(event, run)
            if context_rejection is not None:
                rejection_reasons[event.id].add(context_rejection)
                continue
            if not _temporally_overlaps(
                event, run, window_seconds=window_seconds
            ):
                rejection_reasons[event.id].add("outside_run_window")
                continue
            matched.append(event)
            accepted_event_ids.add(event.id)

        kinds = sorted({event.event_kind for event in matched})
        correlated_members.append(
            {
                **member,
                "exposed": bool(matched),
                "event_ids": sorted(event.id for event in matched),
                "event_kinds": kinds,
            }
        )

    for event in events:
        if event.id not in accepted_event_ids and not rejection_reasons[event.id]:
            rejection_reasons[event.id].add("no_compatible_history_run")

    rejected_events = [
        {
            "event_id": event.id,
            "event_kind": event.event_kind,
            "source_trust": event.source_trust,
            "reasons": sorted(rejection_reasons[event.id]),
        }
        for event in events
        if event.id not in accepted_event_ids
    ]

    exposed = [item for item in correlated_members if item["exposed"]]
    unexposed = [item for item in correlated_members if not item["exposed"]]
    exposed_counts = _outcome_counts([str(item["outcome"]) for item in exposed])
    unexposed_counts = _outcome_counts([str(item["outcome"]) for item in unexposed])
    exposed_denominator = (
        exposed_counts[Outcome.passed.value] + exposed_counts[Outcome.failed.value]
    )
    unexposed_denominator = (
        unexposed_counts[Outcome.passed.value]
        + unexposed_counts[Outcome.failed.value]
    )
    rates = {
        "exposed_failure_rate": _rate(
            exposed_counts[Outcome.failed.value],
            exposed_denominator,
            minimum_support=minimum_support,
        ),
        "unexposed_failure_rate": _rate(
            unexposed_counts[Outcome.failed.value],
            unexposed_denominator,
            minimum_support=minimum_support,
        ),
    }

    kinds = sorted(
        {
            kind
            for item in correlated_members
            for kind in item["event_kinds"]
        }
    )
    associations = [
        _association_row(
            event_kind=kind,
            members=correlated_members,
            minimum_support=minimum_support,
        )
        for kind in kinds
    ]
    confounded_run_ids = [
        str(item["run_id"])
        for item in correlated_members
        if len(item["event_kinds"]) > 1
    ]
    confounders: list[str] = []
    if confounded_run_ids:
        confounders.append("multiple_event_kinds_overlap_the_same_run")
    if history["safety"]["selection_bias_present"]:
        confounders.append("history_contains_impact_selected_runs")
    if history["safety"]["truncated"]:
        confounders.append("history_input_truncated")
    if truncated:
        confounders.append("infrastructure_event_limit_reached")

    rejection_reason_set = {
        reason for item in rejected_events for reason in item["reasons"]
    }
    if truncated:
        status = "TRUNCATED"
    elif not correlated_members:
        status = "INSUFFICIENT_DATA"
    elif not accepted_event_ids:
        if raw_events and rejection_reason_set == {"untrusted_event_source"}:
            status = "UNTRUSTED_EVENT_SOURCE"
        elif raw_events and rejection_reason_set - {"outside_run_window"}:
            status = "INCOMPATIBLE_CONTEXT"
        else:
            status = "NO_MATCHING_EVENTS"
    elif (
        exposed_denominator < minimum_support
        or unexposed_denominator < minimum_support
    ):
        status = "INSUFFICIENT_DATA"
    elif confounded_run_ids and event_kind is None:
        status = "CONFOUNDED"
    else:
        status = "AVAILABLE"

    absolute_difference = (
        round(
            float(rates["exposed_failure_rate"]["value"])
            - float(rates["unexposed_failure_rate"]["value"]),
            6,
        )
        if rates["exposed_failure_rate"]["value"] is not None
        and rates["unexposed_failure_rate"]["value"] is not None
        else None
    )
    relative_risk = (
        round(
            float(rates["exposed_failure_rate"]["value"])
            / float(rates["unexposed_failure_rate"]["value"]),
            6,
        )
        if rates["exposed_failure_rate"]["value"] is not None
        and rates["unexposed_failure_rate"]["value"] not in {None, 0}
        else None
    )
    rates["absolute_failure_rate_difference"] = absolute_difference
    rates["relative_risk"] = relative_risk

    event_digest_inputs = [
        {
            "id": event.id,
            "source_digest": event.source_digest,
            "source_trust": event.source_trust,
            "started_at": _as_utc(event.started_at).isoformat(),
            "ended_at": _as_utc(event.ended_at).isoformat()
            if event.ended_at
            else None,
            "recorded_at": _as_utc(event.recorded_at).isoformat(),
        }
        for event in events
    ]
    digest_payload = {
        "policy_version": INFRASTRUCTURE_POLICY_VERSION,
        "engine_version": INFRASTRUCTURE_ENGINE_VERSION,
        "selected_execution_id": selected_execution.id,
        "selected_run_id": selected_run.id,
        "history_input_digest": history["history_input_digest"],
        "cutoff": cutoff_utc.isoformat(),
        "after": after_utc.isoformat() if after_utc else None,
        "window_seconds": window_seconds,
        "event_kind": event_kind,
        "minimum_support": minimum_support,
        "events": event_digest_inputs,
        "members": [
            {
                "run_id": item["run_id"],
                "outcome": item["outcome"],
                "execution_ids": item["execution_ids"],
                "event_ids": item["event_ids"],
                "event_kinds": item["event_kinds"],
            }
            for item in correlated_members
        ],
        "status": status,
    }
    input_digest = _canonical_digest(digest_payload)
    sample_sizes = {
        "independent_runs": len(correlated_members),
        "exposed_runs": len(exposed),
        "unexposed_runs": len(unexposed),
        "exposed_pass_fail_denominator": exposed_denominator,
        "unexposed_pass_fail_denominator": unexposed_denominator,
        "candidate_events": len(events),
        "accepted_events": len(accepted_event_ids),
        "rejected_events": len(rejected_events),
        "trusted_candidate_events": sum(
            event.source_trust in TRUSTED_SOURCE_TRUST for event in events
        ),
        "untrusted_candidate_events": sum(
            event.source_trust not in TRUSTED_SOURCE_TRUST for event in events
        ),
        "confounded_runs": len(confounded_run_ids),
        "skipped_runs": exposed_counts[Outcome.skipped.value]
        + unexposed_counts[Outcome.skipped.value],
        "cancelled_runs": exposed_counts[Outcome.cancelled.value]
        + unexposed_counts[Outcome.cancelled.value],
        "unknown_runs": exposed_counts[Outcome.unknown.value]
        + unexposed_counts[Outcome.unknown.value],
    }
    safety = {
        "association_only": True,
        "causality_claimed": False,
        "can_support_infrastructure_association": status == "AVAILABLE",
        "can_independently_authorize_infrastructure_classification": False,
        "trusted_sources_only": all(
            event_by_id[event_id].source_trust in TRUSTED_SOURCE_TRUST
            for event_id in accepted_event_ids
        ),
        "prior_only": True,
        "current_run_excluded": exclude_run_id == selected_run.id,
        "truncated": truncated or bool(history["safety"]["truncated"]),
        "notes": [
            "Infrastructure events are independently persisted records; test artifacts cannot self-promote into trusted events.",
            "Temporal overlap and rate differences are associations, not proof of cause.",
            "An infrastructure correlation never removes product-risk evidence or independently changes a failure category.",
            "Current and future events are excluded by the analysis cutoff.",
            "Retries and browser attempts collapse to one conservative outcome per independent run.",
        ],
    }

    snapshot_id: str | None = None
    created_at: datetime | None = None
    if persist:
        existing = session.scalar(
            select(InfrastructureCorrelationSnapshot)
            .where(
                InfrastructureCorrelationSnapshot.project_id == selected_run.project_id,
                InfrastructureCorrelationSnapshot.input_digest == input_digest,
            )
            .options(selectinload(InfrastructureCorrelationSnapshot.members))
        )
        if existing is None:
            snapshot = InfrastructureCorrelationSnapshot(
                project_id=selected_run.project_id,
                selected_run_id=selected_run.id,
                selected_execution_id=selected_execution.id,
                policy_version=INFRASTRUCTURE_POLICY_VERSION,
                engine_version=INFRASTRUCTURE_ENGINE_VERSION,
                history_input_digest=history["history_input_digest"],
                input_digest=input_digest,
                status=status,
                cutoff_at=cutoff_utc,
                after_at=after_utc,
                window_seconds=window_seconds,
                event_kind=event_kind,
                minimum_support=minimum_support,
                accepted_event_ids=sorted(accepted_event_ids),
                rejected_events=rejected_events,
                sample_sizes=sample_sizes,
                exposed_outcomes=exposed_counts,
                unexposed_outcomes=unexposed_counts,
                rates=rates,
                associations=associations,
                confounders=confounders,
                safety=safety,
            )
            session.add(snapshot)
            session.flush()
            for item in correlated_members:
                session.add(
                    InfrastructureCorrelationMember(
                        snapshot_id=snapshot.id,
                        run_id=str(item["run_id"]),
                        execution_ids=list(item["execution_ids"]),
                        outcome=str(item["outcome"]),
                        exposed=bool(item["exposed"]),
                        event_ids=list(item["event_ids"]),
                        event_kinds=list(item["event_kinds"]),
                        observed_at=datetime.fromisoformat(str(item["observed_at"])),
                    )
                )
            session.commit()
            session.refresh(snapshot)
            existing = snapshot
        snapshot_id = existing.id
        created_at = existing.created_at

    return {
        "snapshot_id": snapshot_id,
        "project_id": selected_run.project_id,
        "selected_run_id": selected_run.id,
        "selected_execution_id": selected_execution.id,
        "policy_version": INFRASTRUCTURE_POLICY_VERSION,
        "engine_version": INFRASTRUCTURE_ENGINE_VERSION,
        "history_input_digest": history["history_input_digest"],
        "input_digest": input_digest,
        "status": status,
        "cutoff_at": cutoff_utc,
        "after_at": after_utc,
        "window_seconds": window_seconds,
        "event_kind": event_kind,
        "minimum_support": minimum_support,
        "accepted_event_ids": sorted(accepted_event_ids),
        "accepted_events": [
            infrastructure_event_to_schema(event_by_id[event_id])
            for event_id in sorted(accepted_event_ids)
        ],
        "rejected_events": rejected_events,
        "sample_sizes": sample_sizes,
        "exposed_outcomes": exposed_counts,
        "unexposed_outcomes": unexposed_counts,
        "rates": rates,
        "associations": associations,
        "confounders": confounders,
        "safety": safety,
        "members": correlated_members,
        "created_at": created_at,
    }


def get_infrastructure_correlation(
    session: Session, snapshot_id: str
) -> InfrastructureCorrelationSnapshot | None:
    return session.scalar(
        select(InfrastructureCorrelationSnapshot)
        .where(InfrastructureCorrelationSnapshot.id == snapshot_id)
        .options(
            selectinload(InfrastructureCorrelationSnapshot.members),
            selectinload(InfrastructureCorrelationSnapshot.selected_execution),
            selectinload(InfrastructureCorrelationSnapshot.selected_run),
        )
    )


def infrastructure_correlation_to_schema(
    session: Session, snapshot: InfrastructureCorrelationSnapshot
) -> dict[str, Any]:
    events = {
        event.id: event
        for event in session.scalars(
            select(InfrastructureEvent).where(
                InfrastructureEvent.id.in_(snapshot.accepted_event_ids)
            )
        ).all()
    } if snapshot.accepted_event_ids else {}
    members = sorted(
        snapshot.members,
        key=lambda item: (_as_utc(item.observed_at), item.run_id),
    )
    return {
        "snapshot_id": snapshot.id,
        "project_id": snapshot.project_id,
        "selected_run_id": snapshot.selected_run_id,
        "selected_execution_id": snapshot.selected_execution_id,
        "policy_version": snapshot.policy_version,
        "engine_version": snapshot.engine_version,
        "history_input_digest": snapshot.history_input_digest,
        "input_digest": snapshot.input_digest,
        "status": snapshot.status,
        "cutoff_at": snapshot.cutoff_at,
        "after_at": snapshot.after_at,
        "window_seconds": snapshot.window_seconds,
        "event_kind": snapshot.event_kind,
        "minimum_support": snapshot.minimum_support,
        "accepted_event_ids": snapshot.accepted_event_ids,
        "accepted_events": [
            infrastructure_event_to_schema(events[event_id])
            for event_id in snapshot.accepted_event_ids
            if event_id in events
        ],
        "rejected_events": snapshot.rejected_events,
        "sample_sizes": snapshot.sample_sizes,
        "exposed_outcomes": snapshot.exposed_outcomes,
        "unexposed_outcomes": snapshot.unexposed_outcomes,
        "rates": snapshot.rates,
        "associations": snapshot.associations,
        "confounders": snapshot.confounders,
        "safety": snapshot.safety,
        "members": [
            {
                "run_id": item.run_id,
                "execution_ids": item.execution_ids,
                "outcome": item.outcome,
                "exposed": item.exposed,
                "event_ids": item.event_ids,
                "event_kinds": item.event_kinds,
                "observed_at": item.observed_at,
            }
            for item in members
        ],
        "created_at": snapshot.created_at,
    }
