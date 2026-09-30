"""Membership input, stale authorization and transaction-boundary regressions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pytest
from failurelens import api
from failurelens import models as m
from failurelens.auth import DEMO_PRINCIPAL, Principal, create_auth_session, create_user
from failurelens.config import Settings
from failurelens.db import Base, create_database_engine
from failurelens.schemas import ProjectMembershipCreate, ProjectMembershipUpdate
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker


@dataclass(frozen=True)
class Member:
    id: str
    username: str
    principal: Principal


@dataclass(frozen=True)
class MembershipSetup:
    project_id: str
    first: Member
    second: Member
    viewer: Member
    newcomer: str


@pytest.fixture
def membership_factory(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'members.db'}")
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()


def seed_memberships(factory, *, system_admin=False):
    with factory() as session:
        project = m.Project(slug="members", name="Membership test")
        session.add(project)
        session.flush()
        members = []
        for index, role in enumerate(
            (
                m.ProjectRole.administrator,
                m.ProjectRole.administrator,
                m.ProjectRole.viewer,
            )
        ):
            user = create_user(
                session,
                username=f"member-{index}",
                display_name=f"Member {index}",
                password="membership-test-password",
                system_admin=system_admin and index == 0,
            )
            auth_session, _ = create_auth_session(
                session, user, settings=Settings(demo_mode=True)
            )
            membership = m.ProjectMembership(
                project_id=project.id, user_id=user.id, role=role
            )
            session.add(membership)
            session.flush()
            members.append(
                Member(
                    membership.id,
                    user.username,
                    Principal(
                        kind="user",
                        actor_id=user.id,
                        user_id=user.id,
                        display_name=user.display_name,
                        session_id=auth_session.id,
                        system_admin=user.is_system_admin,
                    ),
                )
            )
        newcomer = create_user(
            session,
            username="newcomer",
            display_name="New member",
            password="membership-test-password",
        )
        session.commit()
        return MembershipSetup(project.id, *members, newcomer.username)


def mutate(session, data, operation, *, actor=None, target=None):
    principal = actor or data.first.principal
    membership_id = target or data.viewer.id
    if operation == "create":
        return api.project_members_create(
            data.project_id,
            ProjectMembershipCreate(username=data.newcomer, role="viewer"),
            principal,
            session,
        )
    if operation == "update":
        return api.project_members_update(
            data.project_id,
            membership_id,
            ProjectMembershipUpdate(role="reviewer"),
            principal,
            session,
        )
    return api.project_members_delete(
        data.project_id, membership_id, principal, session
    )


def change_actor(session, data, change):
    if change == "demoted":
        session.get(m.ProjectMembership, data.first.id).role = m.ProjectRole.viewer
    elif change == "removed":
        session.delete(session.get(m.ProjectMembership, data.first.id))
    elif change == "disabled":
        session.get(m.User, data.first.principal.user_id).is_active = False
    elif change == "revoked":
        session.get(
            m.AuthSession, data.first.principal.session_id
        ).revoked_at = m.utcnow()
    elif change == "expired":
        session.get(m.AuthSession, data.first.principal.session_id).expires_at = (
            m.utcnow() - timedelta(seconds=1)
        )
    elif change == "system_role_lost":
        session.get(m.User, data.first.principal.user_id).is_system_admin = False
        session.get(m.ProjectMembership, data.first.id).role = m.ProjectRole.viewer
    else:
        raise AssertionError(change)


def membership_audits(session):
    return list(
        session.scalars(
            select(m.AuditEvent).where(m.AuditEvent.action.like("project.membership_%"))
        )
    )


@pytest.mark.parametrize("username", [" ", "\t\n", "ß" * 121])
def test_membership_username_normalization_returns_422_without_mutation(
    request_client, session_factory, username
):
    with session_factory.begin() as setup:
        project = m.Project(slug="invalid-member", name="Invalid member")
        setup.add(project)
        setup.flush()
        project_id = project.id
    response = request_client.post(
        f"/api/v1/projects/{project_id}/members",
        json={"username": username, "role": "viewer"},
    )
    assert response.status_code == 422, response.text
    assert (
        response.json()["detail"]
        == "username must contain between 1 and 240 characters"
    )
    with session_factory() as observer:
        assert (
            observer.scalar(select(func.count()).select_from(m.ProjectMembership)) == 0
        )
        assert membership_audits(observer) == []
    assert (
        request_client.get(f"/api/v1/projects/{project_id}/members").status_code == 200
    )


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
def test_membership_revalidates_actor_after_authorization(
    membership_factory, monkeypatch, operation, change, expected
):
    data = seed_memberships(
        membership_factory, system_admin=change == "system_role_lost"
    )
    original = api._lock_membership_administrator

    def authorized_then_changed(session, principal, project_id):
        # Model prior permission reads before the serialization boundary; a
        # competing SQLite writer cannot commit after the reservation is held.
        api._require_project(
            session, principal, project_id, m.ProjectRole.administrator
        )
        with membership_factory.begin() as concurrent:
            change_actor(concurrent, data, change)
        return original(session, principal, project_id)

    monkeypatch.setattr(api, "_lock_membership_administrator", authorized_then_changed)
    with membership_factory() as session:
        # Keep stale ORM objects alive to expose identity-map reuse as well as the
        # immutable principal's old system-administrator flag.
        cached = [
            session.get(m.ProjectMembership, data.first.id),
            session.get(m.User, data.first.principal.user_id),
            session.get(m.AuthSession, data.first.principal.session_id),
        ]
        with pytest.raises(HTTPException) as denied:
            mutate(session, data, operation)
        assert denied.value.status_code == expected
        assert cached
        session.rollback()
        assert session.scalar(text("SELECT 1")) == 1
    with membership_factory() as observer:
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


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_last_project_administrator_is_preserved(membership_factory, operation):
    data = seed_memberships(membership_factory)
    with membership_factory.begin() as session:
        session.delete(session.get(m.ProjectMembership, data.second.id))
    with membership_factory() as session:
        with pytest.raises(HTTPException) as denied:
            mutate(session, data, operation, target=data.first.id)
        assert denied.value.status_code == 409
        session.rollback()
        assert session.scalar(text("SELECT 1")) == 1
    with membership_factory() as observer:
        assert (
            observer.get(m.ProjectMembership, data.first.id).role
            == m.ProjectRole.administrator
        )
        assert membership_audits(observer) == []


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_membership_target_role_is_refreshed_before_last_admin_check(
    membership_factory, monkeypatch, operation
):
    data = seed_memberships(membership_factory, system_admin=True)
    original = api._lock_membership_administrator

    def authorized_then_transferred(session, principal, project_id):
        api._require_project(
            session, principal, project_id, m.ProjectRole.administrator
        )
        with membership_factory.begin() as concurrent:
            for membership_id in (data.first.id, data.second.id):
                concurrent.get(
                    m.ProjectMembership, membership_id
                ).role = m.ProjectRole.viewer
            concurrent.get(
                m.ProjectMembership, data.viewer.id
            ).role = m.ProjectRole.administrator
        return original(session, principal, project_id)

    monkeypatch.setattr(
        api, "_lock_membership_administrator", authorized_then_transferred
    )
    with membership_factory() as session:
        target = session.get(m.ProjectMembership, data.viewer.id)
        assert target.role == m.ProjectRole.viewer
        with pytest.raises(HTTPException) as denied:
            mutate(session, data, operation)
        assert denied.value.status_code == 409
        session.rollback()
    with membership_factory() as observer:
        assert (
            observer.get(m.ProjectMembership, data.viewer.id).role
            == m.ProjectRole.administrator
        )
        assert membership_audits(observer) == []


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_membership_admin_count_retains_existing_inactive_account_semantics(
    membership_factory, operation
):
    data = seed_memberships(membership_factory)
    with membership_factory.begin() as session:
        session.get(m.User, data.second.principal.user_id).is_active = False
    with membership_factory() as session:
        mutate(session, data, operation, target=data.first.id)
    with membership_factory() as observer:
        assert (
            observer.get(m.ProjectMembership, data.second.id).role
            == m.ProjectRole.administrator
        )
        assert len(membership_audits(observer)) == 1


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
@pytest.mark.parametrize("actor_kind", ["project_admin", "system_admin", "demo"])
def test_membership_success_preserves_actor_and_audit_semantics(
    membership_factory, operation, actor_kind
):
    data = seed_memberships(
        membership_factory, system_admin=actor_kind == "system_admin"
    )
    actor = DEMO_PRINCIPAL if actor_kind == "demo" else data.first.principal
    if actor_kind == "system_admin":
        with membership_factory.begin() as session:
            session.delete(session.get(m.ProjectMembership, data.first.id))
    with membership_factory() as session:
        result = mutate(session, data, operation, actor=actor)
    with membership_factory() as observer:
        audits = membership_audits(observer)
        assert len(audits) == 1
        audit = audits[0]
        assert audit.actor_kind == actor.kind
        assert audit.actor_user_id == actor.user_id
        assert audit.actor_display == actor.display_name
        assert audit.project_id == data.project_id
        assert audit.outcome == "succeeded"
        assert audit.action == f"project.membership_{operation}d"
        if operation == "create":
            row = observer.get(m.ProjectMembership, result.id)
            assert row.granted_by_user_id == actor.user_id
            assert row.role == m.ProjectRole.viewer
        elif operation == "update":
            assert (
                observer.get(m.ProjectMembership, data.viewer.id).role
                == m.ProjectRole.reviewer
            )
            assert audit.details["from"] == "viewer"
            assert audit.details["to"] == "reviewer"
        else:
            assert observer.get(m.ProjectMembership, data.viewer.id) is None


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_foreign_membership_id_is_not_disclosed(membership_factory, operation):
    data = seed_memberships(membership_factory)
    with membership_factory.begin() as session:
        foreign = m.Project(slug="foreign", name="Foreign project")
        session.add(foreign)
        session.flush()
        row = m.ProjectMembership(
            project_id=foreign.id,
            user_id=data.viewer.principal.user_id,
            role=m.ProjectRole.viewer,
        )
        session.add(row)
        session.flush()
        foreign_id = row.id
    with membership_factory() as session:
        with pytest.raises(HTTPException) as denied:
            mutate(session, data, operation, target=foreign_id)
        assert denied.value.status_code == 404
        assert denied.value.detail == "membership not found"
        session.rollback()
    with membership_factory() as observer:
        assert (
            observer.get(m.ProjectMembership, foreign_id).role == m.ProjectRole.viewer
        )
        assert membership_audits(observer) == []


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_failed_membership_commit_rolls_back_mutation_and_audit(
    membership_factory, monkeypatch, operation
):
    data = seed_memberships(membership_factory)
    with membership_factory() as session:
        original = session.commit

        def fail_commit():
            session.flush()
            raise RuntimeError("controlled membership commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="controlled membership commit failure"):
            mutate(session, data, operation)
        session.rollback()
        assert session.scalar(text("SELECT 1")) == 1
        with membership_factory() as observer:
            assert (
                observer.get(m.ProjectMembership, data.viewer.id).role
                == m.ProjectRole.viewer
            )
            assert (
                observer.scalar(select(func.count()).select_from(m.ProjectMembership))
                == 3
            )
            assert membership_audits(observer) == []
        monkeypatch.setattr(session, "commit", original)
        mutate(session, data, operation)
    with membership_factory() as observer:
        assert len(membership_audits(observer)) == 1
