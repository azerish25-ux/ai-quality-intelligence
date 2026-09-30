"""Real READ COMMITTED project-membership contention, never a SQLite substitute."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier
from time import monotonic, sleep

import pytest
from failurelens import models as m
from failurelens.retention import lock_project
from fastapi import HTTPException
from sqlalchemy import func, select, text
from test_membership_mutations import (
    change_actor,
    membership_audits,
    mutate,
    seed_memberships,
)

pytest_plugins = ("test_operations_postgres",)


def _bounded_transaction(session):
    session.execute(text("SET LOCAL lock_timeout = '8s'"))
    session.execute(text("SET LOCAL statement_timeout = '10s'"))
    assert session.scalar(text("SHOW transaction_isolation")) == "read committed"
    return session.scalar(text("SELECT pg_backend_pid()"))


def _wait_for_contention(factory, futures, pids):
    # Observe actual PostgreSQL waits. A missing application lock must fail the
    # final invariant, rather than making the test wait forever for that lock.
    deadline = monotonic() + 5
    with factory() as observer:
        _bounded_transaction(observer)
        while monotonic() < deadline:
            waiting = [
                future.done()
                or bool(
                    observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid})
                )
                for future, pid in zip(futures, pids, strict=True)
            ]
            if all(waiting):
                return
            sleep(0.01)
    raise AssertionError("membership contenders did not reach a bounded database wait")


def _attempt(factory, data, operation, actor, target, ready, barrier=None):
    with factory() as session:
        pid = _bounded_transaction(session)
        # Retain references across the wait to ensure cached membership, account
        # and credential objects cannot preserve old authorization afterward.
        cached = [
            session.get(m.User, actor.user_id),
            session.get(m.AuthSession, actor.session_id),
            session.scalar(
                select(m.ProjectMembership).where(
                    m.ProjectMembership.project_id == data.project_id,
                    m.ProjectMembership.user_id == actor.user_id,
                )
            ),
            session.get(m.ProjectMembership, target),
        ]
        ready.put((target, pid))
        if barrier is not None:
            barrier.wait(timeout=5)
        try:
            mutate(session, data, operation, actor=actor, target=target)
            status = (
                204 if operation == "delete" else 201 if operation == "create" else 200
            )
        except HTTPException as exc:
            session.rollback()
            status = exc.status_code
        assert cached
        assert session.scalar(text("SELECT 1")) == 1
        return status, target, operation


@pytest.mark.parametrize(
    "operations",
    [
        ("update", "update"),
        ("delete", "delete"),
        ("update", "delete"),
    ],
)
def test_postgres_concurrent_administrators_cannot_remove_the_last_one(
    pg_factory, operations
):
    factory, _ = pg_factory
    data = seed_memberships(factory)
    ready, barrier = Queue(), Barrier(2)
    with factory() as holder, ThreadPoolExecutor(max_workers=2) as executor:
        _bounded_transaction(holder)
        lock_project(holder, data.project_id)
        futures = [
            executor.submit(
                _attempt,
                factory,
                data,
                operation,
                member.principal,
                member.id,
                ready,
                barrier,
            )
            for operation, member in zip(
                operations, (data.first, data.second), strict=True
            )
        ]
        try:
            ready_pids = dict([ready.get(timeout=5), ready.get(timeout=5)])
            pids = [ready_pids[member.id] for member in (data.first, data.second)]
            # Both requests are in flight while the shared project boundary is
            # held. Before the repair, both count two admins, then block inserting
            # their audit FK; after release both mutations could commit.
            _wait_for_contention(factory, futures, pids)
        finally:
            holder.rollback()
        results = [future.result(timeout=15) for future in futures]
    successes = [result for result in results if result[0] in {200, 204}]
    assert len(successes) == 1, results
    assert sum(result[0] == 409 for result in results) == 1, results
    with factory() as observer:
        assert (
            observer.scalar(
                select(func.count())
                .select_from(m.ProjectMembership)
                .where(
                    m.ProjectMembership.project_id == data.project_id,
                    m.ProjectMembership.role == m.ProjectRole.administrator,
                )
            )
            == 1
        )
        audits = membership_audits(observer)
        assert len(audits) == 1
        _, target, operation = successes[0]
        assert audits[0].resource_id == target
        assert audits[0].action == f"project.membership_{operation}d"
        assert audits[0].outcome == "succeeded"
        for status, target, operation in results:
            row = observer.get(m.ProjectMembership, target)
            if status == 409:
                assert row.role == m.ProjectRole.administrator
            elif operation == "delete":
                assert row is None
            else:
                assert row.role == m.ProjectRole.reviewer


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
@pytest.mark.parametrize(
    "change, expected",
    [
        ("demoted", 403),
        ("removed", 404),
        ("disabled", 401),
        ("revoked", 401),
        ("expired", 401),
        ("system_role_lost", 403),
    ],
)
def test_postgres_membership_permission_is_rechecked_after_waiting(
    pg_factory, operation, change, expected
):
    factory, _ = pg_factory
    data = seed_memberships(factory, system_admin=change == "system_role_lost")
    ready = Queue()
    with factory() as holder, ThreadPoolExecutor(max_workers=1) as executor:
        _bounded_transaction(holder)
        lock_project(holder, data.project_id)
        future = executor.submit(
            _attempt,
            factory,
            data,
            operation,
            data.first.principal,
            data.viewer.id,
            ready,
        )
        try:
            _, pid = ready.get(timeout=5)
            _wait_for_contention(factory, [future], [pid])
            change_actor(holder, data, change)
            holder.commit()
        finally:
            holder.rollback()
        assert future.result(timeout=15)[0] == expected
    with factory() as observer:
        assert (
            observer.get(m.ProjectMembership, data.viewer.id).role
            == m.ProjectRole.viewer
        )
        assert (
            observer.scalar(
                select(m.ProjectMembership)
                .join(m.User, m.ProjectMembership.user_id == m.User.id)
                .where(m.User.username == data.newcomer)
            )
            is None
        )
        assert membership_audits(observer) == []
