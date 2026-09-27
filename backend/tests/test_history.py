from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from failurelens.history import build_test_history, history_context_for_failure
from failurelens.models import Failure, Outcome, ReviewEvent, TestExecution as ExecutionModel
from failurelens.schemas import IngestionRequest, ReviewCreate, TestObservation as ObservationModel
from failurelens.service import (
    add_review,
    analyze_and_persist,
    create_project,
    ingest_normalized,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)
TEST_ID = "checkout::reviewed-timing"
MESSAGE = "reviewed harness timing instability"


def _ingest(
    session,
    project,
    *,
    external_id: str,
    day: int,
    outcomes: list[Outcome],
    test_identity: str = TEST_ID,
    browser: str | None = "chromium",
    branch: str = "main",
    environment: str | None = "ci-linux",
    run_scope: str = "full_suite",
    message: str = MESSAGE,
    worker_count: int | None = 4,
    shard_count: int | None = 2,
):
    observations = [
        ObservationModel(
            test_identity=test_identity,
            suite="checkout",
            source_path="tests/checkout.spec.ts",
            parameterization="CAD",
            browser=browser,
            attempt=index,
            outcome=outcome,
            message=message if outcome is Outcome.failed else None,
            exception_type="HarnessTimeout" if outcome is Outcome.failed else None,
            details={"retry_recovered": outcome is Outcome.passed and index > 0},
        )
        for index, outcome in enumerate(outcomes)
    ]
    run = ingest_normalized(
        session,
        project,
        IngestionRequest(
            external_id=external_id,
            repository="owner/repo",
            commit_sha=f"abcde{day:02d}",
            branch=branch,
            run_scope=run_scope,
            environment=environment,
            timezone="America/Halifax",
            worker_count=worker_count,
            shard_count=shard_count,
            observations=observations,
        ),
    )
    stamp = BASE + timedelta(days=day)
    run.started_at = stamp
    run.ended_at = stamp + timedelta(minutes=5)
    run.created_at = stamp
    session.commit()
    return run


def _failure_for_run(session, run_id: str) -> Failure:
    failure = session.scalar(
        select(Failure).where(Failure.run_id == run_id).order_by(Failure.created_at)
    )
    assert failure is not None
    return failure


def _execution_for_run(session, run_id: str) -> ExecutionModel:
    execution = session.scalar(
        select(ExecutionModel)
        .where(ExecutionModel.run_id == run_id)
        .order_by(ExecutionModel.attempt.desc())
    )
    assert execution is not None
    return execution


def test_history_context_is_prior_only_traceable_and_enables_reviewed_flake(session) -> None:
    project = create_project(session, "history-core", "History Core")
    prior_runs = [
        _ingest(session, project, external_id="prior-0", day=0, outcomes=[Outcome.failed, Outcome.passed]),
        _ingest(session, project, external_id="prior-1", day=1, outcomes=[Outcome.passed]),
        _ingest(session, project, external_id="prior-2", day=2, outcomes=[Outcome.failed]),
        _ingest(session, project, external_id="prior-3", day=3, outcomes=[Outcome.passed]),
        _ingest(session, project, external_id="prior-4", day=4, outcomes=[Outcome.failed, Outcome.passed]),
    ]

    reviewed_failure = _failure_for_run(session, prior_runs[0].id)
    reviewed_analysis = analyze_and_persist(session, reviewed_failure)
    review = add_review(
        session,
        reviewed_analysis,
        ReviewCreate(
            actor="reviewer@example.test",
            decision="category_correction",
            proposed_category="known_flake",
            reason="Repeated controlled harness reproduction confirms fixture ordering instability.",
            expected_version=0,
        ),
    )
    review.created_at = BASE + timedelta(hours=12)
    session.commit()

    current = _ingest(
        session,
        project,
        external_id="current",
        day=6,
        outcomes=[Outcome.failed],
    )
    current_failure = _failure_for_run(session, current.id)

    # Created after the selected run and timestamped after its cutoff: must not leak in.
    _ingest(
        session,
        project,
        external_id="future",
        day=7,
        outcomes=[Outcome.passed],
    )
    other_project = create_project(session, "history-other", "History Other")
    _ingest(
        session,
        other_project,
        external_id="foreign",
        day=1,
        outcomes=[Outcome.passed],
    )

    context = history_context_for_failure(session, current_failure)

    assert context["independent_runs"] == 5
    assert context["independent_observations"] == 5
    assert context["observed_passes"] == 4
    assert context["observed_failures"] == 1
    assert context["retry_recovery_rate"] == 0.666667
    assert context["reviewed_known_flake"] is True
    assert context["review_event_ids"] == [review.id]
    assert context["history_eligible_for_reassurance"] is True
    assert context["insufficient_data_reasons"] == []
    assert len(context["history_input_digest"]) == 64

    analysis = analyze_and_persist(session, current_failure)
    assert analysis.category.value == "known_flake"
    assert analysis.provenance["history_policy_version"] == "history-v1"
    assert analysis.provenance["history_input_digest"] == context["history_input_digest"]
    assert analysis.provenance["history_cutoff"] == context["history_cutoff"]


def test_retries_collapse_and_absent_tests_are_not_counted_as_passes(session) -> None:
    project = create_project(session, "history-collapse", "History Collapse")
    retried = _ingest(
        session,
        project,
        external_id="retried",
        day=0,
        outcomes=[Outcome.failed, Outcome.failed, Outcome.passed],
    )
    _ingest(
        session,
        project,
        external_id="absent",
        day=1,
        outcomes=[Outcome.passed],
        test_identity="unrelated::test",
    )
    current = _ingest(
        session,
        project,
        external_id="current",
        day=2,
        outcomes=[Outcome.failed],
    )
    selected = _failure_for_run(session, current.id)

    report = build_test_history(
        session,
        selected_execution=selected.execution,
        selected_run=current,
        cutoff=current.started_at,
        browser="chromium",
        match_browser=True,
        timezone_name="UTC",
        exclude_run_id=current.id,
        strict_fingerprint=selected.strict_fingerprint,
    )

    assert report["sample_sizes"]["independent_observations"] == 1
    assert report["sample_sizes"]["independent_runs"] == 1
    assert report["sample_sizes"]["comparable_project_runs"] == 2
    assert report["sample_sizes"]["runs_without_matching_test_observation"] == 1
    assert report["outcomes"]["final"]["passed"] == 1
    assert report["rates"]["retry_recovery_rate"]["numerator"] == 1
    assert report["rates"]["retry_recovery_rate"]["denominator"] == 1
    assert report["observations"][0]["run_id"] == retried.id
    assert report["observations"][0]["attempt_count"] == 3
    assert len(report["observations"][0]["execution_ids"]) == 3


def test_selection_scope_and_cohort_breakdowns_are_explicit(session) -> None:
    project = create_project(session, "history-cohorts", "History Cohorts")
    _ingest(
        session,
        project,
        external_id="full-chromium",
        day=0,
        outcomes=[Outcome.failed],
        run_scope="full_suite",
        browser="chromium",
    )
    _ingest(
        session,
        project,
        external_id="selected-firefox",
        day=1,
        outcomes=[Outcome.passed],
        run_scope="impact_selected",
        browser="firefox",
        environment="ci-windows",
        worker_count=8,
        shard_count=4,
    )
    _ingest(
        session,
        project,
        external_id="unknown-scope",
        day=2,
        outcomes=[Outcome.passed],
        run_scope="unknown",
        browser="chromium",
    )
    current = _ingest(
        session,
        project,
        external_id="current",
        day=3,
        outcomes=[Outcome.failed],
    )
    failure = _failure_for_run(session, current.id)

    all_history = build_test_history(
        session,
        selected_execution=failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        timezone_name="America/Halifax",
        exclude_run_id=current.id,
        strict_fingerprint=failure.strict_fingerprint,
    )
    assert all_history["sample_sizes"]["independent_observations"] == 3
    assert all_history["safety"]["selection_bias_present"] is True
    assert "impact_selected_history_has_selection_bias" in all_history["safety"][
        "insufficient_data_reasons"
    ]
    assert "run_scope_unknown" in all_history["safety"]["insufficient_data_reasons"]
    assert {row["value"] for row in all_history["breakdowns"]["browser"]} == {
        "chromium",
        "firefox",
    }
    assert all(
        row["final_failure_rate"]["status"] == "insufficient_data"
        for row in all_history["breakdowns"]["browser"]
    )

    full_suite = build_test_history(
        session,
        selected_execution=failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        run_scope="full_suite",
        timezone_name="UTC",
        exclude_run_id=current.id,
        strict_fingerprint=failure.strict_fingerprint,
    )
    assert full_suite["sample_sizes"]["independent_observations"] == 1
    assert full_suite["sample_sizes"]["impact_selected_observations"] == 0
    assert full_suite["filters"]["run_scope"] == "full_suite"


def test_review_annotation_does_not_rewrite_observed_rates(session) -> None:
    project = create_project(session, "history-review", "History Review")
    prior = _ingest(
        session,
        project,
        external_id="prior",
        day=0,
        outcomes=[Outcome.failed, Outcome.passed],
    )
    current = _ingest(
        session,
        project,
        external_id="current",
        day=2,
        outcomes=[Outcome.failed],
    )
    current_failure = _failure_for_run(session, current.id)

    before = build_test_history(
        session,
        selected_execution=current_failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        timezone_name="UTC",
        exclude_run_id=current.id,
        strict_fingerprint=current_failure.strict_fingerprint,
    )

    prior_failure = _failure_for_run(session, prior.id)
    analysis = analyze_and_persist(session, prior_failure)
    event = add_review(
        session,
        analysis,
        ReviewCreate(
            actor="reviewer@example.test",
            decision="category_correction",
            proposed_category="known_flake",
            reason="Controlled reproduction isolates fixture ordering.",
            expected_version=0,
        ),
    )
    event.created_at = BASE + timedelta(hours=12)
    session.commit()

    after = build_test_history(
        session,
        selected_execution=current_failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        timezone_name="UTC",
        exclude_run_id=current.id,
        strict_fingerprint=current_failure.strict_fingerprint,
    )

    assert before["outcomes"] == after["outcomes"]
    assert before["rates"] == after["rates"]
    assert before["review"]["reviewed_known_flake"] is False
    assert after["review"]["reviewed_known_flake"] is True
    assert before["history_input_digest"] != after["history_input_digest"]


def test_repeated_failures_without_any_pass_cannot_be_reassuring(session) -> None:
    project = create_project(session, "history-no-pass", "History No Pass")
    prior_runs = [
        _ingest(
            session,
            project,
            external_id=f"prior-{index}",
            day=index,
            outcomes=[Outcome.failed],
        )
        for index in range(5)
    ]
    first_failure = _failure_for_run(session, prior_runs[0].id)
    analysis = analyze_and_persist(session, first_failure)
    event = add_review(
        session,
        analysis,
        ReviewCreate(
            actor="reviewer@example.test",
            decision="category_correction",
            proposed_category="known_flake",
            reason="Historical annotation retained for safety regression coverage.",
            expected_version=0,
        ),
    )
    event.created_at = BASE + timedelta(hours=12)
    session.commit()

    current = _ingest(
        session,
        project,
        external_id="current",
        day=6,
        outcomes=[Outcome.failed],
    )
    current_failure = _failure_for_run(session, current.id)
    context = history_context_for_failure(session, current_failure)

    assert context["reviewed_known_flake"] is True
    assert context["observed_passes"] == 0
    assert context["history_eligible_for_reassurance"] is False
    assert "no_prior_pass_observation" in context["insufficient_data_reasons"]
    assert analyze_and_persist(session, current_failure).category.value == "insufficient_evidence"


def test_history_change_creates_new_analysis_revision(session) -> None:
    project = create_project(session, "history-revision", "History Revision")
    current = _ingest(
        session,
        project,
        external_id="current",
        day=10,
        outcomes=[Outcome.failed],
    )
    failure = _failure_for_run(session, current.id)
    first = analyze_and_persist(session, failure)

    # Inserted later, but timestamped before the analysis cutoff. The history digest must change.
    _ingest(
        session,
        project,
        external_id="late-arriving-prior",
        day=1,
        outcomes=[Outcome.passed],
    )
    second = analyze_and_persist(session, failure)

    assert second.id != first.id
    assert second.revision == first.revision + 1
    assert second.provenance["history_input_digest"] != first.provenance[
        "history_input_digest"
    ]


def test_history_api_is_prior_only_paginated_and_timezone_validated(client, session) -> None:
    project = create_project(session, "history-api", "History API")
    _ingest(
        session,
        project,
        external_id="prior-a",
        day=0,
        outcomes=[Outcome.failed, Outcome.passed],
    )
    _ingest(
        session,
        project,
        external_id="prior-b",
        day=1,
        outcomes=[Outcome.failed],
    )
    current = _ingest(
        session,
        project,
        external_id="current",
        day=2,
        outcomes=[Outcome.failed],
    )
    execution = _execution_for_run(session, current.id)

    response = client.get(
        f"/api/v1/tests/{execution.id}/history",
        params={
            "timezone": "America/Halifax",
            "browser": "chromium",
            "branch": "main",
            "environment": "ci-linux",
            "run_scope": "full_suite",
            "worker_count": 4,
            "shard_count": 2,
            "limit": 1,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["window"]["prior_only"] is True
    assert body["window"]["excluded_run_id"] == current.id
    assert body["pagination"] == {"offset": 0, "limit": 1, "returned": 1, "total": 2}
    assert len(body["observations"]) == 1
    assert body["sample_sizes"]["independent_runs"] == 2
    assert body["rates"]["retry_recovery_rate"]["denominator"] == 2
    assert body["logical_test"]["test_identity"] == TEST_ID
    assert body["filters"]["branch"] == "main"
    assert body["filters"]["worker_count"] == 4
    assert body["filters"]["shard_count"] == 2

    invalid_timezone = client.get(
        f"/api/v1/tests/{execution.id}/history",
        params={"timezone": "Mars/Olympus_Mons"},
    )
    assert invalid_timezone.status_code == 422

    invalid_window = client.get(
        f"/api/v1/tests/{execution.id}/history",
        params={"after": current.started_at.isoformat()},
    )
    assert invalid_window.status_code == 422


def test_future_review_is_excluded_by_cutoff(session) -> None:
    project = create_project(session, "history-future-review", "History Future Review")
    prior = _ingest(
        session,
        project,
        external_id="prior",
        day=0,
        outcomes=[Outcome.failed, Outcome.passed],
    )
    current = _ingest(
        session,
        project,
        external_id="current",
        day=2,
        outcomes=[Outcome.failed],
    )
    prior_failure = _failure_for_run(session, prior.id)
    analysis = analyze_and_persist(session, prior_failure)
    event = add_review(
        session,
        analysis,
        ReviewCreate(
            actor="reviewer@example.test",
            decision="category_correction",
            proposed_category="known_flake",
            reason="This review intentionally occurs after the selected analysis cutoff.",
            expected_version=0,
        ),
    )
    event.created_at = BASE + timedelta(days=3)
    session.commit()

    current_failure = _failure_for_run(session, current.id)
    report = build_test_history(
        session,
        selected_execution=current_failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        timezone_name="UTC",
        exclude_run_id=current.id,
        strict_fingerprint=current_failure.strict_fingerprint,
    )
    assert report["review"]["reviewed_known_flake"] is False
    assert report["review"]["events"] == []
    assert session.get(ReviewEvent, event.id) is not None


def test_known_flake_review_must_come_from_the_same_safe_cohort(session) -> None:
    project = create_project(session, "history-review-cohort", "History Review Cohort")
    full_suite_runs = [
        _ingest(session, project, external_id="full-0", day=0, outcomes=[Outcome.failed, Outcome.passed]),
        _ingest(session, project, external_id="full-1", day=1, outcomes=[Outcome.passed]),
        _ingest(session, project, external_id="full-2", day=2, outcomes=[Outcome.failed]),
        _ingest(session, project, external_id="full-3", day=3, outcomes=[Outcome.passed]),
        _ingest(session, project, external_id="full-4", day=4, outcomes=[Outcome.failed, Outcome.passed]),
    ]
    assert len(full_suite_runs) == 5

    selected_subset = _ingest(
        session,
        project,
        external_id="selected-reviewed",
        day=5,
        outcomes=[Outcome.failed],
        run_scope="impact_selected",
    )
    selected_failure = _failure_for_run(session, selected_subset.id)
    selected_analysis = analyze_and_persist(session, selected_failure)
    event = add_review(
        session,
        selected_analysis,
        ReviewCreate(
            actor="reviewer@example.test",
            decision="category_correction",
            proposed_category="known_flake",
            reason="Review belongs only to the selected-subset cohort.",
            expected_version=0,
        ),
    )
    event.created_at = BASE + timedelta(days=5, hours=1)
    session.commit()

    current = _ingest(
        session,
        project,
        external_id="current",
        day=7,
        outcomes=[Outcome.failed],
        run_scope="full_suite",
    )
    current_failure = _failure_for_run(session, current.id)

    context = history_context_for_failure(session, current_failure)
    assert context["independent_runs"] == 5
    assert context["observed_passes"] == 4
    assert context["observed_failures"] == 1
    assert context["reviewed_known_flake"] is False
    assert "no_prior_reviewed_known_flake_decision" in context[
        "insufficient_data_reasons"
    ]
    assert analyze_and_persist(session, current_failure).category.value == "insufficient_evidence"

    exploratory = build_test_history(
        session,
        selected_execution=current_failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        timezone_name="UTC",
        exclude_run_id=current.id,
        strict_fingerprint=current_failure.strict_fingerprint,
    )
    assert exploratory["review"]["reviewed_known_flake"] is True
    assert exploratory["safety"]["selection_bias_present"] is True


def test_repository_and_framework_are_part_of_history_identity(session) -> None:
    project = create_project(session, "history-repository", "History Repository")
    matching = _ingest(
        session,
        project,
        external_id="matching",
        day=0,
        outcomes=[Outcome.passed],
    )
    foreign = _ingest(
        session,
        project,
        external_id="foreign",
        day=1,
        outcomes=[Outcome.passed],
    )
    foreign.repository = "other/repository"
    foreign.framework = "other-framework"
    session.commit()

    current = _ingest(
        session,
        project,
        external_id="current",
        day=2,
        outcomes=[Outcome.failed],
    )
    failure = _failure_for_run(session, current.id)
    report = build_test_history(
        session,
        selected_execution=failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        timezone_name="UTC",
        exclude_run_id=current.id,
        strict_fingerprint=failure.strict_fingerprint,
    )

    assert report["sample_sizes"]["independent_runs"] == 1
    assert report["sample_sizes"]["comparable_project_runs"] == 1
    assert report["observations"][0]["run_id"] == matching.id


def test_analyzer_matches_unknown_environment_instead_of_all_environments(session) -> None:
    project = create_project(session, "history-unknown-env", "History Unknown Environment")
    unknown_environment = _ingest(
        session,
        project,
        external_id="unknown-environment",
        day=0,
        outcomes=[Outcome.passed],
        environment=None,
    )
    _ingest(
        session,
        project,
        external_id="known-environment",
        day=1,
        outcomes=[Outcome.passed],
        environment="ci-linux",
    )
    current = _ingest(
        session,
        project,
        external_id="current",
        day=2,
        outcomes=[Outcome.failed],
        environment=None,
    )
    failure = _failure_for_run(session, current.id)
    report = build_test_history(
        session,
        selected_execution=failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        environment=None,
        match_environment=True,
        run_scope="full_suite",
        timezone_name="UTC",
        exclude_run_id=current.id,
        strict_fingerprint=failure.strict_fingerprint,
    )

    assert report["sample_sizes"]["independent_runs"] == 1
    assert report["observations"][0]["run_id"] == unknown_environment.id
    assert report["filters"]["environment"] is None


def test_ingestion_rejects_unknown_timezone(client, session) -> None:
    project = create_project(session, "history-timezone", "History Timezone")
    response = client.post(
        f"/api/v1/projects/{project.id}/ingestions",
        json={
            "schema_version": "1.0",
            "external_id": "invalid-timezone",
            "timezone": "Mars/Olympus_Mons",
            "observations": [
                {
                    "test_identity": TEST_ID,
                    "outcome": "failed",
                    "message": MESSAGE,
                }
            ],
        },
    )
    assert response.status_code == 422
    assert "unknown timezone" in response.text


def test_latest_review_revision_supersedes_older_known_flake_decision(session) -> None:
    project = create_project(session, "history-review-revision", "History Review Revision")
    prior = _ingest(
        session,
        project,
        external_id="prior",
        day=0,
        outcomes=[Outcome.failed, Outcome.passed],
    )
    prior_failure = _failure_for_run(session, prior.id)
    analysis = analyze_and_persist(session, prior_failure)
    accepted = add_review(
        session,
        analysis,
        ReviewCreate(
            actor="reviewer@example.test",
            decision="category_correction",
            proposed_category="known_flake",
            reason="Initial review classified this historical incident as a known flake.",
            expected_version=0,
        ),
    )
    accepted.created_at = BASE + timedelta(hours=1)
    session.commit()

    superseding = add_review(
        session,
        analysis,
        ReviewCreate(
            actor="reviewer@example.test",
            decision="category_correction",
            proposed_category="product_defect",
            reason="New evidence supersedes the earlier flake assessment.",
            expected_version=1,
        ),
    )
    superseding.created_at = BASE + timedelta(hours=2)
    session.commit()

    current = _ingest(
        session,
        project,
        external_id="current",
        day=2,
        outcomes=[Outcome.failed],
    )
    current_failure = _failure_for_run(session, current.id)
    report = build_test_history(
        session,
        selected_execution=current_failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        browser="chromium",
        match_browser=True,
        environment="ci-linux",
        match_environment=True,
        run_scope="full_suite",
        timezone_name="UTC",
        exclude_run_id=current.id,
        strict_fingerprint=current_failure.strict_fingerprint,
    )

    assert report["review"]["reviewed_known_flake"] is False
    assert report["review"]["events"] == []
    assert "no_prior_reviewed_known_flake_decision" in report["safety"][
        "insufficient_data_reasons"
    ]



def test_multiple_browser_observations_in_one_run_do_not_meet_independent_run_gate(session) -> None:
    project = create_project(session, "history-independent-runs", "History Independent Runs")
    matrix = ingest_normalized(
        session,
        project,
        IngestionRequest(
            external_id="one-matrix-run",
            repository="owner/repo",
            commit_sha="abcdef0",
            branch="main",
            run_scope="full_suite",
            environment="ci-linux",
            timezone="UTC",
            observations=[
                ObservationModel(
                    test_identity=TEST_ID,
                    suite="checkout",
                    source_path="tests/checkout.spec.ts",
                    parameterization="CAD",
                    browser=browser,
                    attempt=0,
                    outcome=Outcome.passed if index % 2 == 0 else Outcome.failed,
                    message=MESSAGE if index % 2 else None,
                    exception_type="HarnessTimeout" if index % 2 else None,
                )
                for index, browser in enumerate(
                    ("chromium", "firefox", "webkit", "edge", "mobile")
                )
            ],
        ),
    )
    matrix.started_at = BASE
    matrix.ended_at = BASE + timedelta(minutes=5)
    matrix.created_at = BASE
    session.commit()

    current = _ingest(
        session,
        project,
        external_id="current",
        day=2,
        outcomes=[Outcome.failed],
    )
    failure = _failure_for_run(session, current.id)
    report = build_test_history(
        session,
        selected_execution=failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        timezone_name="UTC",
        exclude_run_id=current.id,
        strict_fingerprint=failure.strict_fingerprint,
    )

    assert report["sample_sizes"]["independent_observations"] == 5
    assert report["sample_sizes"]["independent_runs"] == 1
    assert report["sample_sizes"]["pass_fail_denominator"] == 1
    assert report["outcomes"]["final"]["failed"] == 1
    assert report["rates"]["final_failure_rate"]["numerator"] == 1
    assert report["rates"]["final_failure_rate"]["denominator"] == 1
    assert report["safety"]["history_eligible_for_reassurance"] is False
    assert "fewer_than_five_prior_independent_runs" in report["safety"][
        "insufficient_data_reasons"
    ]


def test_backfilled_run_created_after_cutoff_is_not_used_as_prior_history(session) -> None:
    project = create_project(session, "history-backfill", "History Backfill")
    backfilled = _ingest(
        session,
        project,
        external_id="backfilled",
        day=0,
        outcomes=[Outcome.passed],
    )
    backfilled.created_at = BASE + timedelta(days=3)
    session.commit()

    current = _ingest(
        session,
        project,
        external_id="current",
        day=2,
        outcomes=[Outcome.failed],
    )
    failure = _failure_for_run(session, current.id)
    report = build_test_history(
        session,
        selected_execution=failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        timezone_name="UTC",
        exclude_run_id=current.id,
        strict_fingerprint=failure.strict_fingerprint,
    )

    assert report["sample_sizes"]["independent_runs"] == 0
    assert report["sample_sizes"]["comparable_project_runs"] == 0
    assert report["observations"] == []


def test_comparable_run_scan_is_bounded_and_blocks_reassurance(session, monkeypatch) -> None:
    monkeypatch.setattr("failurelens.history.MAX_HISTORY_RUNS", 2)
    project = create_project(session, "history-run-bound", "History Run Bound")
    for day in range(3):
        _ingest(
            session,
            project,
            external_id=f"prior-{day}",
            day=day,
            outcomes=[Outcome.passed],
        )
    current = _ingest(
        session,
        project,
        external_id="current",
        day=4,
        outcomes=[Outcome.failed],
    )
    failure = _failure_for_run(session, current.id)
    report = build_test_history(
        session,
        selected_execution=failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        timezone_name="UTC",
        exclude_run_id=current.id,
        strict_fingerprint=failure.strict_fingerprint,
    )

    assert report["sample_sizes"]["comparable_project_runs"] == 2
    assert report["safety"]["truncated"] is True
    assert report["safety"]["history_eligible_for_reassurance"] is False
    assert "history_run_limit_reached" in report["safety"][
        "insufficient_data_reasons"
    ]


def test_review_scan_is_bounded_and_blocks_reassurance(session, monkeypatch) -> None:
    monkeypatch.setattr("failurelens.history.MAX_HISTORY_REVIEWS", 1)
    project = create_project(session, "history-review-bound", "History Review Bound")
    for day in range(2):
        prior = _ingest(
            session,
            project,
            external_id=f"prior-{day}",
            day=day,
            outcomes=[Outcome.failed, Outcome.passed],
        )
        failure = _failure_for_run(session, prior.id)
        analysis = analyze_and_persist(session, failure)
        event = add_review(
            session,
            analysis,
            ReviewCreate(
                actor="reviewer@example.test",
                decision="category_correction",
                proposed_category="known_flake",
                reason="Bounded history review fixture.",
                expected_version=0,
            ),
        )
        event.created_at = BASE + timedelta(days=day, hours=1)
        session.commit()

    current = _ingest(
        session,
        project,
        external_id="current",
        day=3,
        outcomes=[Outcome.failed],
    )
    failure = _failure_for_run(session, current.id)
    report = build_test_history(
        session,
        selected_execution=failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        timezone_name="UTC",
        exclude_run_id=current.id,
        strict_fingerprint=failure.strict_fingerprint,
    )

    assert len(report["review"]["events"]) == 1
    assert report["safety"]["truncated"] is True
    assert report["safety"]["history_eligible_for_reassurance"] is False
    assert "history_review_limit_reached" in report["safety"][
        "insufficient_data_reasons"
    ]


def test_analyzer_requires_same_branch_history(session) -> None:
    project = create_project(session, "history-branch", "History Branch")
    for day in range(5):
        _ingest(
            session,
            project,
            external_id=f"feature-{day}",
            day=day,
            outcomes=[Outcome.passed if day % 2 == 0 else Outcome.failed],
            branch="feature/other",
        )
    current = _ingest(
        session,
        project,
        external_id="current",
        day=6,
        outcomes=[Outcome.failed],
        branch="main",
    )
    failure = _failure_for_run(session, current.id)

    context = history_context_for_failure(session, failure)
    assert context["independent_runs"] == 0
    assert context["cohort"]["branch"] == "main"
    assert "no_prior_matching_observations" in context["insufficient_data_reasons"]

    exploratory = build_test_history(
        session,
        selected_execution=failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        timezone_name="UTC",
        exclude_run_id=current.id,
        strict_fingerprint=failure.strict_fingerprint,
    )
    assert exploratory["sample_sizes"]["independent_runs"] == 5


def test_analyzer_requires_same_worker_and_shard_cohort(session) -> None:
    project = create_project(session, "history-parallelism", "History Parallelism")
    for day in range(5):
        _ingest(
            session,
            project,
            external_id=f"parallel-{day}",
            day=day,
            outcomes=[Outcome.passed if day % 2 == 0 else Outcome.failed],
            worker_count=8,
            shard_count=4,
        )
    current = _ingest(
        session,
        project,
        external_id="current",
        day=6,
        outcomes=[Outcome.failed],
        worker_count=4,
        shard_count=2,
    )
    failure = _failure_for_run(session, current.id)

    context = history_context_for_failure(session, failure)
    assert context["independent_runs"] == 0
    assert context["cohort"]["worker_count"] == 4
    assert context["cohort"]["shard_count"] == 2

    exploratory = build_test_history(
        session,
        selected_execution=failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        timezone_name="UTC",
        exclude_run_id=current.id,
        strict_fingerprint=failure.strict_fingerprint,
    )
    assert exploratory["sample_sizes"]["independent_runs"] == 5
