"""Autonomy control, scoped instructions and durable agent conversations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005_agent"
down_revision = "0004_ai_copilot"
branch_labels = depends_on = None
J = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade():
    op.create_table("automation_control", sa.Column("workspace_id", sa.String(64), primary_key=True),
        sa.Column("stopped", sa.Boolean(), nullable=False), sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("automation_events", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=False), sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("payload", J, nullable=False))
    op.create_index("ix_automation_events_workspace_id", "automation_events", ["workspace_id"])
    op.create_table("media_buyer_profiles", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=False), sa.Column("country", sa.String(2), nullable=False),
        sa.Column("offer", sa.String(128), nullable=False), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", J, nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "country", "offer"))
    op.create_index("ix_media_buyer_profiles_workspace_id", "media_buyer_profiles", ["workspace_id"])
    op.create_table("media_buyer_cooldowns",
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("media_buyer_profiles.id"), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), primary_key=True),
        sa.Column("last_queued_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table("agent_messages", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", sa.String(64), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False), sa.Column("payload", J, nullable=False),
        sa.Column("decision_id", sa.String(36), sa.ForeignKey("ai_decisions.id"), nullable=True),
        sa.Column("telegram_status", sa.String(32), nullable=True))
    for name in ("workspace_id", "conversation_id", "status"):
        op.create_index("ix_agent_messages_"+name, "agent_messages", [name])


def downgrade():
    for name in ("agent_messages", "media_buyer_cooldowns", "media_buyer_profiles", "automation_events", "automation_control"):
        op.drop_table(name)
