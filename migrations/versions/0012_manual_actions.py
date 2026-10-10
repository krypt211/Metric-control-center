"""Add local manual grants and concurrency protection; preserve old requests."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0012_manual_actions"
down_revision = "0011_smart_rules"
branch_labels = depends_on = None


def upgrade() -> None:
    op.add_column(
        "action_requests",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "manual_action_grants",
        sa.Column("workspace_id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True
        ),
        sa.Column("can_control", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "manual_grant_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "payload", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False
        ),
    )
    op.create_index(
        "ix_manual_grant_audit_workspace_id", "manual_grant_audit", ["workspace_id"]
    )
    condition = sa.text(
        "status IN ('DRAFT','PREFLIGHT_PENDING','PREFLIGHT_PASSED',"
        "'PREFLIGHT_FAILED','AWAITING_CONFIRMATION','CONFIRMED','BLOCKED',"
        "'queued','executing','verifying','unknown')"
    )
    op.create_index(
        "uq_manual_pending_entity",
        "action_requests",
        ["entity_id"],
        unique=True,
        postgresql_where=condition,
        sqlite_where=condition,
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup; destructive downgrade is prohibited")
