"""Initial schema with an immutable metadata snapshot.

Revision ID: 0001
Revises: None
"""

from alembic import op

from migrations.schema_v1 import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=False)


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=False)
