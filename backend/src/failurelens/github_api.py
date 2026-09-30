"""Authorized read-only publication history. No transport or submission route."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .auth import Principal, current_principal, require_project_role
from .db import get_session
from .github_publication_schemas import (
    GitHubPublicationList,
    GitHubPublicationRead,
    PublicationScopeError,
    publication_projection,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/github-publications",
    tags=["github-publications"],
)
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(current_principal)]


def _authorize(session, principal, project_id):
    if session.get(m.Project, project_id) is None:
        raise HTTPException(404, "project not found")
    require_project_role(session, principal, project_id)


@router.get("", response_model=GitHubPublicationList)
def publications(
    project_id: str,
    session: SessionDependency,
    principal: PrincipalDependency,
    run_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1000000),
):
    _authorize(session, principal, project_id)
    statement = select(m.GitHubPublication).where(
        m.GitHubPublication.project_id == project_id
    )
    if run_id is not None:
        run = session.get(m.Run, run_id)
        if run is None or run.project_id != project_id:
            raise HTTPException(404, "run not found")
        statement = statement.where(m.GitHubPublication.run_id == run_id)
    rows = list(
        session.scalars(
            statement.order_by(
                m.GitHubPublication.created_at.desc(), m.GitHubPublication.id.desc()
            )
            .offset(offset)
            .limit(limit + 1)
        )
    )
    try:
        items = [publication_projection(session, row) for row in rows[:limit]]
    except PublicationScopeError:
        raise HTTPException(409, "publication history is inconsistent") from None
    return {
        "items": items,
        "limit": limit,
        "offset": offset,
        "has_more": len(rows) > limit,
        "next_offset": offset + limit if len(rows) > limit else None,
    }


@router.get("/{publication_id}", response_model=GitHubPublicationRead)
def publication(
    project_id: str,
    publication_id: str,
    session: SessionDependency,
    principal: PrincipalDependency,
):
    _authorize(session, principal, project_id)
    row = session.get(m.GitHubPublication, publication_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "publication not found")
    try:
        return publication_projection(session, row)
    except PublicationScopeError:
        raise HTTPException(409, "publication history is inconsistent") from None
