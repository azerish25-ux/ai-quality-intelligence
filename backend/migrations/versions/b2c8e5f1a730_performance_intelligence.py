"""add compatible performance baselines and regression comparisons

Revision ID: b2c8e5f1a730
Revises: f1a9d4c7e620
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c8e5f1a730"
down_revision: str | None = "f1a9d4c7e620"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "performance_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("relative_tolerance", sa.Float(), nullable=False),
        sa.Column("absolute_tolerance", sa.Float(), nullable=False),
        sa.Column("min_baseline_runs", sa.Integer(), nullable=False),
        sa.Column("max_baseline_age_days", sa.Integer(), nullable=False),
        sa.Column("require_trusted", sa.Boolean(), nullable=False),
        sa.Column("required_dimensions", sa.JSON(), nullable=False),
        sa.Column("direction_overrides", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "version", name="uq_performance_policy_version"
        ),
    )
    op.create_index(
        "ix_performance_policies_project_id",
        "performance_policies",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_performance_policies_project_created",
        "performance_policies",
        ["project_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "performance_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("run_input_id", sa.String(length=36), nullable=True),
        sa.Column("execution_id", sa.String(length=36), nullable=True),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("metric_key", sa.String(length=64), nullable=False),
        sa.Column("metric_name", sa.String(length=240), nullable=False),
        sa.Column("metric_scope", sa.String(length=40), nullable=False),
        sa.Column("statistic", sa.String(length=80), nullable=False),
        sa.Column("direction", sa.String(length=40), nullable=False),
        sa.Column("original_value", sa.Float(), nullable=False),
        sa.Column("original_unit", sa.String(length=40), nullable=False),
        sa.Column("canonical_value", sa.Float(), nullable=False),
        sa.Column("canonical_unit", sa.String(length=40), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=True),
        sa.Column("producer", sa.String(length=120), nullable=False),
        sa.Column("producer_version", sa.String(length=80), nullable=True),
        sa.Column("workload", sa.String(length=512), nullable=False),
        sa.Column("dimension_signature", sa.String(length=64), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.Column("threshold_status", sa.String(length=40), nullable=False),
        sa.Column("threshold_details", sa.JSON(), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("source_locator", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["run_input_id"], ["run_inputs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["test_executions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "metric_key", name="uq_performance_run_metric"),
    )
    for column in (
        "project_id",
        "run_id",
        "run_input_id",
        "execution_id",
        "evidence_id",
    ):
        op.create_index(
            f"ix_performance_observations_{column}",
            "performance_observations",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_performance_observations_lookup",
        "performance_observations",
        ["project_id", "metric_name", "statistic", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_performance_observations_cohort",
        "performance_observations",
        ["project_id", "dimension_signature", "observed_at"],
        unique=False,
    )

    op.create_table(
        "performance_baseline_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("current_run_id", sa.String(length=36), nullable=False),
        sa.Column("current_observation_id", sa.String(length=36), nullable=False),
        sa.Column("policy_id", sa.String(length=36), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cohort_dimensions", sa.JSON(), nullable=False),
        sa.Column("compatibility", sa.JSON(), nullable=False),
        sa.Column("rejected_candidates", sa.JSON(), nullable=False),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("baseline_value", sa.Float(), nullable=True),
        sa.Column("baseline_min", sa.Float(), nullable=True),
        sa.Column("baseline_max", sa.Float(), nullable=True),
        sa.Column("baseline_mad", sa.Float(), nullable=True),
        sa.Column("baseline_age_seconds", sa.Float(), nullable=True),
        sa.Column("aggregation", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["current_observation_id"],
            ["performance_observations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"], ["performance_policies.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "input_digest", name="uq_performance_baseline_input"
        ),
    )
    for column in (
        "project_id",
        "current_run_id",
        "current_observation_id",
        "policy_id",
    ):
        op.create_index(
            f"ix_performance_baseline_snapshots_{column}",
            "performance_baseline_snapshots",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_performance_baselines_run_created",
        "performance_baseline_snapshots",
        ["current_run_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "performance_baseline_members",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("observation_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["performance_baseline_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["performance_observations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id", "observation_id", name="uq_performance_baseline_member"
        ),
    )
    for column in ("snapshot_id", "observation_id", "run_id"):
        op.create_index(
            f"ix_performance_baseline_members_{column}",
            "performance_baseline_members",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_performance_baseline_members_order",
        "performance_baseline_members",
        ["snapshot_id", "position"],
        unique=False,
    )

    op.create_table(
        "performance_comparisons",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("current_run_id", sa.String(length=36), nullable=False),
        sa.Column("current_observation_id", sa.String(length=36), nullable=False),
        sa.Column("baseline_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("policy_id", sa.String(length=36), nullable=False),
        sa.Column("engine_version", sa.String(length=80), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("current_value", sa.Float(), nullable=False),
        sa.Column("baseline_value", sa.Float(), nullable=True),
        sa.Column("absolute_change", sa.Float(), nullable=True),
        sa.Column("relative_change", sa.Float(), nullable=True),
        sa.Column("allowed_absolute_change", sa.Float(), nullable=False),
        sa.Column("allowed_relative_change", sa.Float(), nullable=False),
        sa.Column("current_sample_count", sa.Integer(), nullable=True),
        sa.Column("baseline_run_count", sa.Integer(), nullable=False),
        sa.Column("baseline_sample_count", sa.Integer(), nullable=False),
        sa.Column("threshold_status", sa.String(length=40), nullable=False),
        sa.Column("effect_size", sa.Float(), nullable=True),
        sa.Column("uncertainty", sa.JSON(), nullable=False),
        sa.Column("compatibility", sa.JSON(), nullable=False),
        sa.Column("confounders", sa.JSON(), nullable=False),
        sa.Column("current_evidence_id", sa.String(length=36), nullable=False),
        sa.Column("baseline_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("next_measurement", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["current_observation_id"],
            ["performance_observations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_snapshot_id"],
            ["performance_baseline_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"], ["performance_policies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["current_evidence_id"], ["evidence.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("baseline_snapshot_id"),
        sa.UniqueConstraint(
            "project_id", "input_digest", name="uq_performance_comparison_input"
        ),
    )
    for column in (
        "project_id",
        "current_run_id",
        "current_observation_id",
        "baseline_snapshot_id",
        "policy_id",
        "current_evidence_id",
    ):
        op.create_index(
            f"ix_performance_comparisons_{column}",
            "performance_comparisons",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_performance_comparisons_run_created",
        "performance_comparisons",
        ["current_run_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_performance_comparisons_status",
        "performance_comparisons",
        ["project_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_performance_comparisons_status", table_name="performance_comparisons"
    )
    op.drop_index(
        "ix_performance_comparisons_run_created", table_name="performance_comparisons"
    )
    for column in (
        "current_evidence_id",
        "policy_id",
        "baseline_snapshot_id",
        "current_observation_id",
        "current_run_id",
        "project_id",
    ):
        op.drop_index(
            f"ix_performance_comparisons_{column}", table_name="performance_comparisons"
        )
    op.drop_table("performance_comparisons")

    op.drop_index(
        "ix_performance_baseline_members_order",
        table_name="performance_baseline_members",
    )
    for column in ("run_id", "observation_id", "snapshot_id"):
        op.drop_index(
            f"ix_performance_baseline_members_{column}",
            table_name="performance_baseline_members",
        )
    op.drop_table("performance_baseline_members")

    op.drop_index(
        "ix_performance_baselines_run_created",
        table_name="performance_baseline_snapshots",
    )
    for column in (
        "policy_id",
        "current_observation_id",
        "current_run_id",
        "project_id",
    ):
        op.drop_index(
            f"ix_performance_baseline_snapshots_{column}",
            table_name="performance_baseline_snapshots",
        )
    op.drop_table("performance_baseline_snapshots")

    op.drop_index(
        "ix_performance_observations_cohort", table_name="performance_observations"
    )
    op.drop_index(
        "ix_performance_observations_lookup", table_name="performance_observations"
    )
    for column in (
        "evidence_id",
        "execution_id",
        "run_input_id",
        "run_id",
        "project_id",
    ):
        op.drop_index(
            f"ix_performance_observations_{column}",
            table_name="performance_observations",
        )
    op.drop_table("performance_observations")

    op.drop_index(
        "ix_performance_policies_project_created", table_name="performance_policies"
    )
    op.drop_index(
        "ix_performance_policies_project_id", table_name="performance_policies"
    )
    op.drop_table("performance_policies")
