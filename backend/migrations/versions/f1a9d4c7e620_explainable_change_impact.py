"""add explainable change-impact recommendations and audited overrides

Revision ID: f1a9d4c7e620
Revises: e4b7c2d9a510
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a9d4c7e620"
down_revision: str | None = "e4b7c2d9a510"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "impact_mapping_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("trusted", sa.Boolean(), nullable=False),
        sa.Column("coverage_complete", sa.Boolean(), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "version",
            name="uq_impact_mapping_snapshot_identity",
        ),
    )
    op.create_index(
        "ix_impact_mapping_snapshots_project_id",
        "impact_mapping_snapshots",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_impact_mapping_snapshots_project_created",
        "impact_mapping_snapshots",
        ["project_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "impact_test_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("test_key", sa.String(length=240), nullable=False),
        sa.Column("test_identity", sa.String(length=512), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=True),
        sa.Column("criticality", sa.String(length=40), nullable=False),
        sa.Column("mandatory", sa.Boolean(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("estimated_duration_ms", sa.Float(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["impact_mapping_snapshots.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id", "test_key", name="uq_impact_test_snapshot_key"
        ),
    )
    op.create_index(
        "ix_impact_test_definitions_snapshot_id",
        "impact_test_definitions",
        ["snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_impact_tests_snapshot_identity",
        "impact_test_definitions",
        ["snapshot_id", "test_identity"],
        unique=False,
    )

    op.create_table(
        "impact_mapping_edges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_value", sa.String(length=1024), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("mapping_source", sa.String(length=120), nullable=False),
        sa.Column("mapping_version", sa.String(length=80), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["impact_mapping_snapshots.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_impact_mapping_edges_snapshot_id",
        "impact_mapping_edges",
        ["snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_impact_edges_snapshot_source",
        "impact_mapping_edges",
        ["snapshot_id", "source_path"],
        unique=False,
    )
    op.create_index(
        "ix_impact_edges_snapshot_target",
        "impact_mapping_edges",
        ["snapshot_id", "target_type", "target_value"],
        unique=False,
    )

    op.create_table(
        "impact_recommendations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("changed_input_id", sa.String(length=36), nullable=False),
        sa.Column("mapping_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("base_sha", sa.String(length=64), nullable=True),
        sa.Column("head_sha", sa.String(length=64), nullable=True),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("changed_files_digest", sa.String(length=64), nullable=False),
        sa.Column("engine_version", sa.String(length=80), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("comparison_trusted", sa.Boolean(), nullable=False),
        sa.Column("mapping_complete", sa.Boolean(), nullable=False),
        sa.Column("full_suite_required", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("changed_files", sa.JSON(), nullable=False),
        sa.Column("safety_reasons", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["changed_input_id"], ["run_inputs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["mapping_snapshot_id"],
            ["impact_mapping_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "input_digest", name="uq_impact_recommendation_input"
        ),
    )
    op.create_index(
        "ix_impact_recommendations_project_id",
        "impact_recommendations",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_impact_recommendations_run_id",
        "impact_recommendations",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_impact_recommendations_changed_input_id",
        "impact_recommendations",
        ["changed_input_id"],
        unique=False,
    )
    op.create_index(
        "ix_impact_recommendations_mapping_snapshot_id",
        "impact_recommendations",
        ["mapping_snapshot_id"],
        unique=False,
    )
    op.create_index(
        "ix_impact_recommendations_project_created",
        "impact_recommendations",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_impact_recommendations_run",
        "impact_recommendations",
        ["run_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "impact_recommendation_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("recommendation_id", sa.String(length=36), nullable=False),
        sa.Column("test_key", sa.String(length=240), nullable=False),
        sa.Column("test_identity", sa.String(length=512), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=True),
        sa.Column("criticality", sa.String(length=40), nullable=False),
        sa.Column("mandatory", sa.Boolean(), nullable=False),
        sa.Column("base_selected", sa.Boolean(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.String(length=40), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("mapping_edge_ids", sa.JSON(), nullable=False),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["recommendation_id"], ["impact_recommendations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recommendation_id",
            "test_key",
            name="uq_impact_recommendation_test",
        ),
    )
    op.create_index(
        "ix_impact_recommendation_items_recommendation_id",
        "impact_recommendation_items",
        ["recommendation_id"],
        unique=False,
    )
    op.create_index(
        "ix_impact_recommendation_items_selected",
        "impact_recommendation_items",
        ["recommendation_id", "base_selected", "rank"],
        unique=False,
    )

    op.create_table(
        "impact_overrides",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("recommendation_id", sa.String(length=36), nullable=False),
        sa.Column("actor", sa.String(length=240), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("test_key", sa.String(length=240), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("revision_before", sa.Integer(), nullable=False),
        sa.Column("revision_after", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["recommendation_id"], ["impact_recommendations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_impact_overrides_recommendation_id",
        "impact_overrides",
        ["recommendation_id"],
        unique=False,
    )
    op.create_index(
        "ix_impact_overrides_recommendation_revision",
        "impact_overrides",
        ["recommendation_id", "revision_after"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_impact_overrides_recommendation_revision", table_name="impact_overrides"
    )
    op.drop_index(
        "ix_impact_overrides_recommendation_id", table_name="impact_overrides"
    )
    op.drop_table("impact_overrides")
    op.drop_index(
        "ix_impact_recommendation_items_selected",
        table_name="impact_recommendation_items",
    )
    op.drop_index(
        "ix_impact_recommendation_items_recommendation_id",
        table_name="impact_recommendation_items",
    )
    op.drop_table("impact_recommendation_items")
    op.drop_index("ix_impact_recommendations_run", table_name="impact_recommendations")
    op.drop_index(
        "ix_impact_recommendations_project_created",
        table_name="impact_recommendations",
    )
    op.drop_index(
        "ix_impact_recommendations_mapping_snapshot_id",
        table_name="impact_recommendations",
    )
    op.drop_index(
        "ix_impact_recommendations_changed_input_id",
        table_name="impact_recommendations",
    )
    op.drop_index(
        "ix_impact_recommendations_run_id", table_name="impact_recommendations"
    )
    op.drop_index(
        "ix_impact_recommendations_project_id", table_name="impact_recommendations"
    )
    op.drop_table("impact_recommendations")
    op.drop_index("ix_impact_edges_snapshot_target", table_name="impact_mapping_edges")
    op.drop_index("ix_impact_edges_snapshot_source", table_name="impact_mapping_edges")
    op.drop_index(
        "ix_impact_mapping_edges_snapshot_id", table_name="impact_mapping_edges"
    )
    op.drop_table("impact_mapping_edges")
    op.drop_index(
        "ix_impact_tests_snapshot_identity", table_name="impact_test_definitions"
    )
    op.drop_index(
        "ix_impact_test_definitions_snapshot_id", table_name="impact_test_definitions"
    )
    op.drop_table("impact_test_definitions")
    op.drop_index(
        "ix_impact_mapping_snapshots_project_created",
        table_name="impact_mapping_snapshots",
    )
    op.drop_index(
        "ix_impact_mapping_snapshots_project_id",
        table_name="impact_mapping_snapshots",
    )
    op.drop_table("impact_mapping_snapshots")
