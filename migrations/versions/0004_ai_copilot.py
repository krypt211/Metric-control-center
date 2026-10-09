"""Durable AI proposals, policy configuration and daily limits."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_ai_copilot"
down_revision = "0003_recommendations"
branch_labels = depends_on = None


def upgrade():
    # Same nullable owner convention as rules. No SQLite table recreation:
    # existing ai_actions may already reference these placeholder decisions.
    op.add_column("ai_decisions", sa.Column("owner_id", sa.String(36), nullable=True))
    op.add_column("ai_decisions", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_decisions", sa.Column("telegram_status", sa.String(32), nullable=True))
    op.create_table("ai_settings",
        sa.Column("workspace_id", sa.String(64), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("ai_quotas",
        sa.Column("workspace_id", sa.String(64), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("queued", sa.Integer(), nullable=False),
        sa.Column("attempted", sa.Integer(), nullable=False),
        sa.Column("analyses", sa.Integer(), nullable=False))
    op.create_table("telegram_cursors",
        sa.Column("workspace_id", sa.String(64), primary_key=True),
        sa.Column("next_update", sa.BigInteger(), nullable=False))


def downgrade():
    for name in ("telegram_cursors", "ai_quotas", "ai_settings"):
        op.drop_table(name)
    for name in ("telegram_status", "expires_at", "owner_id"):
        op.drop_column("ai_decisions", name)
