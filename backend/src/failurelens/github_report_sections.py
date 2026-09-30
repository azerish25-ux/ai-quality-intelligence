"""Bounded read-only projections of persisted report evidence.

Nothing in this module creates analyses, comparisons, recommendations or clusters.
Stored findings describe observations; they never suppress failures or approve releases.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .evidence_validation import validate_scoped_evidence_records
from .github_report import _safe
from .history import _logical_test_key
from .impact import impact_recommendation_to_schema
from .models import (
    ClusterMembership,
    ClusterRevision,
    Evidence,
    Failure,
    FailureCluster,
    ImpactRecommendation,
    PerformanceBaselineMember,
    PerformanceBaselineSnapshot,
    PerformanceComparison,
    PerformanceObservation,
    Run,
    RunInput,
    TestExecution,
)
from .redaction import redact_text

DETAIL_LIMIT = 50
REFERENCE_LIMIT = 10
BASE_RUN_LIMIT = 50
_TRUSTED = {"authenticated_lookup", "trusted_workflow"}


def text(value: Any, limit: int = 400) -> str | None:
    if value is None:
        return None
    return " ".join(redact_text(str(value)).text.split()).replace("@", "@\u200b")[
        :limit
    ]


def _json(value: Any, depth: int = 0) -> Any:
    """Only bounded inert JSON metadata; arbitrary model objects never escape."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return text(value)
    if depth >= 4:
        return "Detail unavailable at nesting limit"
    if isinstance(value, dict):
        keys = sorted(value, key=str)
        result = {
            str(text(key, 120)): _json(value[key], depth + 1) for key in keys[:30]
        }
        if len(keys) > 30:
            result["omitted_fields"] = len(keys) - 30
        return result
    if isinstance(value, (list, tuple)):
        return {
            "items": [_json(item, depth + 1) for item in value[:REFERENCE_LIMIT]],
            "omitted_items": max(0, len(value) - REFERENCE_LIMIT),
        }
    return text(value)


def _texts(values: list[Any], limit: int = REFERENCE_LIMIT) -> list[str]:
    return [text(value) or "unknown" for value in values[:limit]]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _at(run: Run) -> datetime:
    return _utc(run.started_at or run.created_at)


def logical_groups(
    run: Run, executions: list[TestExecution]
) -> list[list[TestExecution]]:
    """Match history identity, with one observation per browser cohort."""
    grouped: dict[tuple[str, str | None], list[TestExecution]] = defaultdict(list)
    for execution in executions:
        grouped[(_logical_test_key(execution, run), execution.browser)].append(
            execution
        )
    return [
        sorted(items, key=lambda item: (item.attempt, item.id))
        for _, items in sorted(
            grouped.items(), key=lambda entry: (entry[0][0], entry[0][1] or "")
        )
    ]


def _execution_identity(execution: TestExecution, run: Run) -> dict[str, Any]:
    return {
        "logical_test_key": _logical_test_key(execution, run),
        "test_identity": text(execution.test_identity),
        "suite": text(execution.suite),
        "source_path": text(execution.source_path),
        "browser": text(execution.browser),
        "parameterization": text(execution.parameterization),
    }


class _Availability:
    def __init__(self, session: Session):
        self.session = session
        self.cache: dict[tuple[str, str, str | None, str | None], str] = {}

    def evidence(
        self,
        evidence: Evidence | None,
        run: Run,
        *,
        execution: TestExecution | None = None,
        run_input: RunInput | None = None,
    ) -> str:
        if run.evidence_expired_at is not None:
            return "expired"
        if evidence is None:
            return "unavailable"
        key = (
            evidence.id,
            run.id,
            execution.id if execution else None,
            run_input.id if run_input else None,
        )
        if key in self.cache:
            return self.cache[key]
        if evidence.project_id != run.project_id or evidence.run_id != run.id:
            return "unavailable"
        if evidence.run_input is not None and evidence.run_input.status != "accepted":
            return (
                "restricted"
                if evidence.run_input.status == "restricted"
                else "unavailable"
            )
        derivative = evidence.derivative
        if derivative is not None and derivative.restricted:
            return "restricted"
        if derivative is not None and derivative.retention_state == "expired":
            return "expired"
        check = validate_scoped_evidence_records(
            run, [evidence], execution=execution, run_input=run_input
        )
        state = "available" if evidence.id in check.accepted_ids else "unavailable"
        self.cache[key] = state
        return state

    def execution(
        self, execution: TestExecution, run: Run
    ) -> tuple[str, list[Evidence]]:
        if run.evidence_expired_at is not None:
            return "expired", []
        rows = self.session.scalars(
            select(Evidence)
            .where(
                Evidence.project_id == run.project_id,
                Evidence.run_id == run.id,
                Evidence.execution_id == execution.id,
            )
            .order_by(Evidence.id)
        ).all()
        accepted = []
        states = []
        expected = {
            "test_identity": execution.test_identity,
            "suite": execution.suite,
            "source_path": execution.source_path,
            "parameterization": execution.parameterization,
            "browser": execution.browser,
            "attempt": execution.attempt,
            "outcome": execution.outcome.value,
        }
        for row in rows:
            state = self.evidence(row, run, execution=execution)
            if state == "available" and all(
                row.observation.get(key) == value for key, value in expected.items()
            ):
                accepted.append(row)
            else:
                states.append(state if state != "available" else "unavailable")
        if accepted:
            return "available", accepted
        return (
            "restricted"
            if "restricted" in states
            else "expired"
            if "expired" in states
            else "unavailable"
        ), []


def skipped_section(
    run: Run, groups: list[list[TestExecution]], available: _Availability
) -> dict[str, Any]:
    skipped = [items[-1] for items in groups if items[-1].outcome.value == "skipped"]
    items: list[dict[str, Any]] = []
    for execution in skipped[:DETAIL_LIMIT]:
        state, evidence = available.execution(execution, run)
        reasons = sorted(
            {
                (text(row.observation.get("message")) or "")
                for row in evidence
                if row.observation.get("message")
            }
        )
        items.append(
            {
                **_execution_identity(execution, run),
                "execution_id": execution.id,
                "attempt": execution.attempt,
                "evidence_state": state,
                "reason": reasons[0] if reasons else None,
                "reason_status": "recorded" if reasons else "unknown",
                "evidence_ids": [row.id for row in evidence[:REFERENCE_LIMIT]],
                "omitted_evidence_ids": max(0, len(evidence) - REFERENCE_LIMIT),
            }
        )
    return {
        "status": "expired" if run.evidence_expired_at else "available",
        "count": len(skipped),
        "items": items,
        "omitted_items": max(0, len(skipped) - len(items)),
    }


def impact_section(session: Session, run: Run) -> dict[str, Any]:
    rows = session.scalars(
        select(ImpactRecommendation)
        .where(
            ImpactRecommendation.project_id == run.project_id,
            ImpactRecommendation.run_id == run.id,
        )
        .options(
            selectinload(ImpactRecommendation.items),
            selectinload(ImpactRecommendation.overrides),
            selectinload(ImpactRecommendation.changed_input),
        )
        .order_by(ImpactRecommendation.created_at.desc(), ImpactRecommendation.id)
    ).all()
    items: list[dict[str, Any]] = []
    selected_total = excluded_total = override_total = fallback_total = 0
    for row in rows:
        view = impact_recommendation_to_schema(row)
        selected_total += len(view.selected_tests)
        excluded_total += len(view.excluded_tests)
        override_total += len(view.overrides)
        fallback_total += int(row.full_suite_required)
        if len(items) >= DETAIL_LIMIT:
            continue
        state = (
            "expired"
            if run.evidence_expired_at
            else "restricted"
            if row.changed_input.status == "restricted"
            else "available"
            if row.changed_input.status == "accepted"
            and row.changed_input.project_id == run.project_id
            and row.changed_input.run_id == run.id
            and row.mapping_snapshot.project_id == run.project_id
            and (
                row.changed_input.digest is None
                or row.changed_input.digest == row.changed_files_digest
            )
            and row.base_sha == run.base_sha
            and row.head_sha == run.commit_sha
            else "unavailable"
        )
        exposed = state == "available"

        def test_item(item):
            return {
                "test_key": text(item.test_key),
                "test_identity": text(item.test_identity),
                "source_path": text(item.source_path),
                "mandatory": item.mandatory,
                "base_selected": item.base_selected,
                "effective_selected": item.effective_selected,
                "selection_source": text(item.selection_source),
                "rank": item.rank,
                "confidence": text(item.confidence),
                "reason_codes": _texts(item.reason_codes),
                "omitted_reason_codes": max(
                    0, len(item.reason_codes) - REFERENCE_LIMIT
                ),
                "reasons": _json(item.reasons),
                "exclusion_reason": text(item.exclusion_reason),
            }

        selected = (
            [test_item(item) for item in view.selected_tests[:DETAIL_LIMIT]]
            if exposed
            else []
        )
        excluded = (
            [test_item(item) for item in view.excluded_tests[:DETAIL_LIMIT]]
            if exposed
            else []
        )
        overrides = (
            [
                {
                    "override_id": event.id,
                    "test_key": text(event.test_key),
                    "action": text(event.action),
                    "actor": text(event.actor),
                    "reason": text(event.reason),
                    "revision_before": event.revision_before,
                    "revision_after": event.revision_after,
                }
                for event in view.overrides[:DETAIL_LIMIT]
            ]
            if exposed
            else []
        )
        items.append(
            {
                "recommendation_id": row.id,
                "revision": row.current_revision,
                "mapping_snapshot_id": row.mapping_snapshot_id,
                "changed_input_id": row.changed_input_id,
                "base_sha": text(row.base_sha, 64),
                "head_sha": text(row.head_sha, 64),
                "status": text(row.status) if exposed else "EVIDENCE_UNAVAILABLE",
                "stored_status": text(row.status),
                "evidence_state": state,
                "full_suite_required": row.full_suite_required,
                "comparison_trusted": row.comparison_trusted,
                "mapping_complete": row.mapping_complete,
                "summary": text(row.summary, 800)
                if exposed
                else "Evidence unavailable; review required.",
                "safety_reasons": _texts(row.safety_reasons) if exposed else [state],
                "omitted_safety_reasons": max(
                    0, len(row.safety_reasons) - REFERENCE_LIMIT
                )
                if exposed
                else len(row.safety_reasons),
                "selected_count": len(view.selected_tests),
                "excluded_count": len(view.excluded_tests),
                "override_count": len(view.overrides),
                "selected_tests": selected,
                "excluded_tests": excluded,
                "overrides": overrides,
                "omitted_selected_tests": len(view.selected_tests) - len(selected),
                "omitted_excluded_tests": len(view.excluded_tests) - len(excluded),
                "omitted_overrides": len(view.overrides) - len(overrides),
            }
        )
    return {
        "status": "expired"
        if run.evidence_expired_at
        else "available"
        if rows
        else "not_recorded",
        "count": len(rows),
        "selected_count": selected_total,
        "excluded_count": excluded_total,
        "override_count": override_total,
        "full_suite_required_count": fallback_total,
        "items": items,
        "omitted_items": len(rows) - len(items),
        "note": "Counts are stored recommendation decisions, not executed or skipped tests; multiple recommendations may overlap.",
    }


def clusters_section(
    session: Session, run: Run, available: _Availability
) -> dict[str, Any]:
    rows = session.execute(
        select(FailureCluster, ClusterRevision)
        .join(ClusterRevision, ClusterRevision.cluster_id == FailureCluster.id)
        .where(
            ClusterRevision.id.in_(
                select(ClusterMembership.revision_id)
                .join(Failure, Failure.id == ClusterMembership.failure_id)
                .where(Failure.run_id == run.id, Failure.project_id == run.project_id)
            ),
            FailureCluster.project_id == run.project_id,
            FailureCluster.status == "active",
            ClusterRevision.revision == FailureCluster.current_revision,
        )
        .order_by(FailureCluster.cluster_key, FailureCluster.id)
    ).all()
    items: list[dict[str, Any]] = []
    for cluster, revision in rows[:DETAIL_LIMIT]:
        memberships = session.scalars(
            select(ClusterMembership)
            .join(Failure, Failure.id == ClusterMembership.failure_id)
            .where(
                ClusterMembership.revision_id == revision.id,
                ClusterMembership.cluster_id == cluster.id,
                Failure.project_id == run.project_id,
            )
            .order_by(ClusterMembership.failure_id)
        ).all()
        current = [member for member in memberships if member.failure.run_id == run.id]
        representative = (
            session.get(Failure, revision.representative_failure_id)
            if revision.representative_failure_id
            else None
        )
        representative_state = "unavailable"
        if representative is not None and representative.project_id == run.project_id:
            representative_state, _ = available.execution(
                representative.execution, representative.run
            )
        revision_states = [
            available.execution(member.failure.execution, member.failure.run)[0]
            for member in memberships
        ]
        revision_state = "available"
        if len(memberships) != revision.member_count:
            revision_state = "unavailable"
        for unavailable_state in ("expired", "restricted", "unavailable"):
            if unavailable_state in revision_states:
                revision_state = unavailable_state
                break
        members = []
        for member in current[:DETAIL_LIMIT]:
            state, _ = available.execution(member.failure.execution, run)
            if revision_state != "available":
                state = revision_state
            members.append(
                {
                    "failure_id": member.failure_id,
                    "test_identity": text(member.failure.execution.test_identity),
                    "role": text(member.role),
                    "assignment_kind": text(member.assignment_kind),
                    "evidence_state": state,
                    "similarity_score": member.similarity_score
                    if state == "available"
                    else None,
                    "matching_signals": _texts(member.matching_signals)
                    if state == "available"
                    else [],
                    "conflicting_signals": _texts(member.conflicting_signals)
                    if state == "available"
                    else [],
                    "omitted_matching_signals": max(
                        0, len(member.matching_signals) - REFERENCE_LIMIT
                    )
                    if state == "available"
                    else len(member.matching_signals),
                    "omitted_conflicting_signals": max(
                        0, len(member.conflicting_signals) - REFERENCE_LIMIT
                    )
                    if state == "available"
                    else len(member.conflicting_signals),
                }
            )
        items.append(
            {
                "cluster_id": cluster.id,
                "revision_id": revision.id,
                "revision": revision.revision,
                "status": text(cluster.status),
                "evidence_state": revision_state,
                "member_count": revision.member_count,
                "run_member_count": len(current),
                "representative_failure_id": representative.id
                if representative is not None
                and representative.project_id == run.project_id
                else None,
                "representative_run_id": representative.run_id
                if representative is not None
                and representative.project_id == run.project_id
                else None,
                "representative_test_identity": text(
                    representative.execution.test_identity
                )
                if representative is not None and representative_state == "available"
                else None,
                "representative_evidence_state": representative_state,
                "uncertainty": text(cluster.uncertainty),
                "uncertainty_flags": _texts(revision.uncertainty_flags)
                if revision_state == "available"
                else [revision_state],
                "omitted_uncertainty_flags": max(
                    0, len(revision.uncertainty_flags) - REFERENCE_LIMIT
                )
                if revision_state == "available"
                else len(revision.uncertainty_flags),
                "members": members,
                "omitted_members": len(current) - len(members),
            }
        )
    return {
        "status": "expired"
        if run.evidence_expired_at
        else "available"
        if rows
        else "not_recorded",
        "count": len(rows),
        "items": items,
        "omitted_items": len(rows) - len(items),
        "note": "Current stored revisions are used; membership does not establish a common cause or reduce failure counts.",
    }


def performance_section(
    session: Session, run: Run, available: _Availability
) -> dict[str, Any]:
    query = select(PerformanceComparison).where(
        PerformanceComparison.project_id == run.project_id,
        PerformanceComparison.current_run_id == run.id,
    )
    raw_counts = dict(
        session.execute(
            select(PerformanceComparison.status, func.count())
            .where(
                PerformanceComparison.project_id == run.project_id,
                PerformanceComparison.current_run_id == run.id,
            )
            .group_by(PerformanceComparison.status)
        ).all()
    )
    counts: Counter[str] = Counter()
    for status, count in raw_counts.items():
        counts[
            status
            if status
            in {
                "REGRESSION",
                "IMPROVEMENT",
                "WITHIN_TOLERANCE",
                "INCONCLUSIVE",
                "BASELINE_UNAVAILABLE",
                "INCOMPATIBLE_BASELINE",
            }
            else "unknown"
        ] += count
    rows = session.scalars(
        query.options(
            selectinload(PerformanceComparison.current_observation),
            selectinload(PerformanceComparison.policy),
            selectinload(PerformanceComparison.baseline_snapshot)
            .selectinload(PerformanceBaselineSnapshot.members)
            .selectinload(PerformanceBaselineMember.observation),
        )
        .order_by(PerformanceComparison.created_at.desc(), PerformanceComparison.id)
        .limit(DETAIL_LIMIT)
    ).all()
    items: list[dict[str, Any]] = []
    for row in rows:
        observation, baseline, policy = (
            row.current_observation,
            row.baseline_snapshot,
            row.policy,
        )
        state = available.evidence(
            observation.evidence,
            run,
            execution=observation.execution,
            run_input=observation.run_input,
        )
        if (
            observation.project_id != run.project_id
            or observation.run_id != run.id
            or row.current_evidence_id != observation.evidence_id
            or baseline.project_id != run.project_id
            or baseline.current_run_id != run.id
            or baseline.current_observation_id != observation.id
            or policy.project_id != run.project_id
        ):
            state = "unavailable"
        members: list[dict[str, Any]] = []
        baseline_states: list[str] = []
        for member in sorted(
            baseline.members, key=lambda member: (member.position, member.id)
        ):
            previous = member.observation
            previous_state = available.evidence(
                previous.evidence,
                previous.run,
                execution=previous.execution,
                run_input=previous.run_input,
            )
            if (
                previous.project_id != run.project_id
                or member.run_id != previous.run_id
            ):
                previous_state = "unavailable"
            baseline_states.append(previous_state)
            if len(members) < DETAIL_LIMIT:
                members.append(
                    {
                        "run_id": previous.run_id
                        if previous.project_id == run.project_id
                        else None,
                        "observation_id": previous.id
                        if previous.project_id == run.project_id
                        else None,
                        "tested_head": text(previous.run.commit_sha, 64)
                        if previous.project_id == run.project_id
                        else None,
                        "evidence_state": previous_state,
                        "evidence_id": previous.evidence_id
                        if previous_state == "available"
                        else None,
                        "value": previous.canonical_value
                        if previous_state == "available"
                        else None,
                        "unit": text(previous.canonical_unit),
                        "sample_count": previous.sample_count,
                    }
                )
        if sorted(row.baseline_evidence_ids) != sorted(
            member.observation.evidence_id for member in baseline.members
        ):
            baseline_states.append("unavailable")
        for failed_state in ("expired", "restricted", "unavailable"):
            if failed_state in baseline_states and state == "available":
                state = failed_state
        exposed = state == "available"
        items.append(
            {
                "comparison_id": row.id,
                "observation_id": observation.id,
                "status": text(row.status) if exposed else "EVIDENCE_UNAVAILABLE",
                "stored_status": text(row.status),
                "evidence_state": state,
                "metric_name": text(observation.metric_name)
                if observation.project_id == run.project_id
                else None,
                "metric_scope": text(observation.metric_scope)
                if observation.project_id == run.project_id
                else None,
                "statistic": text(observation.statistic),
                "unit": text(observation.canonical_unit),
                "direction": text(
                    policy.direction_overrides.get(
                        observation.metric_name, observation.direction
                    )
                ),
                "current_value": row.current_value if exposed else None,
                "baseline_value": row.baseline_value if exposed else None,
                "absolute_change": row.absolute_change if exposed else None,
                "relative_change": row.relative_change if exposed else None,
                "threshold_status": text(row.threshold_status)
                if exposed
                else "unknown",
                "threshold_details": _json(observation.threshold_details)
                if exposed
                else {},
                "policy_id": policy.id,
                "policy_version": text(policy.version),
                "allowed_absolute_change": row.allowed_absolute_change,
                "allowed_relative_change": row.allowed_relative_change,
                "min_baseline_runs": policy.min_baseline_runs,
                "max_baseline_age_days": policy.max_baseline_age_days,
                "require_trusted": policy.require_trusted,
                "current_sample_count": row.current_sample_count,
                "baseline_run_count": row.baseline_run_count,
                "baseline_sample_count": row.baseline_sample_count,
                "baseline_snapshot_id": baseline.id,
                "baseline_status": text(baseline.status)
                if exposed
                else "EVIDENCE_UNAVAILABLE",
                "baseline_cutoff": _utc(baseline.cutoff_at).isoformat(),
                "baseline_aggregation": text(baseline.aggregation),
                "baseline_age_seconds": baseline.baseline_age_seconds,
                "baseline_members": members if exposed else [],
                "omitted_baseline_members": len(baseline.members) - len(members)
                if exposed
                else len(baseline.members),
                "compatibility": _json(row.compatibility) if exposed else {},
                "uncertainty": _json(row.uncertainty) if exposed else {},
                "confounders": _texts(row.confounders) if exposed else [state],
                "omitted_confounders": max(0, len(row.confounders) - REFERENCE_LIMIT)
                if exposed
                else len(row.confounders),
                "summary": text(row.summary, 800)
                if exposed
                else "Evidence unavailable; review required.",
                "next_measurement": text(row.next_measurement, 800)
                if exposed
                else "Restore authorized evidence before interpreting this comparison.",
                "current_evidence_id": row.current_evidence_id if exposed else None,
                "baseline_evidence_ids": _texts(row.baseline_evidence_ids)
                if exposed
                else [],
                "omitted_baseline_evidence_ids": max(
                    0, len(row.baseline_evidence_ids) - REFERENCE_LIMIT
                )
                if exposed
                else len(row.baseline_evidence_ids),
            }
        )
    count = sum(counts.values())
    observation_count = (
        session.scalar(
            select(func.count())
            .select_from(PerformanceObservation)
            .where(
                PerformanceObservation.project_id == run.project_id,
                PerformanceObservation.run_id == run.id,
            )
        )
        or 0
    )
    return {
        "status": "expired"
        if run.evidence_expired_at
        else "available"
        if count
        else "not_assessed",
        "count": count,
        "observation_count": observation_count,
        "stored_status_counts": {
            str(text(key)): value for key, value in sorted(counts.items())
        },
        "items": items,
        "omitted_items": count - len(items),
        "note": "Only stored comparisons are shown. Missing comparisons are unknown; run-level percentiles are not aggregate percentiles and statistical significance is not claimed.",
    }


def _baseline_run_reasons(current: Run, candidate: Run) -> list[str]:
    reasons = []
    for name in (
        "repository",
        "framework",
        "environment",
        "run_scope",
        "worker_count",
        "shard_count",
        "timezone",
    ):
        if getattr(candidate, name) != getattr(current, name):
            reasons.append(f"{name}_mismatch")
    if candidate.run_scope not in {"full_suite", "impact_selected"}:
        reasons.append("unknown_run_scope")
    if candidate.completeness != "complete" or candidate.status.value != "complete":
        reasons.append("incomplete_baseline_run")
    if candidate.evidence_expired_at is not None:
        reasons.append("evidence_expired")
    if _at(candidate) >= _at(current) or _utc(candidate.created_at) >= _at(current):
        reasons.append("not_prior_to_current_run")
    if candidate.ended_at is not None and _utc(candidate.ended_at) >= _at(current):
        reasons.append("baseline_not_finished_before_current_run")
    if candidate.source_metadata.get("comparison_trust") not in _TRUSTED:
        reasons.append("untrusted_baseline_run")
    return reasons


def _failure_fingerprint(
    execution: TestExecution, evidence: list[Evidence]
) -> str | None:
    from .fingerprint import make_fingerprint

    failure = execution.failure
    if failure is None:
        return None
    for row in evidence:
        observation = row.observation
        message = (
            observation.get("message") or row.excerpt or "Test failed without a message"
        )
        exception = observation.get("exception_type")
        if failure.message != message or failure.exception_type != exception:
            continue
        fingerprint, _ = make_fingerprint(
            message, exception, observation.get("details") or {}
        )
        if fingerprint == failure.strict_fingerprint:
            return fingerprint
    return None


def baseline_section(
    session: Session,
    run: Run,
    groups: list[list[TestExecution]],
    available: _Availability,
) -> dict[str, Any]:
    failing = [
        group
        for group in groups
        if any(item.outcome.value == "failed" for item in group)
    ]
    reasons = []
    if not run.base_sha or not re.fullmatch(
        r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", run.base_sha
    ):
        reasons.append("exact_base_sha_unavailable")
    if not run.commit_sha or not re.fullmatch(
        r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", run.commit_sha
    ):
        reasons.append("exact_tested_head_unavailable")
    if run.completeness != "complete" or run.status.value != "complete":
        reasons.append("current_run_incomplete")
    if run.run_scope not in {"full_suite", "impact_selected"}:
        reasons.append("unknown_run_scope")
    if run.evidence_expired_at is not None:
        reasons.append("current_evidence_expired")
    if run.source_metadata.get("comparison_trust") not in _TRUSTED:
        reasons.append("untrusted_current_run")
    query = select(Run).where(
        Run.project_id == run.project_id,
        Run.id != run.id,
        Run.commit_sha == run.base_sha,
    )
    candidate_count = (
        (session.scalar(select(func.count()).select_from(query.subquery())) or 0)
        if run.base_sha
        else 0
    )
    candidates = (
        session.scalars(
            query.order_by(Run.started_at.desc(), Run.created_at.desc(), Run.id).limit(
                BASE_RUN_LIMIT
            )
        ).all()
        if run.base_sha
        else []
    )
    if candidate_count > len(candidates):
        reasons.append("baseline_search_truncated")
    accepted, rejected = [], []
    for candidate in candidates:
        rejected_reasons = _baseline_run_reasons(run, candidate)
        if rejected_reasons:
            rejected.append({"run_id": candidate.id, "reasons": rejected_reasons})
        else:
            accepted.append(candidate)
    if not accepted:
        reasons.append("no_comparable_prior_base_run")
    prior_groups = {}
    for candidate in accepted if not reasons else []:
        executions = session.scalars(
            select(TestExecution)
            .where(TestExecution.run_id == candidate.id)
            .order_by(TestExecution.id)
        ).all()
        prior_groups[candidate.id] = {
            (_logical_test_key(group[0], candidate), group[0].browser): group
            for group in logical_groups(candidate, list(executions))
        }
    counts: Counter[str] = Counter()
    items: list[dict[str, Any]] = []
    for group in failing:
        execution = next(
            item for item in reversed(group) if item.outcome.value == "failed"
        )
        row_reasons = list(reasons)
        supporting = []
        prior_observations: list[dict[str, Any]] = []
        comparison = "unknown"
        current_state, current_evidence = (
            ("expired" if run.evidence_expired_at else "unknown", [])
            if reasons
            else available.execution(execution, run)
        )
        fingerprint = (
            _failure_fingerprint(execution, current_evidence) if not reasons else None
        )
        if not reasons and (current_state != "available" or fingerprint is None):
            row_reasons.append(
                f"current_failure_evidence_{current_state if current_state != 'available' else 'unavailable'}"
            )
        if len({item.attempt for item in group}) != len(group):
            row_reasons.append("duplicate_current_attempt")
        observed_kinds = []
        if not row_reasons:
            for candidate in accepted:
                key = (_logical_test_key(execution, run), execution.browser)
                previous = prior_groups[candidate.id].get(key)
                if not previous:
                    row_reasons.append("test_absent_from_comparable_base_run")
                    observed_kinds.append("unknown")
                    prior_observations.append(
                        {
                            "run_id": candidate.id,
                            "outcome": "not_observed",
                            "execution_ids": [],
                            "evidence_ids": [],
                        }
                    )
                    continue
                state_and_rows = [
                    available.execution(item, candidate) for item in previous
                ]
                states = [entry[0] for entry in state_and_rows]
                failed = [
                    (item, entry[1])
                    for item, entry in zip(previous, state_and_rows, strict=True)
                    if item.outcome.value == "failed"
                ]
                duplicate = len({item.attempt for item in previous}) != len(previous)
                producer_match = all(
                    previous[-1].details.get(name) == execution.details.get(name)
                    for name in ("producer", "producer_version")
                )
                if (
                    duplicate
                    or not producer_match
                    or any(state != "available" for state in states)
                ):
                    kind = "unknown"
                    row_reasons.append("baseline_execution_unavailable_or_incompatible")
                elif any(
                    _failure_fingerprint(item, evidence) == fingerprint
                    for item, evidence in failed
                ):
                    kind = "existing"
                elif not failed and previous[-1].outcome.value == "passed":
                    kind = "new"
                else:
                    kind = "unknown"
                    row_reasons.append(
                        "baseline_failure_differs_or_outcome_unavailable"
                    )
                observed_kinds.append(kind)
                evidence_ids = [row.id for _, rows in state_and_rows for row in rows]
                if kind != "unknown":
                    supporting.extend(evidence_ids)
                prior_observations.append(
                    {
                        "run_id": candidate.id,
                        "external_id": text(candidate.external_id),
                        "attempt": candidate.attempt,
                        "tested_head": text(candidate.commit_sha, 64),
                        "outcome": previous[-1].outcome.value,
                        "observed_failure_count": len(failed),
                        "comparison": kind,
                        "execution_ids": [
                            item.id for item in previous[:REFERENCE_LIMIT]
                        ],
                        "omitted_execution_ids": max(
                            0, len(previous) - REFERENCE_LIMIT
                        ),
                        "evidence_ids": evidence_ids[:REFERENCE_LIMIT],
                        "omitted_evidence_ids": max(
                            0, len(evidence_ids) - REFERENCE_LIMIT
                        ),
                    }
                )
            # An observed matching prior failure is supported even if other base runs
            # pass or lack the test. Those opposing observations remain visible.
            if "existing" in observed_kinds:
                comparison = "existing"
            elif observed_kinds and all(kind == "new" for kind in observed_kinds):
                comparison = "new"
        counts[comparison] += 1
        if len(items) < DETAIL_LIMIT:
            items.append(
                {
                    **_execution_identity(execution, run),
                    "current_failure_execution_id": execution.id,
                    "current_failure_id": execution.failure.id
                    if execution.failure
                    else None,
                    "current_final_outcome": group[-1].outcome.value,
                    "status": comparison,
                    "evidence_state": current_state,
                    "reasons": sorted(set(row_reasons)),
                    "current_evidence_ids": [
                        item.id for item in current_evidence[:REFERENCE_LIMIT]
                    ],
                    "omitted_current_evidence_ids": max(
                        0, len(current_evidence) - REFERENCE_LIMIT
                    ),
                    "supporting_baseline_evidence_ids": sorted(set(supporting))[
                        :REFERENCE_LIMIT
                    ],
                    "omitted_supporting_baseline_evidence_ids": max(
                        0, len(set(supporting)) - REFERENCE_LIMIT
                    ),
                    "prior_observations": prior_observations[:REFERENCE_LIMIT],
                    "omitted_prior_observations": max(
                        0, len(prior_observations) - REFERENCE_LIMIT
                    ),
                }
            )
    status = "available" if accepted and not reasons else "unknown"
    return {
        "status": status,
        "base_sha": text(run.base_sha, 64),
        "cutoff": _at(run).isoformat(),
        "candidate_run_count": candidate_count,
        "comparable_run_count": len(accepted),
        "comparable_run_ids": [item.id for item in accepted],
        "rejected_candidates": rejected,
        "omitted_candidates": max(0, candidate_count - len(candidates)),
        "reasons": reasons,
        "count": len(failing),
        "counts": {key: counts[key] for key in ("new", "existing", "unknown")},
        "items": items,
        "omitted_items": len(failing) - len(items),
        "note": "Comparisons concern the latest failed attempt of each logical test/browser, including retry-recovered tests. New means observed failure after validated passes at the exact base; existing means a matching prior failure fingerprint. Neither means harmless or authorizes ignoring a failure. Missing, incompatible, skipped or restricted evidence remains unknown.",
    }


def report_sections(
    session: Session, run: Run, groups: list[list[TestExecution]]
) -> dict[str, Any]:
    available = _Availability(session)
    return {
        "skipped_tests": skipped_section(run, groups, available),
        "impact": impact_section(session, run),
        "clusters": clusters_section(session, run, available),
        "performance": performance_section(session, run, available),
        "baseline": baseline_section(session, run, groups, available),
    }


def render_sections(sections: dict[str, Any]) -> str:
    lines = []
    skipped = sections["skipped_tests"]
    lines.extend(
        [
            "",
            "### Skipped tests",
            "",
            f"Skipped logical tests: {skipped['count']}. Unknown reasons are not invented.",
        ]
    )
    for item in skipped["items"]:
        lines.append(
            f"- `{_safe(item['test_identity'])}`: {_safe(item['reason'] or 'Reason unknown')} (evidence: {_safe(item['evidence_state'])})"
        )
    if skipped["omitted_items"]:
        lines.append(
            f"{skipped['omitted_items']} skipped-test details omitted; count covers all skipped logical tests."
        )
    impact = sections["impact"]
    lines.extend(
        [
            "",
            "### Stored change impact",
            "",
            f"Status: {_safe(impact['status'])}; recommendations: {impact['count']}; effective selections: {impact['selected_count']}; exclusions: {impact['excluded_count']}; overrides: {impact['override_count']}.",
            impact["note"],
        ]
    )
    for item in impact["items"]:
        lines.append(
            f"- Recommendation `{_safe(item['recommendation_id'])}` revision {item['revision']}: `{_safe(item['status'])}`; evidence: {_safe(item['evidence_state'])}; full-suite required: {str(item['full_suite_required']).lower()}."
        )
        lines.append(f"  {_safe(item['summary'])}")
        for reason in item["safety_reasons"]:
            lines.append(f"  Safety/fallback: {_safe(reason)}")
        for label, key in (
            ("Include", "selected_tests"),
            ("Exclude", "excluded_tests"),
        ):
            for test in item[key]:
                explanation = (
                    test["exclusion_reason"]
                    or ", ".join(test["reason_codes"])
                    or "No reason recorded"
                )
                lines.append(
                    f"  {label} `{_safe(test['test_identity'])}` ({_safe(test['selection_source'])}): {_safe(explanation)}"
                )
            if item[f"omitted_{key}"]:
                lines.append(
                    f"  {item[f'omitted_{key}']} {label.lower()} details omitted."
                )
        for override in item["overrides"]:
            lines.append(
                f"  Override `{_safe(override['override_id'])}` revision {override['revision_after']}: {_safe(override['action'])} `{_safe(override['test_key'])}` by {_safe(override['actor'])}; {_safe(override['reason'])}"
            )
        if item["omitted_overrides"]:
            lines.append(f"  {item['omitted_overrides']} override details omitted.")
    if impact["omitted_items"]:
        lines.append(
            f"{impact['omitted_items']} recommendations omitted; counters cover all stored recommendations."
        )
    clusters = sections["clusters"]
    lines.extend(
        [
            "",
            "### Current failure clusters",
            "",
            f"Status: {_safe(clusters['status'])}; clusters: {clusters['count']}.",
            clusters["note"],
        ]
    )
    for item in clusters["items"]:
        lines.append(
            f"- Cluster `{_safe(item['cluster_id'])}` revision {item['revision']}: {item['run_member_count']} failures from this run / {item['member_count']} stored members; uncertainty: {_safe(item['uncertainty'])}."
        )
        lines.append(
            f"  Representative: `{_safe(item['representative_failure_id'] or 'unknown')}`; {_safe(item['representative_test_identity'] or 'Evidence unavailable')}; evidence: {_safe(item['representative_evidence_state'])}."
        )
        for flag in item["uncertainty_flags"]:
            lines.append(f"  Uncertainty: {_safe(flag)}")
        for member in item["members"]:
            lines.append(
                f"  Member `{_safe(member['failure_id'])}`: `{_safe(member['test_identity'])}`; evidence: {_safe(member['evidence_state'])}."
            )
            for label, key in (
                ("Supporting similarity", "matching_signals"),
                ("Conflicting similarity", "conflicting_signals"),
            ):
                for signal in member[key]:
                    lines.append(f"    {label}: {_safe(signal)}")
        if item["omitted_members"]:
            lines.append(f"  {item['omitted_members']} member details omitted.")
    if clusters["omitted_items"]:
        lines.append(
            f"{clusters['omitted_items']} cluster details omitted; count covers all current clusters."
        )
    performance = sections["performance"]
    lines.extend(
        [
            "",
            "### Stored performance comparisons",
            "",
            f"Status: {_safe(performance['status'])}; comparisons: {performance['count']}; normalized observations: {performance['observation_count']}.",
            performance["note"],
        ]
    )
    for item in performance["items"]:
        lines.append(
            f"- Comparison `{_safe(item['comparison_id'])}`: `{_safe(item['metric_name'])}` / {_safe(item['statistic'])}: `{_safe(item['status'])}`; evidence: {_safe(item['evidence_state'])}."
        )
        lines.append(
            f"  Current: {_safe(item['current_value'])} {_safe(item['unit'])}; baseline: {_safe(item['baseline_value'])} {_safe(item['unit'])}; baseline runs: {item['baseline_run_count']}; samples: {_safe(item['current_sample_count'])} current / {item['baseline_sample_count']} baseline."
        )
        lines.append(
            f"  Policy `{_safe(item['policy_id'])}` ({_safe(item['policy_version'])}): absolute tolerance {_safe(item['allowed_absolute_change'])} {_safe(item['unit'])}; relative tolerance {_safe(item['allowed_relative_change'])}; producer threshold: {_safe(item['threshold_status'])}."
        )
        lines.append(
            f"  Baseline `{_safe(item['baseline_snapshot_id'])}`: {_safe(item['baseline_status'])}; aggregation: {_safe(item['baseline_aggregation'])}; cutoff: {_safe(item['baseline_cutoff'])}."
        )
        for member in item["baseline_members"]:
            lines.append(
                f"  Baseline run `{_safe(member['run_id'])}` head `{_safe(member['tested_head'])}` evidence `{_safe(member['evidence_id'])}`: {_safe(member['value'])} {_safe(member['unit'])}."
            )
        if item["omitted_baseline_members"]:
            lines.append(
                f"  {item['omitted_baseline_members']} baseline member details omitted."
            )
        for confounder in item["confounders"]:
            lines.append(f"  Confounder: {_safe(confounder)}")
        lines.append(f"  Investigate: {_safe(item['next_measurement'])}")
    if performance["omitted_items"]:
        lines.append(
            f"{performance['omitted_items']} performance comparison details omitted; counts cover all stored comparisons."
        )
    baseline = sections["baseline"]
    lines.extend(
        [
            "",
            "### Prior base-run evidence",
            "",
            f"Baseline: {_safe(baseline['status']).upper()}; comparable prior runs: {baseline['comparable_run_count']}; new: {baseline['counts']['new']}; existing: {baseline['counts']['existing']}; unknown: {baseline['counts']['unknown']}.",
            baseline["note"],
        ]
    )
    for reason in baseline["reasons"]:
        lines.append(f"- Comparison limitation: {_safe(reason)}")
    for item in baseline["items"]:
        lines.append(
            f"- `{_safe(item['test_identity'])}` ({_safe(item['browser'])}): `{item['status']}`; current final outcome: {item['current_final_outcome']}."
        )
        for reason in item["reasons"]:
            lines.append(f"  Uncertainty: {_safe(reason)}")
        for previous in item["prior_observations"]:
            lines.append(
                f"  Prior run `{_safe(previous['run_id'])}`: {_safe(previous['outcome'])}; evidence IDs: {', '.join(_safe(value) for value in previous['evidence_ids']) or 'unavailable'}."
            )
        if item["omitted_prior_observations"]:
            lines.append(
                f"  {item['omitted_prior_observations']} prior observations omitted."
            )
    if baseline["omitted_items"]:
        lines.append(
            f"{baseline['omitted_items']} failure comparison details omitted; counts cover all observed failing logical tests."
        )
    return "\n".join(lines) + "\n"


def advisory_reasons(run: Run, sections: dict[str, Any]) -> list[str]:
    reasons = []
    performance = sections["performance"]
    if performance["stored_status_counts"].get("REGRESSION", 0):
        reasons.append("stored_performance_regression")
    if any(item["evidence_state"] != "available" for item in performance["items"]):
        reasons.append("stored_performance_evidence_unavailable")
    if performance["count"] > len(performance["items"]):
        reasons.append("stored_performance_validation_limited")
    if (
        run.run_scope == "impact_selected"
        and sections["impact"]["full_suite_required_count"]
    ):
        reasons.append("required_full_suite_not_observed")
    return reasons


def retained_evidence_references(
    run_id: str, sections: Mapping[str, Any]
) -> dict[str, Any]:
    """References retained in the bounded projection; exporter revalidates each.

    The caller must invoke this after detail trimming. These are selection hints,
    not authorization or evidence-availability certificates.
    """
    evidence_ids: set[str] = set()
    related_run_ids: set[str] = set()
    for item in sections["skipped_tests"]["items"]:
        evidence_ids.update(item["evidence_ids"])
    for item in sections["baseline"]["items"]:
        evidence_ids.update(item["current_evidence_ids"])
        evidence_ids.update(item["supporting_baseline_evidence_ids"])
        if item["supporting_baseline_evidence_ids"]:
            related_run_ids.update(sections["baseline"]["comparable_run_ids"])
        for observation in item["prior_observations"]:
            if observation["evidence_ids"]:
                evidence_ids.update(observation["evidence_ids"])
                related_run_ids.add(observation["run_id"])
    for item in sections["performance"]["items"]:
        if item["current_evidence_id"]:
            evidence_ids.add(item["current_evidence_id"])
        evidence_ids.update(item["baseline_evidence_ids"])
        for member in item["baseline_members"]:
            if member["evidence_id"]:
                evidence_ids.add(member["evidence_id"])
                related_run_ids.add(member["run_id"])
    related_run_ids.discard(run_id)
    return {
        "additional_evidence_ids": sorted(evidence_ids)[:500],
        "allowed_related_run_ids": sorted(related_run_ids)[:100],
        "omitted_evidence_ids": max(0, len(evidence_ids) - 500),
        "omitted_related_run_ids": max(0, len(related_run_ids) - 100),
    }
