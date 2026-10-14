"""Extend existing per-rule/ad cooldown storage; preserve all business rows."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0016_smart_control"
down_revision = "0015_meta_pilot"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "rule_cooldowns",
        sa.Column(
            "smart_state",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade():
    op.drop_column("rule_cooldowns", "smart_state")
