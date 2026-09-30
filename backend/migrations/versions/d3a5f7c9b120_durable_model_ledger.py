"""Durable, explicitly opt-in model reservations and invocation attempts.

Revision ID: d3a5f7c9b120
Revises: c8f2e6a9d410
"""
from alembic import op
import sqlalchemy as sa

revision = "d3a5f7c9b120"
down_revision = "c8f2e6a9d410"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("model_run_budgets",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("max_requests", sa.Integer(), nullable=False),
        sa.Column("max_reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "project_id", name="uq_model_budget_scope"),
        sa.CheckConstraint("max_requests > 0 AND max_reserved_tokens > 0 AND requests >= 0 AND reserved_tokens >= 0", name="ck_model_budget_nonnegative"))
    op.create_index("ix_model_run_budgets_project_id", "model_run_budgets", ["project_id"])
    op.create_table("model_invocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("analysis_id", sa.String(36), sa.ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("analysis_revision", sa.Integer(), nullable=False),
        sa.Column("analysis_digest", sa.String(64), nullable=False),
        sa.Column("evidence_digest", sa.String(64), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("provider_digest", sa.String(64), nullable=False),
        sa.Column("idempotency_digest", sa.String(64), nullable=False),
        sa.Column("deterministic_category", sa.String(40), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("reason", sa.String(80)),
        sa.Column("proposal_json", sa.JSON()),
        sa.Column("owner_token", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("project_id", "idempotency_digest", name="uq_model_invocation_idempotency"),
        sa.ForeignKeyConstraint(["run_id", "project_id"], ["model_run_budgets.run_id", "model_run_budgets.project_id"], ondelete="CASCADE"))
    for column in ("project_id", "run_id", "analysis_id"):
        op.create_index(f"ix_model_invocations_{column}", "model_invocations", [column])
    op.create_index("ix_model_invocations_recovery", "model_invocations", ["project_id", "run_id", "status", "lease_expires_at"])
    op.create_table("model_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("invocation_id", sa.String(36), sa.ForeignKey("model_invocations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_token", sa.String(36), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("accounted_tokens", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("reason", sa.String(80)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("spend_status", sa.String(40), nullable=False),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("estimated_cost", sa.Float()),
        sa.Column("cost_status", sa.String(40), nullable=False),
        sa.Column("input_price_per_million", sa.Float()),
        sa.Column("output_price_per_million", sa.Float()),
        sa.Column("pricing_source", sa.String(240)),
        sa.Column("pricing_date", sa.String(10)),
        sa.Column("currency", sa.String(3)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("invocation_id", "number", name="uq_model_attempt_number"),
        sa.CheckConstraint("number > 0 AND reserved_tokens > 0 AND accounted_tokens >= reserved_tokens", name="ck_model_attempt_reservation"),
        sa.CheckConstraint("(prompt_tokens IS NULL AND completion_tokens IS NULL) OR (prompt_tokens IS NOT NULL AND completion_tokens IS NOT NULL AND prompt_tokens >= 0 AND completion_tokens >= 0)", name="ck_model_attempt_usage"))
    op.create_index("ix_model_attempts_invocation_id", "model_attempts", ["invocation_id"])


def downgrade():
    op.drop_table("model_attempts")
    op.drop_table("model_invocations")
    op.drop_table("model_run_budgets")
