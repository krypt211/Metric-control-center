"""Immutable AD simulations and revisions; existing rules and facts are preserved."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011_smart_rules"
down_revision = "0010_economics"
branch_labels = depends_on = None


def upgrade() -> None:
    j = sa.JSON().with_variant(JSONB(), "postgresql")
    for table in ("rule_versions", "rule_simulations"):
        op.create_table(
            table,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("workspace_id", sa.String(64), nullable=False),
            sa.Column(
                "rule_id", sa.String(36), sa.ForeignKey("rules.id"), nullable=False
            ),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("actor_id", sa.String(36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", j, nullable=False),
            *(
                [sa.UniqueConstraint("rule_id", "revision")]
                if table == "rule_versions"
                else []
            ),
        )
        for column in ("workspace_id", "rule_id"):
            op.create_index(f"ix_{table}_{column}", table, [column])
    op.create_table(
        "rule_audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", j, nullable=False),
    )
    for column in ("workspace_id", "resource_id"):
        op.create_index(f"ix_rule_audit_log_{column}", "rule_audit_log", [column])
    op.create_table(
        "rule_grants",
        sa.Column("workspace_id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True
        ),
        sa.Column("can_edit", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup instead of destructive downgrade")
