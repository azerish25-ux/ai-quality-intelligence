"""Input-scoped safe binary evidence and append-only human decisions.

Revision ID: c8f2e6a9d410
Revises: b7d3a9e5c620
"""
from alembic import op
import sqlalchemy as sa

revision = "c8f2e6a9d410"
down_revision = "b7d3a9e5c620"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("binary_evidence",
        sa.Column("input_id", sa.String(36), sa.ForeignKey("run_inputs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("execution_id", sa.String(36), sa.ForeignKey("test_executions.id", ondelete="SET NULL")),
        sa.Column("current_derivative_id", sa.String(36), sa.ForeignKey("artifact_derivatives.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("correlation", sa.String(80), nullable=False))
    op.create_index("ix_binary_evidence_project_id", "binary_evidence", ["project_id"])
    op.create_index("ix_binary_evidence_run_id", "binary_evidence", ["run_id"])
    op.create_table("binary_evidence_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("input_id", sa.String(36), sa.ForeignKey("binary_evidence.input_id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("derivative_id", sa.String(36), sa.ForeignKey("artifact_derivatives.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(240), nullable=False),
        sa.Column("actor_display", sa.String(240), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("masks", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("input_id", "version", name="uq_binary_decision_version"))
    op.create_index("ix_binary_evidence_decisions_input_id", "binary_evidence_decisions", ["input_id"])
    op.create_index("ix_binary_evidence_decisions_project_id", "binary_evidence_decisions", ["project_id"])


def downgrade():
    op.drop_table("binary_evidence_decisions")
    op.drop_table("binary_evidence")
