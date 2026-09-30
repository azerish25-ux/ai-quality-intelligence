"""durable ingestion pipeline

Revision ID: 7f3c1d9a2b44
Revises: 2bdd16d7c241
Create Date: 2026-09-26 22:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7f3c1d9a2b44"
down_revision: str | None = "2bdd16d7c241"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode keeps the revision executable for the supported SQLite
    # developer profile while remaining a normal ALTER on PostgreSQL.
    with op.batch_alter_table("analyses") as batch_op:
        batch_op.add_column(
            sa.Column("input_digest", sa.String(length=64), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_analysis_input",
            ["failure_id", "analysis_version", "input_digest"],
        )

    op.create_table(
        "ingestions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=240), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("repository", sa.String(length=240), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("base_sha", sa.String(length=64), nullable=True),
        sa.Column("branch", sa.String(length=240), nullable=True),
        sa.Column("source_format", sa.String(length=80), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("original_name", sa.String(length=1024), nullable=False),
        sa.Column("media_type", sa.String(length=160), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("source_size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(length=2048), nullable=False),
        sa.Column("expected_inputs", sa.Integer(), nullable=True),
        sa.Column("received_inputs", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "partial",
                "failed",
                "cancelled",
                "dead_lettered",
                name="ingestionstate",
            ),
            nullable=False,
        ),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("parser_version", sa.String(length=80), nullable=True),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
        sa.UniqueConstraint("run_id"),
        sa.UniqueConstraint(
            "project_id",
            "external_id",
            "attempt",
            "source_digest",
            name="uq_ingestion_identity",
        ),
    )
    op.create_index(
        "ix_ingestions_project_id", "ingestions", ["project_id"], unique=False
    )
    op.create_index(
        "ix_ingestions_project_created",
        "ingestions",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ingestions_state_created",
        "ingestions",
        ["state", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ingestions_state_created", table_name="ingestions")
    op.drop_index("ix_ingestions_project_created", table_name="ingestions")
    op.drop_index("ix_ingestions_project_id", table_name="ingestions")
    op.drop_table("ingestions")
    with op.batch_alter_table("analyses") as batch_op:
        batch_op.drop_constraint("uq_analysis_input", type_="unique")
        batch_op.drop_column("input_digest")
    if op.get_bind().dialect.name == "postgresql":
        sa.Enum(name="ingestionstate").drop(op.get_bind(), checkfirst=True)
