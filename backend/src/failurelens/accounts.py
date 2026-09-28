"""Explicit, attributed account recovery and revocation; startup is never recovery."""
from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .auth import (Principal, _new_token, as_utc, hash_password, record_audit_event,
                   require_system_administrator, token_digest, verify_password)
from .models import AccountRecovery, AuthSession, User, utcnow


def lock_user(session: Session, user_id: str) -> User:
    row = session.scalar(select(User).where(User.id == user_id).with_for_update()
                         .execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, "user not found")
    return row


def active_actor(session: Session, principal: Principal) -> User:
    if principal.kind != "user" or not principal.user_id:
        raise HTTPException(403, "an authenticated human account is required")
    actor = lock_user(session, principal.user_id)
    current = session.get(AuthSession, principal.session_id, populate_existing=True) if principal.session_id else None
    if (not actor.is_active or current is None or current.user_id != actor.id or current.revoked_at is not None
            or as_utc(current.expires_at) <= utcnow()):
        raise HTTPException(401, "session is no longer active")
    return actor


def verify_actor(session: Session, principal: Principal, password: str) -> User:
    actor = active_actor(session, principal)
    if not verify_password(password, actor.password_hash):
        record_audit_event(session, principal, action="auth.reauthentication_denied",
                           resource_type="user", resource_id=actor.id, outcome="denied")
        session.commit()
        raise HTTPException(401, "current password is incorrect")
    return actor


def revoke_all(session: Session, user_id: str) -> None:
    session.execute(update(AuthSession).where(AuthSession.user_id == user_id,
                                             AuthSession.revoked_at.is_(None))
                    .values(revoked_at=utcnow()))


def invalidate_recovery(session: Session, user_id: str) -> None:
    session.execute(update(AccountRecovery).where(AccountRecovery.user_id == user_id,
                                                  AccountRecovery.consumed_at.is_(None))
                    .values(consumed_at=utcnow()))


def _admin_lock(session: Session, principal: Principal, target_id: str, password: str) -> User:
    require_system_administrator(principal)
    # A stable lock order serializes last-administrator protection and two concurrent
    # administrators operating on each other. No project administrator can use this.
    list(session.scalars(select(User).where(User.is_system_admin.is_(True))
                        .order_by(User.id).with_for_update()).all())
    if principal.kind != "demo":
        actor = verify_actor(session, principal, password)
        if not actor.is_system_admin:
            raise HTTPException(403, "system administrator role required")
    return lock_user(session, target_id)


def change_account(session: Session, principal: Principal, user_id: str, *, password: str,
                   active: bool, expected_version: int, reason: str) -> User:
    user = _admin_lock(session, principal, user_id, password)
    if user.lifecycle_version != expected_version:
        raise HTTPException(409, "account version conflict; refresh before retrying")
    if not active and user.is_system_admin and user.is_active:
        others = session.scalar(select(User.id).where(User.is_active.is_(True),
            User.is_system_admin.is_(True), User.id != user.id).limit(1))
        if others is None:
            raise HTTPException(409, "cannot deactivate the last active system administrator")
    user.is_active = active
    user.lifecycle_version += 1
    revoke_all(session, user.id)
    invalidate_recovery(session, user.id)
    record_audit_event(session, principal, action="auth.account_activated" if active else "auth.account_deactivated",
                       resource_type="user", resource_id=user.id, reason=reason,
                       details={"lifecycle_version": user.lifecycle_version})
    session.commit()
    return user


def issue_recovery(session: Session, principal: Principal, user_id: str, *, password: str,
                   expected_version: int, reason: str) -> tuple[User, AccountRecovery, str]:
    user = _admin_lock(session, principal, user_id, password)
    if user.lifecycle_version != expected_version:
        raise HTTPException(409, "account version conflict; refresh before retrying")
    if not user.is_active:
        raise HTTPException(409, "activate the account explicitly before issuing recovery")
    invalidate_recovery(session, user.id)
    revoke_all(session, user.id)
    # Invalidate the old password immediately so it cannot mint sessions during recovery.
    user.password_hash = hash_password(_new_token("invalidated"))
    user.lifecycle_version += 1
    raw = _new_token("flr")
    recovery = AccountRecovery(user_id=user.id, token_hash=token_digest(raw),
                               issued_by_user_id=principal.user_id,
                               expires_at=utcnow() + timedelta(minutes=15))
    session.add(recovery)
    record_audit_event(session, principal, action="auth.recovery_issued", resource_type="user",
                       resource_id=user.id, reason=reason,
                       details={"lifecycle_version": user.lifecycle_version})
    session.commit()
    return user, recovery, raw


def redeem_recovery(session: Session, raw_token: str, new_password: str) -> None:
    row = session.scalar(select(AccountRecovery).where(AccountRecovery.token_hash == token_digest(raw_token)))
    if row is None:
        raise HTTPException(400, "recovery token is invalid or expired")
    user = lock_user(session, row.user_id)
    session.refresh(row, with_for_update=True)
    if row.consumed_at is not None or as_utc(row.expires_at) <= utcnow() or not user.is_active:
        raise HTTPException(400, "recovery token is invalid or expired")
    user.password_hash = hash_password(new_password)
    user.lifecycle_version += 1
    invalidate_recovery(session, user.id)
    revoke_all(session, user.id)
    actor = Principal(kind="user", actor_id=user.id, display_name=user.display_name, user_id=user.id)
    record_audit_event(session, actor, action="auth.recovery_completed", resource_type="user", resource_id=user.id)
    session.commit()


def operator_recovery(session: Session, username: str, *, reason: str,
                      activate: bool = False) -> tuple[User, AccountRecovery, str]:
    """Explicit local database-operator recovery, never invoked by HTTP or startup."""
    from .auth import normalize_username
    user_id = session.scalar(select(User.id).where(User.username == normalize_username(username)))
    if user_id is None:
        raise ValueError("user not found; operator recovery cannot create an account")
    user = lock_user(session, user_id)
    if not user.is_active and not activate:
        raise ValueError("account is inactive; explicit --activate is required")
    if activate:
        user.is_active = True
    invalidate_recovery(session, user.id)
    revoke_all(session, user.id)
    user.password_hash = hash_password(_new_token("invalidated"))
    user.lifecycle_version += 1
    raw = _new_token("flr")
    recovery = AccountRecovery(user_id=user.id, token_hash=token_digest(raw),
                               expires_at=utcnow() + timedelta(minutes=15))
    session.add(recovery)
    record_audit_event(session, Principal(kind="system", actor_id="local-database-operator",
        display_name="Local database operator (not a verified web identity)"), action="auth.operator_recovery_issued",
        resource_type="user", resource_id=user.id, reason=reason,
        details={"activated_explicitly": activate, "lifecycle_version": user.lifecycle_version})
    session.commit()
    return user, recovery, raw
