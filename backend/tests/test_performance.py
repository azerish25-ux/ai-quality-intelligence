from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from failurelens.config import get_settings
from failurelens.ingestion import parse_artifact
from failurelens.models import Evidence, PerformanceObservation, Project, Run
from failurelens.performance import (
    build_observation_dimensions,
    classify_performance_change,
    create_performance_policy,
    create_run_performance_comparisons,
    performance_comparison_to_schema,
    register_performance_observation,
)
from failurelens.schemas import (
    IngestionRequest,
    PerformancePolicyCreate,
    RunMetadata,
)
from failurelens.schemas import (
    TestObservation as ObservationInput,
)
from failurelens.service import create_project, ingest_normalized, ingest_parsed_report
from sqlalchemy import select


def _ingest_duration_run(
    session,
    project: Project,
    *,
    external_id: str,
    duration_ms: float,
    observed_at: datetime,
    environment: str = "ci-linux",
    trust: str = "trusted_workflow",
    test_identity: str = "tests/performance.spec.ts::checkout latency",
) -> tuple[Run, PerformanceObservation]:
    run = ingest_normalized(
        session,
        project,
        IngestionRequest(
            external_id=external_id,
            repository="example/ledgerguard",
            commit_sha=(external_id.encode().hex() + "0" * 40)[:40],
            branch="main",
            run_scope="full_suite",
            comparison_trust=trust,
            environment=environment,
            timezone="UTC",
            worker_count=2,
            shard_count=1,
            source_metadata={
                "load_profile": "steady-10-vus-60s",
                "region": "ca-central-1",
                "executor": "ubuntu-24.04-x64",
            },
            observations=[
                ObservationInput(
                    test_identity=test_identity,
                    suite="performance",
                    browser="chromium",
                    attempt=0,
                    outcome="passed",
                    duration_ms=duration_ms,
                    details={"producer": "playwright", "producer_version": "1.55"},
                )
            ],
        ),
    )
    run.started_at = observed_at
    run.ended_at = observed_at + timedelta(seconds=1)
    run.created_at = observed_at
    observation = session.scalar(
        select(PerformanceObservation).where(PerformanceObservation.run_id == run.id)
    )
    assert observation is not None
    observation.observed_at = observed_at
    session.commit()
    session.refresh(run)
    session.refresh(observation)
    return run, observation


def _register_k6_like_metric(
    session,
    run: Run,
    *,
    value: float,
    observed_at: datetime,
    statistic: str = "p95",
    metric_name: str = "http_req_duration",
) -> PerformanceObservation:
    evidence = session.scalar(select(Evidence).where(Evidence.run_id == run.id))
    assert evidence is not None
    dimensions = build_observation_dimensions(
        run,
        workload="checkout-steady",
        browser=None,
        producer="k6-handleSummary",
        producer_version="0.54.0",
        extra={
            "contains": "time",
            "metric_type": "trend",
            "load_profile": "steady-10-vus-60s",
        },
    )
    row = register_performance_observation(
        session,
        project_id=run.project_id,
        run=run,
        evidence_id=evidence.id,
        metric_name=metric_name,
        metric_scope="k6_summary",
        statistic=statistic,
        original_value=value,
        original_unit="ms",
        sample_count=600,
        producer="k6-handleSummary",
        producer_version="0.54.0",
        workload="checkout-steady",
        dimensions=dimensions,
        threshold_status="passed",
        threshold_details={"thresholds": {"p(95)<250": True}},
        source_digest=evidence.content_digest,
        source_locator=evidence.locator,
        direction="lower_is_better",
        observed_at=observed_at,
    )
    session.commit()
    session.refresh(row)
    return row


def _strict_policy(session, project: Project, *, version: str = "perf-v1"):
    return create_performance_policy(
        session,
        project,
        PerformancePolicyCreate(
            version=version,
            relative_tolerance=0.10,
            absolute_tolerance=5.0,
            min_baseline_runs=3,
            max_baseline_age_days=30,
            require_trusted=True,
        ),
    )


def test_normalized_ingestion_persists_final_duration_with_evidence(session):
    project = create_project(session, "perf-ingestion", "Performance ingestion")
    run = ingest_normalized(
        session,
        project,
        IngestionRequest(
            external_id="retry-duration",
            repository="example/ledgerguard",
            run_scope="full_suite",
            comparison_trust="trusted_workflow",
            environment="ci-linux",
            timezone="UTC",
            source_metadata={
                "load_profile": "steady",
                "executor": "runner-a",
                "region": "ca",
            },
            observations=[
                ObservationInput(
                    test_identity="tests/perf.spec.ts::latency",
                    browser="chromium",
                    attempt=0,
                    outcome="failed",
                    duration_ms=150,
                    message="timeout",
                ),
                ObservationInput(
                    test_identity="tests/perf.spec.ts::latency",
                    browser="chromium",
                    attempt=1,
                    outcome="passed",
                    duration_ms=110,
                ),
            ],
        ),
    )
    rows = list(
        session.scalars(
            select(PerformanceObservation).where(
                PerformanceObservation.run_id == run.id
            )
        ).all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.original_value == 110
    assert row.statistic == "duration"
    assert row.canonical_unit == "ms"
    assert row.execution_id is not None
    assert session.get(Evidence, row.evidence_id) is not None


def test_k6_summary_persists_bounded_metric_values_and_safe_evidence(session):
    project = create_project(session, "perf-k6", "k6 performance")
    content = json.dumps(
        {
            "metrics": {
                "http_req_duration": {
                    "type": "trend",
                    "contains": "time",
                    "values": {"avg": 101.5, "med": 95.0, "p(95)": 210.0, "count": 600},
                    "thresholds": {"p(95)<250": {"ok": True}},
                },
                "http_reqs": {
                    "type": "counter",
                    "contains": "default",
                    "values": {"count": 600, "rate": 10.0},
                    "thresholds": {},
                },
            },
            "state": {"testRunDurationMs": 60000},
        }
    ).encode()
    parsed = parse_artifact(
        content,
        "summary.json",
        get_settings(),
        source_format="k6-summary-json",
        media_type="application/json",
    )
    digest = hashlib.sha256(content).hexdigest()
    run = ingest_parsed_report(
        session,
        project,
        RunMetadata(
            external_id="k6-run-1",
            repository="example/ledgerguard",
            commit_sha="1" * 40,
            branch="main",
            run_scope="full_suite",
            comparison_trust="trusted_workflow",
            environment="ci-linux",
            timezone="UTC",
            source_metadata={
                "workload": "checkout-steady",
                "load_profile": "steady-10-vus-60s",
                "executor": "ubuntu-24.04-x64",
                "region": "ca-central-1",
                "k6_version": "0.54.0",
            },
        ),
        parsed.observations,
        source_name="summary.json",
        source_digest=digest,
        source_size_bytes=len(content),
        storage_path=f"test://{digest}",
        media_type="application/json",
        source_format=parsed.source_format,
        parser_version=parsed.parser_version,
        parser_warnings=parsed.warnings,
        input_records=parsed.inputs,
        parsed_expected_inputs=parsed.expected_inputs,
        parsed_received_inputs=parsed.received_inputs,
        parsed_completeness=parsed.completeness,
        manifest_version=parsed.manifest_version,
        restricted=False,
    )
    rows = list(
        session.scalars(
            select(PerformanceObservation)
            .where(PerformanceObservation.run_id == run.id)
            .order_by(
                PerformanceObservation.metric_name, PerformanceObservation.statistic
            )
        ).all()
    )
    assert {(row.metric_name, row.statistic, row.canonical_unit) for row in rows} == {
        ("http_req_duration", "avg", "ms"),
        ("http_req_duration", "count", "count"),
        ("http_req_duration", "median", "ms"),
        ("http_req_duration", "p95", "ms"),
        ("http_reqs", "count", "count"),
        ("http_reqs", "rate", "requests/s"),
    }
    p95 = next(
        row
        for row in rows
        if row.metric_name == "http_req_duration" and row.statistic == "p95"
    )
    evidence = session.get(Evidence, p95.evidence_id)
    assert evidence is not None
    assert evidence.kind == "performance_metric_observation"
    assert evidence.locator["source"]["pointer"].endswith(
        "/metrics/http_req_duration/values/p(95)"
    )
    assert p95.threshold_status == "passed"


def test_compatible_prior_baseline_detects_regression_and_is_idempotent(session):
    project = create_project(session, "perf-regression", "Regression project")
    policy = _strict_policy(session, project)
    start = datetime(2026, 8, 1, 12, tzinfo=UTC)
    for index, value in enumerate((100.0, 105.0, 95.0)):
        _ingest_duration_run(
            session,
            project,
            external_id=f"baseline-{index}",
            duration_ms=value,
            observed_at=start + timedelta(days=index),
        )
    current_run, current_observation = _ingest_duration_run(
        session,
        project,
        external_id="current",
        duration_ms=130.0,
        observed_at=start + timedelta(days=4),
    )

    rows = create_run_performance_comparisons(
        session, current_run, policy, observation_ids=[current_observation.id]
    )
    assert len(rows) == 1
    comparison = rows[0]
    assert comparison.status == "REGRESSION"
    assert comparison.baseline_value == 100.0
    assert comparison.absolute_change == 30.0
    assert comparison.relative_change == pytest.approx(0.30)
    assert comparison.baseline_run_count == 3
    assert len(comparison.baseline_evidence_ids) == 3
    assert comparison.current_evidence_id == current_observation.evidence_id
    assert comparison.uncertainty["significance_claimed"] is False

    replay = create_run_performance_comparisons(
        session, current_run, policy, observation_ids=[current_observation.id]
    )
    assert replay[0].id == comparison.id
    schema = performance_comparison_to_schema(replay[0])
    assert schema.baseline.aggregation == "median_of_run_level_observations"
    assert [member.canonical_value for member in schema.baseline.members] == [
        100.0,
        105.0,
        95.0,
    ]


def test_incompatible_environment_cannot_form_reassuring_baseline(session):
    project = create_project(session, "perf-incompatible", "Incompatible baseline")
    policy = _strict_policy(session, project)
    start = datetime(2026, 8, 10, 12, tzinfo=UTC)
    for index in range(3):
        _ingest_duration_run(
            session,
            project,
            external_id=f"staging-{index}",
            duration_ms=100 + index,
            observed_at=start + timedelta(days=index),
            environment="staging",
        )
    current_run, current_observation = _ingest_duration_run(
        session,
        project,
        external_id="production-current",
        duration_ms=80,
        observed_at=start + timedelta(days=4),
        environment="production",
    )
    comparison = create_run_performance_comparisons(
        session, current_run, policy, observation_ids=[current_observation.id]
    )[0]
    assert comparison.status == "INCOMPATIBLE_BASELINE"
    assert comparison.baseline_value is None
    assert comparison.relative_change is None
    assert (
        comparison.compatibility["rejected_reason_counts"][
            "dimension_mismatch:environment"
        ]
        == 3
    )
    assert "no usable compatible baseline" in comparison.summary


def test_untrusted_and_future_runs_never_enter_prior_baseline(session):
    project = create_project(session, "perf-prior-only", "Prior-only baseline")
    policy = _strict_policy(session, project)
    start = datetime(2026, 8, 20, 12, tzinfo=UTC)
    current_run, current_observation = _ingest_duration_run(
        session,
        project,
        external_id="current-first",
        duration_ms=100,
        observed_at=start,
    )
    for index in range(3):
        _ingest_duration_run(
            session,
            project,
            external_id=f"future-{index}",
            duration_ms=200,
            observed_at=start + timedelta(days=index + 1),
        )
    comparison = create_run_performance_comparisons(
        session, current_run, policy, observation_ids=[current_observation.id]
    )[0]
    assert comparison.status == "BASELINE_UNAVAILABLE"
    assert comparison.baseline_run_count == 0

    untrusted_run, untrusted_observation = _ingest_duration_run(
        session,
        project,
        external_id="untrusted-current",
        duration_ms=90,
        observed_at=start + timedelta(days=10),
        trust="self_reported",
    )
    untrusted = create_run_performance_comparisons(
        session, untrusted_run, policy, observation_ids=[untrusted_observation.id]
    )[0]
    assert untrusted.status == "INCOMPATIBLE_BASELINE"
    assert "current_run_untrusted" in untrusted.compatibility["current_blockers"]


def test_run_level_p95_uses_median_and_never_claims_aggregate_percentile(session):
    project = create_project(session, "perf-percentile", "Percentile safety")
    policy = _strict_policy(session, project)
    start = datetime(2026, 7, 1, 12, tzinfo=UTC)
    for index, value in enumerate((90.0, 100.0, 120.0)):
        run, _ = _ingest_duration_run(
            session,
            project,
            external_id=f"p95-base-{index}",
            duration_ms=10,
            observed_at=start + timedelta(days=index),
        )
        _register_k6_like_metric(
            session, run, value=value, observed_at=start + timedelta(days=index)
        )
    current_run, _ = _ingest_duration_run(
        session,
        project,
        external_id="p95-current",
        duration_ms=10,
        observed_at=start + timedelta(days=4),
    )
    current = _register_k6_like_metric(
        session, current_run, value=135.0, observed_at=start + timedelta(days=4)
    )
    comparison = create_run_performance_comparisons(
        session, current_run, policy, observation_ids=[current.id]
    )[0]
    assert comparison.status == "REGRESSION"
    assert comparison.baseline_value == 100.0
    assert comparison.baseline_snapshot.baseline_mad == 10.0
    assert (
        "run_level_percentiles_are_not_an_aggregate_percentile"
        in comparison.confounders
    )
    assert "never averaged" in comparison.uncertainty["note"]


def test_classification_handles_direction_tolerance_and_zero_baseline():
    lower = classify_performance_change(
        current_value=120,
        baseline_value=100,
        direction="lower_is_better",
        absolute_tolerance=5,
        relative_tolerance=0.10,
    )
    assert lower["status"] == "REGRESSION"
    higher = classify_performance_change(
        current_value=80,
        baseline_value=100,
        direction="higher_is_better",
        absolute_tolerance=5,
        relative_tolerance=0.10,
    )
    assert higher["status"] == "REGRESSION"
    zero = classify_performance_change(
        current_value=1,
        baseline_value=0,
        direction="lower_is_better",
        absolute_tolerance=2,
        relative_tolerance=0.10,
    )
    assert zero["status"] == "WITHIN_TOLERANCE"
    assert zero["relative_change"] is None


def test_performance_api_exposes_policies_observations_baselines_and_comparisons(
    client, session
):
    project = create_project(session, "perf-api", "Performance API")
    start = datetime(2026, 6, 1, 12, tzinfo=UTC)
    for index, value in enumerate((100.0, 101.0, 99.0)):
        _ingest_duration_run(
            session,
            project,
            external_id=f"api-base-{index}",
            duration_ms=value,
            observed_at=start + timedelta(days=index),
        )
    current_run, current_observation = _ingest_duration_run(
        session,
        project,
        external_id="api-current",
        duration_ms=125.0,
        observed_at=start + timedelta(days=4),
    )

    policy_response = client.post(
        f"/api/v1/projects/{project.id}/performance-policies",
        json={
            "version": "api-policy-v1",
            "relative_tolerance": 0.1,
            "absolute_tolerance": 5,
            "min_baseline_runs": 3,
            "max_baseline_age_days": 30,
            "require_trusted": True,
            "required_dimensions": [
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
            ],
            "direction_overrides": {},
        },
    )
    assert policy_response.status_code == 201
    policy_id = policy_response.json()["id"]

    observations_response = client.get(
        f"/api/v1/runs/{current_run.id}/performance-observations"
    )
    assert observations_response.status_code == 200
    assert (
        observations_response.json()[0]["evidence_id"]
        == current_observation.evidence_id
    )

    baseline_response = client.post(
        f"/api/v1/projects/{project.id}/performance-baselines",
        json={"current_observation_id": current_observation.id, "policy_id": policy_id},
    )
    assert baseline_response.status_code == 201
    assert baseline_response.json()["status"] == "AVAILABLE"
    assert baseline_response.json()["run_count"] == 3

    comparison_response = client.post(
        f"/api/v1/runs/{current_run.id}/performance-comparisons",
        json={"policy_id": policy_id, "observation_ids": [current_observation.id]},
    )
    assert comparison_response.status_code == 201
    comparison = comparison_response.json()[0]
    assert comparison["status"] == "REGRESSION"
    assert comparison["baseline"]["run_count"] == 3
    assert comparison["current_evidence_id"] == current_observation.evidence_id

    listed = client.get(f"/api/v1/runs/{current_run.id}/performance-comparisons")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == comparison["id"]

    detail = client.get(f"/api/v1/performance-comparisons/{comparison['id']}")
    assert detail.status_code == 200
    assert detail.json()["input_digest"] == comparison["input_digest"]
