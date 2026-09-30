from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatchcase
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .models import (
    PerformanceBaselineMember,
    PerformanceBaselineSnapshot,
    PerformanceComparison,
    PerformanceObservation,
    PerformancePolicy,
    Project,
    Run,
)
from .schemas import (
    PerformanceBaselineMemberRead,
    PerformanceBaselineRead,
    PerformanceComparisonRead,
    PerformanceObservationRead,
    PerformancePolicyCreate,
    PerformancePolicyRead,
)

PERFORMANCE_ENGINE_VERSION = "performance-engine-v1"
DEFAULT_PERFORMANCE_POLICY_VERSION = "performance-policy-v1"
TRUSTED_COMPARISON_SOURCES = {"authenticated_lookup", "trusted_workflow"}
DEFAULT_REQUIRED_DIMENSIONS = (
    "repository",
    "workload",
    "environment",
    "browser",
    "run_scope",
    "producer",
    "producer_version",
    "load_profile",
    "region",
    "executor",
)
MAX_BASELINE_CANDIDATES = 10_000
MAX_REJECTED_CANDIDATES_RECORDED = 250

_EXPLICIT_UNIT_CONVERSIONS: dict[tuple[str, str], float] = {
    ("ns", "ms"): 0.000001,
    ("us", "ms"): 0.001,
    ("µs", "ms"): 0.001,
    ("ms", "ms"): 1.0,
    ("s", "ms"): 1000.0,
    ("B", "B"): 1.0,
    ("KB", "B"): 1000.0,
    ("MB", "B"): 1_000_000.0,
    ("GB", "B"): 1_000_000_000.0,
    ("KiB", "B"): 1024.0,
    ("MiB", "B"): 1_048_576.0,
    ("GiB", "B"): 1_073_741_824.0,
    ("count", "count"): 1.0,
    ("ratio", "ratio"): 1.0,
    ("percent", "ratio"): 0.01,
    ("requests/s", "requests/s"): 1.0,
    ("iterations/s", "iterations/s"): 1.0,
    ("events/s", "events/s"): 1.0,
    ("unknown", "unknown"): 1.0,
}


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _safe_dimension_value(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str):
            return value[:512]
        return value
    return str(value)[:512]


def normalize_dimensions(dimensions: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key)[:80]: _safe_dimension_value(value)
        for key, value in sorted(dimensions.items())
    }


def canonicalize_value(value: float, unit: str) -> tuple[float, str]:
    if not math.isfinite(value):
        raise ValueError("performance values must be finite")
    normalized = unit.strip() or "unknown"
    canonical = (
        "ms"
        if normalized in {"ns", "us", "µs", "ms", "s"}
        else (
            "B"
            if normalized in {"B", "KB", "MB", "GB", "KiB", "MiB", "GiB"}
            else ("ratio" if normalized in {"ratio", "percent"} else normalized)
        )
    )
    factor = _EXPLICIT_UNIT_CONVERSIONS.get((normalized, canonical))
    if factor is None:
        raise ValueError(
            f"unsupported performance unit conversion: {normalized} -> {canonical}"
        )
    return value * factor, canonical


def infer_metric_direction(
    metric_name: str,
    *,
    metric_scope: str,
    statistic: str,
    contains: str | None = None,
) -> str:
    lowered = metric_name.casefold()
    if (
        metric_scope == "test_duration"
        or contains == "time"
        or "duration" in lowered
        or "latency" in lowered
    ):
        return "lower_is_better"
    if any(token in lowered for token in ("error", "fail", "dropped", "timeout")):
        return "lower_is_better"
    if any(
        token in lowered
        for token in ("throughput", "requests_per_second", "iterations_per_second")
    ):
        return "higher_is_better"
    if statistic in {"rate", "throughput"} and any(
        token in lowered for token in ("http_reqs", "iterations", "requests")
    ):
        return "higher_is_better"
    return "neutral"


def build_observation_dimensions(
    run: Run,
    *,
    workload: str,
    browser: str | None,
    producer: str,
    producer_version: str | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = run.source_metadata or {}
    dimensions: dict[str, Any] = {
        "repository": run.repository,
        "workload": workload,
        "environment": run.environment,
        "browser": browser,
        "run_scope": run.run_scope,
        "producer": producer,
        "producer_version": producer_version,
        "load_profile": metadata.get("load_profile")
        or metadata.get("workload_profile"),
        "region": metadata.get("region"),
        "executor": metadata.get("executor") or metadata.get("runner"),
        "framework": run.framework,
        "worker_count": run.worker_count,
        "shard_count": run.shard_count,
    }
    if extra:
        dimensions.update(extra)
    return normalize_dimensions(dimensions)


def register_performance_observation(
    session: Session,
    *,
    project_id: str,
    run: Run,
    evidence_id: str,
    metric_name: str,
    metric_scope: str,
    statistic: str,
    original_value: float,
    original_unit: str,
    sample_count: int | None,
    producer: str,
    producer_version: str | None,
    workload: str,
    dimensions: dict[str, Any],
    threshold_status: str,
    threshold_details: dict[str, Any],
    source_digest: str,
    source_locator: dict[str, Any],
    run_input_id: str | None = None,
    execution_id: str | None = None,
    direction: str | None = None,
    observed_at: datetime | None = None,
) -> PerformanceObservation:
    if sample_count is not None and sample_count < 0:
        raise ValueError("performance sample count cannot be negative")
    canonical_value, canonical_unit = canonicalize_value(
        float(original_value), original_unit
    )
    normalized_dimensions = normalize_dimensions(dimensions)
    resolved_direction = direction or infer_metric_direction(
        metric_name,
        metric_scope=metric_scope,
        statistic=statistic,
        contains=str(normalized_dimensions.get("contains") or "") or None,
    )
    if resolved_direction not in {"lower_is_better", "higher_is_better", "neutral"}:
        raise ValueError("invalid performance metric direction")
    metric_identity = {
        "metric_name": metric_name,
        "metric_scope": metric_scope,
        "statistic": statistic,
        "canonical_unit": canonical_unit,
        "workload": workload,
        "dimensions": normalized_dimensions,
    }
    metric_key = _canonical_digest(metric_identity)
    existing = session.scalar(
        select(PerformanceObservation).where(
            PerformanceObservation.run_id == run.id,
            PerformanceObservation.metric_key == metric_key,
        )
    )
    if existing is not None:
        if not math.isclose(
            existing.canonical_value, canonical_value, rel_tol=0, abs_tol=1e-12
        ):
            raise ValueError(
                "performance observation identity already exists with a different value"
            )
        return existing
    row = PerformanceObservation(
        project_id=project_id,
        run_id=run.id,
        run_input_id=run_input_id,
        execution_id=execution_id,
        evidence_id=evidence_id,
        metric_key=metric_key,
        metric_name=metric_name[:240],
        metric_scope=metric_scope[:40],
        statistic=statistic[:80],
        direction=resolved_direction,
        original_value=float(original_value),
        original_unit=original_unit[:40],
        canonical_value=canonical_value,
        canonical_unit=canonical_unit[:40],
        sample_count=sample_count,
        producer=producer[:120],
        producer_version=producer_version[:80] if producer_version else None,
        workload=workload[:512],
        dimension_signature=_canonical_digest(normalized_dimensions),
        dimensions=normalized_dimensions,
        threshold_status=threshold_status[:40],
        threshold_details=threshold_details,
        source_digest=source_digest,
        source_locator=source_locator,
        observed_at=_utc(
            observed_at or run.ended_at or run.started_at or run.created_at
        ),
    )
    session.add(row)
    session.flush()
    return row


def _validate_policy_content(
    existing: PerformancePolicy, request: PerformancePolicyCreate
) -> None:
    existing_payload = {
        "version": existing.version,
        "relative_tolerance": existing.relative_tolerance,
        "absolute_tolerance": existing.absolute_tolerance,
        "min_baseline_runs": existing.min_baseline_runs,
        "max_baseline_age_days": existing.max_baseline_age_days,
        "require_trusted": existing.require_trusted,
        "required_dimensions": existing.required_dimensions,
        "direction_overrides": existing.direction_overrides,
    }
    if _canonical_digest(existing_payload) != _canonical_digest(
        request.model_dump(mode="json")
    ):
        raise ValueError(
            "performance policy version already exists with different immutable content"
        )


def create_performance_policy(
    session: Session,
    project: Project,
    request: PerformancePolicyCreate,
) -> PerformancePolicy:
    existing = session.scalar(
        select(PerformancePolicy).where(
            PerformancePolicy.project_id == project.id,
            PerformancePolicy.version == request.version,
        )
    )
    if existing is not None:
        _validate_policy_content(existing, request)
        return existing
    row = PerformancePolicy(
        project_id=project.id,
        version=request.version,
        relative_tolerance=request.relative_tolerance,
        absolute_tolerance=request.absolute_tolerance,
        min_baseline_runs=request.min_baseline_runs,
        max_baseline_age_days=request.max_baseline_age_days,
        require_trusted=request.require_trusted,
        required_dimensions=request.required_dimensions,
        direction_overrides=request.direction_overrides,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(PerformancePolicy).where(
                PerformancePolicy.project_id == project.id,
                PerformancePolicy.version == request.version,
            )
        )
        if existing is not None:
            _validate_policy_content(existing, request)
            return existing
        raise
    session.refresh(row)
    return row


def ensure_default_performance_policy(
    session: Session, project: Project
) -> PerformancePolicy:
    existing = session.scalar(
        select(PerformancePolicy)
        .where(PerformancePolicy.project_id == project.id)
        .order_by(PerformancePolicy.created_at.desc())
    )
    if existing is not None:
        return existing
    return create_performance_policy(
        session,
        project,
        PerformancePolicyCreate(
            version=DEFAULT_PERFORMANCE_POLICY_VERSION,
            required_dimensions=list(DEFAULT_REQUIRED_DIMENSIONS),
        ),
    )


def list_performance_policies(
    session: Session, project_id: str, *, limit: int = 100, offset: int = 0
) -> list[PerformancePolicy]:
    return list(
        session.scalars(
            select(PerformancePolicy)
            .where(PerformancePolicy.project_id == project_id)
            .order_by(PerformancePolicy.created_at.desc(), PerformancePolicy.id)
            .limit(limit)
            .offset(offset)
        ).all()
    )


def _comparison_trust(run: Run) -> str:
    return str((run.source_metadata or {}).get("comparison_trust") or "self_reported")


def _candidate_reasons(
    current: PerformanceObservation,
    current_run: Run,
    candidate: PerformanceObservation,
    candidate_run: Run,
    policy: PerformancePolicy,
    cutoff: datetime,
) -> list[str]:
    reasons: list[str] = []
    if candidate.metric_scope != current.metric_scope:
        reasons.append("metric_scope_mismatch")
    if candidate.statistic != current.statistic:
        reasons.append("statistic_mismatch")
    if candidate.canonical_unit != current.canonical_unit:
        reasons.append("unit_mismatch")
    if candidate.direction != current.direction:
        reasons.append("direction_mismatch")
    if candidate.observed_at is None or _utc(candidate.observed_at) >= cutoff:
        reasons.append("not_prior_to_current_run")
    if candidate_run.completeness != "complete":
        reasons.append("baseline_run_incomplete")
    if (
        policy.require_trusted
        and _comparison_trust(candidate_run) not in TRUSTED_COMPARISON_SOURCES
    ):
        reasons.append("baseline_run_untrusted")
    age = cutoff - _utc(candidate.observed_at)
    if age > timedelta(days=policy.max_baseline_age_days):
        reasons.append("baseline_too_old")
    for dimension in policy.required_dimensions:
        if current.dimensions.get(dimension) != candidate.dimensions.get(dimension):
            reasons.append(f"dimension_mismatch:{dimension}")
    if current_run.repository != candidate_run.repository:
        reasons.append("repository_mismatch")
    if not candidate.evidence_id:
        reasons.append("baseline_evidence_missing")
    return sorted(set(reasons))


def _baseline_options():
    return (
        selectinload(PerformanceBaselineSnapshot.current_observation).selectinload(
            PerformanceObservation.run
        ),
        selectinload(PerformanceBaselineSnapshot.policy),
        selectinload(PerformanceBaselineSnapshot.members)
        .selectinload(PerformanceBaselineMember.observation)
        .selectinload(PerformanceObservation.run),
    )


def _comparison_options():
    return (
        selectinload(PerformanceComparison.current_observation).selectinload(
            PerformanceObservation.run
        ),
        selectinload(PerformanceComparison.policy),
        selectinload(PerformanceComparison.baseline_snapshot)
        .selectinload(PerformanceBaselineSnapshot.members)
        .selectinload(PerformanceBaselineMember.observation)
        .selectinload(PerformanceObservation.run),
        selectinload(PerformanceComparison.baseline_snapshot).selectinload(
            PerformanceBaselineSnapshot.policy
        ),
        selectinload(PerformanceComparison.baseline_snapshot).selectinload(
            PerformanceBaselineSnapshot.current_observation
        ),
    )


def get_performance_baseline(
    session: Session, baseline_id: str
) -> PerformanceBaselineSnapshot | None:
    return session.scalar(
        select(PerformanceBaselineSnapshot)
        .where(PerformanceBaselineSnapshot.id == baseline_id)
        .options(*_baseline_options())
    )


def build_performance_baseline(
    session: Session,
    current: PerformanceObservation,
    policy: PerformancePolicy,
    *,
    commit: bool = True,
) -> PerformanceBaselineSnapshot:
    current_run = session.get(Run, current.run_id)
    if current_run is None:
        raise ValueError("current performance run not found")
    if current.project_id != policy.project_id:
        raise ValueError("performance policy belongs to a different project")
    cutoff = _utc(current_run.started_at or current_run.created_at)
    current_blockers: list[str] = []
    if current_run.completeness != "complete":
        current_blockers.append("current_run_incomplete")
    if (
        policy.require_trusted
        and _comparison_trust(current_run) not in TRUSTED_COMPARISON_SOURCES
    ):
        current_blockers.append("current_run_untrusted")
    if not current.evidence_id:
        current_blockers.append("current_evidence_missing")

    candidates = list(
        session.scalars(
            select(PerformanceObservation)
            .where(
                PerformanceObservation.project_id == current.project_id,
                PerformanceObservation.run_id != current.run_id,
                PerformanceObservation.metric_name == current.metric_name,
                PerformanceObservation.workload == current.workload,
                PerformanceObservation.observed_at < cutoff,
            )
            .options(selectinload(PerformanceObservation.run))
            .order_by(
                PerformanceObservation.observed_at.desc(), PerformanceObservation.id
            )
            .limit(MAX_BASELINE_CANDIDATES)
        ).all()
    )

    accepted: list[PerformanceObservation] = []
    rejected: list[dict[str, Any]] = []
    seen_runs: set[str] = set()
    reason_counts: Counter[str] = Counter()
    for candidate in candidates:
        candidate_run = candidate.run
        reasons = _candidate_reasons(
            current, current_run, candidate, candidate_run, policy, cutoff
        )
        if candidate.run_id in seen_runs:
            reasons.append("duplicate_metric_in_run")
        if reasons or current_blockers:
            all_reasons = sorted({*reasons, *current_blockers})
            reason_counts.update(all_reasons)
            if len(rejected) < MAX_REJECTED_CANDIDATES_RECORDED:
                rejected.append(
                    {
                        "observation_id": candidate.id,
                        "run_id": candidate.run_id,
                        "external_id": candidate_run.external_id,
                        "observed_at": _utc(candidate.observed_at).isoformat(),
                        "reasons": all_reasons,
                    }
                )
            continue
        accepted.append(candidate)
        seen_runs.add(candidate.run_id)

    if current_blockers:
        status = "INCOMPATIBLE_BASELINE"
    elif len(accepted) >= policy.min_baseline_runs:
        status = "AVAILABLE"
    elif candidates:
        status = "BASELINE_UNAVAILABLE" if accepted else "INCOMPATIBLE_BASELINE"
    else:
        status = "BASELINE_UNAVAILABLE"

    if len(accepted) < policy.min_baseline_runs:
        reason_counts["insufficient_baseline_runs"] += 1
    values = [item.canonical_value for item in accepted]
    usable = status == "AVAILABLE"
    baseline_value = statistics.median(values) if usable else None
    baseline_min = min(values) if usable else None
    baseline_max = max(values) if usable else None
    baseline_mad = (
        statistics.median(abs(value - baseline_value) for value in values)
        if usable and baseline_value is not None
        else None
    )
    newest = max((_utc(item.observed_at) for item in accepted), default=None)
    baseline_age_seconds = (cutoff - newest).total_seconds() if newest else None
    sample_count = sum(item.sample_count or 0 for item in accepted)
    cohort_dimensions = {
        key: current.dimensions.get(key) for key in policy.required_dimensions
    }
    compatibility = {
        "policy_version": policy.version,
        "required_dimensions": list(policy.required_dimensions),
        "candidate_count": len(candidates),
        "accepted_count": len(accepted),
        "minimum_baseline_runs": policy.min_baseline_runs,
        "current_blockers": current_blockers,
        "rejected_reason_counts": dict(sorted(reason_counts.items())),
        "rejected_candidates_truncated": len(rejected)
        < len(candidates) - len(accepted),
        "prior_only_cutoff": cutoff.isoformat(),
        "unit_conversion": "explicit_lossless_only",
    }
    digest_payload = {
        "schema_version": "performance-baseline-v1",
        "current_observation_id": current.id,
        "current_metric_key": current.metric_key,
        "policy_id": policy.id,
        "policy_version": policy.version,
        "cutoff": cutoff.isoformat(),
        "accepted_observation_ids": [item.id for item in accepted],
        "status": status,
        "compatibility": compatibility,
    }
    input_digest = _canonical_digest(digest_payload)
    existing = session.scalar(
        select(PerformanceBaselineSnapshot)
        .where(
            PerformanceBaselineSnapshot.project_id == current.project_id,
            PerformanceBaselineSnapshot.input_digest == input_digest,
        )
        .options(*_baseline_options())
    )
    if existing is not None:
        return existing

    snapshot = PerformanceBaselineSnapshot(
        project_id=current.project_id,
        current_run_id=current.run_id,
        current_observation_id=current.id,
        policy_id=policy.id,
        input_digest=input_digest,
        status=status,
        cutoff_at=cutoff,
        cohort_dimensions=cohort_dimensions,
        compatibility=compatibility,
        rejected_candidates=rejected,
        run_count=len(accepted),
        sample_count=sample_count,
        baseline_value=baseline_value,
        baseline_min=baseline_min,
        baseline_max=baseline_max,
        baseline_mad=baseline_mad,
        baseline_age_seconds=baseline_age_seconds,
        aggregation="median_of_run_level_observations",
    )
    session.add(snapshot)
    session.flush()
    for position, observation in enumerate(
        sorted(accepted, key=lambda item: (_utc(item.observed_at), item.id)), start=1
    ):
        session.add(
            PerformanceBaselineMember(
                snapshot_id=snapshot.id,
                observation_id=observation.id,
                run_id=observation.run_id,
                position=position,
            )
        )
    if commit:
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = session.scalar(
                select(PerformanceBaselineSnapshot)
                .where(
                    PerformanceBaselineSnapshot.project_id == current.project_id,
                    PerformanceBaselineSnapshot.input_digest == input_digest,
                )
                .options(*_baseline_options())
            )
            if existing is not None:
                return existing
            raise
        return get_performance_baseline(session, snapshot.id) or snapshot
    session.flush()
    return snapshot


def _policy_direction(
    policy: PerformancePolicy, observation: PerformanceObservation
) -> str:
    for pattern, direction in sorted(policy.direction_overrides.items()):
        if fnmatchcase(observation.metric_name, pattern):
            return direction
    return observation.direction


class PerformanceChange(TypedDict):
    status: str
    absolute_change: float
    relative_change: float | None
    allowed_absolute_change: float


def classify_performance_change(
    *,
    current_value: float,
    baseline_value: float,
    direction: str,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> PerformanceChange:
    delta = current_value - baseline_value
    relative = delta / abs(baseline_value) if baseline_value != 0 else None
    allowed = max(absolute_tolerance, abs(baseline_value) * relative_tolerance)
    if direction == "lower_is_better":
        status = (
            "REGRESSION"
            if delta > allowed
            else ("IMPROVEMENT" if delta < -allowed else "WITHIN_TOLERANCE")
        )
    elif direction == "higher_is_better":
        status = (
            "REGRESSION"
            if delta < -allowed
            else ("IMPROVEMENT" if delta > allowed else "WITHIN_TOLERANCE")
        )
    else:
        status = "INCONCLUSIVE"
    return {
        "status": status,
        "absolute_change": delta,
        "relative_change": relative,
        "allowed_absolute_change": allowed,
    }


def _next_measurement(
    status: str,
    current: PerformanceObservation,
    baseline: PerformanceBaselineSnapshot,
) -> str:
    if status in {"BASELINE_UNAVAILABLE", "INCOMPATIBLE_BASELINE"}:
        reasons = baseline.compatibility.get("rejected_reason_counts", {})
        if "baseline_too_old" in reasons:
            return "Run the same trusted workload on the current executor at least three times to establish a fresh compatible baseline."
        return "Repeat the identical trusted workload with matching environment, producer version, load profile and units until the policy minimum baseline-run count is met."
    if status == "INCONCLUSIVE":
        return "Capture repeated raw samples for the same workload and metric direction; do not infer significance from one exported summary pair."
    if current.statistic.startswith("p") and current.statistic[1:].isdigit():
        return "Repeat the identical workload and retain raw trend samples; this finding compares run-level percentiles and is not an aggregate percentile."
    if status == "REGRESSION":
        return "Repeat the identical workload on the same executor and inspect the cited current and baseline evidence before attributing the change."
    return "Continue collecting compatible repeated measurements so future comparisons retain an auditable baseline distribution."


def create_performance_comparison(
    session: Session,
    current: PerformanceObservation,
    policy: PerformancePolicy,
    *,
    commit: bool = True,
) -> PerformanceComparison:
    if current.project_id != policy.project_id:
        raise ValueError(
            "performance observation and policy belong to different projects"
        )
    baseline = build_performance_baseline(session, current, policy, commit=False)
    direction = _policy_direction(policy, current)
    status = baseline.status
    absolute_change: float | None = None
    relative_change: float | None = None
    allowed_absolute_change = policy.absolute_tolerance
    effect_size: float | None = None
    if baseline.status == "AVAILABLE" and baseline.baseline_value is not None:
        classified = classify_performance_change(
            current_value=current.canonical_value,
            baseline_value=baseline.baseline_value,
            direction=direction,
            absolute_tolerance=policy.absolute_tolerance,
            relative_tolerance=policy.relative_tolerance,
        )
        status = str(classified["status"])
        absolute_change = float(classified["absolute_change"])
        relative_change = (
            float(classified["relative_change"])
            if classified["relative_change"] is not None
            else None
        )
        allowed_absolute_change = float(classified["allowed_absolute_change"])
        if (
            baseline.baseline_mad
            and baseline.baseline_mad > 0
            and baseline.run_count >= 3
        ):
            effect_size = absolute_change / (1.4826 * baseline.baseline_mad)

    confounders: list[str] = []
    if current.statistic.startswith("p") and current.statistic[1:].isdigit():
        confounders.append("run_level_percentiles_are_not_an_aggregate_percentile")
    if current.sample_count is None:
        confounders.append("current_sample_count_unavailable")
    if baseline.sample_count == 0:
        confounders.append("baseline_sample_counts_unavailable")
    if baseline.baseline_value == 0:
        confounders.append("relative_change_unavailable_for_zero_baseline")
    if current.threshold_status == "failed" and status != "REGRESSION":
        confounders.append(
            "producer_threshold_failed_without_compatible_regression_attribution"
        )
    if current.threshold_status == "passed" and status == "REGRESSION":
        confounders.append(
            "producer_threshold_passed_but_baseline_policy_detected_regression"
        )
    confounders.append("no_statistical_significance_claim_from_single_current_summary")

    uncertainty = {
        "method": "compatible_prior_run_distribution",
        "baseline_aggregation": baseline.aggregation,
        "baseline_min": baseline.baseline_min,
        "baseline_max": baseline.baseline_max,
        "baseline_mad": baseline.baseline_mad,
        "robust_standardized_change": effect_size,
        "significance_claimed": False,
        "note": (
            "The baseline is the median of compatible run-level observations. "
            "Exported percentiles are never averaged or presented as an aggregate percentile."
        ),
    }
    baseline_evidence_ids = [
        member.observation.evidence_id for member in baseline.members
    ]
    summary = (
        f"{current.metric_name} {current.statistic}: {status}. Current "
        f"{current.canonical_value:.6g} {current.canonical_unit}; "
        + (
            f"compatible baseline {baseline.baseline_value:.6g} {current.canonical_unit} "
            f"from {baseline.run_count} prior run(s)."
            if baseline.baseline_value is not None
            else f"no usable compatible baseline ({baseline.status})."
        )
    )
    input_payload = {
        "schema_version": "performance-comparison-v1",
        "engine_version": PERFORMANCE_ENGINE_VERSION,
        "current_observation_id": current.id,
        "current_metric_key": current.metric_key,
        "current_value": current.canonical_value,
        "baseline_input_digest": baseline.input_digest,
        "policy_id": policy.id,
        "policy_version": policy.version,
        "direction": direction,
    }
    input_digest = _canonical_digest(input_payload)
    existing = session.scalar(
        select(PerformanceComparison)
        .where(
            PerformanceComparison.project_id == current.project_id,
            PerformanceComparison.input_digest == input_digest,
        )
        .options(*_comparison_options())
    )
    if existing is not None:
        return existing

    row = PerformanceComparison(
        project_id=current.project_id,
        current_run_id=current.run_id,
        current_observation_id=current.id,
        baseline_snapshot_id=baseline.id,
        policy_id=policy.id,
        engine_version=PERFORMANCE_ENGINE_VERSION,
        input_digest=input_digest,
        status=status,
        current_value=current.canonical_value,
        baseline_value=baseline.baseline_value,
        absolute_change=absolute_change,
        relative_change=relative_change,
        allowed_absolute_change=allowed_absolute_change,
        allowed_relative_change=policy.relative_tolerance,
        current_sample_count=current.sample_count,
        baseline_run_count=baseline.run_count,
        baseline_sample_count=baseline.sample_count,
        threshold_status=current.threshold_status,
        effect_size=effect_size,
        uncertainty=uncertainty,
        compatibility=baseline.compatibility,
        confounders=sorted(set(confounders)),
        current_evidence_id=current.evidence_id,
        baseline_evidence_ids=baseline_evidence_ids,
        next_measurement=_next_measurement(status, current, baseline),
        summary=summary,
    )
    session.add(row)
    if commit:
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = session.scalar(
                select(PerformanceComparison)
                .where(
                    PerformanceComparison.project_id == current.project_id,
                    PerformanceComparison.input_digest == input_digest,
                )
                .options(*_comparison_options())
            )
            if existing is not None:
                return existing
            raise
        return get_performance_comparison(session, row.id) or row
    session.flush()
    return row


def create_run_performance_comparisons(
    session: Session,
    run: Run,
    policy: PerformancePolicy,
    *,
    observation_ids: Iterable[str] = (),
) -> list[PerformanceComparison]:
    if run.project_id != policy.project_id:
        raise ValueError("run and performance policy belong to different projects")
    requested = list(dict.fromkeys(observation_ids))
    query = select(PerformanceObservation).where(
        PerformanceObservation.run_id == run.id,
        PerformanceObservation.project_id == run.project_id,
    )
    if requested:
        query = query.where(PerformanceObservation.id.in_(requested))
    observations = list(
        session.scalars(
            query.order_by(
                PerformanceObservation.metric_name, PerformanceObservation.statistic
            )
        ).all()
    )
    if requested and {item.id for item in observations} != set(requested):
        raise ValueError(
            "one or more performance observations do not belong to this run"
        )
    if not observations:
        raise ValueError("run has no normalized performance observations")
    rows: list[PerformanceComparison] = []
    for observation in observations:
        rows.append(
            create_performance_comparison(session, observation, policy, commit=False)
        )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise
    return [get_performance_comparison(session, row.id) or row for row in rows]


def list_run_performance_observations(
    session: Session, run_id: str, *, limit: int = 5000, offset: int = 0
) -> list[PerformanceObservation]:
    return list(
        session.scalars(
            select(PerformanceObservation)
            .where(PerformanceObservation.run_id == run_id)
            .order_by(
                PerformanceObservation.metric_name,
                PerformanceObservation.statistic,
                PerformanceObservation.id,
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )


def get_performance_comparison(
    session: Session, comparison_id: str
) -> PerformanceComparison | None:
    return session.scalar(
        select(PerformanceComparison)
        .where(PerformanceComparison.id == comparison_id)
        .options(*_comparison_options())
    )


def list_run_performance_comparisons(
    session: Session, run_id: str, *, limit: int = 5000, offset: int = 0
) -> list[PerformanceComparison]:
    return list(
        session.scalars(
            select(PerformanceComparison)
            .where(PerformanceComparison.current_run_id == run_id)
            .options(*_comparison_options())
            .order_by(PerformanceComparison.created_at.desc(), PerformanceComparison.id)
            .limit(limit)
            .offset(offset)
        ).all()
    )


def performance_policy_to_schema(row: PerformancePolicy) -> PerformancePolicyRead:
    return PerformancePolicyRead.model_validate(
        {
            "id": row.id,
            "project_id": row.project_id,
            "version": row.version,
            "relative_tolerance": row.relative_tolerance,
            "absolute_tolerance": row.absolute_tolerance,
            "min_baseline_runs": row.min_baseline_runs,
            "max_baseline_age_days": row.max_baseline_age_days,
            "require_trusted": row.require_trusted,
            "required_dimensions": row.required_dimensions,
            "direction_overrides": row.direction_overrides,
            "created_at": row.created_at,
        }
    )


def performance_observation_to_schema(
    row: PerformanceObservation,
) -> PerformanceObservationRead:
    return PerformanceObservationRead(
        id=row.id,
        project_id=row.project_id,
        run_id=row.run_id,
        run_input_id=row.run_input_id,
        execution_id=row.execution_id,
        evidence_id=row.evidence_id,
        metric_key=row.metric_key,
        metric_name=row.metric_name,
        metric_scope=row.metric_scope,
        statistic=row.statistic,
        direction=row.direction,
        original_value=row.original_value,
        original_unit=row.original_unit,
        canonical_value=row.canonical_value,
        canonical_unit=row.canonical_unit,
        sample_count=row.sample_count,
        producer=row.producer,
        producer_version=row.producer_version,
        workload=row.workload,
        dimension_signature=row.dimension_signature,
        dimensions=row.dimensions,
        threshold_status=row.threshold_status,
        threshold_details=row.threshold_details,
        source_digest=row.source_digest,
        source_locator=row.source_locator,
        observed_at=row.observed_at,
        created_at=row.created_at,
    )


def performance_baseline_to_schema(
    row: PerformanceBaselineSnapshot,
) -> PerformanceBaselineRead:
    members = sorted(row.members, key=lambda item: (item.position, item.id))
    return PerformanceBaselineRead(
        id=row.id,
        project_id=row.project_id,
        current_run_id=row.current_run_id,
        current_observation_id=row.current_observation_id,
        policy_id=row.policy_id,
        input_digest=row.input_digest,
        status=row.status,
        cutoff_at=row.cutoff_at,
        cohort_dimensions=row.cohort_dimensions,
        compatibility=row.compatibility,
        rejected_candidates=row.rejected_candidates,
        run_count=row.run_count,
        sample_count=row.sample_count,
        baseline_value=row.baseline_value,
        baseline_min=row.baseline_min,
        baseline_max=row.baseline_max,
        baseline_mad=row.baseline_mad,
        baseline_age_seconds=row.baseline_age_seconds,
        aggregation=row.aggregation,
        members=[
            PerformanceBaselineMemberRead(
                observation_id=item.observation_id,
                run_id=item.run_id,
                evidence_id=item.observation.evidence_id,
                external_id=item.observation.run.external_id,
                commit_sha=item.observation.run.commit_sha,
                observed_at=item.observation.observed_at,
                canonical_value=item.observation.canonical_value,
                canonical_unit=item.observation.canonical_unit,
                sample_count=item.observation.sample_count,
                position=item.position,
            )
            for item in members
        ],
        created_at=row.created_at,
    )


def performance_comparison_to_schema(
    row: PerformanceComparison,
) -> PerformanceComparisonRead:
    observation = row.current_observation
    return PerformanceComparisonRead(
        id=row.id,
        project_id=row.project_id,
        current_run_id=row.current_run_id,
        current_observation_id=row.current_observation_id,
        baseline_snapshot_id=row.baseline_snapshot_id,
        policy_id=row.policy_id,
        engine_version=row.engine_version,
        input_digest=row.input_digest,
        status=row.status,
        metric_name=observation.metric_name,
        metric_scope=observation.metric_scope,
        statistic=observation.statistic,
        direction=_policy_direction(row.policy, observation),
        workload=observation.workload,
        canonical_unit=observation.canonical_unit,
        current_value=row.current_value,
        baseline_value=row.baseline_value,
        absolute_change=row.absolute_change,
        relative_change=row.relative_change,
        allowed_absolute_change=row.allowed_absolute_change,
        allowed_relative_change=row.allowed_relative_change,
        current_sample_count=row.current_sample_count,
        baseline_run_count=row.baseline_run_count,
        baseline_sample_count=row.baseline_sample_count,
        threshold_status=row.threshold_status,
        effect_size=row.effect_size,
        uncertainty=row.uncertainty,
        compatibility=row.compatibility,
        confounders=row.confounders,
        current_evidence_id=row.current_evidence_id,
        baseline_evidence_ids=row.baseline_evidence_ids,
        next_measurement=row.next_measurement,
        summary=row.summary,
        baseline=performance_baseline_to_schema(row.baseline_snapshot),
        created_at=row.created_at,
    )


def evaluate_performance_fixture_case(case: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a controlled performance fixture with the runtime policy semantics.

    This compact entry point keeps evaluation labels outside the application data
    path while reusing the same tolerance classification and compatibility rules.
    """

    current = dict(case["current"])
    policy = dict(case["policy"])
    required_dimensions = list(
        policy.get("required_dimensions", DEFAULT_REQUIRED_DIMENSIONS)
    )
    current_blockers: list[str] = []
    if current.get("completeness") != "complete":
        current_blockers.append("current_run_incomplete")
    if (
        policy.get("require_trusted", True)
        and current.get("trust") not in TRUSTED_COMPARISON_SOURCES
    ):
        current_blockers.append("current_run_untrusted")
    if not current.get("evidence_id"):
        current_blockers.append("current_evidence_missing")

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_runs: set[str] = set()
    for candidate in case.get("baselines", []):
        reasons: list[str] = []
        if candidate.get("project") != current.get("project"):
            reasons.append("project_mismatch")
        if candidate.get("repository") != current.get("repository"):
            reasons.append("repository_mismatch")
        if candidate.get("metric_scope") != current.get("metric_scope"):
            reasons.append("metric_scope_mismatch")
        if candidate.get("metric_name") != current.get("metric_name"):
            reasons.append("metric_name_mismatch")
        if candidate.get("statistic") != current.get("statistic"):
            reasons.append("statistic_mismatch")
        try:
            candidate_value, candidate_unit = canonicalize_value(
                float(candidate["value"]), str(candidate["unit"])
            )
            current_value, current_unit = canonicalize_value(
                float(current["value"]), str(current["unit"])
            )
        except (KeyError, TypeError, ValueError) as exc:
            reasons.append(f"unit_conversion_error:{type(exc).__name__}")
            candidate_value = None
            candidate_unit = None
            current_value = None
            current_unit = None
        if candidate_unit != current_unit:
            reasons.append("unit_mismatch")
        if candidate.get("workload") != current.get("workload"):
            reasons.append("dimension_mismatch:workload")
        if candidate.get("completeness") != "complete":
            reasons.append("baseline_run_incomplete")
        if (
            policy.get("require_trusted", True)
            and candidate.get("trust") not in TRUSTED_COMPARISON_SOURCES
        ):
            reasons.append("baseline_run_untrusted")
        if not candidate.get("prior", True):
            reasons.append("not_prior_to_current_run")
        if float(candidate.get("age_days", 0)) > float(
            policy.get("max_baseline_age_days", 30)
        ):
            reasons.append("baseline_too_old")
        current_dimensions = dict(current.get("dimensions", {}))
        candidate_dimensions = dict(candidate.get("dimensions", {}))
        for dimension in required_dimensions:
            current_dimension = (
                current.get(dimension)
                if dimension in current
                else current_dimensions.get(dimension)
            )
            candidate_dimension = (
                candidate.get(dimension)
                if dimension in candidate
                else candidate_dimensions.get(dimension)
            )
            if current_dimension != candidate_dimension:
                reasons.append(f"dimension_mismatch:{dimension}")
        run_id = str(candidate.get("run_id"))
        if run_id in seen_runs:
            reasons.append("duplicate_metric_in_run")
        if not candidate.get("evidence_id"):
            reasons.append("baseline_evidence_missing")
        all_reasons = sorted({*reasons, *current_blockers})
        if all_reasons:
            rejected.append({"run_id": run_id, "reasons": all_reasons})
        else:
            accepted.append(
                {
                    **candidate,
                    "canonical_value": candidate_value,
                    "canonical_unit": candidate_unit,
                }
            )
            seen_runs.add(run_id)

    minimum = int(policy.get("min_baseline_runs", 3))
    values = [float(item["canonical_value"]) for item in accepted]
    current_value, current_unit = canonicalize_value(
        float(current["value"]), str(current["unit"])
    )
    baseline_value: float | None = None
    classified: PerformanceChange | None = None
    if current_blockers:
        status = "INCOMPATIBLE_BASELINE"
    elif len(accepted) >= minimum:
        baseline_value = statistics.median(values)
        classified = classify_performance_change(
            current_value=current_value,
            baseline_value=baseline_value,
            direction=str(current.get("direction", "neutral")),
            absolute_tolerance=float(policy.get("absolute_tolerance", 0)),
            relative_tolerance=float(policy.get("relative_tolerance", 0.1)),
        )
        status = str(classified["status"])
    else:
        status = (
            "INCOMPATIBLE_BASELINE"
            if case.get("baselines") and not accepted
            else "BASELINE_UNAVAILABLE"
        )
    return {
        "case_id": case["case_id"],
        "status": status,
        "accepted_run_ids": [str(item.get("run_id")) for item in accepted],
        "rejected": rejected,
        "baseline_value": baseline_value,
        "canonical_unit": current_unit,
        "absolute_change": classified["absolute_change"] if classified else None,
        "relative_change": classified["relative_change"] if classified else None,
        "allowed_absolute_change": (
            classified["allowed_absolute_change"]
            if classified
            else float(policy.get("absolute_tolerance", 0))
        ),
        "aggregation": "median_of_run_level_observations",
        "significance_claimed": False,
        "current_evidence_id": current.get("evidence_id"),
        "baseline_evidence_ids": [item.get("evidence_id") for item in accepted],
    }
