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


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    runs: Mapped[list[Run]] = relationship(back_populates="project", cascade="all, delete-orphan")
    ingestions: Mapped[list[Ingestion]] = relationship(back_populates="project", cascade="all, delete-orphan")
    clusters: Mapped[list[FailureCluster]] = relationship(
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
    decision: Mapped[str] = mapped_column(String(80))
    proposed_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    analysis: Mapped[Analysis] = relationship(back_populates="reviews")
