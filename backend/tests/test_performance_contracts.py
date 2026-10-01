"""Synthetic performance contracts, separate from frozen diagnostic acceptance.

The original development performance fixtures are also collected here unchanged.
They were already evaluated by the standalone harness; this makes their runtime
branches visible to the canonical backend collector, not new held-out evidence.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from failurelens import models as m
from failurelens import performance
from failurelens.performance import (
    build_observation_dimensions,
    build_performance_baseline,
    canonicalize_value,
    classify_performance_change,
    create_performance_comparison,
    create_performance_policy,
    create_run_performance_comparisons,
    ensure_default_performance_policy,
    evaluate_performance_fixture_case,
    infer_metric_direction,
    register_performance_observation,
)
from failurelens.performance_numeric import (
    PerformanceNumericError,
    finite_mad,
    finite_median,
    ratio,
)
from failurelens.schemas import IngestionRequest, PerformancePolicyCreate
from failurelens.service import create_project, ingest_normalized
from pydantic import ValidationError
from sqlalchemy import inspect, select
from test_performance import _ingest_duration_run

from evaluation.performance_harness import DEFAULT_CASES, load_cases

CURRENT_TIME = datetime(2026, 8, 20, 12, tzinfo=UTC)
INPUT_MODELS = (m.Run, m.PerformanceObservation, m.Evidence, m.PerformancePolicy)
DERIVED_MODELS = (
    m.PerformanceBaselineSnapshot,
    m.PerformanceBaselineMember,
    m.PerformanceComparison,
)


def _durable(factory, models=INPUT_MODELS):
    with factory() as reader:
        return {
            (model.__name__, row.id): json.dumps(
                {
                    column.key: getattr(row, column.key)
                    for column in inspect(model).column_attrs
                },
                sort_keys=True,
                default=str,
            )
            for model in models
            for row in reader.scalars(select(model))
        }


def _metric(session, project, name, *, observed_at=CURRENT_TIME, **changes):
    run, _ = _ingest_duration_run(
        session,
        project,
        external_id=name,
        duration_ms=100,
        observed_at=observed_at,
    )
    run.repository = changes.pop("repository", run.repository)
    run.completeness = changes.pop("completeness", run.completeness)
    trust = changes.pop("trust", None)
    if trust is not None:
        run.source_metadata = {**run.source_metadata, "comparison_trust": trust}
    evidence = session.scalar(select(m.Evidence).where(m.Evidence.run_id == run.id))
    dimensions = build_observation_dimensions(
        run,
        workload="checkout-steady",
        browser=None,
        producer="synthetic-summary",
        producer_version="1",
    )
    dimensions.update(changes.pop("dimensions", {}))
    arguments = {
        "project_id": project.id,
        "run": run,
        "evidence_id": evidence.id,
        "metric_name": "checkout_latency",
        "metric_scope": "k6_summary",
        "statistic": "p95",
        "original_value": 100,
        "original_unit": "ms",
        "sample_count": 100,
        "producer": "synthetic-summary",
        "producer_version": "1",
        "workload": "checkout-steady",
        "dimensions": dimensions,
        "threshold_status": "passed",
        "threshold_details": {},
        "source_digest": evidence.content_digest,
        "source_locator": evidence.locator,
        "direction": "lower_is_better",
        "observed_at": observed_at,
        **changes,
    }
    observation = register_performance_observation(session, **arguments)
    session.commit()
    return run, observation, arguments


def _cohort(session, **policy_changes):
    project = create_project(session, "performance-contracts", "Synthetic cohort")
    policy = create_performance_policy(
        session,
        project,
        PerformancePolicyCreate(
            version="contract-v1",
            required_dimensions=["environment", "load_profile"],
            **policy_changes,
        ),
    )
    _, current, _ = _metric(session, project, "current", original_value=130)
    controls = [
        _metric(
            session,
            project,
            f"control-{index}",
            observed_at=CURRENT_TIME - timedelta(days=index + 1),
            original_value=value,
        )[1]
        for index, value in enumerate((95, 100, 105))
    ]
    return project, policy, current, controls


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"metric_scope": "test_duration"}, "metric_scope_mismatch"),
        ({"statistic": "avg"}, "statistic_mismatch"),
        ({"original_unit": "B"}, "unit_mismatch"),
        ({"direction": "higher_is_better"}, "direction_mismatch"),
        ({"completeness": "partial"}, "baseline_run_incomplete"),
        ({"trust": "self_reported"}, "baseline_run_untrusted"),
        ({"observed_at": CURRENT_TIME - timedelta(days=31)}, "baseline_too_old"),
        ({"repository": "other/project"}, "repository_mismatch"),
        (
            {"dimensions": {"environment": "production"}},
            "dimension_mismatch:environment",
        ),
        ({"dimensions": {"load_profile": "burst"}}, "dimension_mismatch:load_profile"),
    ],
)
def test_incompatible_candidate_cannot_dilute_a_real_regression(
    session, session_factory, changes, reason
):
    project, policy, current, controls = _cohort(session)
    _, rejected, _ = _metric(
        session,
        project,
        "incompatible",
        **{
            "observed_at": CURRENT_TIME - timedelta(hours=1),
            "original_value": 10000,
            **changes,
        },
    )
    inputs = _durable(session_factory)

    comparison = create_performance_comparison(session, current, policy)

    assert comparison.status == "REGRESSION"
    assert comparison.baseline_value == 100
    assert comparison.baseline_run_count == 3
    assert comparison.baseline_sample_count == 300
    baseline = comparison.baseline_snapshot
    assert {member.observation_id for member in baseline.members} == {
        row.id for row in controls
    }
    assert baseline.compatibility["candidate_count"] == 4
    assert baseline.compatibility["rejected_reason_counts"] == {reason: 1}
    assert [
        (row["observation_id"], row["reasons"]) for row in baseline.rejected_candidates
    ] == [(rejected.id, [reason])]
    assert _durable(session_factory) == inputs


@pytest.mark.parametrize(
    "exclusion", ["project", "metric", "workload", "at-cutoff", "future"]
)
def test_candidate_query_excludes_other_populations_before_aggregation(
    session, session_factory, exclusion
):
    project, policy, current, controls = _cohort(session)
    foreign_project = create_project(session, "other-project", "Other project")
    changes = {
        "observed_at": CURRENT_TIME - timedelta(hours=1),
        "original_value": 10000,
    }
    if exclusion == "metric":
        changes["metric_name"] = "unrelated_latency"
    elif exclusion == "workload":
        changes["workload"] = "unrelated-workload"
    elif exclusion in {"at-cutoff", "future"}:
        changes["observed_at"] = CURRENT_TIME + timedelta(days=exclusion == "future")
    _, excluded, _ = _metric(
        session,
        foreign_project if exclusion == "project" else project,
        "excluded",
        **changes,
    )
    inputs = _durable(session_factory)

    comparison = create_performance_comparison(session, current, policy)

    assert comparison.status == "REGRESSION"
    assert comparison.baseline_value == 100
    baseline = comparison.baseline_snapshot
    assert {member.observation_id for member in baseline.members} == {
        row.id for row in controls
    }
    assert excluded.id not in {member.observation_id for member in baseline.members}
    assert baseline.compatibility["candidate_count"] == 3
    assert baseline.rejected_candidates == []
    assert _durable(session_factory) == inputs


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"completeness": "partial"}, "current_run_incomplete"),
        ({"trust": "self_reported"}, "current_run_untrusted"),
    ],
)
def test_incomplete_or_untrusted_current_run_never_gets_reassuring_baseline(
    session, session_factory, changes, reason
):
    project, policy, _, _ = _cohort(session)
    _, current, _ = _metric(
        session, project, "blocked-current", original_value=1, **changes
    )
    inputs = _durable(session_factory)
    comparison = create_performance_comparison(session, current, policy)
    assert comparison.status == "INCOMPATIBLE_BASELINE"
    assert comparison.baseline_value is None
    assert comparison.baseline_run_count == 0
    assert comparison.baseline_evidence_ids == []
    assert comparison.compatibility["current_blockers"] == [reason]
    assert comparison.compatibility["rejected_reason_counts"] == {
        reason: 3,
        "insufficient_baseline_runs": 1,
    }
    assert _durable(session_factory) == inputs


def test_one_run_cannot_count_twice_toward_the_baseline_minimum(
    session, session_factory
):
    project, policy, current, controls = _cohort(session)
    duplicate = register_performance_observation(
        session,
        project_id=project.id,
        run=controls[0].run,
        evidence_id=controls[0].evidence_id,
        metric_name=current.metric_name,
        metric_scope=current.metric_scope,
        statistic=current.statistic,
        original_value=10000,
        original_unit="ms",
        sample_count=9000,
        producer=current.producer,
        producer_version=current.producer_version,
        workload=current.workload,
        dimensions={**controls[0].dimensions, "non_cohort_annotation": "duplicate"},
        threshold_status="passed",
        threshold_details={},
        source_digest=controls[0].source_digest,
        source_locator=controls[0].source_locator,
        direction=current.direction,
        observed_at=controls[0].observed_at - timedelta(seconds=1),
    )
    session.commit()
    inputs = _durable(session_factory)
    comparison = create_performance_comparison(session, current, policy)
    assert comparison.status == "REGRESSION"
    assert comparison.baseline_run_count == 3
    assert comparison.baseline_sample_count == 300
    assert comparison.baseline_value == 100
    assert comparison.compatibility["rejected_reason_counts"] == {
        "duplicate_metric_in_run": 1
    }
    assert (
        comparison.baseline_snapshot.rejected_candidates[0]["observation_id"]
        == duplicate.id
    )
    assert _durable(session_factory) == inputs


def test_rejection_detail_cap_preserves_all_reason_counts_and_valid_members(
    session, session_factory, monkeypatch
):
    project, policy, current, controls = _cohort(session)
    # A smaller boundary exercises truncation without creating hundreds of files.
    # The production default and acceptance configuration remain unchanged.
    monkeypatch.setattr(performance, "MAX_REJECTED_CANDIDATES_RECORDED", 2)
    rejected = [
        _metric(
            session,
            project,
            f"rejected-{index}",
            observed_at=CURRENT_TIME - timedelta(hours=index + 1),
            dimensions={"environment": "incompatible"},
            original_value=10000,
        )[1]
        for index in range(3)
    ]
    inputs = _durable(session_factory)
    comparison = create_performance_comparison(session, current, policy)
    baseline = comparison.baseline_snapshot
    assert comparison.status == "REGRESSION"
    assert comparison.baseline_value == 100
    assert baseline.compatibility["candidate_count"] == 6
    assert baseline.compatibility["accepted_count"] == 3
    assert baseline.compatibility["rejected_reason_counts"] == {
        "dimension_mismatch:environment": 3
    }
    assert baseline.compatibility["rejected_candidates_truncated"] is True
    assert [row["observation_id"] for row in baseline.rejected_candidates] == [
        row.id for row in rejected[:2]
    ]
    assert {member.observation_id for member in baseline.members} == {
        row.id for row in controls
    }
    assert _durable(session_factory) == inputs


def test_newly_available_prior_run_creates_a_new_snapshot_without_rewriting_history(
    session, session_factory
):
    project, policy, current, controls = _cohort(session)
    original = create_performance_comparison(session, current, policy)
    original_state = _durable(session_factory, DERIVED_MODELS)
    _, additional, _ = _metric(
        session,
        project,
        "late-import-of-prior-run",
        observed_at=CURRENT_TIME - timedelta(hours=1),
        original_value=90,
    )
    inputs = _durable(session_factory)
    updated = create_performance_comparison(session, current, policy)
    assert updated.id != original.id
    assert updated.input_digest != original.input_digest
    assert updated.baseline_snapshot_id != original.baseline_snapshot_id
    assert updated.status == "REGRESSION"
    assert updated.baseline_value == 97.5
    assert updated.baseline_run_count == 4
    assert {member.observation_id for member in updated.baseline_snapshot.members} == {
        *(row.id for row in controls),
        additional.id,
    }
    assert create_performance_comparison(session, current, policy).id == updated.id
    after = _durable(session_factory, DERIVED_MODELS)
    assert {key: after[key] for key in original_state} == original_state
    assert _durable(session_factory) == inputs


def test_explicit_untrusted_policy_can_compare_self_reported_measurements(session):
    project, policy, _, _ = _cohort(session, require_trusted=False)
    _, current, _ = _metric(
        session,
        project,
        "self-reported-current",
        trust="self_reported",
        original_value=130,
    )
    _, prior, _ = _metric(
        session,
        project,
        "self-reported-prior",
        observed_at=CURRENT_TIME - timedelta(hours=1),
        trust="self_reported",
        original_value=100,
    )
    comparison = create_performance_comparison(session, current, policy)
    assert comparison.status == "REGRESSION"
    assert comparison.baseline_run_count == 4
    assert comparison.baseline_value == 100
    assert prior.id in {
        member.observation_id for member in comparison.baseline_snapshot.members
    }
    assert comparison.compatibility["current_blockers"] == []
    assert comparison.compatibility["rejected_reason_counts"] == {}


@pytest.mark.parametrize(
    "target",
    [
        "run-policy",
        "observation-policy",
        "baseline-policy",
        "missing-observation",
        "other-run-observation",
        "empty-run",
    ],
)
def test_invalid_comparison_scope_does_not_persist_partial_results(
    session, session_factory, target
):
    project, policy, current, controls = _cohort(session)
    other = create_project(session, "scope-other", "Other project")
    other_policy = create_performance_policy(session, other, PerformancePolicyCreate())
    empty = ingest_normalized(
        session,
        project,
        IngestionRequest.model_validate(
            {
                "external_id": "no-performance-observations",
                "observations": [{"test_identity": "no-duration", "outcome": "passed"}],
            }
        ),
    )
    before = _durable(session_factory, INPUT_MODELS + DERIVED_MODELS)
    if target == "run-policy":
        action = lambda: create_run_performance_comparisons(
            session, current.run, other_policy
        )
        message = "run and performance policy belong to different projects"
    elif target == "observation-policy":
        action = lambda: create_performance_comparison(session, current, other_policy)
        message = "performance observation and policy belong to different projects"
    elif target == "baseline-policy":
        action = lambda: build_performance_baseline(session, current, other_policy)
        message = "performance policy belongs to a different project"
    elif target == "empty-run":
        action = lambda: create_run_performance_comparisons(session, empty, policy)
        message = "run has no normalized performance observations"
    else:
        wrong_id = (
            "missing-observation" if target == "missing-observation" else controls[0].id
        )
        action = lambda: create_run_performance_comparisons(
            session, current.run, policy, observation_ids=[current.id, wrong_id]
        )
        message = "one or more performance observations do not belong to this run"
    with pytest.raises(ValueError, match=message):
        action()
    session.commit()
    assert _durable(session_factory, INPUT_MODELS + DERIVED_MODELS) == before
    control = create_run_performance_comparisons(
        session, current.run, policy, observation_ids=[current.id, current.id]
    )
    assert len(control) == 1
    assert control[0].status == "REGRESSION"


def test_registration_is_idempotent_but_never_overwrites_a_conflicting_measurement(
    session, session_factory
):
    project = create_project(session, "registration", "Registration")
    _, observation, arguments = _metric(session, project, "source")
    before = _durable(session_factory)
    assert register_performance_observation(session, **arguments).id == observation.id
    with pytest.raises(
        ValueError, match="identity already exists with a different value"
    ):
        register_performance_observation(
            session, **{**arguments, "original_value": 101}
        )
    session.commit()
    assert _durable(session_factory) == before


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("sample_count", -1, "sample count cannot be negative"),
        ("direction", "anything", "invalid performance metric direction"),
        ("original_unit", "minutes", "unsupported performance unit conversion"),
    ],
)
def test_invalid_registration_leaves_existing_measurements_intact(
    session, session_factory, field, value, message
):
    project = create_project(session, "invalid-registration", "Invalid registration")
    _, _, arguments = _metric(session, project, "source")
    before = _durable(session_factory)
    with pytest.raises(ValueError, match=message):
        register_performance_observation(
            session, **{**arguments, "metric_name": "new_metric", field: value}
        )
    session.commit()
    assert _durable(session_factory) == before


def test_default_policy_uses_latest_existing_immutable_policy(session, session_factory):
    project = create_project(session, "default-policy", "Default policy")
    first = ensure_default_performance_policy(session, project)
    assert first.version == "performance-policy-v1"
    second = create_performance_policy(
        session,
        project,
        PerformancePolicyCreate(version="new-version", absolute_tolerance=7),
    )
    before = _durable(session_factory)
    assert ensure_default_performance_policy(session, project).id == second.id
    assert _durable(session_factory) == before


@pytest.mark.parametrize(
    ("dimensions", "message"),
    [
        ([" ", "\t"], "at least one compatibility dimension"),
        (["x" * 81], "at most 80 characters"),
    ],
)
def test_policy_rejects_unusable_dimension_names(dimensions, message):
    with pytest.raises(ValidationError, match=message):
        PerformancePolicyCreate(required_dimensions=dimensions)
    assert PerformancePolicyCreate(
        required_dimensions=[" environment ", "environment", "repository"]
    ).required_dimensions == ["environment", "repository"]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"checkout_*": "higher_is_better"}, "IMPROVEMENT"),
        ({"unrelated_*": "higher_is_better"}, "REGRESSION"),
        ({"checkout_*": "neutral"}, "INCONCLUSIVE"),
    ],
)
def test_policy_direction_override_is_explicit_and_metric_scoped(
    session, overrides, expected
):
    _, policy, current, _ = _cohort(session, direction_overrides=overrides)
    comparison = create_performance_comparison(session, current, policy)
    assert comparison.status == expected
    assert comparison.absolute_change == 30
    assert comparison.baseline_value == 100
    assert comparison.uncertainty["significance_claimed"] is False


def test_failed_producer_threshold_remains_visible_without_baseline_attribution(
    session,
):
    project, policy, _, _ = _cohort(session)
    _, current, _ = _metric(
        session,
        project,
        "threshold-failure",
        original_value=100,
        threshold_status="failed",
    )
    comparison = create_performance_comparison(session, current, policy)
    assert comparison.status == "WITHIN_TOLERANCE"
    assert comparison.threshold_status == "failed"
    assert (
        "producer_threshold_failed_without_compatible_regression_attribution"
        in comparison.confounders
    )
    assert comparison.uncertainty["significance_claimed"] is False


@pytest.mark.parametrize(
    ("metric", "statistic", "expected"),
    [
        ("dropped_packets", "count", "lower_is_better"),
        ("errors", "rate", "lower_is_better"),
        ("requests", "rate", "higher_is_better"),
        ("queue_depth", "avg", "neutral"),
    ],
)
def test_direction_inference_preserves_unknown_and_error_semantics(
    metric, statistic, expected
):
    assert (
        infer_metric_direction(metric, metric_scope="k6_summary", statistic=statistic)
        == expected
    )


@pytest.mark.parametrize("invalid", [True, "100", None, float("inf"), float("nan")])
def test_non_numeric_or_nonfinite_values_cannot_be_ratio_inputs(invalid):
    with pytest.raises(PerformanceNumericError):
        ratio(invalid)
    assert ratio(100) == 100


@pytest.mark.parametrize("values", [[], [100, float("inf")], [100, float("nan")]])
def test_missing_or_nonfinite_distribution_has_no_median(values):
    with pytest.raises(PerformanceNumericError):
        finite_median(values)
    assert finite_median([95, 100, 105]) == 100


def test_empty_distribution_has_no_deviation():
    with pytest.raises(PerformanceNumericError):
        finite_mad([], 100)
    assert finite_mad([95, 100, 105], 100) == 5


@pytest.mark.parametrize(("absolute", "relative"), [(-1, 0.1), (1, -0.1)])
def test_negative_tolerance_cannot_classify_a_change(absolute, relative):
    with pytest.raises(PerformanceNumericError):
        classify_performance_change(
            current_value=130,
            baseline_value=100,
            direction="lower_is_better",
            absolute_tolerance=absolute,
            relative_tolerance=relative,
        )


@pytest.mark.parametrize("unit", ["minutes", "milliseconds", "unknown-unit"])
def test_unsupported_units_never_silently_change_scale(unit):
    with pytest.raises(ValueError, match="unsupported performance unit conversion"):
        canonicalize_value(100, unit)
    assert canonicalize_value(0.1, "s") == (100, "ms")


@pytest.mark.parametrize(
    "case", load_cases(DEFAULT_CASES), ids=lambda case: case["case_id"]
)
def test_retained_development_performance_case(case):
    original = deepcopy(case)
    result = evaluate_performance_fixture_case(case)
    assert result["status"] == case["expected_status"]
    assert result["current_evidence_id"] == case["current"]["evidence_id"]
    assert result["aggregation"] == "median_of_run_level_observations"
    assert result["significance_claimed"] is False
    assert len(result["baseline_evidence_ids"]) == len(result["accepted_run_ids"])
    assert all(result["baseline_evidence_ids"])
    assert len(set(result["accepted_run_ids"])) == len(result["accepted_run_ids"])
    assert evaluate_performance_fixture_case(case) == result
    assert case == original
