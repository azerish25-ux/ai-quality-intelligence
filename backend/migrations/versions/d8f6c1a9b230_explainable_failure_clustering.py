"""add explainable failure clustering and append-only revisions

Revision ID: d8f6c1a9b230
Revises: c4e1d9a7b2f0
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8f6c1a9b230"
down_revision: str | None = "c4e1d9a7b2f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "failure_clusters",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("cluster_key", sa.String(length=64), nullable=False),
        sa.Column("algorithm_version", sa.String(length=80), nullable=False),
        sa.Column("feature_version", sa.String(length=80), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("representative_failure_id", sa.String(length=36), nullable=True),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("uncertainty", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("superseded_by_cluster_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["representative_failure_id"], ["failures.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_cluster_id"], ["failure_clusters.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "cluster_key", name="uq_failure_cluster_key"),
    )
    op.create_index(
        op.f("ix_failure_clusters_project_id"),
        "failure_clusters",
        ["project_id"],
    )
    op.create_index(
        op.f("ix_failure_clusters_representative_failure_id"),
        "failure_clusters",
        ["representative_failure_id"],
    )
    op.create_index(
        op.f("ix_failure_clusters_superseded_by_cluster_id"),
        "failure_clusters",
        ["superseded_by_cluster_id"],
    )
    op.create_index(
        "ix_failure_clusters_project_status",
        "failure_clusters",
        ["project_id", "status"],
    )

    op.create_table(
        "cluster_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("cluster_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("algorithm_version", sa.String(length=80), nullable=False),
        sa.Column("feature_version", sa.String(length=80), nullable=False),
        sa.Column("representative_failure_id", sa.String(length=36), nullable=True),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("score_summary", sa.JSON(), nullable=False),
        sa.Column("uncertainty_flags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["cluster_id"], ["failure_clusters.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["representative_failure_id"], ["failures.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cluster_id", "revision", name="uq_cluster_revision"),
    )
    op.create_index(
        op.f("ix_cluster_revisions_cluster_id"),
        "cluster_revisions",
        ["cluster_id"],
    )
    op.create_index(
        op.f("ix_cluster_revisions_representative_failure_id"),
        "cluster_revisions",
        ["representative_failure_id"],
    )
    op.create_index(
        "ix_cluster_revisions_cluster_created",
        "cluster_revisions",
        ["cluster_id", "created_at"],
    )

    op.create_table(
        "cluster_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("cluster_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("failure_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("score_components", sa.JSON(), nullable=False),
        sa.Column("matching_signals", sa.JSON(), nullable=False),
        sa.Column("conflicting_signals", sa.JSON(), nullable=False),
        sa.Column("candidate_reasons", sa.JSON(), nullable=False),
        sa.Column("assignment_kind", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["cluster_id"], ["failure_clusters.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["cluster_revisions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["failure_id"], ["failures.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "revision_id", "failure_id", name="uq_cluster_revision_failure"
        ),
    )
    op.create_index(
        op.f("ix_cluster_memberships_cluster_id"),
        "cluster_memberships",
        ["cluster_id"],
    )
    op.create_index(
        op.f("ix_cluster_memberships_revision_id"),
        "cluster_memberships",
        ["revision_id"],
    )
    op.create_index(
        op.f("ix_cluster_memberships_failure_id"),
        "cluster_memberships",
        ["failure_id"],
    )
    op.create_index(
        "ix_cluster_memberships_cluster_revision",
        "cluster_memberships",
        ["cluster_id", "revision_id"],
    )
    op.create_index(
        "ix_cluster_memberships_failure_revision",
        "cluster_memberships",
        ["failure_id", "revision_id"],
    )

    op.create_table(
        "cluster_membership_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("cluster_id", sa.String(length=36), nullable=False),
        sa.Column("target_cluster_id", sa.String(length=36), nullable=True),
        sa.Column("actor", sa.String(length=240), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("failure_ids", sa.JSON(), nullable=False),
        sa.Column("revision_before", sa.Integer(), nullable=False),
        sa.Column("revision_after", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["cluster_id"], ["failure_clusters.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_cluster_id"], ["failure_clusters.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_cluster_membership_decisions_cluster_id"),
        "cluster_membership_decisions",
        ["cluster_id"],
    )
    op.create_index(
        op.f("ix_cluster_membership_decisions_target_cluster_id"),
        "cluster_membership_decisions",
        ["target_cluster_id"],
    )
    op.create_index(
        "ix_cluster_decisions_cluster_created",
        "cluster_membership_decisions",
        ["cluster_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cluster_decisions_cluster_created",
        table_name="cluster_membership_decisions",
    )
    op.drop_index(
        op.f("ix_cluster_membership_decisions_target_cluster_id"),
        table_name="cluster_membership_decisions",
    )
    op.drop_index(
        op.f("ix_cluster_membership_decisions_cluster_id"),
        table_name="cluster_membership_decisions",
    )
    op.drop_table("cluster_membership_decisions")

    op.drop_index(
        "ix_cluster_memberships_failure_revision", table_name="cluster_memberships"
    )
    op.drop_index(
        "ix_cluster_memberships_cluster_revision", table_name="cluster_memberships"
    )
    op.drop_index(
        op.f("ix_cluster_memberships_failure_id"), table_name="cluster_memberships"
    )
    op.drop_index(
        op.f("ix_cluster_memberships_revision_id"), table_name="cluster_memberships"
    )
    op.drop_index(
        op.f("ix_cluster_memberships_cluster_id"), table_name="cluster_memberships"
    )
    op.drop_table("cluster_memberships")

    op.drop_index(
        "ix_cluster_revisions_cluster_created", table_name="cluster_revisions"
    )
    op.drop_index(
        op.f("ix_cluster_revisions_representative_failure_id"),
        table_name="cluster_revisions",
    )
    op.drop_index(
        op.f("ix_cluster_revisions_cluster_id"), table_name="cluster_revisions"
    )
    op.drop_table("cluster_revisions")

    op.drop_index("ix_failure_clusters_project_status", table_name="failure_clusters")
    op.drop_index(
        op.f("ix_failure_clusters_superseded_by_cluster_id"),
        table_name="failure_clusters",
    )
    op.drop_index(
        op.f("ix_failure_clusters_representative_failure_id"),
        table_name="failure_clusters",
    )
    op.drop_index(op.f("ix_failure_clusters_project_id"), table_name="failure_clusters")
    op.drop_table("failure_clusters")
