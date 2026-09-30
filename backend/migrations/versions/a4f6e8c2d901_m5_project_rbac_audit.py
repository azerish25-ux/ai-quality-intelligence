"""add project-scoped authentication, authorization, and audit records

Revision ID: a4f6e8c2d901
Revises: c7a9e2f4b610
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4f6e8c2d901"
down_revision: str | None = "c7a9e2f4b610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

project_role = sa.Enum("viewer", "reviewer", "administrator", name="projectrole")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("username", sa.String(240), nullable=False),
        sa.Column("display_name", sa.String(240), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "is_system_admin", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_table(
        "project_memberships",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role", project_role, nullable=False),
        sa.Column("granted_by_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_membership"),
    )
    op.create_index(
        "ix_project_memberships_project_id", "project_memberships", ["project_id"]
    )
    op.create_index(
        "ix_project_memberships_user_id", "project_memberships", ["user_id"]
    )
    op.create_index(
        "ix_project_memberships_user_project",
        "project_memberships",
        ["user_id", "project_id"],
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("token_prefix", sa.String(24), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_auth_session_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_token_prefix", "auth_sessions", ["token_prefix"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_index(
        "ix_auth_sessions_user_expiry", "auth_sessions", ["user_id", "expires_at"]
    )
    op.create_table(
        "ingestion_tokens",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("token_prefix", sa.String(24), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_ingestion_token_hash"),
    )
    op.create_index(
        "ix_ingestion_tokens_project_id", "ingestion_tokens", ["project_id"]
    )
    op.create_index(
        "ix_ingestion_tokens_token_prefix", "ingestion_tokens", ["token_prefix"]
    )
    op.create_index(
        "ix_ingestion_tokens_project_active",
        "ingestion_tokens",
        ["project_id", "revoked_at"],
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("actor_kind", sa.String(40), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("actor_display", sa.String(240), nullable=False),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(240), nullable=True),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(120), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_project_id", "audit_events", ["project_id"])
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_resource_type", "audit_events", ["resource_type"])
    op.create_index(
        "ix_audit_events_project_created", "audit_events", ["project_id", "created_at"]
    )
    op.create_index(
        "ix_audit_events_actor_created", "audit_events", ["actor_user_id", "created_at"]
    )
    op.create_index(
        "ix_audit_events_resource", "audit_events", ["resource_type", "resource_id"]
    )

    with op.batch_alter_table("cluster_membership_decisions") as batch:
        batch.add_column(
            sa.Column(
                "actor_kind", sa.String(40), nullable=False, server_default="legacy"
            )
        )
        batch.add_column(sa.Column("actor_user_id", sa.String(36), nullable=True))
        batch.create_index(
            "ix_cluster_membership_decisions_actor_user_id", ["actor_user_id"]
        )
        batch.create_foreign_key(
            "fk_cluster_decisions_actor_user",
            "users",
            ["actor_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("review_events") as batch:
        batch.add_column(
            sa.Column(
                "actor_kind", sa.String(40), nullable=False, server_default="legacy"
            )
        )
        batch.add_column(sa.Column("actor_user_id", sa.String(36), nullable=True))
        batch.add_column(
            sa.Column(
                "supporting_evidence_ids",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.add_column(
            sa.Column(
                "contradictory_evidence_ids",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.add_column(
            sa.Column(
                "hypothesis_decisions",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.add_column(sa.Column("investigation_outcome", sa.Text(), nullable=True))
        batch.add_column(sa.Column("release_advice", sa.String(80), nullable=True))
        batch.create_index("ix_review_events_actor_user_id", ["actor_user_id"])
        batch.create_foreign_key(
            "fk_review_events_actor_user",
            "users",
            ["actor_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("impact_overrides") as batch:
        batch.add_column(
            sa.Column(
                "actor_kind", sa.String(40), nullable=False, server_default="legacy"
            )
        )
        batch.add_column(sa.Column("actor_user_id", sa.String(36), nullable=True))
        batch.create_index("ix_impact_overrides_actor_user_id", ["actor_user_id"])
        batch.create_foreign_key(
            "fk_impact_overrides_actor_user",
            "users",
            ["actor_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("impact_overrides") as batch:
        batch.drop_constraint("fk_impact_overrides_actor_user", type_="foreignkey")
        batch.drop_index("ix_impact_overrides_actor_user_id")
        batch.drop_column("actor_user_id")
        batch.drop_column("actor_kind")
    with op.batch_alter_table("review_events") as batch:
        batch.drop_constraint("fk_review_events_actor_user", type_="foreignkey")
        batch.drop_index("ix_review_events_actor_user_id")
        for name in [
            "release_advice",
            "investigation_outcome",
            "hypothesis_decisions",
            "contradictory_evidence_ids",
            "supporting_evidence_ids",
            "actor_user_id",
            "actor_kind",
        ]:
            batch.drop_column(name)
    with op.batch_alter_table("cluster_membership_decisions") as batch:
        batch.drop_constraint("fk_cluster_decisions_actor_user", type_="foreignkey")
        batch.drop_index("ix_cluster_membership_decisions_actor_user_id")
        batch.drop_column("actor_user_id")
        batch.drop_column("actor_kind")
    for name in [
        "ix_audit_events_resource",
        "ix_audit_events_actor_created",
        "ix_audit_events_project_created",
        "ix_audit_events_resource_type",
        "ix_audit_events_action",
        "ix_audit_events_actor_user_id",
        "ix_audit_events_project_id",
    ]:
        op.drop_index(name, table_name="audit_events")
    op.drop_table("audit_events")
    for name in [
        "ix_ingestion_tokens_project_active",
        "ix_ingestion_tokens_token_prefix",
        "ix_ingestion_tokens_project_id",
    ]:
        op.drop_index(name, table_name="ingestion_tokens")
    op.drop_table("ingestion_tokens")
    for name in [
        "ix_auth_sessions_user_expiry",
        "ix_auth_sessions_expires_at",
        "ix_auth_sessions_token_prefix",
        "ix_auth_sessions_user_id",
    ]:
        op.drop_index(name, table_name="auth_sessions")
    op.drop_table("auth_sessions")
    for name in [
        "ix_project_memberships_user_project",
        "ix_project_memberships_user_id",
        "ix_project_memberships_project_id",
    ]:
        op.drop_index(name, table_name="project_memberships")
    op.drop_table("project_memberships")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
    project_role.drop(op.get_bind(), checkfirst=True)
