from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import Settings, get_settings
from .db import get_session
from .models import (
    AuditEvent,
    AuthSession,
    IngestionToken,
    ProjectMembership,
    ProjectRole,
    User,
    utcnow,
)

_ROLE_ORDER: dict[ProjectRole, int] = {
    ProjectRole.viewer: 1,
    ProjectRole.reviewer: 2,
    ProjectRole.administrator: 3,
}


@dataclass(frozen=True, slots=True)
class Principal:
    kind: Literal["demo", "user", "ingestion_token", "system"]
    actor_id: str | None
    display_name: str
    user_id: str | None = None
    session_id: str | None = None
    project_id: str | None = None
    scopes: tuple[str, ...] = ()
    system_admin: bool = False

    @property
    def audit_kind(self) -> str:
        return self.kind


DEMO_PRINCIPAL = Principal(
    kind="demo",
    actor_id="demo-administrator",
    display_name="Synthetic demo administrator",
    system_admin=True,
)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_username(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized or len(normalized) > 240:
        raise ValueError("username must contain between 1 and 240 characters")
    return normalized


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    if len(password) > 1024:
        raise ValueError("password is too long")
    salt = os.urandom(16)
    n, r, p = 2**14, 8, 1
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=64
    )
    return f"scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n_text, r_text, p_text, salt_hex, digest_hex = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n_text),
            r=int(r_text),
            p=int(p_text),
            dklen=len(expected),
        )
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(candidate, expected)


def token_digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _new_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def create_user(
    session: Session,
    *,
    username: str,
    display_name: str,
    password: str,
    system_admin: bool = False,
) -> User:
    normalized = normalize_username(username)
    if session.scalar(select(User).where(User.username == normalized)) is not None:
        raise ValueError("username already exists")
    display = display_name.strip()
    if not display or len(display) > 240:
        raise ValueError("display name must contain between 1 and 240 characters")
    row = User(
        username=normalized,
        display_name=display,
        password_hash=hash_password(password),
        is_active=True,
        is_system_admin=system_admin,
    )
    session.add(row)
    session.flush()
    return row


def create_auth_session(
    session: Session,
    user: User,
    *,
    settings: Settings | None = None,
) -> tuple[AuthSession, str]:
    effective = settings or get_settings()
    raw_token = _new_token("fls")
    now = utcnow()
    row = AuthSession(
        user_id=user.id,
        token_prefix=raw_token[:16],
        token_hash=token_digest(raw_token),
        expires_at=now + timedelta(hours=effective.session_ttl_hours),
        last_used_at=now,
    )
    session.add(row)
    session.flush()
    return row, raw_token


def create_project_ingestion_token(
    session: Session,
    *,
    project_id: str,
    name: str,
    created_by_user_id: str | None,
    expires_at: datetime | None = None,
) -> tuple[IngestionToken, str]:
    token_name = name.strip()
    if not token_name or len(token_name) > 240:
        raise ValueError("token name must contain between 1 and 240 characters")
    raw_token = _new_token("fli")
    row = IngestionToken(
        project_id=project_id,
        name=token_name,
        token_prefix=raw_token[:16],
        token_hash=token_digest(raw_token),
        scopes=["ingestion:create"],
        created_by_user_id=created_by_user_id,
        expires_at=expires_at,
    )
    session.add(row)
    session.flush()
    return row, raw_token


def record_audit_event(
    session: Session,
    principal: Principal,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    project_id: str | None = None,
    reason: str | None = None,
    outcome: str = "succeeded",
    correlation_id: str | None = None,
    details: dict[str, object] | None = None,
) -> AuditEvent:
    row = AuditEvent(
        project_id=project_id,
        actor_kind=principal.audit_kind,
        actor_user_id=principal.user_id,
        actor_display=principal.display_name,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        reason=reason,
        correlation_id=correlation_id,
        details=details or {},
    )
    session.add(row)
    return row


def ensure_bootstrap_administrator(session: Session, settings: Settings) -> User | None:
    settings.validate_security()
    if settings.demo_mode:
        return None
    username = normalize_username(settings.bootstrap_admin_username or "")
    user = session.scalar(select(User).where(User.username == username))
    if user is None and session.scalar(select(User.id).limit(1)) is not None:
        return None
    if user is None:
        user = create_user(
            session,
            username=username,
            display_name=settings.bootstrap_admin_display_name,
            password=settings.bootstrap_admin_password or "",
            system_admin=True,
        )
        record_audit_event(
            session,
            Principal(
                kind="user",
                actor_id=user.id,
                display_name=user.display_name,
                user_id=user.id,
                system_admin=True,
            ),
            action="auth.bootstrap_administrator_created",
            resource_type="user",
            resource_id=user.id,
            details={"username": user.username},
        )
    session.commit()
    session.refresh(user)
    return user


def _extract_raw_token(request: Request, settings: Settings) -> str | None:
    authorization = request.headers.get("authorization", "").strip()
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not value.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid authorization header",
            )
        return value.strip()
    ingestion_header = request.headers.get("x-failurelens-token")
    if ingestion_header:
        return ingestion_header.strip()
    cookie = request.cookies.get(settings.session_cookie_name)
    return cookie.strip() if cookie else None


def _authenticate_session(session: Session, raw_token: str) -> Principal | None:
    row = session.scalar(
        select(AuthSession)
        .where(AuthSession.token_hash == token_digest(raw_token))
        .options(selectinload(AuthSession.user))
    )
    if row is None:
        return None
    now = utcnow()
    if row.revoked_at is not None or as_utc(row.expires_at) <= now:
        return None
    if not row.user.is_active:
        return None
    row.last_used_at = now
    session.flush()
    return Principal(
        kind="user",
        actor_id=row.user.id,
        display_name=row.user.display_name,
        user_id=row.user.id,
        session_id=row.id,
        system_admin=row.user.is_system_admin,
    )


def _authenticate_ingestion_token(session: Session, raw_token: str) -> Principal | None:
    row = session.scalar(
        select(IngestionToken).where(
            IngestionToken.token_hash == token_digest(raw_token)
        )
    )
    if row is None:
        return None
    now = utcnow()
    if row.revoked_at is not None:
        return None
    if row.expires_at is not None and as_utc(row.expires_at) <= now:
        return None
    row.last_used_at = now
    session.flush()
    return Principal(
        kind="ingestion_token",
        actor_id=row.id,
        display_name=f"Ingestion token: {row.name}",
        project_id=row.project_id,
        scopes=tuple(str(value) for value in row.scopes),
    )


def current_principal(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> Principal:
    settings = get_settings()
    raw_token = _extract_raw_token(request, settings)
    if raw_token:
        principal: Principal | None
        if raw_token.startswith("fls_"):
            principal = _authenticate_session(session, raw_token)
        elif raw_token.startswith("fli_"):
            principal = _authenticate_ingestion_token(session, raw_token)
        else:
            principal = _authenticate_session(session, raw_token)
            if principal is None:
                principal = _authenticate_ingestion_token(session, raw_token)
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="credential is invalid, expired, or revoked",
            )
        request.state.principal = principal
        return principal
    if settings.demo_mode:
        request.state.principal = DEMO_PRINCIPAL
        return DEMO_PRINCIPAL
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication required",
    )


def require_user(principal: Principal) -> None:
    if principal.kind == "ingestion_token":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ingestion credentials cannot access this operation",
        )


def require_system_administrator(principal: Principal) -> None:
    require_user(principal)
    if not principal.system_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="system administrator role required",
        )


def membership_for_project(
    session: Session, principal: Principal, project_id: str
) -> ProjectMembership | None:
    if principal.user_id is None:
        return None
    return session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == principal.user_id,
        )
    )


def require_project_role(
    session: Session,
    principal: Principal,
    project_id: str,
    minimum_role: ProjectRole = ProjectRole.viewer,
    *,
    allow_ingestion_scope: str | None = None,
) -> ProjectRole | None:
    if principal.kind == "ingestion_token":
        if principal.project_id != project_id:
            raise HTTPException(status_code=404, detail="project not found")
        if allow_ingestion_scope and allow_ingestion_scope in principal.scopes:
            return None
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ingestion credential does not authorize this operation",
        )
    if principal.system_admin:
        return ProjectRole.administrator
    membership = membership_for_project(session, principal, project_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="project not found")
    if _ROLE_ORDER[membership.role] < _ROLE_ORDER[minimum_role]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{minimum_role.value} project role required",
        )
    return membership.role


def visible_project_ids(session: Session, principal: Principal) -> list[str] | None:
    require_user(principal)
    if principal.system_admin:
        return None
    return list(
        session.scalars(
            select(ProjectMembership.project_id).where(
                ProjectMembership.user_id == principal.user_id
            )
        ).all()
    )
