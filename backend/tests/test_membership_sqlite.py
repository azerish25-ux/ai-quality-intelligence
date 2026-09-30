"""Real file-backed SQLite membership serialization and transaction ownership."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier, Lock

import pytest
from failurelens import api
from failurelens import models as m
from failurelens.auth import DEMO_PRINCIPAL
from fastapi import HTTPException
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import OperationalError
from test_membership_mutations import (
    membership_audits,
    mutate,
    seed_memberships,
)

pytest_plugins = ("test_membership_mutations",)


@pytest.mark.parametrize(
    "operations", [("update", "update"), ("delete", "delete"), ("update", "delete")]
)
def test_sqlite_concurrent_administrators_preserve_one_admin(
    membership_factory, operations
):
    factory = membership_factory
    data = seed_memberships(factory)
    engine = factory.kw["bind"]
    ready, barrier, guard = Queue(), Barrier(2), Lock()
    seen = set()

    def checkpoint(connection):
        target = connection.info.get("membership_contender")
        if target is not None:
            with guard:
                if target not in seen:
                    seen.add(target)
                    ready.put(target)

    def before_execute(connection, cursor, statement, parameters, context, many):
        compiled = context.compiled
        table = getattr(getattr(compiled, "statement", None), "table", None)
        if context.isupdate and getattr(table, "name", None) == "projects":
            checkpoint(connection)

    def after_execute(connection, cursor, statement, parameters, context, many):
        # Before the repair, both real COUNTs finish while the holder prevents
        # either mutation from writing. With the repair, both handlers instead
        # reach their project write reservation before any authorization/count.
        if statement.upper().startswith("SELECT COUNT(PROJECT_MEMBERSHIPS.ID)"):
            checkpoint(connection)

    def attempt(member, operation):
        with factory() as session:
            session.connection().info["membership_contender"] = member.id
            session.execute(text("PRAGMA busy_timeout = 5000"))
            barrier.wait(timeout=3)
            try:
                mutate(
                    session, data, operation, actor=member.principal, target=member.id
                )
                status = 204 if operation == "delete" else 200
            except HTTPException as exc:
                session.rollback()
                status = exc.status_code
            assert session.scalar(text("SELECT 1")) == 1
            return status, member.id, operation

    event.listen(engine, "before_cursor_execute", before_execute)
    event.listen(engine, "after_cursor_execute", after_execute)
    try:
        with factory() as holder, ThreadPoolExecutor(max_workers=2) as executor:
            holder.execute(
                update(m.Project)
                .where(m.Project.id == data.project_id)
                .values(id=m.Project.id)
            )
            futures = [
                executor.submit(attempt, member, operation)
                for member, operation in zip(
                    (data.first, data.second), operations, strict=True
                )
            ]
            try:
                assert {ready.get(timeout=3), ready.get(timeout=3)} == {
                    data.first.id,
                    data.second.id,
                }
            finally:
                holder.rollback()
            results = [future.result(timeout=10) for future in futures]
    finally:
        event.remove(engine, "before_cursor_execute", before_execute)
        event.remove(engine, "after_cursor_execute", after_execute)
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


def test_sqlite_membership_reservation_preserves_caller_rollback_and_project(
    membership_factory,
):
    data = seed_memberships(membership_factory)
    with membership_factory() as session:
        project = session.get(m.Project, data.project_id)
        original = (project.id, project.slug, project.name, project.created_at)
        pending = m.Project(slug="caller-owned", name="Caller-owned transaction")
        session.add(pending)
        session.flush()
        pending_id = pending.id
        api._lock_membership_administrator(session, DEMO_PRINCIPAL, data.project_id)
        assert session.in_transaction()
        session.rollback()
        assert session.scalar(text("SELECT 1")) == 1
    with membership_factory() as observer:
        assert observer.get(m.Project, pending_id) is None
        project = observer.get(m.Project, data.project_id)
        assert (project.id, project.slug, project.name, project.created_at) == original
        assert membership_audits(observer) == []


@pytest.mark.parametrize("exists", [True, False])
def test_sqlite_membership_reservation_preserves_foreign_project_privacy(
    membership_factory, exists
):
    data = seed_memberships(membership_factory)
    with membership_factory.begin() as setup:
        foreign = m.Project(slug="foreign", name="Foreign project")
        setup.add(foreign)
        setup.flush()
        project_id = foreign.id if exists else "missing-project"
    with membership_factory() as session:
        with pytest.raises(HTTPException) as denied:
            api._lock_membership_administrator(
                session, data.first.principal, project_id
            )
        assert denied.value.status_code == 404
        assert denied.value.detail == "project not found"
        session.rollback()
    with membership_factory() as observer:
        assert membership_audits(observer) == []


def test_sqlite_stale_read_snapshot_fails_without_resetting_the_transaction(
    membership_factory,
):
    factory = membership_factory
    data = seed_memberships(factory)
    engine = factory.kw["bind"]
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA journal_mode = WAL")) == "wal"
    count = (
        select(func.count())
        .select_from(m.ProjectMembership)
        .where(
            m.ProjectMembership.project_id == data.project_id,
            m.ProjectMembership.role == m.ProjectRole.administrator,
        )
    )
    with factory() as reader:
        reader.execute(text("PRAGMA busy_timeout = 100"))
        reader.execute(text("BEGIN"))
        assert reader.scalar(count) == 2
        with factory.begin() as writer:
            writer.get(m.ProjectMembership, data.first.id).role = m.ProjectRole.viewer
        with pytest.raises(OperationalError) as denied:
            mutate(
                reader,
                data,
                "update",
                actor=data.second.principal,
                target=data.second.id,
            )
        assert denied.value.orig.sqlite_errorcode == sqlite3.SQLITE_BUSY_SNAPSHOT
        assert reader.in_transaction()
        assert reader.scalar(count) == 2
        reader.rollback()
        assert reader.scalar(count) == 1
    with factory() as observer:
        assert (
            observer.get(m.ProjectMembership, data.second.id).role
            == m.ProjectRole.administrator
        )
        assert membership_audits(observer) == []
