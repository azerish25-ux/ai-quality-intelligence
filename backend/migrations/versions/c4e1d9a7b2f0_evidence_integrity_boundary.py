"""add execution-scoped evidence and immutable derivative provenance

Revision ID: c4e1d9a7b2f0
Revises: a91f2c7d4e10
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e1d9a7b2f0"
down_revision: str | None = "a91f2c7d4e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifact_derivatives",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=2048), nullable=False),
        sa.Column("media_type", sa.String(length=160), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("redaction_version", sa.String(length=40), nullable=False),
        sa.Column("source_map", sa.JSON(), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("restricted", sa.Boolean(), nullable=False),
        sa.Column("approval_state", sa.String(length=40), nullable=False),
        sa.Column("retention_state", sa.String(length=40), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_id",
            "kind",
            "digest",
            name="uq_artifact_derivative_content",
        ),
    )
    op.create_index(
        "ix_artifact_derivatives_artifact_id",
        "artifact_derivatives",
        ["artifact_id"],
    )
    op.create_index(
        "ix_artifact_derivatives_project_id",
        "artifact_derivatives",
        ["project_id"],
    )
    op.create_index(
        "ix_artifact_derivatives_run_id",
        "artifact_derivatives",
        ["run_id"],
    )
    op.create_index(
        "ix_artifact_derivatives_project_digest",
        "artifact_derivatives",
        ["project_id", "digest"],
    )

    # Nullable foreign keys deliberately preserve legacy data without guessing
    # which execution/input produced evidence in multi-failure or multi-input runs.
    with op.batch_alter_table("evidence") as batch_op:
        batch_op.add_column(
            sa.Column("run_input_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("execution_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("derivative_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "provenance_kind",
                sa.String(length=80),
                nullable=False,
                server_default="legacy_unscoped",
            )
        )
        batch_op.add_column(
            sa.Column(
                "locator_version",
                sa.String(length=40),
                nullable=False,
                server_default="evidence-locator-v1",
            )
        )
        batch_op.add_column(
            sa.Column(
                "observation",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "extractor_version",
                sa.String(length=80),
                nullable=False,
                server_default="legacy",
            )
        )
        batch_op.add_column(
            sa.Column(
                "redaction_version",
                sa.String(length=40),
                nullable=False,
                server_default="redaction-v1",
            )
        )
        batch_op.create_foreign_key(
            "fk_evidence_run_input_id",
            "run_inputs",
            ["run_input_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_evidence_execution_id",
            "test_executions",
            ["execution_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_evidence_derivative_id",
            "artifact_derivatives",
            ["derivative_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_index("ix_evidence_run_input_id", "evidence", ["run_input_id"])
    op.create_index("ix_evidence_execution_id", "evidence", ["execution_id"])
    op.create_index("ix_evidence_derivative_id", "evidence", ["derivative_id"])
    op.create_index(
        "ix_evidence_execution_scope", "evidence", ["run_id", "execution_id"]
    )
    op.create_index("ix_evidence_input_scope", "evidence", ["run_id", "run_input_id"])

    # A legacy run with exactly one execution/input is unambiguous and can be
    # scoped safely. Multi-execution/input legacy evidence stays unscoped and is
    # rejected by the publication validator until re-ingested.
    op.execute(
        sa.text(
            """
            UPDATE evidence
            SET execution_id = (
                SELECT test_executions.id
                FROM test_executions
                WHERE test_executions.run_id = evidence.run_id
                LIMIT 1
            )
            WHERE 1 = (
                SELECT COUNT(*)
                FROM test_executions
                WHERE test_executions.run_id = evidence.run_id
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE evidence
            SET run_input_id = (
                SELECT run_inputs.id
                FROM run_inputs
                WHERE run_inputs.run_id = evidence.run_id
                LIMIT 1
            )
            WHERE 1 = (
                SELECT COUNT(*)
                FROM run_inputs
                WHERE run_inputs.run_id = evidence.run_id
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE evidence
            SET provenance_kind = 'current_execution'
            WHERE execution_id IS NOT NULL
            """
        )
    )

    with op.batch_alter_table("evidence") as batch_op:
        batch_op.alter_column("provenance_kind", server_default=None)
        batch_op.alter_column("locator_version", server_default=None)
        batch_op.alter_column("observation", server_default=None)
        batch_op.alter_column("extractor_version", server_default=None)
        batch_op.alter_column("redaction_version", server_default=None)

    with op.batch_alter_table("analyses") as batch_op:
        batch_op.add_column(
            sa.Column("validation_version", sa.String(length=80), nullable=True)
        )
        batch_op.add_column(sa.Column("validation_results", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("analyses") as batch_op:
        batch_op.drop_column("validation_results")
        batch_op.drop_column("validation_version")

    op.drop_index("ix_evidence_input_scope", table_name="evidence")
    op.drop_index("ix_evidence_execution_scope", table_name="evidence")
    op.drop_index("ix_evidence_derivative_id", table_name="evidence")
    op.drop_index("ix_evidence_execution_id", table_name="evidence")
    op.drop_index("ix_evidence_run_input_id", table_name="evidence")
    with op.batch_alter_table("evidence") as batch_op:
        batch_op.drop_constraint("fk_evidence_derivative_id", type_="foreignkey")
        batch_op.drop_constraint("fk_evidence_execution_id", type_="foreignkey")
        batch_op.drop_constraint("fk_evidence_run_input_id", type_="foreignkey")
        batch_op.drop_column("redaction_version")
        batch_op.drop_column("extractor_version")
        batch_op.drop_column("observation")
        batch_op.drop_column("locator_version")
        batch_op.drop_column("provenance_kind")
        batch_op.drop_column("derivative_id")
        batch_op.drop_column("execution_id")
        batch_op.drop_column("run_input_id")

    op.drop_index(
        "ix_artifact_derivatives_project_digest",
        table_name="artifact_derivatives",
    )
    op.drop_index("ix_artifact_derivatives_run_id", table_name="artifact_derivatives")
    op.drop_index(
        "ix_artifact_derivatives_project_id", table_name="artifact_derivatives"
    )
    op.drop_index(
        "ix_artifact_derivatives_artifact_id", table_name="artifact_derivatives"
    )
    op.drop_table("artifact_derivatives")
