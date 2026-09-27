"""persist manifest-level run input diagnostics

Revision ID: a91f2c7d4e10
Revises: 7f3c1d9a2b44
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a91f2c7d4e10"
down_revision: str | None = "7f3c1d9a2b44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_inputs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("input_id", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("media_type", sa.String(length=160), nullable=False),
        sa.Column("parser_version", sa.String(length=80), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "input_id", name="uq_run_input_identity"),
    )
    op.create_index(op.f("ix_run_inputs_project_id"), "run_inputs", ["project_id"])
    op.create_index(op.f("ix_run_inputs_run_id"), "run_inputs", ["run_id"])
    op.create_index("ix_run_inputs_run_status", "run_inputs", ["run_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_run_inputs_run_status", table_name="run_inputs")
    op.drop_index(op.f("ix_run_inputs_run_id"), table_name="run_inputs")
    op.drop_index(op.f("ix_run_inputs_project_id"), table_name="run_inputs")
    op.drop_table("run_inputs")
