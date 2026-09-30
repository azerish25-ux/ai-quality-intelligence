"""Authenticated, evidence-bound optional provider operations. No transport here."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .auth import Principal, current_principal, require_project_role
from .config import get_settings
from .db import get_session
from .provider_jobs import (
    cancel_model_invocation,
    project_invocation,
    provider_preview,
    provider_status,
    scoped_invocation,
    submit_model_invocation,
)
from .provider_schemas import (
    ProviderInvocationList,
    ProviderInvocationRead,
    ProviderPreview,
    ProviderStatus,
    ProviderSubmit,
)
from .provider_service import ProviderIdempotencyConflict, ProviderScopeError, _analysis
from .providers import ProviderBoundaryError

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["optional-provider"])
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]
BASE = "/runs/{run_id}/analyses/{analysis_id}/provider"


def _authorize(session, principal, project_id):
    if session.get(m.Project, project_id) is None:
        raise HTTPException(404, "project not found")
    require_project_role(session, principal, project_id)


def _error(exc):
    if isinstance(exc, ProviderScopeError):
        return HTTPException(404, "requested provider scope not found")
    if isinstance(exc, ProviderIdempotencyConflict):
        return HTTPException(409, "idempotency key conflicts with an existing request")
    return HTTPException(409, str(exc))


@router.get("/provider/status", response_model=ProviderStatus)
def status(project_id: str, session: SessionDependency, principal: PrincipalDependency):
    _authorize(session, principal, project_id)
    return provider_status(session, get_settings(), principal, project_id)


@router.get(BASE + "/preview", response_model=ProviderPreview)
def preview(
    project_id: str,
    run_id: str,
    analysis_id: str,
    session: SessionDependency,
    principal: PrincipalDependency,
):
    _authorize(session, principal, project_id)
    try:
        return provider_preview(
            session, get_settings(), principal, project_id, run_id, analysis_id
        )
    except (ProviderScopeError, ProviderBoundaryError) as exc:
        raise _error(exc) from None


@router.post(
    BASE + "/invocations", response_model=ProviderInvocationRead, status_code=202
)
def submit(
    project_id: str,
    run_id: str,
    analysis_id: str,
    body: ProviderSubmit,
    session: SessionDependency,
    principal: PrincipalDependency,
):
    _authorize(session, principal, project_id)
    try:
        invocation = submit_model_invocation(
            session, get_settings(), principal, project_id, run_id, analysis_id, body
        )
        session.commit()
        return project_invocation(session, get_settings(), invocation)
    except (
        ProviderScopeError,
        ProviderBoundaryError,
        ProviderIdempotencyConflict,
    ) as exc:
        session.rollback()
        raise _error(exc) from None


@router.get(BASE + "/invocations", response_model=ProviderInvocationList)
def invocations(
    project_id: str,
    run_id: str,
    analysis_id: str,
    session: SessionDependency,
    principal: PrincipalDependency,
):
    _authorize(session, principal, project_id)
    try:
        _analysis(session, project_id, run_id, analysis_id)
    except ProviderScopeError as exc:
        raise _error(exc) from None
    rows = list(
        session.scalars(
            select(m.ModelInvocation)
            .where(
                m.ModelInvocation.project_id == project_id,
                m.ModelInvocation.run_id == run_id,
                m.ModelInvocation.analysis_id == analysis_id,
                m.ModelInvocation.job_id.is_not(None),
            )
            .order_by(m.ModelInvocation.created_at.desc(), m.ModelInvocation.id.desc())
            .limit(51)
        )
    )
    return {
        "schema_version": "1.0",
        "items": [
            project_invocation(session, get_settings(), row) for row in rows[:50]
        ],
        "limit": 50,
        "truncated": len(rows) > 50,
    }


@router.get(
    BASE + "/invocations/{invocation_id}", response_model=ProviderInvocationRead
)
def invocation(
    project_id: str,
    run_id: str,
    analysis_id: str,
    invocation_id: str,
    session: SessionDependency,
    principal: PrincipalDependency,
):
    _authorize(session, principal, project_id)
    try:
        row = scoped_invocation(session, project_id, run_id, analysis_id, invocation_id)
        return project_invocation(session, get_settings(), row)
    except ProviderScopeError as exc:
        raise _error(exc) from None


@router.post(
    BASE + "/invocations/{invocation_id}/cancel", response_model=ProviderInvocationRead
)
def cancel(
    project_id: str,
    run_id: str,
    analysis_id: str,
    invocation_id: str,
    session: SessionDependency,
    principal: PrincipalDependency,
):
    _authorize(session, principal, project_id)
    try:
        row = cancel_model_invocation(
            session,
            get_settings(),
            principal,
            project_id,
            run_id,
            analysis_id,
            invocation_id,
        )
        session.commit()
        return project_invocation(session, get_settings(), row)
    except (ProviderScopeError, ProviderBoundaryError) as exc:
        session.rollback()
        raise _error(exc) from None
