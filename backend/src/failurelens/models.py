from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class RunStatus(str, enum.Enum):
    queued = "queued"
    processing = "processing"
    complete = "complete"
    partial = "partial"
    failed = "failed"


class Outcome(str, enum.Enum):
    passed = "passed"
    failed = "failed"
    skipped = "skipped"
    cancelled = "cancelled"
    unknown = "unknown"


class Category(str, enum.Enum):
    product_defect = "product_defect"
    test_defect = "test_defect"
    infrastructure_failure = "infrastructure_failure"
    known_flake = "known_flake"
    insufficient_evidence = "insufficient_evidence"


class ProjectRole(str, enum.Enum):
    viewer = "viewer"
    reviewer = "reviewer"
    administrator = "administrator"


class JobState(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    partial = "partial"
    failed = "failed"
    cancelled = "cancelled"
    dead_lettered = "dead_lettered"


class IngestionState(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    partial = "partial"
    failed = "failed"
    cancelled = "cancelled"
    dead_lettered = "dead_lettered"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(240))
    password_hash: Mapped[str] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_system_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lifecycle_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    memberships: Mapped[list[ProjectMembership]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="ProjectMembership.user_id",
    )
    sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ProjectMembership(Base):
    __tablename__ = "project_memberships"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_membership"),
        Index("ix_project_memberships_user_project", "user_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[ProjectRole] = mapped_column(Enum(ProjectRole))
    granted_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships", foreign_keys=[user_id])
    granted_by: Mapped[User | None] = relationship(foreign_keys=[granted_by_user_id])


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_session_token_hash"),
        Index("ix_auth_sessions_user_expiry", "user_id", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_prefix: Mapped[str] = mapped_column(String(24), index=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="sessions")


class IngestionToken(Base):
    __tablename__ = "ingestion_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_ingestion_token_hash"),
        Index("ix_ingestion_tokens_project_active", "project_id", "revoked_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    token_prefix: Mapped[str] = mapped_column(String(24), index=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="ingestion_tokens")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_user_id])


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_project_created", "project_id", "created_at"),
        Index("ix_audit_events_actor_created", "actor_user_id", "created_at"),
        Index("ix_audit_events_resource", "resource_type", "resource_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    actor_kind: Mapped[str] = mapped_column(String(40))
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_display: Mapped[str] = mapped_column(String(240))
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str] = mapped_column(String(80), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    outcome: Mapped[str] = mapped_column(String(40), default="succeeded")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project | None] = relationship(back_populates="audit_events")
    actor_user: Mapped[User | None] = relationship(foreign_keys=[actor_user_id])


class AccountRecovery(Base):
    """Only a one-time token digest is retained; never a temporary password."""
    __tablename__ = "account_recoveries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    issued_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RetentionPolicy(Base):
    __tablename__ = "retention_policies"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    source_days: Mapped[int] = mapped_column(Integer, default=7)
    evidence_days: Mapped[int] = mapped_column(Integer, default=90)
    audit_days: Mapped[int] = mapped_column(Integer, default=365)
    export_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    export_max_rows: Mapped[int] = mapped_column(Integer, default=10000)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RetentionTombstone(Base):
    __tablename__ = "retention_tombstones"
    __table_args__ = (UniqueConstraint("project_id", "resource_type", "resource_id", name="uq_retention_tombstone"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str] = mapped_column(String(240))
    policy_version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(120), default="retention_expired")
    expired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StorageDeletion(Base):
    """Transactional deletion outbox. Tombstone first, unlink after commit."""
    __tablename__ = "storage_deletions"
    __table_args__ = (UniqueConstraint("project_id", "storage_path", name="uq_storage_deletion_path"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    storage_path: Mapped[str] = mapped_column(String(2048))
    state: Mapped[str] = mapped_column(String(40), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[list[ProjectMembership]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    ingestion_tokens: Mapped[list[IngestionToken]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    runs: Mapped[list[Run]] = relationship(back_populates="project", cascade="all, delete-orphan")
    ingestions: Mapped[list[Ingestion]] = relationship(back_populates="project", cascade="all, delete-orphan")
    clusters: Mapped[list[FailureCluster]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    impact_mapping_snapshots: Mapped[list[ImpactMappingSnapshot]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    impact_recommendations: Mapped[list[ImpactRecommendation]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    performance_policies: Mapped[list[PerformancePolicy]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    performance_observations: Mapped[list[PerformanceObservation]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    performance_baselines: Mapped[list[PerformanceBaselineSnapshot]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    performance_comparisons: Mapped[list[PerformanceComparison]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    infrastructure_events: Mapped[list[InfrastructureEvent]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    infrastructure_correlation_snapshots: Mapped[list[InfrastructureCorrelationSnapshot]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("project_id", "external_id", "attempt", "manifest_digest", name="uq_run_identity"),
        Index("ix_runs_project_started", "project_id", "started_at"),
        Index("ix_runs_project_history", "project_id", "created_at", "run_scope"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(240))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    repository: Mapped[str | None] = mapped_column(String(240), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(240), nullable=True)
    framework: Mapped[str] = mapped_column(String(64), default="unknown")
    run_scope: Mapped[str] = mapped_column(String(40), default="unknown")
    environment: Mapped[str | None] = mapped_column(String(160), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    worker_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shard_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.queued)
    completeness: Mapped[str] = mapped_column(String(32), default="unknown")
    expected_inputs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_inputs: Mapped[int] = mapped_column(Integer, default=0)
    manifest_digest: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    retention_policy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    project: Mapped[Project] = relationship(back_populates="runs")
    executions: Mapped[list[TestExecution]] = relationship(back_populates="run", cascade="all, delete-orphan")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="run", cascade="all, delete-orphan")
    derivatives: Mapped[list[ArtifactDerivative]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    failures: Mapped[list[Failure]] = relationship(back_populates="run", cascade="all, delete-orphan")
    ingestion: Mapped[Ingestion | None] = relationship(
        back_populates="run",
        uselist=False,
        foreign_keys="Ingestion.run_id",
    )
    inputs: Mapped[list[RunInput]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    impact_recommendations: Mapped[list[ImpactRecommendation]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    performance_observations: Mapped[list[PerformanceObservation]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    performance_baselines: Mapped[list[PerformanceBaselineSnapshot]] = relationship(
        back_populates="current_run", cascade="all, delete-orphan"
    )
    performance_comparisons: Mapped[list[PerformanceComparison]] = relationship(
        back_populates="current_run", cascade="all, delete-orphan"
    )
    infrastructure_correlation_snapshots: Mapped[list[InfrastructureCorrelationSnapshot]] = relationship(
        back_populates="selected_run", cascade="all, delete-orphan"
    )
    infrastructure_correlation_members: Mapped[list[InfrastructureCorrelationMember]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_claim", "state", "available_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    state: Mapped[JobState] = mapped_column(Enum(JobState), default=JobState.queued)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_owner: Mapped[str | None] = mapped_column(String(240), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    ingestion: Mapped[Ingestion | None] = relationship(
        back_populates="job",
        uselist=False,
        foreign_keys="Ingestion.job_id",
    )


class Ingestion(Base):
    __tablename__ = "ingestions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "external_id",
            "attempt",
            "source_digest",
            name="uq_ingestion_identity",
        ),
        Index("ix_ingestions_project_created", "project_id", "created_at"),
        Index("ix_ingestions_state_created", "state", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(240))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    repository: Mapped[str | None] = mapped_column(String(240), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_format: Mapped[str] = mapped_column(String(80), default="auto")
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    original_name: Mapped[str] = mapped_column(String(1024))
    media_type: Mapped[str] = mapped_column(String(160), default="application/octet-stream")
    source_digest: Mapped[str] = mapped_column(String(64))
    source_size_bytes: Mapped[int] = mapped_column(Integer)
    source_expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(2048))
    expected_inputs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_inputs: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[IngestionState] = mapped_column(Enum(IngestionState), default=IngestionState.queued)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"),
        unique=True,
        nullable=True,
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"),
        unique=True,
        nullable=True,
    )
    parser_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(80), default="artifact-policy-v1")
    diagnostics: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="ingestions")
    run: Mapped[Run | None] = relationship(
        back_populates="ingestion",
        foreign_keys=[run_id],
    )
    job: Mapped[Job | None] = relationship(
        back_populates="ingestion",
        foreign_keys=[job_id],
    )


class RunInput(Base):
    __tablename__ = "run_inputs"
    __table_args__ = (
        UniqueConstraint("run_id", "input_id", name="uq_run_input_identity"),
        Index("ix_run_inputs_run_status", "run_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    input_id: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(80))
    path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(40))
    digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    media_type: Mapped[str] = mapped_column(
        String(160), default="application/octet-stream"
    )
    parser_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[Run] = relationship(back_populates="inputs")
    evidence: Mapped[list[Evidence]] = relationship(back_populates="run_input")
    impact_recommendations: Mapped[list[ImpactRecommendation]] = relationship(
        back_populates="changed_input"
    )
    performance_observations: Mapped[list[PerformanceObservation]] = relationship(
        back_populates="run_input"
    )


class TestExecution(Base):
    __tablename__ = "test_executions"
    __table_args__ = (
        Index("ix_execution_identity", "run_id", "test_identity"),
        Index("ix_execution_history_identity", "test_identity", "browser", "run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    test_identity: Mapped[str] = mapped_column(String(512))
    suite: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    parameterization: Mapped[str | None] = mapped_column(String(512), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[Outcome] = mapped_column(Enum(Outcome))
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    retry_recovered: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    run: Mapped[Run] = relationship(back_populates="executions")
    failure: Mapped[Failure | None] = relationship(back_populates="execution", uselist=False)
    evidence: Mapped[list[Evidence]] = relationship(back_populates="execution")
    performance_observations: Mapped[list[PerformanceObservation]] = relationship(
        back_populates="execution"
    )
    infrastructure_correlation_snapshots: Mapped[list[InfrastructureCorrelationSnapshot]] = relationship(
        back_populates="selected_execution", cascade="all, delete-orphan"
    )


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("run_id", "digest", "kind", name="uq_artifact_run_digest_kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(80))
    original_name: Mapped[str] = mapped_column(String(1024))
    digest: Mapped[str] = mapped_column(String(64))
    safe_storage_path: Mapped[str] = mapped_column(String(2048))
    media_type: Mapped[str] = mapped_column(
        String(160), default="application/octet-stream"
    )
    size_bytes: Mapped[int] = mapped_column(Integer)
    redaction_version: Mapped[str] = mapped_column(
        String(40), default="redaction-v1"
    )
    restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    run: Mapped[Run] = relationship(back_populates="artifacts")
    derivatives: Mapped[list[ArtifactDerivative]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan"
    )
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan"
    )


class ArtifactDerivative(Base):
    __tablename__ = "artifact_derivatives"
    __table_args__ = (
        UniqueConstraint(
            "artifact_id",
            "kind",
            "digest",
            name="uq_artifact_derivative_content",
        ),
        Index("ix_artifact_derivatives_project_digest", "project_id", "digest"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(80))
    digest: Mapped[str] = mapped_column(String(64))
    source_digest: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(2048))
    media_type: Mapped[str] = mapped_column(String(160))
    size_bytes: Mapped[int] = mapped_column(Integer)
    redaction_version: Mapped[str] = mapped_column(String(40))
    source_map: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    restricted: Mapped[bool] = mapped_column(Boolean, default=True)
    approval_state: Mapped[str] = mapped_column(String(40), default="pending")
    retention_state: Mapped[str] = mapped_column(String(40), default="active")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    run: Mapped[Run] = relationship(back_populates="derivatives")
    artifact: Mapped[Artifact] = relationship(back_populates="derivatives")
    evidence: Mapped[list[Evidence]] = relationship(back_populates="derivative")


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_execution_scope", "run_id", "execution_id"),
        Index("ix_evidence_input_scope", "run_id", "run_input_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), index=True
    )
    run_input_id: Mapped[str | None] = mapped_column(
        ForeignKey("run_inputs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("test_executions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    derivative_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_derivatives.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(80))
    provenance_kind: Mapped[str] = mapped_column(
        String(80), default="current_execution"
    )
    locator_version: Mapped[str] = mapped_column(
        String(40), default="evidence-locator-v2"
    )
    locator: Mapped[dict[str, Any]] = mapped_column(JSON)
    excerpt: Mapped[str] = mapped_column(Text)
    observation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_digest: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(80))
    extractor_version: Mapped[str] = mapped_column(
        String(80), default="observation-extractor-v1"
    )
    redaction_version: Mapped[str] = mapped_column(
        String(40), default="redaction-v1"
    )
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)

    artifact: Mapped[Artifact] = relationship(back_populates="evidence")
    run_input: Mapped[RunInput | None] = relationship(back_populates="evidence")
    execution: Mapped[TestExecution | None] = relationship(back_populates="evidence")
    derivative: Mapped[ArtifactDerivative | None] = relationship(
        back_populates="evidence"
    )
    performance_observations: Mapped[list[PerformanceObservation]] = relationship(
        back_populates="evidence"
    )
    infrastructure_events: Mapped[list[InfrastructureEvent]] = relationship(
        back_populates="evidence"
    )


class Failure(Base):
    __tablename__ = "failures"
    __table_args__ = (Index("ix_failure_fingerprint", "project_id", "strict_fingerprint"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("test_executions.id", ondelete="CASCADE"), unique=True)
    message: Mapped[str] = mapped_column(Text)
    exception_type: Mapped[str | None] = mapped_column(String(240), nullable=True)
    strict_fingerprint: Mapped[str] = mapped_column(String(64))
    loose_features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[Run] = relationship(back_populates="failures")
    execution: Mapped[TestExecution] = relationship(back_populates="failure")
    analyses: Mapped[list[Analysis]] = relationship(back_populates="failure", cascade="all, delete-orphan")
    cluster_memberships: Mapped[list[ClusterMembership]] = relationship(
        back_populates="failure", cascade="all, delete-orphan"
    )


class FailureCluster(Base):
    __tablename__ = "failure_clusters"
    __table_args__ = (
        UniqueConstraint("project_id", "cluster_key", name="uq_failure_cluster_key"),
        Index("ix_failure_clusters_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    cluster_key: Mapped[str] = mapped_column(String(64))
    algorithm_version: Mapped[str] = mapped_column(String(80))
    feature_version: Mapped[str] = mapped_column(String(80))
    current_revision: Mapped[int] = mapped_column(Integer, default=0)
    representative_failure_id: Mapped[str | None] = mapped_column(
        ForeignKey("failures.id", ondelete="SET NULL"), nullable=True, index=True
    )
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    uncertainty: Mapped[str] = mapped_column(String(40), default="none")
    status: Mapped[str] = mapped_column(String(40), default="active")
    superseded_by_cluster_id: Mapped[str | None] = mapped_column(
        ForeignKey("failure_clusters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship(back_populates="clusters")
    representative_failure: Mapped[Failure | None] = relationship(
        foreign_keys=[representative_failure_id]
    )
    superseded_by: Mapped[FailureCluster | None] = relationship(
        remote_side=[id], foreign_keys=[superseded_by_cluster_id]
    )
    revisions: Mapped[list[ClusterRevision]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )
    memberships: Mapped[list[ClusterMembership]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )
    decisions: Mapped[list[ClusterMembershipDecision]] = relationship(
        back_populates="cluster",
        cascade="all, delete-orphan",
        foreign_keys="ClusterMembershipDecision.cluster_id",
    )


class ClusterRevision(Base):
    __tablename__ = "cluster_revisions"
    __table_args__ = (
        UniqueConstraint("cluster_id", "revision", name="uq_cluster_revision"),
        Index("ix_cluster_revisions_cluster_created", "cluster_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cluster_id: Mapped[str] = mapped_column(
        ForeignKey("failure_clusters.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(80))
    algorithm_version: Mapped[str] = mapped_column(String(80))
    feature_version: Mapped[str] = mapped_column(String(80))
    representative_failure_id: Mapped[str | None] = mapped_column(
        ForeignKey("failures.id", ondelete="SET NULL"), nullable=True, index=True
    )
    member_count: Mapped[int] = mapped_column(Integer)
    score_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    uncertainty_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    cluster: Mapped[FailureCluster] = relationship(back_populates="revisions")
    representative_failure: Mapped[Failure | None] = relationship(
        foreign_keys=[representative_failure_id]
    )
    memberships: Mapped[list[ClusterMembership]] = relationship(
        back_populates="revision", cascade="all, delete-orphan"
    )


class ClusterMembership(Base):
    __tablename__ = "cluster_memberships"
    __table_args__ = (
        UniqueConstraint("revision_id", "failure_id", name="uq_cluster_revision_failure"),
        Index("ix_cluster_memberships_cluster_revision", "cluster_id", "revision_id"),
        Index("ix_cluster_memberships_failure_revision", "failure_id", "revision_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cluster_id: Mapped[str] = mapped_column(
        ForeignKey("failure_clusters.id", ondelete="CASCADE"), index=True
    )
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("cluster_revisions.id", ondelete="CASCADE"), index=True
    )
    failure_id: Mapped[str] = mapped_column(
        ForeignKey("failures.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(40), default="member")
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_components: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    matching_signals: Mapped[list[str]] = mapped_column(JSON, default=list)
    conflicting_signals: Mapped[list[str]] = mapped_column(JSON, default=list)
    candidate_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    assignment_kind: Mapped[str] = mapped_column(String(40), default="automatic")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    cluster: Mapped[FailureCluster] = relationship(back_populates="memberships")
    revision: Mapped[ClusterRevision] = relationship(back_populates="memberships")
    failure: Mapped[Failure] = relationship(back_populates="cluster_memberships")


class ClusterMembershipDecision(Base):
    __tablename__ = "cluster_membership_decisions"
    __table_args__ = (
        Index("ix_cluster_decisions_cluster_created", "cluster_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cluster_id: Mapped[str] = mapped_column(
        ForeignKey("failure_clusters.id", ondelete="CASCADE"), index=True
    )
    target_cluster_id: Mapped[str | None] = mapped_column(
        ForeignKey("failure_clusters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor: Mapped[str] = mapped_column(String(240))
    actor_kind: Mapped[str] = mapped_column(String(40), default="legacy")
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    decision: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    failure_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    revision_before: Mapped[int] = mapped_column(Integer)
    revision_after: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    cluster: Mapped[FailureCluster] = relationship(
        back_populates="decisions", foreign_keys=[cluster_id]
    )
    target_cluster: Mapped[FailureCluster | None] = relationship(
        foreign_keys=[target_cluster_id]
    )
    actor_user: Mapped[User | None] = relationship(foreign_keys=[actor_user_id])


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (
        UniqueConstraint("failure_id", "revision", name="uq_analysis_revision"),
        UniqueConstraint(
            "failure_id",
            "analysis_version",
            "input_digest",
            name="uq_analysis_input",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    failure_id: Mapped[str] = mapped_column(ForeignKey("failures.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    analysis_version: Mapped[str] = mapped_column(String(40), default="deterministic-v1")
    input_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[Category] = mapped_column(Enum(Category))
    severity: Mapped[str] = mapped_column(String(32), default="medium")
    confidence_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_kind: Mapped[str] = mapped_column(String(40), default="heuristic_score")
    confidence_explanation: Mapped[str] = mapped_column(Text)
    evidence_completeness: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text)
    claims: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    supporting_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    contradictory_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_evidence: Mapped[list[str]] = mapped_column(JSON, default=list)
    hypotheses: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    next_investigation: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    abstention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_version: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    validation_results: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    failure: Mapped[Failure] = relationship(back_populates="analyses")
    reviews: Mapped[list[ReviewEvent]] = relationship(back_populates="analysis", cascade="all, delete-orphan")


class ReviewEvent(Base):
    __tablename__ = "review_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(240))
    actor_kind: Mapped[str] = mapped_column(String(40), default="legacy")
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    decision: Mapped[str] = mapped_column(String(80))
    proposed_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    supporting_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    contradictory_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    hypothesis_decisions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    investigation_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    release_advice: Mapped[str | None] = mapped_column(String(80), nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    analysis: Mapped[Analysis] = relationship(back_populates="reviews")
    actor_user: Mapped[User | None] = relationship(foreign_keys=[actor_user_id])


class ImpactMappingSnapshot(Base):
    __tablename__ = "impact_mapping_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "version",
            name="uq_impact_mapping_snapshot_identity",
        ),
        Index(
            "ix_impact_mapping_snapshots_project_created",
            "project_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(80))
    policy_version: Mapped[str] = mapped_column(String(80))
    source_digest: Mapped[str] = mapped_column(String(64))
    trusted: Mapped[bool] = mapped_column(Boolean, default=False)
    coverage_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="impact_mapping_snapshots")
    tests: Mapped[list[ImpactTestDefinition]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )
    edges: Mapped[list[ImpactMappingEdge]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )
    recommendations: Mapped[list[ImpactRecommendation]] = relationship(
        back_populates="mapping_snapshot"
    )


class ImpactTestDefinition(Base):
    __tablename__ = "impact_test_definitions"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "test_key", name="uq_impact_test_snapshot_key"
        ),
        Index("ix_impact_tests_snapshot_identity", "snapshot_id", "test_identity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("impact_mapping_snapshots.id", ondelete="CASCADE"), index=True
    )
    test_key: Mapped[str] = mapped_column(String(240))
    test_identity: Mapped[str] = mapped_column(String(512))
    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    criticality: Mapped[str] = mapped_column(String(40), default="normal")
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    estimated_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    snapshot: Mapped[ImpactMappingSnapshot] = relationship(back_populates="tests")


class ImpactMappingEdge(Base):
    __tablename__ = "impact_mapping_edges"
    __table_args__ = (
        Index("ix_impact_edges_snapshot_source", "snapshot_id", "source_path"),
        Index(
            "ix_impact_edges_snapshot_target",
            "snapshot_id",
            "target_type",
            "target_value",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("impact_mapping_snapshots.id", ondelete="CASCADE"), index=True
    )
    source_path: Mapped[str] = mapped_column(String(1024))
    target_type: Mapped[str] = mapped_column(String(20))
    target_value: Mapped[str] = mapped_column(String(1024))
    kind: Mapped[str] = mapped_column(String(80))
    confidence: Mapped[float] = mapped_column(Float)
    mapping_source: Mapped[str] = mapped_column(String(120))
    mapping_version: Mapped[str] = mapped_column(String(80))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    snapshot: Mapped[ImpactMappingSnapshot] = relationship(back_populates="edges")


class ImpactRecommendation(Base):
    __tablename__ = "impact_recommendations"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "input_digest", name="uq_impact_recommendation_input"
        ),
        Index(
            "ix_impact_recommendations_project_created",
            "project_id",
            "created_at",
        ),
        Index("ix_impact_recommendations_run", "run_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    changed_input_id: Mapped[str] = mapped_column(
        ForeignKey("run_inputs.id", ondelete="RESTRICT"), index=True
    )
    mapping_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("impact_mapping_snapshots.id", ondelete="RESTRICT"), index=True
    )
    base_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    head_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_digest: Mapped[str] = mapped_column(String(64))
    changed_files_digest: Mapped[str] = mapped_column(String(64))
    engine_version: Mapped[str] = mapped_column(String(80))
    policy_version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40))
    current_revision: Mapped[int] = mapped_column(Integer, default=0)
    comparison_trusted: Mapped[bool] = mapped_column(Boolean, default=False)
    mapping_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    full_suite_required: Mapped[bool] = mapped_column(Boolean, default=True)
    summary: Mapped[str] = mapped_column(Text)
    changed_files: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    safety_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship(back_populates="impact_recommendations")
    run: Mapped[Run] = relationship(back_populates="impact_recommendations")
    changed_input: Mapped[RunInput] = relationship(
        back_populates="impact_recommendations"
    )
    mapping_snapshot: Mapped[ImpactMappingSnapshot] = relationship(
        back_populates="recommendations"
    )
    items: Mapped[list[ImpactRecommendationItem]] = relationship(
        back_populates="recommendation", cascade="all, delete-orphan"
    )
    overrides: Mapped[list[ImpactOverride]] = relationship(
        back_populates="recommendation", cascade="all, delete-orphan"
    )


class ImpactRecommendationItem(Base):
    __tablename__ = "impact_recommendation_items"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_id",
            "test_key",
            name="uq_impact_recommendation_test",
        ),
        Index(
            "ix_impact_recommendation_items_selected",
            "recommendation_id",
            "base_selected",
            "rank",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    recommendation_id: Mapped[str] = mapped_column(
        ForeignKey("impact_recommendations.id", ondelete="CASCADE"), index=True
    )
    test_key: Mapped[str] = mapped_column(String(240))
    test_identity: Mapped[str] = mapped_column(String(512))
    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    criticality: Mapped[str] = mapped_column(String(40))
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    base_selected: Mapped[bool] = mapped_column(Boolean)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[str] = mapped_column(String(40), default="none")
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    mapping_edge_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    recommendation: Mapped[ImpactRecommendation] = relationship(back_populates="items")


class ImpactOverride(Base):
    __tablename__ = "impact_overrides"
    __table_args__ = (
        Index(
            "ix_impact_overrides_recommendation_revision",
            "recommendation_id",
            "revision_after",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    recommendation_id: Mapped[str] = mapped_column(
        ForeignKey("impact_recommendations.id", ondelete="CASCADE"), index=True
    )
    actor: Mapped[str] = mapped_column(String(240))
    actor_kind: Mapped[str] = mapped_column(String(40), default="legacy")
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(20))
    test_key: Mapped[str] = mapped_column(String(240))
    reason: Mapped[str] = mapped_column(Text)
    revision_before: Mapped[int] = mapped_column(Integer)
    revision_after: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    recommendation: Mapped[ImpactRecommendation] = relationship(
        back_populates="overrides"
    )
    actor_user: Mapped[User | None] = relationship(foreign_keys=[actor_user_id])


class PerformancePolicy(Base):
    __tablename__ = "performance_policies"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "version", name="uq_performance_policy_version"
        ),
        Index("ix_performance_policies_project_created", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(80))
    relative_tolerance: Mapped[float] = mapped_column(Float, default=0.10)
    absolute_tolerance: Mapped[float] = mapped_column(Float, default=0.0)
    min_baseline_runs: Mapped[int] = mapped_column(Integer, default=3)
    max_baseline_age_days: Mapped[int] = mapped_column(Integer, default=30)
    require_trusted: Mapped[bool] = mapped_column(Boolean, default=True)
    required_dimensions: Mapped[list[str]] = mapped_column(JSON, default=list)
    direction_overrides: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="performance_policies")
    baselines: Mapped[list[PerformanceBaselineSnapshot]] = relationship(
        back_populates="policy"
    )
    comparisons: Mapped[list[PerformanceComparison]] = relationship(
        back_populates="policy"
    )


class PerformanceObservation(Base):
    __tablename__ = "performance_observations"
    __table_args__ = (
        UniqueConstraint("run_id", "metric_key", name="uq_performance_run_metric"),
        Index(
            "ix_performance_observations_lookup",
            "project_id",
            "metric_name",
            "statistic",
            "observed_at",
        ),
        Index(
            "ix_performance_observations_cohort",
            "project_id",
            "dimension_signature",
            "observed_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    run_input_id: Mapped[str | None] = mapped_column(
        ForeignKey("run_inputs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("test_executions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"), index=True
    )
    metric_key: Mapped[str] = mapped_column(String(64))
    metric_name: Mapped[str] = mapped_column(String(240))
    metric_scope: Mapped[str] = mapped_column(String(40))
    statistic: Mapped[str] = mapped_column(String(80))
    direction: Mapped[str] = mapped_column(String(40), default="lower_is_better")
    original_value: Mapped[float] = mapped_column(Float)
    original_unit: Mapped[str] = mapped_column(String(40))
    canonical_value: Mapped[float] = mapped_column(Float)
    canonical_unit: Mapped[str] = mapped_column(String(40))
    sample_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    producer: Mapped[str] = mapped_column(String(120))
    producer_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    workload: Mapped[str] = mapped_column(String(512))
    dimension_signature: Mapped[str] = mapped_column(String(64))
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    threshold_status: Mapped[str] = mapped_column(String(40), default="unknown")
    threshold_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_digest: Mapped[str] = mapped_column(String(64))
    source_locator: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="performance_observations")
    run: Mapped[Run] = relationship(back_populates="performance_observations")
    run_input: Mapped[RunInput | None] = relationship(
        back_populates="performance_observations"
    )
    execution: Mapped[TestExecution | None] = relationship(
        back_populates="performance_observations"
    )
    evidence: Mapped[Evidence] = relationship(back_populates="performance_observations")
    baseline_memberships: Mapped[list[PerformanceBaselineMember]] = relationship(
        back_populates="observation"
    )
    current_baselines: Mapped[list[PerformanceBaselineSnapshot]] = relationship(
        back_populates="current_observation",
        foreign_keys="PerformanceBaselineSnapshot.current_observation_id",
    )
    current_comparisons: Mapped[list[PerformanceComparison]] = relationship(
        back_populates="current_observation",
        foreign_keys="PerformanceComparison.current_observation_id",
    )


class PerformanceBaselineSnapshot(Base):
    __tablename__ = "performance_baseline_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "input_digest", name="uq_performance_baseline_input"
        ),
        Index("ix_performance_baselines_run_created", "current_run_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    current_run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    current_observation_id: Mapped[str] = mapped_column(
        ForeignKey("performance_observations.id", ondelete="CASCADE"), index=True
    )
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("performance_policies.id", ondelete="RESTRICT"), index=True
    )
    input_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cohort_dimensions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    compatibility: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rejected_candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    baseline_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_mad: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_age_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    aggregation: Mapped[str] = mapped_column(
        String(80), default="median_of_run_level_observations"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="performance_baselines")
    current_run: Mapped[Run] = relationship(back_populates="performance_baselines")
    current_observation: Mapped[PerformanceObservation] = relationship(
        back_populates="current_baselines",
        foreign_keys=[current_observation_id],
    )
    policy: Mapped[PerformancePolicy] = relationship(back_populates="baselines")
    members: Mapped[list[PerformanceBaselineMember]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )
    comparison: Mapped[PerformanceComparison | None] = relationship(
        back_populates="baseline_snapshot", uselist=False
    )


class PerformanceBaselineMember(Base):
    __tablename__ = "performance_baseline_members"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "observation_id", name="uq_performance_baseline_member"
        ),
        Index("ix_performance_baseline_members_order", "snapshot_id", "position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("performance_baseline_snapshots.id", ondelete="CASCADE"), index=True
    )
    observation_id: Mapped[str] = mapped_column(
        ForeignKey("performance_observations.id", ondelete="RESTRICT"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    snapshot: Mapped[PerformanceBaselineSnapshot] = relationship(back_populates="members")
    observation: Mapped[PerformanceObservation] = relationship(
        back_populates="baseline_memberships"
    )
    run: Mapped[Run] = relationship()


class PerformanceComparison(Base):
    __tablename__ = "performance_comparisons"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "input_digest", name="uq_performance_comparison_input"
        ),
        Index("ix_performance_comparisons_run_created", "current_run_id", "created_at"),
        Index("ix_performance_comparisons_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    current_run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    current_observation_id: Mapped[str] = mapped_column(
        ForeignKey("performance_observations.id", ondelete="CASCADE"), index=True
    )
    baseline_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("performance_baseline_snapshots.id", ondelete="RESTRICT"),
        unique=True,
        index=True,
    )
    policy_id: Mapped[str] = mapped_column(
        ForeignKey("performance_policies.id", ondelete="RESTRICT"), index=True
    )
    engine_version: Mapped[str] = mapped_column(String(80))
    input_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40))
    current_value: Mapped[float] = mapped_column(Float)
    baseline_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    absolute_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    allowed_absolute_change: Mapped[float] = mapped_column(Float)
    allowed_relative_change: Mapped[float] = mapped_column(Float)
    current_sample_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    baseline_run_count: Mapped[int] = mapped_column(Integer, default=0)
    baseline_sample_count: Mapped[int] = mapped_column(Integer, default=0)
    threshold_status: Mapped[str] = mapped_column(String(40), default="unknown")
    effect_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    compatibility: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confounders: Mapped[list[str]] = mapped_column(JSON, default=list)
    current_evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence.id", ondelete="RESTRICT"), index=True
    )
    baseline_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    next_measurement: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="performance_comparisons")
    current_run: Mapped[Run] = relationship(back_populates="performance_comparisons")
    current_observation: Mapped[PerformanceObservation] = relationship(
        back_populates="current_comparisons",
        foreign_keys=[current_observation_id],
    )
    baseline_snapshot: Mapped[PerformanceBaselineSnapshot] = relationship(
        back_populates="comparison"
    )
    policy: Mapped[PerformancePolicy] = relationship(back_populates="comparisons")
    current_evidence: Mapped[Evidence] = relationship(
        foreign_keys=[current_evidence_id]
    )


class InfrastructureEvent(Base):
    __tablename__ = "infrastructure_events"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "producer",
            "producer_event_id",
            name="uq_infrastructure_event_identity",
        ),
        Index(
            "ix_infrastructure_events_project_time",
            "project_id",
            "started_at",
            "ended_at",
        ),
        Index(
            "ix_infrastructure_events_project_kind",
            "project_id",
            "event_kind",
            "started_at",
        ),
        Index(
            "ix_infrastructure_events_project_trust",
            "project_id",
            "source_trust",
            "recorded_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    repository: Mapped[str | None] = mapped_column(String(240), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(160), nullable=True)
    producer: Mapped[str] = mapped_column(String(120))
    producer_event_id: Mapped[str] = mapped_column(String(240))
    event_kind: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(40), default="unknown")
    status: Mapped[str] = mapped_column(String(40), default="observed")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    workflow_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    workflow_run_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    workflow_attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    runner_identity: Mapped[str | None] = mapped_column(String(240), nullable=True)
    runner_group: Mapped[str | None] = mapped_column(String(240), nullable=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    worker_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shard_identity: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_trust: Mapped[str] = mapped_column(String(40), default="unknown")
    source_digest: Mapped[str] = mapped_column(String(64))
    evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence.id", ondelete="SET NULL"), nullable=True, index=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="infrastructure_events")
    evidence: Mapped[Evidence | None] = relationship(
        back_populates="infrastructure_events"
    )


class InfrastructureCorrelationSnapshot(Base):
    __tablename__ = "infrastructure_correlation_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "input_digest",
            name="uq_infrastructure_correlation_input",
        ),
        Index(
            "ix_infrastructure_correlations_execution_created",
            "selected_execution_id",
            "created_at",
        ),
        Index(
            "ix_infrastructure_correlations_project_status",
            "project_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    selected_run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    selected_execution_id: Mapped[str] = mapped_column(
        ForeignKey("test_executions.id", ondelete="CASCADE"), index=True
    )
    policy_version: Mapped[str] = mapped_column(String(80))
    engine_version: Mapped[str] = mapped_column(String(80))
    history_input_digest: Mapped[str] = mapped_column(String(64))
    input_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40))
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    after_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    window_seconds: Mapped[int] = mapped_column(Integer)
    event_kind: Mapped[str | None] = mapped_column(String(80), nullable=True)
    minimum_support: Mapped[int] = mapped_column(Integer)
    accepted_event_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    rejected_events: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    sample_sizes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    exposed_outcomes: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    unexposed_outcomes: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    rates: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    associations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    confounders: Mapped[list[str]] = mapped_column(JSON, default=list)
    safety: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(
        back_populates="infrastructure_correlation_snapshots"
    )
    selected_run: Mapped[Run] = relationship(
        back_populates="infrastructure_correlation_snapshots"
    )
    selected_execution: Mapped[TestExecution] = relationship(
        back_populates="infrastructure_correlation_snapshots"
    )
    members: Mapped[list[InfrastructureCorrelationMember]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class InfrastructureCorrelationMember(Base):
    __tablename__ = "infrastructure_correlation_members"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "run_id", name="uq_infrastructure_correlation_run"
        ),
        Index(
            "ix_infrastructure_correlation_members_snapshot_exposed",
            "snapshot_id",
            "exposed",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("infrastructure_correlation_snapshots.id", ondelete="CASCADE"),
        index=True,
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT"), index=True
    )
    execution_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    outcome: Mapped[str] = mapped_column(String(40))
    exposed: Mapped[bool] = mapped_column(Boolean, default=False)
    event_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    event_kinds: Mapped[list[str]] = mapped_column(JSON, default=list)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    snapshot: Mapped[InfrastructureCorrelationSnapshot] = relationship(
        back_populates="members"
    )
    run: Mapped[Run] = relationship(
        back_populates="infrastructure_correlation_members"
    )


class BinaryEvidence(Base):
    """An input-bound binary evidence workflow; the source itself stays restricted."""
    __tablename__ = "binary_evidence"
    input_id: Mapped[str] = mapped_column(ForeignKey("run_inputs.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id", ondelete="CASCADE"))
    execution_id: Mapped[str | None] = mapped_column(ForeignKey("test_executions.id", ondelete="SET NULL"), nullable=True)
    current_derivative_id: Mapped[str | None] = mapped_column(ForeignKey("artifact_derivatives.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(40), default="restricted")
    correlation: Mapped[str] = mapped_column(String(80), default="unassociated")


class BinaryEvidenceDecision(Base):
    __tablename__ = "binary_evidence_decisions"
    __table_args__ = (UniqueConstraint("input_id", "version", name="uq_binary_decision_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    input_id: Mapped[str] = mapped_column(ForeignKey("binary_evidence.input_id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    derivative_id: Mapped[str | None] = mapped_column(ForeignKey("artifact_derivatives.id", ondelete="SET NULL"), nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[str] = mapped_column(String(240))
    actor_display: Mapped[str] = mapped_column(String(240))
    reason: Mapped[str] = mapped_column(Text)
    masks: Mapped[list[dict[str, int]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
