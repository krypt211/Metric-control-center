"""Daily reach/frequency and workspace detector thresholds."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_recommendations"
down_revision = "0002_automation"
branch_labels = depends_on = None


def upgrade():
    op.add_column("daily_metrics", sa.Column("reach", sa.BigInteger(), nullable=True))
    op.add_column("daily_metrics", sa.Column("frequency", sa.Numeric(24, 8), nullable=True))
    op.create_table("recommendation_settings",
        sa.Column("workspace_id", sa.String(64), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("recommendation_settings")
    op.drop_column("daily_metrics", "frequency")
    op.drop_column("daily_metrics", "reach")
