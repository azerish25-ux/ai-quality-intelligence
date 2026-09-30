"""add historical outcome cohort metadata and indexes

Revision ID: e4b7c2d9a510
Revises: d8f6c1a9b230
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4b7c2d9a510"
down_revision: str | None = "d8f6c1a9b230"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "run_scope",
            sa.String(length=40),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "runs", sa.Column("environment", sa.String(length=160), nullable=True)
    )
    op.add_column("runs", sa.Column("timezone", sa.String(length=80), nullable=True))
    op.add_column("runs", sa.Column("worker_count", sa.Integer(), nullable=True))
    op.add_column("runs", sa.Column("shard_count", sa.Integer(), nullable=True))
    op.create_index(
        "ix_runs_project_history",
        "runs",
        ["project_id", "created_at", "run_scope"],
        unique=False,
    )
    op.create_index(
        "ix_execution_history_identity",
        "test_executions",
        ["test_identity", "browser", "run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_execution_history_identity", table_name="test_executions")
    op.drop_index("ix_runs_project_history", table_name="runs")
    op.drop_column("runs", "shard_count")
    op.drop_column("runs", "worker_count")
    op.drop_column("runs", "timezone")
    op.drop_column("runs", "environment")
    op.drop_column("runs", "run_scope")
