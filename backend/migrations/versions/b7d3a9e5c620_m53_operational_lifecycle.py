"""M5.3 account lifecycle, retention policies and crash-safe deletion outbox.

Revision ID: b7d3a9e5c620
Revises: a4f6e8c2d901
"""
from alembic import op
import sqlalchemy as sa

revision = "b7d3a9e5c620"
down_revision = "a4f6e8c2d901"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("lifecycle_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("runs", sa.Column("source_expired_at", sa.DateTime(timezone=True)))
    op.add_column("runs", sa.Column("evidence_expired_at", sa.DateTime(timezone=True)))
    op.add_column("runs", sa.Column("retention_policy_version", sa.Integer()))
    op.create_index("ix_runs_evidence_expired_at", "runs", ["evidence_expired_at"])
    op.add_column("ingestions", sa.Column("source_expired_at", sa.DateTime(timezone=True)))
    op.create_table("account_recoveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("issued_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_account_recoveries_user_id", "account_recoveries", ["user_id"])
    op.create_table("retention_policies",
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_days", sa.Integer(), nullable=False),
        sa.Column("evidence_days", sa.Integer(), nullable=False),
        sa.Column("audit_days", sa.Integer(), nullable=False),
        sa.Column("export_enabled", sa.Boolean(), nullable=False),
        sa.Column("export_max_rows", sa.Integer(), nullable=False),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("retention_tombstones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(240), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(120), nullable=False),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "resource_type", "resource_id", name="uq_retention_tombstone"))
    op.create_index("ix_retention_tombstones_project_id", "retention_tombstones", ["project_id"])
    op.create_table("storage_deletions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_path", sa.String(2048), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("project_id", "storage_path", name="uq_storage_deletion_path"))
    op.create_index("ix_storage_deletions_project_id", "storage_deletions", ["project_id"])

    # Reconcile two pre-existing metadata/migration differences without changing
    # their logical constraints: parser-version width and the already-unique baseline link.
    with op.batch_alter_table("evidence") as batch:
        batch.alter_column("parser_version", existing_type=sa.String(40), type_=sa.String(80), existing_nullable=False)
    op.drop_index("ix_performance_comparisons_baseline_snapshot_id", table_name="performance_comparisons")
    op.create_index("ix_performance_comparisons_baseline_snapshot_id", "performance_comparisons", ["baseline_snapshot_id"], unique=True)


def downgrade():
    op.drop_index("ix_performance_comparisons_baseline_snapshot_id", table_name="performance_comparisons")
    op.create_index("ix_performance_comparisons_baseline_snapshot_id", "performance_comparisons", ["baseline_snapshot_id"], unique=False)
    with op.batch_alter_table("evidence") as batch:
        batch.alter_column("parser_version", existing_type=sa.String(80), type_=sa.String(40), existing_nullable=False)

    for table in ("storage_deletions", "retention_tombstones", "retention_policies", "account_recoveries"):
        op.drop_table(table)
    op.drop_column("ingestions", "source_expired_at")
    op.drop_index("ix_runs_evidence_expired_at", table_name="runs")
    for column in ("retention_policy_version", "evidence_expired_at", "source_expired_at"):
        op.drop_column("runs", column)
    op.drop_column("users", "lifecycle_version")
