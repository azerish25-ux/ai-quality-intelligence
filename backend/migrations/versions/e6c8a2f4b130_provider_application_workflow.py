"""Optional provider jobs, requester attribution and service-wide admission.

Revision ID: e6c8a2f4b130
Revises: d3a5f7c9b120
"""

import sqlalchemy as sa
from alembic import op

revision = "e6c8a2f4b130"
down_revision = "d3a5f7c9b120"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_provider_admissions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("active_permits", sa.Integer(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("next_allowed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_until", sa.DateTime(timezone=True)),
        sa.Column("worker_seen_at", sa.DateTime(timezone=True)),
        sa.Column("worker_configuration_digest", sa.String(64)),
        sa.CheckConstraint(
            "active_permits >= 0 AND failures >= 0", name="ck_provider_admission_counts"
        ),
    )
    with op.batch_alter_table("model_invocations") as batch:
        batch.add_column(sa.Column("provider_identity_digest", sa.String(64)))
        batch.add_column(sa.Column("preview_digest", sa.String(64)))
        batch.add_column(sa.Column("job_id", sa.String(36)))
        batch.add_column(sa.Column("requester_user_id", sa.String(36)))
        batch.add_column(sa.Column("requester_session_id", sa.String(36)))
        batch.add_column(sa.Column("cancel_requested_at", sa.DateTime(timezone=True)))
        batch.create_foreign_key(
            "fk_provider_job", "jobs", ["job_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_foreign_key(
            "fk_provider_requester",
            "users",
            ["requester_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_provider_session",
            "auth_sessions",
            ["requester_session_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint("uq_provider_job", ["job_id"])
    with op.batch_alter_table("model_attempts") as batch:
        batch.add_column(
            sa.Column(
                "circuit_accounted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(sa.Column("admission_id", sa.String(64)))
        batch.add_column(
            sa.Column("transport_terminated_at", sa.DateTime(timezone=True))
        )
        batch.create_foreign_key(
            "fk_attempt_admission",
            "model_provider_admissions",
            ["admission_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade():
    with op.batch_alter_table("model_attempts") as batch:
        batch.drop_constraint("fk_attempt_admission", type_="foreignkey")
        batch.drop_column("transport_terminated_at")
        batch.drop_column("admission_id")
        batch.drop_column("circuit_accounted")
    with op.batch_alter_table("model_invocations") as batch:
        batch.drop_constraint("uq_provider_job", type_="unique")
        for name in ("fk_provider_job", "fk_provider_requester", "fk_provider_session"):
            batch.drop_constraint(name, type_="foreignkey")
        for name in (
            "provider_identity_digest",
            "preview_digest",
            "job_id",
            "requester_user_id",
            "requester_session_id",
            "cancel_requested_at",
        ):
            batch.drop_column(name)
    op.drop_table("model_provider_admissions")
