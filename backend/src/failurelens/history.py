from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from statistics import median
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Analysis,
    Category,
    Failure,
    Outcome,
    ReviewEvent,
    Run,
    TestExecution,
)

HISTORY_POLICY_VERSION = "history-v1"
MIN_RATE_SUPPORT = 3
MIN_FLAKE_HISTORY_RUNS = 5
MAX_HISTORY_EXECUTIONS = 20_000
MAX_HISTORY_RUNS = 20_000
MAX_HISTORY_REVIEWS = 10_000


class _HistoryAttempt(NamedTuple):
    id: str
    browser: str | None
    attempt: int
    outcome: Outcome
    duration_ms: float | None


class _HistoryRun(NamedTuple):
    id: str
    external_id: str
    commit_sha: str | None
    branch: str | None
    environment: str | None
    run_scope: str
    completeness: str
    evidence_expired_at: datetime | None
    timezone: str | None
    worker_count: int | None
    shard_count: int | None
    started_at: datetime | None
    created_at: datetime
    repository: str | None
    framework: str


class _ComparableRun(NamedTuple):
    id: str
    started_at: datetime | None
    created_at: datetime
    repository: str | None
    framework: str
    branch: str | None
    environment: str | None
    run_scope: str
    worker_count: int | None
    shard_count: int | None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _run_timestamp(run: Run | _HistoryRun | _ComparableRun) -> datetime:
    return _as_utc(run.started_at or run.created_at)


def _nullable_equal(column: Any, value: Any) -> Any:
    return column.is_(None) if value is None else column == value


def _canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _logical_test_key(execution: TestExecution, run: Run) -> str:
    return _canonical_digest(
        {
            "project_id": run.project_id,
            "repository": run.repository,
            "framework": run.framework,
            "test_identity": execution.test_identity,
            "suite": execution.suite,
            "source_path": execution.source_path,
            "parameterization": execution.parameterization,
        }
    )


def _normalize_scope(value: str | None) -> str:
    return value if value in {"full_suite", "impact_selected", "unknown"} else "unknown"


def _outcome_counts(values: list[str]) -> dict[str, int]:
    counter = Counter(values)
    return {outcome.value: counter.get(outcome.value, 0) for outcome in Outcome}


def _aggregate_run_outcome(values: list[str]) -> str:
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


def _wilson_interval(numerator: int, denominator: int) -> tuple[float, float] | None:
    if denominator <= 0:
        return None
    z = 1.959963984540054
    proportion = numerator / denominator
    z2 = z * z
    denominator_adjusted = 1 + z2 / denominator
    centre = proportion + z2 / (2 * denominator)
    margin = z * math.sqrt(
        (proportion * (1 - proportion) + z2 / (4 * denominator)) / denominator
    )
    low = max(0.0, (centre - margin) / denominator_adjusted)
    high = min(1.0, (centre + margin) / denominator_adjusted)
    return round(low, 6), round(high, 6)


def _rate(
    *,
    numerator: int,
    denominator: int,
    definition: str,
    minimum_support: int = MIN_RATE_SUPPORT,
) -> dict[str, Any]:
    interval = _wilson_interval(numerator, denominator)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 6) if denominator else None,
        "interval_95": list(interval) if interval is not None else None,
        "status": (
            "available"
            if denominator >= minimum_support
            else "insufficient_data"
            if denominator
            else "unavailable"
        ),
        "minimum_support": minimum_support,
        "definition": definition,
    }


def _time_bucket(value: datetime, timezone_name: str) -> str:
    local = _as_utc(value).astimezone(ZoneInfo(timezone_name))
    if local.hour < 6:
        return "00:00-05:59"
    if local.hour < 12:
        return "06:00-11:59"
    if local.hour < 18:
        return "12:00-17:59"
    return "18:00-23:59"


def _breakdown_rows(
    observations: list[dict[str, Any]], field: str
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        raw = observation.get(field)
        label = "unknown" if raw in {None, ""} else str(raw)
        grouped[label].append(observation)

    rows: list[dict[str, Any]] = []
    for label, items in sorted(grouped.items(), key=lambda pair: pair[0]):
        outcomes = [str(item["final_outcome"]) for item in items]
        counts = _outcome_counts(outcomes)
        pass_fail_denominator = counts[Outcome.passed.value] + counts[Outcome.failed.value]
        rows.append(
            {
                "value": label,
                "sample_size": len(items),
                "outcomes": counts,
                "final_failure_rate": _rate(
                    numerator=counts[Outcome.failed.value],
                    denominator=pass_fail_denominator,
                    definition=(
                        "Final failures divided by final pass/fail observations in this cohort; "
                        "skipped, cancelled and unknown outcomes remain visible but are excluded "
                        "from the rate denominator."
                    ),
                ),
            }
        )
    return rows


def _sequence_summary(observations: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = [
        item
        for item in sorted(
            observations,
            key=lambda value: (value["observed_at"], value["run_id"], value["browser"] or ""),
        )
        if item["final_outcome"] in {Outcome.passed.value, Outcome.failed.value}
    ]
    transitions: Counter[str] = Counter()
    maximum = {Outcome.passed.value: 0, Outcome.failed.value: 0}
    current_outcome: str | None = None
    current_length = 0
    failure_times: list[datetime] = []

    for item in ordered:
        outcome = str(item["final_outcome"])
        if current_outcome is not None:
            transitions[f"{current_outcome}->{outcome}"] += 1
        if outcome == current_outcome:
            current_length += 1
        else:
            current_outcome = outcome
            current_length = 1
        maximum[outcome] = max(maximum[outcome], current_length)
        if outcome == Outcome.failed.value:
            failure_times.append(datetime.fromisoformat(str(item["observed_at"])))

    intervals = [
        (_as_utc(current) - _as_utc(previous)).total_seconds()
        for previous, current in zip(failure_times, failure_times[1:])
    ]
    return {
        "ordered_pass_fail_observations": len(ordered),
        "current_streak": {
            "outcome": current_outcome,
            "length": current_length if current_outcome is not None else 0,
        },
        "maximum_streaks": maximum,
        "transitions": dict(sorted(transitions.items())),
        "failure_recurrence_seconds": {
            "count": len(intervals),
            "minimum": round(min(intervals), 3) if intervals else None,
            "median": round(median(intervals), 3) if intervals else None,
            "maximum": round(max(intervals), 3) if intervals else None,
        },
    }


def _reviewed_known_flake_events(
    session: Session,
    *,
    selected_execution: TestExecution,
    selected_run: Run,
    strict_fingerprint: str | None,
    cutoff: datetime,
    exclude_run_id: str | None,
    browser: str | None,
    match_browser: bool,
    branch: str | None,
    match_branch: bool,
    environment: str | None,
    match_environment: bool,
    run_scope: str | None,
    worker_count: int | None,
    match_worker_count: bool,
    shard_count: int | None,
    match_shard_count: bool,
) -> tuple[list[dict[str, Any]], bool]:
    if strict_fingerprint is None:
        return [], False

    conditions = [
        Run.evidence_expired_at.is_(None),
        Failure.project_id == selected_run.project_id,
        Failure.strict_fingerprint == strict_fingerprint,
        _nullable_equal(Run.repository, selected_run.repository),
        Run.framework == selected_run.framework,
        TestExecution.test_identity == selected_execution.test_identity,
        _nullable_equal(TestExecution.suite, selected_execution.suite),
        _nullable_equal(TestExecution.source_path, selected_execution.source_path),
        _nullable_equal(
            TestExecution.parameterization, selected_execution.parameterization
        ),
        ReviewEvent.created_at < cutoff,
        func.coalesce(Run.started_at, Run.created_at) < cutoff,
        Run.created_at < cutoff,
    ]
    if exclude_run_id:
        conditions.append(Run.id != exclude_run_id)
    if match_branch:
        conditions.append(_nullable_equal(Run.branch, branch))
    if match_environment:
        conditions.append(_nullable_equal(Run.environment, environment))
    if run_scope is not None:
        conditions.append(Run.run_scope == run_scope)
    if match_worker_count:
        conditions.append(_nullable_equal(Run.worker_count, worker_count))
    if match_shard_count:
        conditions.append(_nullable_equal(Run.shard_count, shard_count))
    if match_browser:
        conditions.append(_nullable_equal(TestExecution.browser, browser))

    statement = (
        select(ReviewEvent, Analysis, Failure, TestExecution, Run)
        .join(Analysis, ReviewEvent.analysis_id == Analysis.id)
        .join(Failure, Analysis.failure_id == Failure.id)
        .join(TestExecution, Failure.execution_id == TestExecution.id)
        .join(Run, Failure.run_id == Run.id)
        .where(*conditions)
        .order_by(ReviewEvent.created_at.desc(), ReviewEvent.id.desc())
        .limit(MAX_HISTORY_REVIEWS + 1)
    )
    review_rows = list(session.execute(statement))
    review_truncated = len(review_rows) > MAX_HISTORY_REVIEWS
    latest_by_analysis: dict[
        str, tuple[ReviewEvent, Analysis, Failure, TestExecution, Run]
    ] = {}
    for event, analysis, failure, execution, run in review_rows[:MAX_HISTORY_REVIEWS]:
        if exclude_run_id and run.id == exclude_run_id:
            continue
        if (
            _run_timestamp(run) >= cutoff
            or _as_utc(run.created_at) >= cutoff
            or _as_utc(event.created_at) >= cutoff
        ):
            continue
        if match_branch and run.branch != branch:
            continue
        if match_environment and run.environment != environment:
            continue
        if run_scope is not None and _normalize_scope(run.run_scope) != run_scope:
            continue
        if match_worker_count and run.worker_count != worker_count:
            continue
        if match_shard_count and run.shard_count != shard_count:
            continue
        if match_browser and execution.browser != browser:
            continue
        current = latest_by_analysis.get(analysis.id)
        if current is None or (event.version, _as_utc(event.created_at), event.id) > (
            current[0].version,
            _as_utc(current[0].created_at),
            current[0].id,
        ):
            latest_by_analysis[analysis.id] = (
                event,
                analysis,
                failure,
                execution,
                run,
            )

    events: list[dict[str, Any]] = []
    for event, analysis, failure, execution, run in sorted(
        latest_by_analysis.values(),
        key=lambda item: (_as_utc(item[0].created_at), item[0].id),
    ):
        accepted_existing = (
            event.decision == "accept"
            and analysis.category == Category.known_flake
            and event.proposed_category in {None, Category.known_flake.value}
        )
        corrected = (
            event.decision == "category_correction"
            and event.proposed_category == Category.known_flake.value
        )
        if not (accepted_existing or corrected):
            continue
        events.append(
            {
                "review_event_id": event.id,
                "analysis_id": analysis.id,
                "failure_id": failure.id,
                "execution_id": execution.id,
                "run_id": run.id,
                "decision": event.decision,
                "actor": event.actor,
                "created_at": _as_utc(event.created_at).isoformat(),
            }
        )
    return events, review_truncated


def build_test_history(
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
    observation_limit: int = 200,
    observation_offset: int = 0,
) -> dict[str, Any]:
    """Compute traceable prior-only statistics for one exact logical test identity.

    Retries are collapsed into one run/browser observation. Missing test executions are
    never converted into passes. The cutoff is enforced for runs and review events.
    """

    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {timezone_name}") from exc

    cutoff_utc = _as_utc(cutoff)
    after_utc = _as_utc(after) if after is not None else None
    normalized_scope = _normalize_scope(run_scope) if run_scope is not None else None

    conditions = [
        Run.project_id == selected_run.project_id,
        _nullable_equal(Run.repository, selected_run.repository),
        Run.framework == selected_run.framework,
        TestExecution.test_identity == selected_execution.test_identity,
        _nullable_equal(TestExecution.suite, selected_execution.suite),
        _nullable_equal(TestExecution.source_path, selected_execution.source_path),
        _nullable_equal(
            TestExecution.parameterization, selected_execution.parameterization
        ),
        func.coalesce(Run.started_at, Run.created_at) < cutoff_utc,
        Run.created_at < cutoff_utc,
    ]
    if exclude_run_id is not None:
        conditions.append(Run.id != exclude_run_id)
    if after_utc is not None:
        conditions.append(func.coalesce(Run.started_at, Run.created_at) >= after_utc)
    if match_branch:
        conditions.append(_nullable_equal(Run.branch, branch))
    if match_environment:
        conditions.append(_nullable_equal(Run.environment, environment))
    if normalized_scope is not None:
        conditions.append(Run.run_scope == normalized_scope)
    if match_worker_count:
        conditions.append(_nullable_equal(Run.worker_count, worker_count))
    if match_shard_count:
        conditions.append(_nullable_equal(Run.shard_count, shard_count))
    if match_browser:
        conditions.append(_nullable_equal(TestExecution.browser, browser))

    statement = (
        select(
            TestExecution.id, TestExecution.browser, TestExecution.attempt,
            TestExecution.outcome, TestExecution.duration_ms,
            Run.id, Run.external_id, Run.commit_sha, Run.branch,
            Run.environment, Run.run_scope, Run.completeness, Run.evidence_expired_at,
            Run.timezone, Run.worker_count, Run.shard_count, Run.started_at,
            Run.created_at, Run.repository, Run.framework,
        )
        .select_from(TestExecution)
        .join(Run, TestExecution.run_id == Run.id)
        .where(*conditions)
        .order_by(
            func.coalesce(Run.started_at, Run.created_at),
            Run.id,
            TestExecution.attempt,
            TestExecution.id,
        )
        .limit(MAX_HISTORY_EXECUTIONS + 1)
    )
    raw_rows = [(_HistoryAttempt(*row[:5]), _HistoryRun(*row[5:])) for row in session.execute(statement)]
    truncated = len(raw_rows) > MAX_HISTORY_EXECUTIONS
    raw_rows = raw_rows[:MAX_HISTORY_EXECUTIONS]

    # Scalar row projections avoid hydrating unused JSON bodies and ORM entities.
    grouped: dict[tuple[str, str], list[_HistoryAttempt]] = defaultdict(list)
    runs_by_id: dict[str, _HistoryRun] = {}
    for execution, run in raw_rows:
        observed_at = _run_timestamp(run)
        if exclude_run_id and run.id == exclude_run_id:
            continue
        if observed_at >= cutoff_utc or _as_utc(run.created_at) >= cutoff_utc:
            continue
        if after_utc is not None and observed_at < after_utc:
            continue
        if run.repository != selected_run.repository or run.framework != selected_run.framework:
            continue
        if match_branch and run.branch != branch:
            continue
        if match_environment and run.environment != environment:
            continue
        if normalized_scope is not None and _normalize_scope(run.run_scope) != normalized_scope:
            continue
        if match_worker_count and run.worker_count != worker_count:
            continue
        if match_shard_count and run.shard_count != shard_count:
            continue
        if match_browser and execution.browser != browser:
            continue
        key = (run.id, execution.browser or "")
        grouped[key].append(execution)
        runs_by_id[run.id] = run

    observations: list[dict[str, Any]] = []
    for (run_id, browser_key), attempts in sorted(grouped.items()):
        run = runs_by_id[run_id]
        ordered = sorted(attempts, key=lambda item: (item.attempt, item.id))
        first = ordered[0]
        final = ordered[-1]
        first_outcome = first.outcome.value
        final_outcome = final.outcome.value
        attempt_numbers = [item.attempt for item in ordered]
        retry_recovered = (
            first.outcome is Outcome.failed
            and final.outcome is Outcome.passed
            and len(ordered) > 1
        )
        observed_at = _run_timestamp(run)
        observations.append(
            {
                "run_id": run.id,
                "external_id": run.external_id,
                "commit_sha": run.commit_sha,
                "branch": run.branch,
                "browser": browser_key or None,
                "environment": run.environment,
                "run_scope": _normalize_scope(run.run_scope),
                "run_completeness": "expired" if run.evidence_expired_at else run.completeness,
                "timezone": run.timezone,
                "worker_count": run.worker_count,
                "shard_count": run.shard_count,
                "time_bucket": _time_bucket(observed_at, timezone_name),
                "observed_at": observed_at.isoformat(),
                "first_outcome": first_outcome,
                "final_outcome": final_outcome,
                "attempt_count": len(ordered),
                "attempt_numbers": attempt_numbers,
                "execution_ids": [item.id for item in ordered],
                "first_execution_id": first.id,
                "final_execution_id": final.id,
                "retry_recovered": retry_recovered,
                "duration_ms": final.duration_ms,
                "duplicate_attempt_numbers": len(set(attempt_numbers)) != len(attempt_numbers),
            }
        )

    observations.sort(
        key=lambda item: (item["observed_at"], item["run_id"], item["browser"] or "")
    )

    observations_by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        observations_by_run[str(observation["run_id"])].append(observation)

    run_observations: list[dict[str, Any]] = []
    for run_id, items in observations_by_run.items():
        ordered_items = sorted(items, key=lambda item: (item["browser"] or ""))
        representative = ordered_items[0]
        first_outcome = _aggregate_run_outcome(
            [str(item["first_outcome"]) for item in ordered_items]
        )
        final_outcome = _aggregate_run_outcome(
            [str(item["final_outcome"]) for item in ordered_items]
        )
        run_observations.append(
            {
                **{
                    key: representative[key]
                    for key in (
                        "run_id",
                        "external_id",
                        "commit_sha",
                        "branch",
                        "environment",
                        "run_scope",
                        "run_completeness",
                        "timezone",
                        "worker_count",
                        "shard_count",
                        "time_bucket",
                        "observed_at",
                    )
                },
                "browser": None,
                "browsers": sorted(
                    str(item["browser"])
                    for item in ordered_items
                    if item["browser"] is not None
                ),
                "browser_observation_count": len(ordered_items),
                "first_outcome": first_outcome,
                "final_outcome": final_outcome,
                "retry_recovered": (
                    first_outcome == Outcome.failed.value
                    and final_outcome == Outcome.passed.value
                ),
                "execution_ids": [
                    execution_id
                    for item in ordered_items
                    for execution_id in item["execution_ids"]
                ],
                "duplicate_attempt_numbers": any(
                    bool(item["duplicate_attempt_numbers"]) for item in ordered_items
                ),
            }
        )
    run_observations.sort(key=lambda item: (item["observed_at"], item["run_id"]))

    first_counts = _outcome_counts(
        [str(item["first_outcome"]) for item in run_observations]
    )
    final_counts = _outcome_counts(
        [str(item["final_outcome"]) for item in run_observations]
    )
    pass_fail_denominator = final_counts[Outcome.passed.value] + final_counts[Outcome.failed.value]
    first_pass_fail_denominator = (
        first_counts[Outcome.passed.value] + first_counts[Outcome.failed.value]
    )
    retry_eligible = [
        item
        for item in run_observations
        if item["first_outcome"] == Outcome.failed.value
    ]
    retry_recovered_count = sum(bool(item["retry_recovered"]) for item in retry_eligible)

    comparable_runs_statement = (
        select(Run.id, Run.started_at, Run.created_at, Run.repository, Run.framework,
               Run.branch, Run.environment, Run.run_scope, Run.worker_count, Run.shard_count)
        .where(
            Run.project_id == selected_run.project_id,
            _nullable_equal(Run.repository, selected_run.repository),
            Run.framework == selected_run.framework,
            func.coalesce(Run.started_at, Run.created_at) < cutoff_utc,
            Run.created_at < cutoff_utc,
        )
        .order_by(func.coalesce(Run.started_at, Run.created_at), Run.id)
        .limit(MAX_HISTORY_RUNS + 1)
    )
    comparable_rows = [_ComparableRun(*row) for row in session.execute(comparable_runs_statement)]
    comparable_truncated = len(comparable_rows) > MAX_HISTORY_RUNS
    candidate_run_ids: set[str] = set()
    for run in comparable_rows[:MAX_HISTORY_RUNS]:
        observed_at = _run_timestamp(run)
        if exclude_run_id and run.id == exclude_run_id:
            continue
        if observed_at >= cutoff_utc or _as_utc(run.created_at) >= cutoff_utc:
            continue
        if after_utc is not None and observed_at < after_utc:
            continue
        if run.repository != selected_run.repository or run.framework != selected_run.framework:
            continue
        if match_branch and run.branch != branch:
            continue
        if match_environment and run.environment != environment:
            continue
        if normalized_scope is not None and _normalize_scope(run.run_scope) != normalized_scope:
            continue
        if match_worker_count and run.worker_count != worker_count:
            continue
        if match_shard_count and run.shard_count != shard_count:
            continue
        candidate_run_ids.add(run.id)

    observed_run_ids = {str(item["run_id"]) for item in run_observations}
    reviewed_events, review_truncated = _reviewed_known_flake_events(
        session,
        selected_execution=selected_execution,
        selected_run=selected_run,
        strict_fingerprint=strict_fingerprint,
        cutoff=cutoff_utc,
        exclude_run_id=exclude_run_id,
        browser=browser,
        match_browser=match_browser,
        branch=branch,
        match_branch=match_branch,
        environment=environment,
        match_environment=match_environment,
        run_scope=normalized_scope,
        worker_count=worker_count,
        match_worker_count=match_worker_count,
        shard_count=shard_count,
        match_shard_count=match_shard_count,
    )

    incomplete_count = sum(
        item["run_completeness"] != "complete" for item in run_observations
    )
    selected_subset_count = sum(
        item["run_scope"] == "impact_selected" for item in run_observations
    )
    unknown_scope_count = sum(
        item["run_scope"] == "unknown" for item in run_observations
    )
    duplicate_attempt_count = sum(
        bool(item["duplicate_attempt_numbers"]) for item in run_observations
    )

    insufficient_reasons: list[str] = []
    if not observations:
        insufficient_reasons.append("no_prior_matching_observations")
    if len(observed_run_ids) < MIN_FLAKE_HISTORY_RUNS:
        insufficient_reasons.append("fewer_than_five_prior_independent_runs")
    if pass_fail_denominator < MIN_FLAKE_HISTORY_RUNS:
        insufficient_reasons.append("fewer_than_five_prior_pass_fail_observations")
    if final_counts[Outcome.passed.value] == 0:
        insufficient_reasons.append("no_prior_pass_observation")
    if final_counts[Outcome.failed.value] == 0:
        insufficient_reasons.append("no_prior_failure_observation")
    if selected_subset_count:
        insufficient_reasons.append("impact_selected_history_has_selection_bias")
    if unknown_scope_count:
        insufficient_reasons.append("run_scope_unknown")
    if incomplete_count:
        insufficient_reasons.append("incomplete_run_history")
    if duplicate_attempt_count:
        insufficient_reasons.append("duplicate_attempt_numbers_present")
    if truncated:
        insufficient_reasons.append("history_execution_limit_reached")
    if comparable_truncated:
        insufficient_reasons.append("history_run_limit_reached")
    if review_truncated:
        insufficient_reasons.append("history_review_limit_reached")
    if not reviewed_events:
        insufficient_reasons.append("no_prior_reviewed_known_flake_decision")

    history_eligible = not insufficient_reasons
    rate_status = (
        "no_data"
        if not observations
        else "available"
        if pass_fail_denominator >= MIN_RATE_SUPPORT
        else "insufficient_data"
    )

    breakdowns = {
        "browser": _breakdown_rows(observations, "browser"),
        **{
            field: _breakdown_rows(run_observations, field)
            for field in (
                "branch",
                "environment",
                "run_scope",
                "worker_count",
                "shard_count",
                "time_bucket",
            )
        },
    }
    sequence = _sequence_summary(run_observations)
    digest_payload = {
        "policy_version": HISTORY_POLICY_VERSION,
        "logical_test_key": _logical_test_key(selected_execution, selected_run),
        "cutoff": cutoff_utc.isoformat(),
        "after": after_utc.isoformat() if after_utc else None,
        "filters": {
            "browser": browser if match_browser else None,
            "browser_match": match_browser,
            "branch": branch if match_branch else None,
            "branch_match": match_branch,
            "environment": environment if match_environment else None,
            "environment_match": match_environment,
            "run_scope": normalized_scope,
            "worker_count": worker_count if match_worker_count else None,
            "worker_count_match": match_worker_count,
            "shard_count": shard_count if match_shard_count else None,
            "shard_count_match": match_shard_count,
            "timezone": timezone_name,
        },
        "observations": [
            {
                "run_id": item["run_id"],
                "execution_ids": item["execution_ids"],
                "first_outcome": item["first_outcome"],
                "final_outcome": item["final_outcome"],
                "run_scope": item["run_scope"],
                "run_completeness": item["run_completeness"],
                "observed_at": item["observed_at"],
            }
            for item in observations
        ],
        "run_outcomes": [
            {
                "run_id": item["run_id"],
                "execution_ids": item["execution_ids"],
                "browsers": item["browsers"],
                "first_outcome": item["first_outcome"],
                "final_outcome": item["final_outcome"],
                "run_scope": item["run_scope"],
                "run_completeness": item["run_completeness"],
                "observed_at": item["observed_at"],
            }
            for item in run_observations
        ],
        "review_event_ids": [item["review_event_id"] for item in reviewed_events],
        "comparable_run_ids": sorted(candidate_run_ids),
        "insufficient_data_reasons": sorted(set(insufficient_reasons)),
        "execution_truncated": truncated,
        "comparable_runs_truncated": comparable_truncated,
        "reviews_truncated": review_truncated,
    }
    history_digest = _canonical_digest(digest_payload)

    paged_observations = observations[
        observation_offset : observation_offset + observation_limit
    ]
    return {
        "policy_version": HISTORY_POLICY_VERSION,
        "history_input_digest": history_digest,
        "status": rate_status,
        "logical_test": {
            "key": _logical_test_key(selected_execution, selected_run),
            "project_id": selected_run.project_id,
            "repository": selected_run.repository,
            "framework": selected_run.framework,
            "test_identity": selected_execution.test_identity,
            "suite": selected_execution.suite,
            "source_path": selected_execution.source_path,
            "parameterization": selected_execution.parameterization,
        },
        "window": {
            "after": after_utc.isoformat() if after_utc else None,
            "before": cutoff_utc.isoformat(),
            "timezone": timezone_name,
            "prior_only": True,
            "excluded_run_id": exclude_run_id,
        },
        "filters": {
            "browser": browser if match_browser else None,
            "browser_match": match_browser,
            "branch": branch if match_branch else None,
            "branch_match": match_branch,
            "environment": environment if match_environment else None,
            "environment_match": match_environment,
            "run_scope": normalized_scope,
            "worker_count": worker_count if match_worker_count else None,
            "worker_count_match": match_worker_count,
            "shard_count": shard_count if match_shard_count else None,
            "shard_count_match": match_shard_count,
        },
        "sample_sizes": {
            "independent_observations": len(observations),
            "independent_runs": len(run_observations),
            "comparable_project_runs": len(candidate_run_ids),
            "runs_without_matching_test_observation": len(
                candidate_run_ids - observed_run_ids
            ),
            "pass_fail_denominator": pass_fail_denominator,
            "first_attempt_pass_fail_denominator": first_pass_fail_denominator,
            "retry_eligible_first_failures": len(retry_eligible),
            "incomplete_runs": incomplete_count,
            "impact_selected_observations": selected_subset_count,
            "unknown_scope_observations": unknown_scope_count,
            "skipped": final_counts[Outcome.skipped.value],
            "cancelled": final_counts[Outcome.cancelled.value],
            "unknown": final_counts[Outcome.unknown.value],
        },
        "outcomes": {
            "first_attempt": first_counts,
            "final": final_counts,
        },
        "rates": {
            "observed_pass_rate": _rate(
                numerator=final_counts[Outcome.passed.value],
                denominator=pass_fail_denominator,
                definition=(
                    "Independent runs whose conservative final outcome passed divided by "
                    "independent runs whose final outcome was pass or fail. Retries are collapsed "
                    "within each browser, then browser outcomes are collapsed per run with any "
                    "failure taking precedence."
                ),
            ),
            "first_attempt_failure_rate": _rate(
                numerator=first_counts[Outcome.failed.value],
                denominator=first_pass_fail_denominator,
                definition=(
                    "Independent runs whose conservative first-attempt outcome failed divided "
                    "by independent runs whose first-attempt outcome was pass or fail."
                ),
            ),
            "final_failure_rate": _rate(
                numerator=final_counts[Outcome.failed.value],
                denominator=pass_fail_denominator,
                definition=(
                    "Independent runs whose conservative final outcome failed divided by "
                    "independent runs whose final outcome was pass or fail."
                ),
            ),
            "retry_recovery_rate": _rate(
                numerator=retry_recovered_count,
                denominator=len(retry_eligible),
                definition=(
                    "Independent runs whose conservative first-attempt outcome failed and "
                    "final outcome passed divided by all independent runs whose first-attempt "
                    "outcome failed."
                ),
            ),
        },
        "breakdowns": breakdowns,
        "sequences": sequence,
        "review": {
            "reviewed_known_flake": bool(reviewed_events),
            "events": reviewed_events,
        },
        "safety": {
            "history_eligible_for_reassurance": history_eligible,
            "insufficient_data_reasons": sorted(set(insufficient_reasons)),
            "selection_bias_present": bool(selected_subset_count),
            "truncated": truncated or comparable_truncated or review_truncated,
            "notes": [
                "Overall rates use one conservative outcome per independent run; browser "
                "breakdowns use run/browser cohorts.",
                "Retries are not counted as independent runs.",
                "Runs without a matching test observation are not counted as passes.",
                "Review decisions and runs at or after the cutoff are excluded.",
                "Breakdown rates are associations and do not establish causation.",
            ],
        },
        "pagination": {
            "offset": observation_offset,
            "limit": observation_limit,
            "returned": len(paged_observations),
            "total": len(observations),
        },
        "observations": paged_observations,
    }


def history_context_for_failure(session: Session, failure: Failure) -> dict[str, Any]:
    """Return the conservative prior-only context used by deterministic analysis."""

    report = build_test_history(
        session,
        selected_execution=failure.execution,
        selected_run=failure.run,
        cutoff=_run_timestamp(failure.run),
        browser=failure.execution.browser,
        match_browser=True,
        branch=failure.run.branch,
        match_branch=True,
        environment=failure.run.environment,
        match_environment=True,
        run_scope="full_suite",
        worker_count=failure.run.worker_count,
        match_worker_count=True,
        shard_count=failure.run.shard_count,
        match_shard_count=True,
        timezone_name=failure.run.timezone or "UTC",
        exclude_run_id=failure.run_id,
        strict_fingerprint=failure.strict_fingerprint,
        observation_limit=0,
        observation_offset=0,
    )
    retry_rate = report["rates"]["retry_recovery_rate"]["value"]
    final_counts = report["outcomes"]["final"]
    return {
        "policy_version": HISTORY_POLICY_VERSION,
        "history_input_digest": report["history_input_digest"],
        "history_cutoff": report["window"]["before"],
        "independent_runs": report["sample_sizes"]["independent_runs"],
        "independent_observations": report["sample_sizes"][
            "independent_observations"
        ],
        "observed_passes": final_counts[Outcome.passed.value],
        "observed_failures": final_counts[Outcome.failed.value],
        "reviewed_known_flake": report["review"]["reviewed_known_flake"],
        "review_event_ids": [
            item["review_event_id"] for item in report["review"]["events"]
        ],
        "retry_recovery_rate": float(retry_rate or 0.0),
        "history_eligible_for_reassurance": report["safety"][
            "history_eligible_for_reassurance"
        ],
        "insufficient_data_reasons": report["safety"][
            "insufficient_data_reasons"
        ],
        "cohort": {
            "browser": failure.execution.browser,
            "branch": failure.run.branch,
            "environment": failure.run.environment,
            "run_scope": "full_suite",
            "worker_count": failure.run.worker_count,
            "shard_count": failure.run.shard_count,
        },
    }
