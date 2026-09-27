from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from failurelens.infrastructure import (
    build_infrastructure_correlation,
    create_infrastructure_event,
    get_infrastructure_correlation,
)
from failurelens.models import (
    Failure,
    InfrastructureEvent,
    Outcome,
    TestExecution as ExecutionModel,
)
from failurelens.schemas import (
    InfrastructureEventCreate,
    IngestionRequest,
    TestObservation as ObservationInput,
)
from failurelens.service import analyze_and_persist, create_project, ingest_normalized

BASE = datetime(2026, 2, 1, tzinfo=UTC)
TEST_ID = "checkout::infrastructure-sensitive"


def _ingest(
    session,
    project,
    *,
    external_id: str,
    day: int,
    outcome: Outcome,
    message: str = "gateway timed out while waiting for checkout",
    repository: str = "owner/repo",
    environment: str = "ci-linux",
):
    run = ingest_normalized(
        session,
        project,
        IngestionRequest(
            external_id=external_id,
            repository=repository,
            commit_sha=f"abcde{day:02d}",
            branch="main",
            run_scope="full_suite",
            environment=environment,
            timezone="UTC",
            worker_count=4,
            shard_count=2,
            source_metadata={
                "workflow_name": "ci",
                "runner_identity": "runner-1",
                "runner_group": "hosted",
                "region": "ca-east",
            },
            observations=[
                ObservationInput(
                    test_identity=TEST_ID,
                    suite="checkout",
                    source_path="tests/checkout.spec.ts",
                    browser="chromium",
                    outcome=outcome,
                    message=message if outcome is Outcome.failed else None,
                    exception_type="GatewayTimeout" if outcome is Outcome.failed else None,
                )
            ],
        ),
    )
    stamp = BASE + timedelta(days=day)
    run.started_at = stamp
    run.ended_at = stamp + timedelta(minutes=10)
    run.created_at = stamp
    session.commit()
    return run


def _execution(session, run_id: str) -> ExecutionModel:
    value = session.scalar(
        select(ExecutionModel).where(ExecutionModel.run_id == run_id)
    )
    assert value is not None
    return value


def _failure(session, run_id: str) -> Failure:
    value = session.scalar(select(Failure).where(Failure.run_id == run_id))
    assert value is not None
    return value


def _event(
    session,
    project,
    *,
    event_id: str,
    day: int,
    trust: str = "verified_monitor",
    repository: str = "owner/repo",
    environment: str = "ci-linux",
    kind: str = "service_outage",
    recorded_day: int | None = None,
):
    return create_infrastructure_event(
        session,
        project,
        InfrastructureEventCreate(
            repository=repository,
            environment=environment,
            producer="status-monitor",
            producer_event_id=event_id,
            event_kind=kind,
            severity="error",
            status="resolved",
            started_at=BASE + timedelta(days=day, minutes=2),
            ended_at=BASE + timedelta(days=day, minutes=8),
            recorded_at=BASE + timedelta(days=recorded_day if recorded_day is not None else day, minutes=9),
            workflow_name="ci",
            runner_identity="runner-1",
            runner_group="hosted",
            region="ca-east",
            worker_count=4,
            source_trust=trust,
            metadata={"monitor_check": "checkout-gateway"},
        ),
    )


def test_trusted_events_create_traceable_available_snapshot(session) -> None:
    project = create_project(session, "infra-available", "Infrastructure Available")
    exposed_runs = [
        _ingest(
            session,
            project,
            external_id=f"failed-{index}",
            day=index,
            outcome=Outcome.failed,
        )
        for index in range(3)
    ]
    for index in range(3):
        _event(session, project, event_id=f"outage-{index}", day=index)
    for index in range(3, 6):
        _ingest(
            session,
            project,
            external_id=f"passed-{index}",
            day=index,
            outcome=Outcome.passed,
        )
    current = _ingest(
        session,
        project,
        external_id="current",
        day=8,
        outcome=Outcome.failed,
    )
    selected = _execution(session, current.id)

    result = build_infrastructure_correlation(
        session,
        selected_execution=selected,
        selected_run=current,
        cutoff=current.started_at,
        browser="chromium",
        match_browser=True,
        run_scope="full_suite",
        environment="ci-linux",
        match_environment=True,
        timezone_name="UTC",
        exclude_run_id=current.id,
        minimum_support=3,
        persist=True,
    )

    assert result["status"] == "AVAILABLE"
    assert result["sample_sizes"]["independent_runs"] == 6
    assert result["sample_sizes"]["exposed_runs"] == 3
    assert result["sample_sizes"]["unexposed_runs"] == 3
    assert result["rates"]["exposed_failure_rate"]["value"] == 1.0
    assert result["rates"]["unexposed_failure_rate"]["value"] == 0.0
    assert result["rates"]["absolute_failure_rate_difference"] == 1.0
    assert result["safety"]["association_only"] is True
    assert result["safety"]["can_independently_authorize_infrastructure_classification"] is False
    assert set(result["accepted_event_ids"]) == {
        event.id for event in session.scalars(select(InfrastructureEvent)).all()
    }
    assert {member["run_id"] for member in result["members"] if member["exposed"]} == {
        run.id for run in exposed_runs
    }

    snapshot = get_infrastructure_correlation(session, result["snapshot_id"])
    assert snapshot is not None
    assert len(snapshot.members) == 6
    repeated = build_infrastructure_correlation(
        session,
        selected_execution=selected,
        selected_run=current,
        cutoff=current.started_at,
        browser="chromium",
        match_browser=True,
        run_scope="full_suite",
        environment="ci-linux",
        match_environment=True,
        timezone_name="UTC",
        exclude_run_id=current.id,
        minimum_support=3,
        persist=True,
    )
    assert repeated["snapshot_id"] == result["snapshot_id"]
    assert repeated["input_digest"] == result["input_digest"]


def test_untrusted_event_cannot_support_correlation(session) -> None:
    project = create_project(session, "infra-untrusted", "Infrastructure Untrusted")
    _ingest(session, project, external_id="failed", day=0, outcome=Outcome.failed)
    _ingest(session, project, external_id="passed", day=1, outcome=Outcome.passed)
    _event(
        session,
        project,
        event_id="artifact-claim",
        day=0,
        trust="artifact_derived",
    )
    current = _ingest(
        session,
        project,
        external_id="current",
        day=3,
        outcome=Outcome.failed,
    )
    result = build_infrastructure_correlation(
        session,
        selected_execution=_execution(session, current.id),
        selected_run=current,
        cutoff=current.started_at,
        exclude_run_id=current.id,
        minimum_support=1,
    )

    assert result["status"] == "UNTRUSTED_EVENT_SOURCE"
    assert result["accepted_event_ids"] == []
    assert result["sample_sizes"]["untrusted_candidate_events"] == 1
    assert result["rejected_events"][0]["reasons"] == ["untrusted_event_source"]
    assert result["safety"]["can_support_infrastructure_association"] is False


def test_cross_context_and_future_events_are_excluded(session) -> None:
    project = create_project(session, "infra-boundary", "Infrastructure Boundary")
    _ingest(session, project, external_id="prior", day=0, outcome=Outcome.failed)
    _event(
        session,
        project,
        event_id="wrong-repo",
        day=0,
        repository="other/repo",
    )
    current = _ingest(
        session,
        project,
        external_id="current",
        day=3,
        outcome=Outcome.failed,
    )
    _event(
        session,
        project,
        event_id="future-record",
        day=0,
        recorded_day=4,
    )

    result = build_infrastructure_correlation(
        session,
        selected_execution=_execution(session, current.id),
        selected_run=current,
        cutoff=current.started_at,
        exclude_run_id=current.id,
        minimum_support=1,
    )

    assert result["status"] == "INCOMPATIBLE_CONTEXT"
    assert result["sample_sizes"]["candidate_events"] == 1
    assert result["rejected_events"][0]["reasons"] == ["repository_mismatch"]
    assert all(event["producer_event_id"] != "future-record" for event in result["accepted_events"])


def test_correlation_never_downgrades_product_defect(session) -> None:
    project = create_project(session, "infra-product", "Infrastructure Product Risk")
    prior = _ingest(
        session,
        project,
        external_id="prior",
        day=0,
        outcome=Outcome.failed,
        message="duplicate committed transfer left the ledger unbalanced",
    )
    _event(session, project, event_id="outage", day=0)
    current = _ingest(
        session,
        project,
        external_id="current",
        day=2,
        outcome=Outcome.failed,
        message="duplicate committed transfer left the ledger unbalanced",
    )
    failure = _failure(session, current.id)
    before = analyze_and_persist(session, failure)
    assert before.category.value == "product_defect"

    result = build_infrastructure_correlation(
        session,
        selected_execution=failure.execution,
        selected_run=current,
        cutoff=current.started_at,
        exclude_run_id=current.id,
        minimum_support=1,
        persist=True,
    )
    after = analyze_and_persist(session, failure)

    assert prior.id in {member["run_id"] for member in result["members"] if member["exposed"]}
    assert after.category.value == "product_defect"
    assert result["safety"]["can_independently_authorize_infrastructure_classification"] is False


def test_event_identity_is_idempotent_but_conflicting_content_is_rejected(session) -> None:
    project = create_project(session, "infra-idempotent", "Infrastructure Idempotent")
    first = _event(session, project, event_id="same", day=0)
    repeated = _event(session, project, event_id="same", day=0)
    assert repeated.id == first.id

    try:
        _event(
            session,
            project,
            event_id="same",
            day=0,
            kind="dns_failure",
        )
    except ValueError as exc:
        assert "different content" in str(exc)
    else:
        raise AssertionError("conflicting infrastructure event content was accepted")


def test_event_timestamps_cannot_leak_future_state(session) -> None:
    project = create_project(session, "infra-time-validity", "Infrastructure Time Validity")
    request = InfrastructureEventCreate(
        repository="owner/repo",
        environment="ci-linux",
        producer="status-monitor",
        producer_event_id="future-end",
        event_kind="service_outage",
        severity="error",
        status="resolved",
        started_at=BASE,
        ended_at=BASE + timedelta(minutes=10),
        recorded_at=BASE + timedelta(minutes=5),
        source_trust="verified_monitor",
    )

    try:
        create_infrastructure_event(session, project, request)
    except ValueError as exc:
        assert "recorded_at must not be earlier than ended_at" in str(exc)
    else:
        raise AssertionError("future event state was accepted before it was recorded")


def test_infrastructure_api_and_history_surface_real_correlation(client, session) -> None:
    project = create_project(session, "infra-api", "Infrastructure API")
    _ingest(session, project, external_id="prior-failed", day=0, outcome=Outcome.failed)
    _ingest(session, project, external_id="prior-passed", day=1, outcome=Outcome.passed)
    current = _ingest(
        session,
        project,
        external_id="current",
        day=3,
        outcome=Outcome.failed,
    )
    execution = _execution(session, current.id)

    response = client.post(
        f"/api/v1/projects/{project.id}/infrastructure-events",
        json={
            "repository": "owner/repo",
            "environment": "ci-linux",
            "producer": "status-monitor",
            "producer_event_id": "api-outage",
            "event_kind": "service_outage",
            "severity": "error",
            "status": "resolved",
            "started_at": (BASE + timedelta(minutes=2)).isoformat(),
            "ended_at": (BASE + timedelta(minutes=8)).isoformat(),
            "recorded_at": (BASE + timedelta(minutes=9)).isoformat(),
            "workflow_name": "ci",
            "runner_identity": "runner-1",
            "runner_group": "hosted",
            "region": "ca-east",
            "worker_count": 4,
            "source_trust": "verified_monitor",
            "metadata": {"monitor_check": "checkout-gateway"},
        },
    )
    assert response.status_code == 201
    assert response.json()["trusted_for_correlation"] is True

    history = client.get(
        f"/api/v1/tests/{execution.id}/history?environment=ci-linux&run_scope=full_suite"
    )
    assert history.status_code == 200
    correlation = history.json()["infrastructure_correlations"]
    assert correlation["snapshot_id"] is None
    assert correlation["sample_sizes"]["candidate_events"] == 1
    assert correlation["safety"]["association_only"] is True

    created = client.post(
        f"/api/v1/tests/{execution.id}/infrastructure-correlations",
        json={
            "environment": "ci-linux",
            "run_scope": "full_suite",
            "minimum_support": 1,
        },
    )
    assert created.status_code == 201
    assert created.json()["snapshot_id"]
    fetched = client.get(
        f"/api/v1/infrastructure-correlations/{created.json()['snapshot_id']}"
    )
    assert fetched.status_code == 200
    assert fetched.json()["input_digest"] == created.json()["input_digest"]
