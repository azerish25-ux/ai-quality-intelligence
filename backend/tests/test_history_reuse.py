from unittest.mock import Mock

import pytest
from failurelens.history import build_test_history
from failurelens.infrastructure import (
    MAX_CORRELATION_RUNS,
    build_infrastructure_correlation,
)
from failurelens.models import Run
from failurelens.models import TestExecution as Execution

from evaluation.operational_benchmark import seed_workload


def history_arguments(session):
    _, run_id, execution_id = seed_workload(session, runs=8, tests_per_run=2)
    run = session.get(Run, run_id)
    execution = session.get(Execution, execution_id)
    return {
        "selected_execution": execution,
        "selected_run": run,
        "cutoff": run.created_at,
        "exclude_run_id": run.id,
        "timezone_name": "UTC",
    }


def test_request_local_reuse_has_identical_results_without_second_history_query(
    session, monkeypatch
):
    from failurelens import infrastructure

    args = history_arguments(session)
    report = build_test_history(session, **args, observation_limit=MAX_CORRELATION_RUNS)
    expected = build_infrastructure_correlation(session, **args)
    forbidden = Mock(side_effect=AssertionError("history was recomputed"))
    monkeypatch.setattr(infrastructure, "build_test_history", forbidden)
    assert (
        build_infrastructure_correlation(session, **args, request_history=report)
        == expected
    )
    forbidden.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("project_id", "foreign"),
        ("repository", "other/repo"),
        ("test_identity", "another-test"),
    ],
)
def test_reuse_rejects_wrong_logical_scope(session, field, value):
    args = history_arguments(session)
    report = build_test_history(session, **args, observation_limit=MAX_CORRELATION_RUNS)
    report["logical_test"][field] = value
    with pytest.raises(ValueError, match="scope or completeness"):
        build_infrastructure_correlation(session, **args, request_history=report)


def test_reuse_rejects_incomplete_page_and_wrong_cutoff(session):
    args = history_arguments(session)
    report = build_test_history(session, **args, observation_limit=1)
    with pytest.raises(ValueError, match="scope or completeness"):
        build_infrastructure_correlation(session, **args, request_history=report)
    report = build_test_history(session, **args, observation_limit=MAX_CORRELATION_RUNS)
    report["window"]["before"] = "2099-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="scope or completeness"):
        build_infrastructure_correlation(session, **args, request_history=report)


def test_api_reuses_full_request_history_and_paginates_only_returned_observations(
    client, session, monkeypatch
):
    import failurelens.api as api_module
    from failurelens import infrastructure

    _, _, execution = seed_workload(session, runs=210, tests_per_run=1)
    spy = Mock(wraps=api_module.build_test_history)
    monkeypatch.setattr(api_module, "build_test_history", spy)
    monkeypatch.setattr(
        infrastructure,
        "build_test_history",
        Mock(side_effect=AssertionError("duplicate history read")),
    )
    response = client.get(f"/api/v1/tests/{execution}/history?limit=17&offset=20")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["pagination"] == {
        "offset": 20,
        "limit": 17,
        "returned": 17,
        "total": 209,
    }
    assert len(report["observations"]) == 17
    assert report["sample_sizes"]["independent_runs"] == 209
    assert (
        report["infrastructure_correlations"]["sample_sizes"]["independent_runs"] == 209
    )
    assert spy.call_count == 1


def test_large_history_queries_do_not_load_unused_json_bodies(session):
    from sqlalchemy import event

    args = history_arguments(session)
    statements = []

    def record(_, __, statement, ___, ____, _____):
        statements.append(statement)

    event.listen(session.bind, "before_cursor_execute", record)
    try:
        report = build_test_history(
            session, **args, observation_limit=MAX_CORRELATION_RUNS
        )
        build_infrastructure_correlation(session, **args, request_history=report)
    finally:
        event.remove(session.bind, "before_cursor_execute", record)
    selected_columns = [
        statement.split("FROM", 1)[0]
        for statement in statements
        if statement.lstrip().startswith("SELECT")
    ]
    assert selected_columns
    assert all(
        "test_executions.details" not in columns
        and "runs.source_metadata" not in columns
        for columns in selected_columns
    )
    assert report["sample_sizes"]["independent_runs"] == 7
