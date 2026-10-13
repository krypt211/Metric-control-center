"""Add durable pilot preparation without enabling any provider."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0015_meta_pilot"
down_revision = "0014_meta_jobs"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "meta_pilot_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("account_id", sa.String(80), nullable=False),
        sa.Column("start_day", sa.Date(), nullable=False),
        sa.Column("end_day", sa.Date(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("used_attempts", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("credential_revision", sa.Integer(), nullable=False),
        sa.Column(
            "job_id", sa.String(36), sa.ForeignKey("provider_jobs.id"), unique=True
        ),
        sa.Column(
            "result", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False
        ),
        sa.CheckConstraint("max_attempts BETWEEN 1 AND 20"),
        sa.CheckConstraint("used_attempts BETWEEN 0 AND max_attempts"),
        sa.CheckConstraint("timeout_seconds BETWEEN 30 AND 900"),
        sa.CheckConstraint("start_day <= end_day"),
    )
    op.create_index(
        "ix_meta_pilot_sessions_workspace_id", "meta_pilot_sessions", ["workspace_id"]
    )


def downgrade():
    raise RuntimeError("DESTRUCTIVE_PILOT_HISTORY_DOWNGRADE_NOT_SUPPORTED")
