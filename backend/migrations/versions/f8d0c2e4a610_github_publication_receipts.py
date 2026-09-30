"""Durable GitHub publication receipts and target reservations."""

import sqlalchemy as sa
from alembic import op

revision = "f8d0c2e4a610"
down_revision = "e6c8a2f4b130"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "github_publication_targets",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("repository", sa.String(240), nullable=False),
        sa.Column("pull_number", sa.BigInteger, nullable=False),
        sa.Column("active_publication_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id",
            "repository",
            "pull_number",
            name="uq_github_publication_target",
        ),
        sa.CheckConstraint("pull_number > 0", name="ck_github_target_pull_positive"),
    )
    op.create_index(
        "ix_github_publication_targets_project_id",
        "github_publication_targets",
        ["project_id"],
    )

    op.create_table(
        "github_publications",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "target_id",
            sa.String(36),
            sa.ForeignKey("github_publication_targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_kind", sa.String(32), nullable=False),
        sa.Column("publisher_id", sa.String(36), nullable=False),
        sa.Column("tested_head", sa.String(40), nullable=False),
        sa.Column("current_head", sa.String(40), nullable=True),
        sa.Column("report_digest", sa.String(64), nullable=False),
        sa.Column("report_schema_version", sa.String(40), nullable=False),
        sa.Column("analysis_manifest_digest", sa.String(64), nullable=False),
        sa.Column("analysis_count", sa.Integer(), nullable=False),
        sa.Column("analysis_revisions", sa.JSON(), nullable=False),
        sa.Column("omitted_analysis_revisions", sa.Integer(), nullable=False),
        sa.Column("bot_login", sa.String(120), nullable=False),
        sa.Column("bot_user_id", sa.BigInteger, nullable=True),
        sa.Column("actor_verification", sa.String(32), nullable=False),
        sa.Column("actor_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment_id", sa.BigInteger, nullable=True),
        sa.Column("source_run_id", sa.String(20), nullable=True),
        sa.Column("source_run_attempt", sa.Integer, nullable=True),
        sa.Column("source_verification", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('prepared','active','reconciling','created','updated','unchanged','stale','failed','uncertain')",
            name="ck_github_publication_status",
        ),
        sa.CheckConstraint(
            "actor_kind = 'publisher_process'", name="ck_github_publication_actor_kind"
        ),
        sa.CheckConstraint(
            "report_schema_version = 'github-report-v2'",
            name="ck_github_publication_report_schema",
        ),
        sa.CheckConstraint(
            "analysis_count >= 0 AND omitted_analysis_revisions >= 0 "
            "AND analysis_count >= omitted_analysis_revisions "
            "AND analysis_count - omitted_analysis_revisions <= 50",
            name="ck_github_publication_analysis_counts",
        ),
        sa.CheckConstraint(
            "actor_verification IN ('not_verified','verified')",
            name="ck_github_publication_actor_verification",
        ),
        sa.CheckConstraint(
            "source_verification IN ('not_supplied','unverified')",
            name="ck_github_publication_source_verification",
        ),
        sa.CheckConstraint(
            "(source_run_id IS NULL AND source_run_attempt IS NULL) OR (source_run_id IS NOT NULL AND source_run_attempt IS NOT NULL AND source_run_attempt BETWEEN 1 AND 1000000)",
            name="ck_github_publication_source_pair",
        ),
        sa.CheckConstraint(
            "(source_verification = 'not_supplied' AND source_run_id IS NULL AND source_run_attempt IS NULL) OR (source_verification = 'unverified' AND source_run_id IS NOT NULL AND source_run_attempt IS NOT NULL)",
            name="ck_github_publication_source_verification_pair",
        ),
        sa.CheckConstraint(
            "actor_verification != 'verified' OR (bot_user_id IS NOT NULL AND bot_user_id > 0 AND actor_verified_at IS NOT NULL)",
            name="ck_github_publication_verified_actor",
        ),
        sa.CheckConstraint(
            "comment_id IS NULL OR comment_id > 0",
            name="ck_github_publication_comment_positive",
        ),
        sa.CheckConstraint(
            "bot_user_id IS NULL OR bot_user_id > 0",
            name="ck_github_publication_bot_positive",
        ),
    )
    op.create_index(
        "ix_github_publications_target_id", "github_publications", ["target_id"]
    )
    op.create_index(
        "ix_github_publications_project_id", "github_publications", ["project_id"]
    )
    op.create_index("ix_github_publications_run_id", "github_publications", ["run_id"])
    op.create_index(
        "ix_github_publications_project_created",
        "github_publications",
        ["project_id", "created_at", "id"],
    )
    op.create_index(
        "ix_github_publications_run_created",
        "github_publications",
        ["run_id", "created_at", "id"],
    )

    op.create_table(
        "github_publication_writes",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "publication_id",
            sa.String(36),
            sa.ForeignKey("github_publications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("method", sa.String(5), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("tested_head", sa.String(40), nullable=False),
        sa.Column("comment_id", sa.BigInteger, nullable=True),
        sa.Column("body_digest", sa.String(64), nullable=False),
        sa.Column("revalidated_report_digest", sa.String(64), nullable=False),
        sa.Column("current_head", sa.String(40), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "publication_id", "sequence", name="uq_github_publication_write_sequence"
        ),
        sa.CheckConstraint(
            "sequence BETWEEN 1 AND 2", name="ck_github_publication_write_sequence"
        ),
        sa.CheckConstraint(
            "purpose IN ('report','stale')", name="ck_github_publication_write_purpose"
        ),
        sa.CheckConstraint(
            "method IN ('POST','PATCH')", name="ck_github_publication_write_method"
        ),
        sa.CheckConstraint(
            "state IN ('dispatching','observed','uncertain')",
            name="ck_github_publication_write_state",
        ),
        sa.CheckConstraint(
            "comment_id IS NULL OR comment_id > 0",
            name="ck_github_publication_write_comment_positive",
        ),
    )
    op.create_index(
        "ix_github_publication_writes_publication_id",
        "github_publication_writes",
        ["publication_id"],
    )


def downgrade():
    op.drop_table("github_publication_writes")
    op.drop_table("github_publications")
    op.drop_table("github_publication_targets")
