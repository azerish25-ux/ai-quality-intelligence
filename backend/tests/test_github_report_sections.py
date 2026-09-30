from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from failurelens.clustering import cluster_project_failures, review_cluster
from failurelens.github_snapshot import MAX_SNAPSHOT_BYTES, report_snapshot
from failurelens.models import (
    ClusterRevision,
    Evidence,
    ImpactMappingSnapshot,
    ImpactOverride,
    ImpactRecommendation,
    ImpactRecommendationItem,
    Outcome,
    PerformanceObservation,
    Run,
    RunInput,
)
from failurelens.performance import (
    create_performance_policy,
    create_run_performance_comparisons,
)
from failurelens.schemas import IngestionRequest, PerformancePolicyCreate
from failurelens.schemas import TestObservation as Observation
from failurelens.service import create_project, ingest_normalized
from sqlalchemy import func, select

BASE = "1" * 40
HEAD = "2" * 40
NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


def _observation(outcome="failed", **kwargs):
    return Observation(
        test_identity=kwargs.pop("test_identity", "checkout::charge"),
        suite=kwargs.pop("suite", "payments"),
        source_path=kwargs.pop("source_path", "tests/payments.py"),
        browser=kwargs.pop("browser", "chromium"),
        outcome=outcome,
        message=kwargs.pop(
            "message",
            "Expected account balance 100 but got 200" if outcome == "failed" else None,
        ),
        exception_type="AssertionError" if outcome == "failed" else None,
        details={"producer": "pytest", "producer_version": "8.4"},
        **kwargs,
    )


def _run(
    session,
    project,
    external_id,
    *,
    observations=None,
    sha=HEAD,
    base=BASE,
    when=NOW,
    **kwargs,
):
    run = ingest_normalized(
        session,
        project,
        IngestionRequest(
            external_id=external_id,
            attempt=kwargs.pop("attempt", 1),
            repository="owner/repo",
            commit_sha=sha,
            base_sha=base,
            framework="normalized",
            run_scope=kwargs.pop("run_scope", "full_suite"),
            comparison_trust=kwargs.pop("comparison_trust", "trusted_workflow"),
            environment="ci-linux",
            timezone="UTC",
            worker_count=2,
            shard_count=1,
            expected_inputs=1,
            source_metadata={
                "load_profile": "steady",
                "region": "ca",
                "executor": "runner-a",
            },
            observations=observations if observations is not None else [_observation()],
            **kwargs,
        ),
    )
    run.started_at = when
    run.created_at = when
    run.ended_at = when + timedelta(seconds=1)
    for observation in session.scalars(
        select(PerformanceObservation).where(PerformanceObservation.run_id == run.id)
    ):
        observation.observed_at = when
    session.commit()
    return run


def _project(session):
    return create_project(session, "rich-report", "Rich report")


def test_report_exact_identity_and_logical_counts_include_suite_and_source_path(
    session,
):
    project = _project(session)
    run = _run(
        session,
        project,
        "run-identity",
        attempt=3,
        observations=[
            _observation("passed", suite="a", source_path="tests/a.py"),
            _observation("failed", suite="b", source_path="tests/a.py"),
            _observation(
                "skipped",
                suite="b",
                source_path="tests/b.py",
                message="Disabled for maintenance",
            ),
            _observation("passed", suite="b", source_path="tests/a.py", attempt=1),
        ],
    )
    report = report_snapshot(session, run)
    assert report["external_id"] == "run-identity"
    assert report["attempt"] == 3
    assert report["tested_head"] == HEAD
    assert report["base_sha"] == BASE
    assert report["run_scope"] == "full_suite"
    assert report["outcomes"]["logical_tests"] == 3
    assert report["outcomes"]["attempts"] == 4
    assert report["outcomes"]["retried"] == 1
    assert report["outcomes"]["retry_recovered"] == 1
    assert report["outcomes"]["passed"] == 2
    assert report["outcomes"]["skipped"] == 1
    skipped = report["skipped_tests"]["items"][0]
    assert skipped["reason"] == "Disabled for maintenance"
    assert skipped["reason_status"] == "recorded"
    assert skipped["evidence_ids"]


@pytest.mark.parametrize("state", ["restricted", "expired", "missing_bytes"])
def test_skip_reason_never_survives_evidence_unavailability(session, state):
    from pathlib import Path

    from failurelens.config import get_settings

    project = _project(session)
    run = _run(
        session,
        project,
        "skipped-unavailable",
        observations=[_observation("skipped", message="private skip canary")],
    )
    evidence = session.scalar(select(Evidence).where(Evidence.run_id == run.id))
    if state == "restricted":
        evidence.derivative.restricted = True
    elif state == "expired":
        run.evidence_expired_at = NOW
    else:
        (Path(get_settings().artifact_root) / evidence.derivative.storage_path).unlink()
    session.commit()
    report = report_snapshot(session, run)
    skipped = report["skipped_tests"]["items"][0]
    assert skipped["reason"] is None
    assert skipped["reason_status"] == "unknown"
    assert "private skip canary" not in json.dumps(report)
    assert skipped["evidence_ids"] == []


def test_new_failure_requires_validated_exact_prior_base_pass(session):
    project = _project(session)
    previous = _run(
        session,
        project,
        "prior-base",
        observations=[_observation("passed")],
        sha=BASE,
        base=None,
        when=NOW - timedelta(days=1),
    )
    current = _run(session, project, "head-failure")
    report = report_snapshot(session, current)
    assert report["baseline_status"] == "available"
    assert report["baseline"]["counts"] == {"new": 1, "existing": 0, "unknown": 0}
    comparison = report["baseline"]["items"][0]
    assert comparison["prior_observations"][0]["run_id"] == previous.id
    assert comparison["prior_observations"][0]["tested_head"] == BASE
    assert comparison["supporting_baseline_evidence_ids"]
    assert "harmless or authorizes ignoring a failure" in report["markdown"]
    assert report["advisory_status"] == "HOLD_FOR_REVIEW"


def test_existing_failure_preserves_opposing_base_pass_and_recovery(session):
    project = _project(session)
    failed_base = _run(
        session, project, "base-fail", sha=BASE, base=None, when=NOW - timedelta(days=2)
    )
    _run(
        session,
        project,
        "base-pass",
        observations=[_observation("passed")],
        sha=BASE,
        base=None,
        when=NOW - timedelta(days=1),
    )
    current = _run(
        session,
        project,
        "head-recovered",
        observations=[_observation(), _observation("passed", attempt=1)],
    )
    report = report_snapshot(session, current)
    assert report["outcomes"]["retry_recovered"] == 1
    assert report["baseline"]["counts"]["existing"] == 1
    comparison = report["baseline"]["items"][0]
    assert comparison["current_final_outcome"] == "passed"
    assert {item["outcome"] for item in comparison["prior_observations"]} == {
        "passed",
        "failed",
    }
    assert failed_base.id in {
        item["run_id"] for item in comparison["prior_observations"]
    }


@pytest.mark.parametrize(
    "change",
    [
        "wrong_sha",
        "future",
        "late_ingestion",
        "wrong_project",
        "different_suite",
        "different_source",
        "skipped",
        "different_failure",
        "restricted",
        "expired",
        "missing_test",
        "partial",
        "untrusted",
        "environment",
        "unknown_scope",
        "changed_execution",
    ],
)
def test_unsafe_or_unobserved_baseline_never_becomes_new_or_existing(session, change):
    project = _project(session)
    previous_project = (
        create_project(session, "foreign", "Foreign")
        if change == "wrong_project"
        else project
    )
    observation = _observation("passed")
    if change == "different_suite":
        observation.suite = "other"
    if change == "different_source":
        observation.source_path = "tests/other.py"
    if change == "missing_test":
        observation.test_identity = "unrelated"
    if change == "skipped":
        observation.outcome = Outcome.skipped
    if change == "different_failure":
        observation = _observation(message="Request timed out waiting for network")
    previous = _run(
        session,
        previous_project,
        "baseline",
        observations=[observation],
        sha="3" * 40 if change == "wrong_sha" else BASE,
        base=None,
        when=NOW + timedelta(days=1) if change == "future" else NOW - timedelta(days=1),
    )
    if change == "late_ingestion":
        previous.created_at = NOW + timedelta(seconds=1)
    elif change == "restricted":
        session.scalar(
            select(Evidence).where(Evidence.run_id == previous.id)
        ).derivative.restricted = True
    elif change == "expired":
        previous.evidence_expired_at = NOW
    elif change == "partial":
        previous.completeness = "partial"
    elif change == "untrusted":
        previous.source_metadata = {
            **previous.source_metadata,
            "comparison_trust": "self_reported",
        }
    elif change == "environment":
        previous.environment = "other"
    elif change == "unknown_scope":
        previous.run_scope = "unknown"
    elif change == "changed_execution":
        previous.executions[0].outcome = Outcome.failed
    session.commit()
    current = _run(session, project, "head")
    report = report_snapshot(session, current)
    assert report["baseline"]["counts"] == {"new": 0, "existing": 0, "unknown": 1}


def _impact(session, run, *, fallback=False):
    mapping = ImpactMappingSnapshot(
        project_id=run.project_id,
        version="mapping-v1",
        policy_version="policy-v1",
        source_digest="a" * 64,
        trusted=True,
        coverage_complete=True,
        source_metadata={},
    )
    session.add(mapping)
    session.flush()
    changed = session.scalar(select(RunInput).where(RunInput.run_id == run.id))
    row = ImpactRecommendation(
        project_id=run.project_id,
        run_id=run.id,
        changed_input_id=changed.id,
        mapping_snapshot_id=mapping.id,
        base_sha=BASE,
        head_sha=HEAD,
        input_digest="b" * 64,
        changed_files_digest=changed.digest,
        engine_version="impact-v1",
        policy_version="policy-v1",
        status="FULL_SUITE_REQUIRED" if fallback else "FOCUSED",
        current_revision=1,
        comparison_trusted=True,
        mapping_complete=True,
        full_suite_required=fallback,
        summary="Stored focused proposal",
        changed_files=[],
        safety_reasons=["unmapped_change"] if fallback else [],
        metrics={},
    )
    session.add(row)
    session.flush()
    for key, selected in (("selected", True), ("excluded", False), ("override", False)):
        session.add(
            ImpactRecommendationItem(
                recommendation_id=row.id,
                test_key=key,
                test_identity=key,
                criticality="normal",
                mandatory=False,
                base_selected=selected,
                rank=1 if selected else None,
                score=0.7,
                confidence="medium",
                reason_codes=["mapped"],
                reasons=[{"code": "mapping", "source": "coverage"}],
                mapping_edge_ids=[],
                exclusion_reason=None if selected else "No mapped change",
            )
        )
    session.add(
        ImpactOverride(
            recommendation_id=row.id,
            actor="reviewer",
            action="include",
            test_key="override",
            reason="Review adds coupling coverage",
            revision_before=0,
            revision_after=1,
        )
    )
    session.commit()
    return row


def test_effective_stored_impact_overrides_exclusions_and_fallback(session):
    project = _project(session)
    run = _run(session, project, "impact", run_scope="impact_selected")
    recommendation = _impact(session, run)
    report = report_snapshot(session, run)
    impact = report["impact"]
    assert impact["selected_count"] == 2 and impact["excluded_count"] == 1
    row = impact["items"][0]
    assert row["recommendation_id"] == recommendation.id and row["revision"] == 1
    included = next(
        item for item in row["selected_tests"] if item["test_key"] == "override"
    )
    assert included["selection_source"].startswith("override:")
    assert row["overrides"][0]["reason"] == "Review adds coupling coverage"
    assert row["excluded_tests"][0]["exclusion_reason"] == "No mapped change"
    recommendation.full_suite_required = True
    recommendation.status = "FULL_SUITE_REQUIRED"
    recommendation.safety_reasons = ["unmapped_change"]
    session.commit()
    report = report_snapshot(session, run)
    assert "required_full_suite_not_observed" in report["advisory_reasons"]
    assert report["advisory_status"] == "HOLD_FOR_REVIEW"
    assert "unmapped_change" in report["markdown"]


def test_current_cluster_revision_representative_and_uncertainty(session):
    project = _project(session)
    run = _run(
        session,
        project,
        "cluster",
        observations=[_observation(), _observation(test_identity="checkout::refund")],
    )
    clusters = cluster_project_failures(session, project.id)
    cluster = clusters[0]
    first_revision = cluster.current_revision
    review_cluster(
        session,
        cluster,
        decision="confirm",
        actor="reviewer",
        reason="Checked shared failure",
        expected_revision=first_revision,
    )
    report = report_snapshot(session, run)
    item = next(
        row for row in report["clusters"]["items"] if row["cluster_id"] == cluster.id
    )
    assert item["revision"] == cluster.current_revision
    assert item["revision"] > first_revision
    assert item["representative_failure_id"]
    assert item["representative_evidence_state"] == "available"
    assert "human_reviewed_membership" in item["uncertainty_flags"]
    assert item["run_member_count"] == len(item["members"])
    assert (
        session.scalar(
            select(func.count())
            .select_from(ClusterRevision)
            .where(ClusterRevision.cluster_id == cluster.id)
        )
        >= 2
    )


def _performance(session, project):
    baseline = []
    for index, value in enumerate((100, 105, 110)):
        baseline.append(
            _run(
                session,
                project,
                f"performance-base-{index}",
                observations=[_observation("passed", duration_ms=value)],
                sha=BASE,
                base=None,
                when=NOW - timedelta(days=3 - index),
            )
        )
    current = _run(
        session,
        project,
        "performance-current",
        observations=[_observation("passed", duration_ms=150)],
    )
    policy = create_performance_policy(
        session,
        project,
        PerformancePolicyCreate(
            version="report-policy",
            relative_tolerance=0.1,
            absolute_tolerance=5,
            min_baseline_runs=3,
            max_baseline_age_days=30,
            require_trusted=True,
        ),
    )
    comparisons = create_run_performance_comparisons(session, current, policy)
    assert len(comparisons) == 1
    return current, comparisons[0], baseline


def test_stored_performance_thresholds_baselines_units_confounders_and_hold(session):
    project = _project(session)
    run, comparison, previous = _performance(session, project)
    report = report_snapshot(session, run)
    item = report["performance"]["items"][0]
    assert item["comparison_id"] == comparison.id
    assert item["status"] == "REGRESSION"
    assert item["unit"] == "ms"
    assert item["current_value"] == 150
    assert item["baseline_value"] == 105
    assert item["allowed_relative_change"] == 0.1
    assert item["allowed_absolute_change"] == 10.5
    assert item["baseline_run_count"] == 3
    assert {row["run_id"] for row in item["baseline_members"]} == {
        row.id for row in previous
    }
    assert item["uncertainty"]["significance_claimed"] is False
    assert item["next_measurement"]
    assert "stored_performance_regression" in report["advisory_reasons"]
    assert report["advisory_status"] == "HOLD_FOR_REVIEW"


@pytest.mark.parametrize(
    "which,state",
    [("current", "restricted"), ("base", "restricted"), ("base", "expired")],
)
def test_performance_revalidates_current_and_baseline_availability(
    session, which, state
):
    project = _project(session)
    run, _comparison, previous = _performance(session, project)
    target = run if which == "current" else previous[0]
    if state == "restricted":
        session.scalar(
            select(Evidence).where(Evidence.run_id == target.id)
        ).derivative.restricted = True
    else:
        target.evidence_expired_at = NOW
    session.commit()
    report = report_snapshot(session, run)
    item = report["performance"]["items"][0]
    assert item["stored_status"] == "REGRESSION"
    assert item["status"] == "EVIDENCE_UNAVAILABLE"
    assert item["evidence_state"] == state
    assert item["current_value"] is None and item["baseline_value"] is None
    assert item["baseline_members"] == []
    assert "stored_performance_evidence_unavailable" in report["advisory_reasons"]


def test_rich_report_read_only_repeatable_safe_and_bounded(session):
    project = _project(session)
    run = _run(
        session,
        project,
        "safe-report",
        observations=[
            _observation(
                "skipped",
                message="![remote](https://evil.example) @everyone token=skip-secret-123456",
            )
        ],
    )
    _impact(session, run)
    before = {
        table.name: session.scalar(select(func.count()).select_from(table))
        for table in Run.metadata.sorted_tables
    }
    first = report_snapshot(session, run)
    second = report_snapshot(session, run)
    after = {
        table.name: session.scalar(select(func.count()).select_from(table))
        for table in Run.metadata.sorted_tables
    }
    assert first == second
    assert before == after
    assert not session.new and not session.dirty and not session.deleted
    assert "skip-secret-123456" not in json.dumps(first)
    assert "![remote]" not in first["markdown"] and "@everyone" not in first["markdown"]
    assert len(first["markdown"].encode()) <= 50_000
    assert len(json.dumps(first, sort_keys=True).encode()) <= MAX_SNAPSHOT_BYTES
    unsigned = {key: value for key, value in first.items() if key != "report_digest"}
    assert (
        first["report_digest"]
        == hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def test_skip_and_base_omissions_preserve_full_counts(session):
    project = _project(session)
    run = _run(
        session,
        project,
        "many-skips",
        observations=[
            _observation("skipped", test_identity=f"skip-{index}")
            for index in range(65)
        ],
    )
    report = report_snapshot(session, run)
    assert report["outcomes"]["skipped"] == 65
    assert report["skipped_tests"]["count"] == 65
    assert report["skipped_tests"]["omitted_items"] == 65 - len(
        report["skipped_tests"]["items"]
    )
    assert report["skipped_tests"]["omitted_items"] >= 15
    assert report["performance"]["status"] == "not_assessed"


def test_large_rich_section_omits_whole_records_and_keeps_aggregate_counts(session):
    project = _project(session)
    run = _run(session, project, "large-impact-report")
    recommendation = _impact(session, run)
    for index in range(60):
        session.add(
            ImpactRecommendationItem(
                recommendation_id=recommendation.id,
                test_key=f"large-{index}",
                test_identity=f"test-{index}-" + "界" * 480,
                criticality="normal",
                mandatory=False,
                base_selected=True,
                score=0.8,
                confidence="medium",
                reason_codes=["界" * 400] * 10,
                reasons=[{"detail": "界" * 400}] * 10,
                mapping_edge_ids=[],
            )
        )
    session.commit()
    report = report_snapshot(session, run)
    impact = report["impact"]
    assert impact["count"] == 1
    assert impact["selected_count"] == 62
    assert impact["excluded_count"] == 1
    assert impact["omitted_items"] == 1 - len(impact["items"])
    assert len(json.dumps(report, sort_keys=True).encode()) <= MAX_SNAPSHOT_BYTES
    assert len(report["markdown"].encode()) <= 50_000
    if not impact["items"]:
        assert recommendation.id not in report["markdown"]
        assert "1 recommendations omitted" in report["markdown"]


def test_retained_evidence_references_include_exact_prior_run_scope(session):
    from failurelens.github_report_sections import retained_evidence_references

    project = _project(session)
    previous = _run(
        session,
        project,
        "prior-export-base",
        observations=[_observation("passed")],
        sha=BASE,
        base=None,
        when=NOW - timedelta(days=1),
    )
    current = _run(session, project, "export-head")
    report = report_snapshot(session, current)
    references = retained_evidence_references(current.id, report)
    assert references["allowed_related_run_ids"] == [previous.id]
    assert references["omitted_evidence_ids"] == 0
    assert references["omitted_related_run_ids"] == 0
    cited = set(references["additional_evidence_ids"])
    assert report["baseline"]["items"][0]["current_evidence_ids"][0] in cited
    assert (
        report["baseline"]["items"][0]["supporting_baseline_evidence_ids"][0] in cited
    )
    report["baseline"]["items"] = []
    assert (
        retained_evidence_references(current.id, report)["additional_evidence_ids"]
        == []
    )
