"""Secret-free, bounded publication history; no GitHub transport imports."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m


class PublicationScopeError(ValueError):
    """Requested persisted publication scope is absent or inconsistent."""


class AnalysisRevisionReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    analysis_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    failure_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    revision: int = Field(ge=1, le=2147483647)


class PublicationRevisionIdentity(BaseModel):
    report_schema_version: Literal["github-report-v2"]
    analysis_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_count: int = Field(ge=0, le=2147483647, strict=True)
    analysis_revisions: list[AnalysisRevisionReference] = Field(max_length=50)
    omitted_analysis_revisions: int = Field(ge=0, le=2147483647, strict=True)

    @model_validator(mode="after")
    def consistent_revision_identity(self) -> Self:
        if (
            self.analysis_count
            != len(self.analysis_revisions) + self.omitted_analysis_revisions
        ):
            raise ValueError("inconsistent analysis revision count")
        if len({item.analysis_id for item in self.analysis_revisions}) != len(
            self.analysis_revisions
        ) or len({item.failure_id for item in self.analysis_revisions}) != len(
            self.analysis_revisions
        ):
            raise ValueError("duplicate analysis revision identity")
        return self


def publication_revision_identity(snapshot: Mapping[str, Any]) -> dict:
    """Persist only bounded revision identities, never analysis text or evidence."""
    manifest = snapshot.get("analysis_manifest")
    details = snapshot.get("analyses")
    count = snapshot.get("analysis_count")
    omitted = snapshot.get("omitted_analyses")
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "report-analysis-revisions-v1"
        or type(manifest.get("count")) is not int
        or type(count) is not int
        or manifest["count"] != count
        or not isinstance(details, list)
        or len(details) > 50
        or any(not isinstance(item, dict) for item in details)
        or type(omitted) is not int
        or omitted != count - len(details)
    ):
        raise PublicationScopeError("publication revision identity is inconsistent")
    refs = [
        {key: item.get(key) for key in ("analysis_id", "failure_id", "revision")}
        for item in details
    ]
    try:
        return PublicationRevisionIdentity.model_validate(
            {
                "report_schema_version": snapshot.get("schema_version"),
                "analysis_manifest_digest": manifest.get("digest"),
                "analysis_count": count,
                "analysis_revisions": refs,
                "omitted_analysis_revisions": omitted,
            }
        ).model_dump(mode="json")
    except ValidationError:
        raise PublicationScopeError(
            "publication revision identity is inconsistent"
        ) from None


class GitHubPublicationWriteRead(BaseModel):
    write_id: str
    sequence: int = Field(ge=1, le=2)
    method: Literal["POST", "PATCH"]
    purpose: Literal["report", "stale"]
    tested_head: str = Field(pattern=r"^[0-9a-f]{40}$")
    current_head: str = Field(pattern=r"^[0-9a-f]{40}$")
    comment_id: int | None = Field(ge=1)
    body_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    revalidated_report_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["dispatching", "observed", "uncertain"]
    error_code: str | None = Field(max_length=80, pattern=r"^[a-z0-9_]+$")
    created_at: datetime
    completed_at: datetime | None


class GitHubPublicationRead(PublicationRevisionIdentity):
    schema_version: Literal["github-publication-v1"] = "github-publication-v1"
    publication_id: str
    target_id: str
    project_id: str
    run_id: str
    repository: str = Field(max_length=240)
    pull_number: int = Field(ge=1)
    actor_kind: Literal["publisher_process"]
    publisher_id: str
    tested_head: str = Field(pattern=r"^[0-9a-f]{40}$")
    current_head: str | None = Field(pattern=r"^[0-9a-f]{40}$")
    report_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    bot_login: str = Field(max_length=120, pattern=r"^[A-Za-z0-9_-]+\[bot\]$")
    bot_user_id: int | None = Field(ge=1)
    actor_verification: Literal["not_verified", "verified"]
    actor_verified_at: datetime | None
    comment_id: int | None = Field(ge=1)
    source_run_id: str | None = Field(max_length=20, pattern=r"^[1-9][0-9]{0,19}$")
    source_run_attempt: int | None = Field(ge=1, le=1000000)
    source_verification: Literal["not_supplied", "unverified"]
    status: Literal[
        "prepared",
        "active",
        "reconciling",
        "created",
        "updated",
        "unchanged",
        "stale",
        "failed",
        "uncertain",
    ]
    error_code: str | None = Field(max_length=80, pattern=r"^[a-z0-9_]+$")
    target_reserved: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    reconciled_at: datetime | None
    writes: list[GitHubPublicationWriteRead] = Field(max_length=2)


class GitHubPublicationList(BaseModel):
    schema_version: Literal["github-publications-v1"] = "github-publications-v1"
    items: list[GitHubPublicationRead] = Field(max_length=100)
    limit: int
    offset: int
    has_more: bool
    next_offset: int | None


def publication_scope(session: Session, row):
    target = session.get(m.GitHubPublicationTarget, row.target_id)
    run = session.get(m.Run, row.run_id)
    if (
        target is None
        or run is None
        or session.get(m.Project, row.project_id) is None
        or run.project_id != row.project_id
        or target.project_id != row.project_id
    ):
        raise PublicationScopeError("publication scope is inconsistent")
    if target.active_publication_id:
        active = session.get(m.GitHubPublication, target.active_publication_id)
        active_run = session.get(m.Run, active.run_id) if active else None
        if (
            active is None
            or active.target_id != target.id
            or active.project_id != target.project_id
            or active_run is None
            or active_run.project_id != target.project_id
            or active.status not in {"prepared", "active", "reconciling", "uncertain"}
        ):
            raise PublicationScopeError("publication reservation is inconsistent")
    return target, run


def publication_projection(session: Session, row) -> dict:
    target, _ = publication_scope(session, row)
    writes = list(
        session.scalars(
            select(m.GitHubPublicationWrite)
            .where(m.GitHubPublicationWrite.publication_id == row.id)
            .order_by(m.GitHubPublicationWrite.sequence)
            .limit(3)
        )
    )
    keys = (
        "project_id",
        "run_id",
        "actor_kind",
        "publisher_id",
        "tested_head",
        "current_head",
        "report_digest",
        "report_schema_version",
        "analysis_manifest_digest",
        "analysis_count",
        "analysis_revisions",
        "omitted_analysis_revisions",
        "bot_login",
        "bot_user_id",
        "actor_verification",
        "actor_verified_at",
        "comment_id",
        "source_run_id",
        "source_run_attempt",
        "source_verification",
        "status",
        "error_code",
        "created_at",
        "updated_at",
        "completed_at",
        "reconciled_at",
    )
    write_keys = (
        "sequence",
        "method",
        "purpose",
        "tested_head",
        "current_head",
        "comment_id",
        "body_digest",
        "revalidated_report_digest",
        "state",
        "error_code",
        "created_at",
        "completed_at",
    )
    value = {key: getattr(row, key) for key in keys}
    value.update(
        publication_id=row.id,
        target_id=target.id,
        repository=target.repository,
        pull_number=target.pull_number,
        target_reserved=target.active_publication_id == row.id,
        writes=[
            {"write_id": item.id, **{key: getattr(item, key) for key in write_keys}}
            for item in writes
        ],
    )
    try:
        return GitHubPublicationRead.model_validate(value).model_dump(mode="json")
    except ValidationError:
        raise PublicationScopeError("publication record is inconsistent") from None
