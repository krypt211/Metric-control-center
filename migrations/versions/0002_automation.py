"""Durable batches, rule evaluation and action provenance."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_automation"
down_revision = "0001"
branch_labels = depends_on = None
J = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade():
    op.add_column("action_requests", sa.Column("provenance", J, nullable=False, server_default=sa.text("'{}'")))
    op.add_column("rules", sa.Column("owner_id", sa.String(36), nullable=True))
    op.add_column("rules", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("rules", sa.Column("next_evaluation_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("rule_runs", sa.Column("evaluation_key", sa.String(64), nullable=True))
    op.create_index("uq_rule_evaluation", "rule_runs", ["rule_id", "evaluation_key"], unique=True)
    op.create_table("rule_cooldowns",
        sa.Column("rule_id", sa.String(36), sa.ForeignKey("rules.id"), primary_key=True),
        sa.Column("entity_id", sa.String(36), sa.ForeignKey("entities.id"), primary_key=True),
        sa.Column("last_queued_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("batch_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(64), nullable=False),
        sa.Column("initiator_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", J, nullable=False),
        sa.UniqueConstraint("workspace_id", "initiator_id", "idempotency_key"))
    op.create_index("ix_batch_actions_workspace_id", "batch_actions", ["workspace_id"])
    op.create_table("batch_items",
        sa.Column("batch_id", sa.String(36), sa.ForeignKey("batch_actions.id"), primary_key=True),
        sa.Column("entity_id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), sa.ForeignKey("action_requests.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("reason", sa.Text(), nullable=True))


def downgrade():
    op.drop_table("batch_items")
    op.drop_table("batch_actions")
    op.drop_table("rule_cooldowns")
    op.drop_index("uq_rule_evaluation", table_name="rule_runs")
    op.drop_column("rule_runs", "evaluation_key")
    for column in ("next_evaluation_at", "revision", "owner_id"):
        op.drop_column("rules", column)
    op.drop_column("action_requests", "provenance")
