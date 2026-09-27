"""add independently recorded infrastructure event correlation

Revision ID: c7a9e2f4b610
Revises: b2c8e5f1a730
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7a9e2f4b610"
down_revision: str | None = "b2c8e5f1a730"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "infrastructure_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("repository", sa.String(length=240), nullable=True),
        sa.Column("environment", sa.String(length=160), nullable=True),
        sa.Column("producer", sa.String(length=120), nullable=False),
        sa.Column("producer_event_id", sa.String(length=240), nullable=False),
        sa.Column("event_kind", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workflow_name", sa.String(length=240), nullable=True),
        sa.Column("workflow_run_id", sa.String(length=120), nullable=True),
        sa.Column("workflow_attempt", sa.Integer(), nullable=True),
        sa.Column("runner_identity", sa.String(length=240), nullable=True),
        sa.Column("runner_group", sa.String(length=240), nullable=True),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("worker_count", sa.Integer(), nullable=True),
        sa.Column("shard_identity", sa.String(length=120), nullable=True),
        sa.Column("source_trust", sa.String(length=40), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "producer",
            "producer_event_id",
            name="uq_infrastructure_event_identity",
        ),
    )
    op.create_index(
        "ix_infrastructure_events_project_id",
        "infrastructure_events",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_infrastructure_events_evidence_id",
        "infrastructure_events",
        ["evidence_id"],
        unique=False,
    )
    op.create_index(
        "ix_infrastructure_events_project_time",
        "infrastructure_events",
        ["project_id", "started_at", "ended_at"],
        unique=False,
    )
    op.create_index(
        "ix_infrastructure_events_project_kind",
        "infrastructure_events",
        ["project_id", "event_kind", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_infrastructure_events_project_trust",
        "infrastructure_events",
        ["project_id", "source_trust", "recorded_at"],
        unique=False,
    )

    op.create_table(
        "infrastructure_correlation_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("selected_run_id", sa.String(length=36), nullable=False),
        sa.Column("selected_execution_id", sa.String(length=36), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("engine_version", sa.String(length=80), nullable=False),
        sa.Column("history_input_digest", sa.String(length=64), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("after_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("event_kind", sa.String(length=80), nullable=True),
        sa.Column("minimum_support", sa.Integer(), nullable=False),
        sa.Column("accepted_event_ids", sa.JSON(), nullable=False),
        sa.Column("rejected_events", sa.JSON(), nullable=False),
        sa.Column("sample_sizes", sa.JSON(), nullable=False),
        sa.Column("exposed_outcomes", sa.JSON(), nullable=False),
        sa.Column("unexposed_outcomes", sa.JSON(), nullable=False),
        sa.Column("rates", sa.JSON(), nullable=False),
        sa.Column("associations", sa.JSON(), nullable=False),
        sa.Column("confounders", sa.JSON(), nullable=False),
        sa.Column("safety", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["selected_run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["selected_execution_id"], ["test_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "input_digest", name="uq_infrastructure_correlation_input"
        ),
    )
    for column in ("project_id", "selected_run_id", "selected_execution_id"):
        op.create_index(
            f"ix_infrastructure_correlation_snapshots_{column}",
            "infrastructure_correlation_snapshots",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_infrastructure_correlations_execution_created",
        "infrastructure_correlation_snapshots",
        ["selected_execution_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_infrastructure_correlations_project_status",
        "infrastructure_correlation_snapshots",
        ["project_id", "status"],
        unique=False,
    )

    op.create_table(
        "infrastructure_correlation_members",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("execution_ids", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("exposed", sa.Boolean(), nullable=False),
        sa.Column("event_ids", sa.JSON(), nullable=False),
        sa.Column("event_kinds", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["infrastructure_correlation_snapshots.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id", "run_id", name="uq_infrastructure_correlation_run"
        ),
    )
    op.create_index(
        "ix_infrastructure_correlation_members_snapshot_id",
        "infrastructure_correlation_members",
        ["snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_infrastructure_correlation_members_run_id",
        "infrastructure_correlation_members",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_infrastructure_correlation_members_snapshot_exposed",
        "infrastructure_correlation_members",
        ["snapshot_id", "exposed"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_infrastructure_correlation_members_snapshot_exposed",
        table_name="infrastructure_correlation_members",
    )
    op.drop_index(
        "ix_infrastructure_correlation_members_run_id",
        table_name="infrastructure_correlation_members",
    )
    op.drop_index(
        "ix_infrastructure_correlation_members_snapshot_id",
        table_name="infrastructure_correlation_members",
    )
    op.drop_table("infrastructure_correlation_members")

    op.drop_index(
        "ix_infrastructure_correlations_project_status",
        table_name="infrastructure_correlation_snapshots",
    )
    op.drop_index(
        "ix_infrastructure_correlations_execution_created",
        table_name="infrastructure_correlation_snapshots",
    )
    for column in ("selected_execution_id", "selected_run_id", "project_id"):
        op.drop_index(
            f"ix_infrastructure_correlation_snapshots_{column}",
            table_name="infrastructure_correlation_snapshots",
        )
    op.drop_table("infrastructure_correlation_snapshots")

    op.drop_index(
        "ix_infrastructure_events_project_trust", table_name="infrastructure_events"
    )
    op.drop_index(
        "ix_infrastructure_events_project_kind", table_name="infrastructure_events"
    )
    op.drop_index(
        "ix_infrastructure_events_project_time", table_name="infrastructure_events"
    )
    op.drop_index(
        "ix_infrastructure_events_evidence_id", table_name="infrastructure_events"
    )
    op.drop_index(
        "ix_infrastructure_events_project_id", table_name="infrastructure_events"
    )
    op.drop_table("infrastructure_events")
