"""Production bootstrap cannot replace or elevate existing accounts."""

import pytest
from failurelens.auth import (
    create_user,
    ensure_bootstrap_administrator,
    verify_password,
)
from failurelens.config import Settings
from failurelens.models import AuditEvent, User
from sqlalchemy import func, select

ORIGINAL_PASSWORD = "bootstrap-regression-password"
CHANGED_PASSWORD = "different-bootstrap-regression-password"


def configuration(username="initial-operator", password=ORIGINAL_PASSWORD):
    return Settings(
        demo_mode=False,
        bootstrap_admin_username=username,
        bootstrap_admin_password=password,
        bootstrap_admin_display_name="Configured Operator",
        session_cookie_secure=True,
    )


def test_production_bootstrap_creates_one_attributed_admin_and_never_resets_it(
    session,
):
    created = ensure_bootstrap_administrator(session, configuration())
    assert created is not None
    assert created.is_system_admin and created.is_active
    assert created.username == "initial-operator"
    assert created.display_name == "Configured Operator"
    assert verify_password(ORIGINAL_PASSWORD, created.password_hash)
    original_hash = created.password_hash
    repeated = ensure_bootstrap_administrator(
        session, configuration(password=CHANGED_PASSWORD)
    )
    assert repeated.id == created.id
    assert repeated.password_hash == original_hash
    assert not verify_password(CHANGED_PASSWORD, repeated.password_hash)
    assert session.scalar(select(func.count()).select_from(User)) == 1
    events = session.scalars(select(AuditEvent)).all()
    assert len(events) == 1
    event = events[0]
    assert event.action == "auth.bootstrap_administrator_created"
    assert event.actor_user_id == event.resource_id == created.id
    assert event.actor_kind == "user"
    assert event.actor_display == "Configured Operator"
    assert event.outcome == "succeeded"


@pytest.mark.parametrize("active", [True, False])
def test_existing_ordinary_account_cannot_be_promoted_or_reactivated_by_bootstrap(
    session, active
):
    existing = create_user(
        session,
        username="initial-operator",
        display_name="Existing Ordinary User",
        password=ORIGINAL_PASSWORD,
        system_admin=False,
    )
    existing.is_active = active
    session.commit()
    original_hash = existing.password_hash
    result = ensure_bootstrap_administrator(
        session, configuration(password=CHANGED_PASSWORD)
    )
    session.refresh(existing)
    assert result.id == existing.id
    assert existing.is_system_admin is False
    assert existing.is_active is active
    assert existing.display_name == "Existing Ordinary User"
    assert existing.password_hash == original_hash
    assert session.scalar(select(func.count()).select_from(User)) == 1
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_existing_differently_named_account_blocks_new_bootstrap_administrator(
    session,
):
    existing = create_user(
        session,
        username="ordinary-existing",
        display_name="Existing User",
        password=ORIGINAL_PASSWORD,
        system_admin=False,
    )
    session.commit()
    original_hash = existing.password_hash
    assert ensure_bootstrap_administrator(session, configuration()) is None
    session.refresh(existing)
    assert existing.is_system_admin is False and existing.is_active
    assert existing.password_hash == original_hash
    assert session.scalar(select(func.count()).select_from(User)) == 1
    assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0
