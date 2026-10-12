"""Add isolated credential metadata and shared Meta telemetry; preserve all facts."""

from alembic import op

from migrations.integration_schema_v13 import Base

revision = "0013_integrations"
down_revision = "0012_manual_actions"
branch_labels = depends_on = None


def upgrade():
    for table in Base.metadata.sorted_tables:
        table.create(bind=op.get_bind())


def downgrade():
    for table in reversed(Base.metadata.sorted_tables):
        table.drop(bind=op.get_bind())
