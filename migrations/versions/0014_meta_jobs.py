"""Add Meta job deadlines/dedup/leases without assigning TTL to old jobs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0014_meta_jobs"
down_revision = "0013_integrations"
branch_labels = depends_on = None


def upgrade():
    for column in (
        sa.Column("purpose", sa.String(16)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("dedup_key", sa.String(64)),
        sa.Column("active_key", sa.String(64)),
        sa.Column("account_scope", sa.JSON().with_variant(JSONB(), "postgresql")),
        sa.Column("request_params", sa.JSON().with_variant(JSONB(), "postgresql")),
        sa.Column("config_revision", sa.Integer()),
        sa.Column("config_hash", sa.String(64)),
        sa.Column("timezone", sa.String(64)),
        sa.Column("slot", sa.String(64)),
        sa.Column("owner", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("cancel_requested", sa.Boolean()),
        sa.Column("recoveries", sa.Integer()),
    ):
        op.add_column("provider_jobs", column)
    op.create_index(
        "uq_provider_job_dedup", "provider_jobs", ["dedup_key"], unique=True
    )
    predicate = sa.text(
        "provider = 'meta' AND active_key IS NOT NULL AND status IN ('queued','running')"
    )
    op.create_index(
        "uq_meta_job_active",
        "provider_jobs",
        ["active_key"],
        unique=True,
        postgresql_where=predicate,
        sqlite_where=predicate,
    )
    op.create_table(
        "provider_job_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id", sa.String(36), sa.ForeignKey("provider_jobs.id"), nullable=False
        ),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36)),
    )
    op.create_index("ix_provider_job_audit_job_id", "provider_job_audit", ["job_id"])
    op.create_index(
        "ix_provider_job_audit_workspace_id", "provider_job_audit", ["workspace_id"]
    )


def downgrade():
    raise RuntimeError("DESTRUCTIVE_JOB_HISTORY_DOWNGRADE_NOT_SUPPORTED")
