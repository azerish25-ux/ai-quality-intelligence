"""Account and project-governance operations with server-side authorization."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import accounts, retention
from .auth import (
    Principal,
    as_utc,
    create_auth_session,
    current_principal,
    hash_password,
    record_audit_event,
    require_project_role,
    require_system_administrator,
)
from .config import get_settings
from .db import get_session
from .governance import audit_query, review_queue_page
from .models import (
    AuditEvent,
    AuthSession,
    Category,
    Job,
    ProjectRole,
    RetentionPolicy,
    RetentionTombstone,
    User,
    utcnow,
)
from .schemas import (
    AdminAccountChange,
    AuditEventRead,
    AuditPage,
    PasswordChange,
    RecoveryCreate,
    RecoveryCreated,
    RecoveryRedeem,
    RetentionCleanupCreate,
    RetentionCleanupRead,
    RetentionPolicyChange,
    RetentionPolicyRead,
    RetentionPreview,
    ReviewQueuePage,
    SessionRead,
    UserRead,
)

router = APIRouter(prefix="/api/v1")
PageSize = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


class Reauthenticate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(default="", max_length=1024)
    reason: str = Field(min_length=1, max_length=2000)


class AuditExport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(default="", max_length=160)
    outcome: str = Field(default="", max_length=80)
    search: str = Field(default="", max_length=200)
    sort: Literal["newest", "oldest"] = "newest"


def _human(principal: Principal) -> str:
    if principal.kind != "user" or not principal.user_id:
        raise HTTPException(403, "sign in with a human account to manage sessions")
    return principal.user_id


def _session_read(row: AuthSession, current_id: str | None) -> SessionRead:
    state: Literal["active", "expired", "revoked"] = (
        "revoked"
        if row.revoked_at
        else "expired"
        if as_utc(row.expires_at) <= utcnow()
        else "active"
    )
    return SessionRead(
        id=row.id,
        user_id=row.user_id,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        current=row.id == current_id,
        state=state,
    )


@router.get("/auth/sessions", response_model=list[SessionRead])
def my_sessions(
    limit: PageSize = 25,
    offset: Offset = 0,
    *,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    user_id = _human(principal)
    return [
        _session_read(row, principal.session_id)
        for row in session.scalars(
            select(AuthSession)
            .where(AuthSession.user_id == user_id)
            .order_by(AuthSession.created_at.desc(), AuthSession.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ]


@router.post("/auth/sessions/{session_id}/revoke", status_code=204)
def revoke_session(
    session_id: str,
    response: Response,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    session.rollback()  # start a fresh handler transaction before ordered account locks
    user_id = _human(principal)
    accounts.active_actor(session, principal)
    row = session.scalar(
        select(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404, "session not found")
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        record_audit_event(
            session,
            principal,
            action="auth.session_revoked",
            resource_type="auth_session",
            resource_id=row.id,
        )
    session.commit()
    if session_id == principal.session_id:
        response.delete_cookie(get_settings().session_cookie_name, path="/")
    response.status_code = 204
    return response


@router.get("/users/{user_id}/sessions", response_model=list[SessionRead])
def user_sessions(
    user_id: str,
    limit: PageSize = 25,
    offset: Offset = 0,
    *,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    require_system_administrator(principal)
    if session.get(User, user_id) is None:
        raise HTTPException(404, "user not found")
    return [
        _session_read(row, principal.session_id)
        for row in session.scalars(
            select(AuthSession)
            .where(AuthSession.user_id == user_id)
            .order_by(AuthSession.created_at.desc(), AuthSession.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ]


@router.post("/users/{user_id}/sessions/revoke", status_code=204)
def revoke_user_sessions(
    user_id: str,
    body: Reauthenticate,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    session.rollback()  # start a fresh handler transaction before ordered account locks
    accounts._admin_lock(session, principal, user_id, body.current_password)
    accounts.revoke_all(session, user_id)
    record_audit_event(
        session,
        principal,
        action="auth.all_sessions_revoked",
        resource_type="user",
        resource_id=user_id,
        reason=body.reason,
    )
    session.commit()
    return Response(status_code=204)


@router.post("/auth/password", status_code=204)
def change_password(
    body: PasswordChange,
    response: Response,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    session.rollback()  # start a fresh handler transaction before ordered account locks
    user = accounts.verify_actor(session, principal, body.current_password)
    user.password_hash = hash_password(body.new_password)
    user.lifecycle_version += 1
    accounts.revoke_all(session, user.id)
    accounts.invalidate_recovery(session, user.id)
    _fresh, raw = create_auth_session(session, user, settings=get_settings())
    record_audit_event(
        session,
        principal,
        action="auth.password_changed",
        resource_type="user",
        resource_id=user.id,
        details={"lifecycle_version": user.lifecycle_version},
    )
    session.commit()
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        raw,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
        max_age=settings.session_ttl_hours * 3600,
    )
    response.status_code = 204
    return response


@router.patch("/users/{user_id}", response_model=UserRead)
def update_account(
    user_id: str,
    body: AdminAccountChange,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    session.rollback()  # start a fresh handler transaction before ordered account locks
    return accounts.change_account(
        session,
        principal,
        user_id,
        password=body.current_password,
        active=body.is_active,
        expected_version=body.expected_version,
        reason=body.reason,
    )


@router.post(
    "/users/{user_id}/recovery", response_model=RecoveryCreated, status_code=201
)
def create_recovery(
    user_id: str,
    body: RecoveryCreate,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    session.rollback()  # start a fresh handler transaction before ordered account locks
    user, recovery, token = accounts.issue_recovery(
        session,
        principal,
        user_id,
        password=body.current_password,
        expected_version=body.expected_version,
        reason=body.reason,
    )
    return RecoveryCreated(
        token=token,
        expires_at=recovery.expires_at,
        user_id=user.id,
        lifecycle_version=user.lifecycle_version,
    )


@router.post("/auth/recovery", status_code=204)
def finish_recovery(
    body: RecoveryRedeem, session: Annotated[Session, Depends(get_session)]
):
    accounts.redeem_recovery(session, body.token, body.new_password)
    response = Response(status_code=204)
    response.delete_cookie(get_settings().session_cookie_name, path="/")
    return response


@router.get("/projects/{project_id}/review-queue/page", response_model=ReviewQueuePage)
def review_page(
    project_id: str,
    status: Literal["pending", "reviewed", "all", "needs_more_evidence"] = "pending",
    category: Category | None = None,
    search: Annotated[str, Query(max_length=200)] = "",
    sort: Literal["newest", "oldest", "severity", "test"] = "newest",
    limit: PageSize = 25,
    offset: Offset = 0,
    *,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    require_project_role(session, principal, project_id, ProjectRole.reviewer)
    return review_queue_page(
        session,
        project_id,
        status=status,
        category=category.value if category else None,
        search=search,
        sort=sort,
        limit=limit,
        offset=offset,
    )


def _policy_schema(session: Session, project_id: str) -> RetentionPolicyRead:
    policy = retention.policy_for(session, project_id)
    value = RetentionPolicyRead.model_validate(policy)
    session.commit()
    return value


@router.get("/projects/{project_id}/retention", response_model=RetentionPolicyRead)
def get_retention(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    require_project_role(session, principal, project_id)
    return _policy_schema(session, project_id)


def _proposed_policy(project_id: str, body: RetentionPolicyChange) -> RetentionPolicy:
    if body.source_days > body.evidence_days:
        raise HTTPException(422, "restricted originals must not outlive safe evidence")
    return RetentionPolicy(
        project_id=project_id,
        version=body.expected_version + 1,
        **body.model_dump(exclude={"reason", "expected_version"}),
    )


@router.post(
    "/projects/{project_id}/retention/preview", response_model=RetentionPreview
)
def preview_policy(
    project_id: str,
    body: RetentionPolicyChange,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    require_project_role(session, principal, project_id, ProjectRole.administrator)
    policy = retention.policy_for(session, project_id)
    if policy.version != body.expected_version:
        raise HTTPException(409, "retention policy changed; reload settings")
    result = retention.preview(
        session, project_id, proposed=_proposed_policy(project_id, body)
    )
    session.commit()
    return result


@router.put("/projects/{project_id}/retention", response_model=RetentionPolicyRead)
def set_retention(
    project_id: str,
    body: RetentionPolicyChange,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    require_project_role(session, principal, project_id, ProjectRole.administrator)
    retention.lock_project(session, project_id)
    proposed = _proposed_policy(project_id, body)
    policy = retention.policy_for(session, project_id)
    session.refresh(policy, with_for_update=True)
    if policy.version != body.expected_version:
        raise HTTPException(409, "retention policy changed; reload settings")
    for field in (
        "source_days",
        "evidence_days",
        "audit_days",
        "export_enabled",
        "export_max_rows",
    ):
        setattr(policy, field, getattr(proposed, field))
    policy.version += 1
    policy.updated_at = utcnow()
    record_audit_event(
        session,
        principal,
        project_id=project_id,
        action="retention.policy_changed",
        resource_type="retention_policy",
        resource_id=project_id,
        reason=body.reason,
        details={
            "version": policy.version,
            "source_days": policy.source_days,
            "evidence_days": policy.evidence_days,
            "audit_days": policy.audit_days,
            "export_enabled": policy.export_enabled,
        },
    )
    session.commit()
    return RetentionPolicyRead.model_validate(policy)


@router.get("/projects/{project_id}/retention/preview", response_model=RetentionPreview)
def preview_cleanup(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    require_project_role(session, principal, project_id, ProjectRole.administrator)
    result = retention.preview(session, project_id)
    session.commit()
    return result


def _job_read(job: Job) -> RetentionCleanupRead:
    return RetentionCleanupRead(
        job_id=job.id,
        state=job.state.value,
        policy_version=job.payload["policy_version"],
        progress=job.payload.get("progress", {}),
        error_code=job.last_error,
    )


@router.post(
    "/projects/{project_id}/retention/cleanup",
    response_model=RetentionCleanupRead,
    status_code=202,
)
def queue_cleanup(
    project_id: str,
    body: RetentionCleanupCreate,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    require_project_role(session, principal, project_id, ProjectRole.administrator)
    retention.lock_project(session, project_id)
    if as_utc(body.as_of) < utcnow() - timedelta(minutes=15):
        raise HTTPException(409, "preview expired; preview cleanup again")
    proof = retention.preview(session, project_id, as_of=body.as_of)
    if (
        body.expected_version != proof.policy_version
        or body.confirmation_digest != proof.confirmation_digest
    ):
        raise HTTPException(
            409, "retention policy or candidate set changed; preview cleanup again"
        )
    return _job_read(retention.enqueue(session, project_id, proof, principal))


@router.get(
    "/projects/{project_id}/retention/jobs", response_model=list[RetentionCleanupRead]
)
def retention_jobs(
    project_id: str,
    limit: PageSize = 25,
    offset: Offset = 0,
    *,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    require_project_role(session, principal, project_id, ProjectRole.administrator)
    return [
        _job_read(row)
        for row in session.scalars(
            select(Job)
            .where(
                Job.project_id == project_id, Job.kind == retention.RETENTION_JOB_KIND
            )
            .order_by(Job.created_at.desc(), Job.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ]


@router.get(
    "/projects/{project_id}/retention/jobs/{job_id}",
    response_model=RetentionCleanupRead,
)
def retention_job(
    project_id: str,
    job_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    require_project_role(session, principal, project_id, ProjectRole.administrator)
    job = session.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.project_id == project_id,
            Job.kind == retention.RETENTION_JOB_KIND,
        )
    )
    if job is None:
        raise HTTPException(404, "cleanup job not found")
    return _job_read(job)


@router.get("/projects/{project_id}/retention/tombstones")
def tombstones(
    project_id: str,
    limit: PageSize = 25,
    offset: Offset = 0,
    *,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    require_project_role(session, principal, project_id)
    rows = session.scalars(
        select(RetentionTombstone)
        .where(RetentionTombstone.project_id == project_id)
        .order_by(RetentionTombstone.expired_at.desc(), RetentionTombstone.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [
        {
            "id": r.id,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "policy_version": r.policy_version,
            "reason": r.reason,
            "expired_at": r.expired_at,
        }
        for r in rows
    ]


@router.get("/projects/{project_id}/audit-events/page", response_model=AuditPage)
def audit_page(
    project_id: str,
    action: Annotated[str, Query(max_length=160)] = "",
    outcome: Annotated[str, Query(max_length=80)] = "",
    search: Annotated[str, Query(max_length=200)] = "",
    sort: Literal["newest", "oldest"] = "newest",
    limit: PageSize = 25,
    offset: Offset = 0,
    *,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    require_project_role(session, principal, project_id, ProjectRole.reviewer)
    query = audit_query(
        project_id, action=action, outcome=outcome, search=search, sort=sort
    )
    policy = retention.policy_for(session, project_id)
    result = AuditPage(
        items=[
            AuditEventRead.model_validate(row)
            for row in session.scalars(query.offset(offset).limit(limit))
        ],
        total=session.scalar(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
        or 0,
        limit=limit,
        offset=offset,
        actions=list(
            session.scalars(
                select(AuditEvent.action)
                .where(AuditEvent.project_id == project_id)
                .distinct()
                .order_by(AuditEvent.action)
            )
        ),
        outcomes=list(
            session.scalars(
                select(AuditEvent.outcome)
                .where(AuditEvent.project_id == project_id)
                .distinct()
                .order_by(AuditEvent.outcome)
            )
        ),
        export_enabled=policy.export_enabled,
    )
    session.commit()
    return result


def _csv_cell(value) -> str:
    text = str(value) if value is not None else ""
    # Excel also treats formulas after whitespace/control characters as active.
    return (
        "'" + text
        if text.lstrip(" \t\r\n\ufeff").startswith(("=", "+", "-", "@"))
        else text
    )


@router.post("/projects/{project_id}/audit-events/export")
def export_audit(
    project_id: str,
    body: AuditExport,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    require_project_role(session, principal, project_id, ProjectRole.administrator)
    retention.lock_project(session, project_id)
    policy = retention.policy_for(session, project_id)
    if not policy.export_enabled:
        raise HTTPException(403, "audit export is disabled by project policy")
    query = audit_query(project_id, **body.model_dump())
    rows = list(session.scalars(query.limit(policy.export_max_rows + 1)))
    if len(rows) > policy.export_max_rows:
        raise HTTPException(413, "export exceeds policy row limit; narrow the filters")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    fields = (
        "created_at",
        "actor_display",
        "action",
        "outcome",
        "resource_type",
        "resource_id",
        "reason",
    )
    writer.writerow(fields)
    for row in rows:
        writer.writerow([_csv_cell(getattr(row, field)) for field in fields])
    record_audit_event(
        session,
        principal,
        project_id=project_id,
        action="audit.exported",
        resource_type="audit_export",
        details={
            "rows": len(rows),
            "policy_version": policy.version,
            "filter_digest": hashlib.sha256(
                json.dumps(body.model_dump(), sort_keys=True).encode()
            ).hexdigest(),
        },
    )
    session.commit()
    return Response(
        stream.getvalue(),
        media_type="text/csv",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": 'attachment; filename="failurelens-audit.csv"',
        },
    )
