"""Real concurrent policy creation; skip explicitly without PostgreSQL."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest
from failurelens.models import PerformancePolicy, Project
from failurelens.performance import create_performance_policy
from failurelens.service import create_project
from sqlalchemy import event, select, text
from test_performance_policy import (
    CONFLICT_MESSAGE,
    POLICY_CHANGES,
    _persisted_payload,
    policy_request,
)

pytest_plugins = ("test_operations_postgres",)


def _race_creators(factory, requests):
    with factory() as session:
        project_id = create_project(
            session, "policy-race", "Concurrent policy creation"
        ).id

    barrier, guard, violations = Barrier(2), Lock(), []
    engine = factory.kw["bind"]

    def record_constraint_violation(context):
        error = context.original_exception
        if getattr(error, "sqlstate", None) == "23505":
            with guard:
                violations.append(error.diag.constraint_name)

    def limit_transaction(session, transaction, connection):
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(text("SET LOCAL statement_timeout = '10s'"))

    def synchronize_inserts(session, flush_context, instances):
        assert any(isinstance(row, PerformancePolicy) for row in session.new)
        # Both real SELECTs have observed no policy before either INSERT runs.
        # The unique constraint must choose a winner; ordinary repeat lookup
        # alone cannot make this test pass.
        barrier.wait(timeout=10)

    def create(request):
        with factory() as session:
            event.listen(session, "after_begin", limit_transaction)
            project = session.get(Project, project_id)
            assert project is not None
            event.listen(session, "before_flush", synchronize_inserts, once=True)
            try:
                row = create_performance_policy(session, project, request)
                result = {
                    "status": "created",
                    "id": row.id,
                    "payload": _persisted_payload(row),
                }
            except ValueError as exc:
                result = {"status": "conflict", "message": str(exc)}
            assert session.is_active
            # Prove rollback recovery leaves both sessions usable, including
            # the transaction that reports a content conflict.
            assert len(session.scalars(select(PerformancePolicy)).all()) == 1
            return result

    event.listen(engine, "handle_error", record_constraint_violation)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(create, request) for request in requests]
            try:
                results = [future.result(timeout=30) for future in futures]
            finally:
                barrier.abort()
    finally:
        event.remove(engine, "handle_error", record_constraint_violation)

    assert violations == ["uq_performance_policy_version"]
    with factory() as session:
        rows = session.scalars(select(PerformancePolicy)).all()
        assert len(rows) == 1
        persisted = {
            "id": rows[0].id,
            "project_id": rows[0].project_id,
            "payload": _persisted_payload(rows[0]),
        }
    assert persisted["project_id"] == project_id
    return results, persisted


def test_postgres_equivalent_policy_creators_share_one_immutable_row(pg_factory):
    factory, _ = pg_factory
    original = policy_request()
    equivalent = policy_request(
        required_dimensions=[" environment ", "repository", "environment"],
        direction_overrides={
            "requests": "higher_is_better",
            "latency": "lower_is_better",
        },
    )

    results, persisted = _race_creators(factory, [original, equivalent])

    assert [result["status"] for result in results] == ["created", "created"]
    assert {result["id"] for result in results} == {persisted["id"]}
    assert persisted["payload"] == original.model_dump(mode="json")
    assert all(result["payload"] == persisted["payload"] for result in results)


@pytest.mark.parametrize("changes", POLICY_CHANGES)
def test_postgres_different_policy_creators_reject_loser_without_mutating_winner(
    pg_factory, changes
):
    factory, _ = pg_factory
    requests = [policy_request(), policy_request(**changes)]

    results, persisted = _race_creators(factory, requests)

    assert sorted(result["status"] for result in results) == ["conflict", "created"]
    for request, result in zip(requests, results, strict=True):
        if result["status"] == "created":
            assert result["id"] == persisted["id"]
            assert result["payload"] == persisted["payload"]
            assert persisted["payload"] == request.model_dump(mode="json")
        else:
            assert result["message"] == CONFLICT_MESSAGE
            assert persisted["payload"] != request.model_dump(mode="json")
