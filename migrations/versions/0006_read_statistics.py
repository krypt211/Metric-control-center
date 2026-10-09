"""Exact-scope READ observations without changing core ad/day facts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision="0006_read_statistics"
down_revision="0005_agent"
branch_labels=depends_on=None
def upgrade():
    op.create_table("read_statistics",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("account_id",sa.String(36),sa.ForeignKey("ad_accounts.id"),nullable=False),
        sa.Column("kind",sa.String(16),nullable=False),
        sa.Column("scope_key",sa.String(64),nullable=False),
        sa.Column("start_day",sa.Date(),nullable=False),
        sa.Column("end_day",sa.Date(),nullable=False),
        sa.Column("currency",sa.String(3),nullable=True),
        sa.Column("timezone",sa.String(64),nullable=True),
        sa.Column("observed_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("payload",sa.JSON().with_variant(JSONB(),"postgresql"),nullable=False),
        sa.UniqueConstraint("account_id","kind","scope_key","start_day","end_day"),
        sa.CheckConstraint("kind IN ('tracker','creative')"),
        sa.CheckConstraint("start_day <= end_day"))
    op.create_index("ix_read_statistics_window","read_statistics",["account_id","kind","start_day","end_day"])
def downgrade():
    op.drop_table("read_statistics")
