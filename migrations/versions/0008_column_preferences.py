"""Private column presets and persistent working views."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="0008_column_preferences"
down_revision="0007_auth"
branch_labels=depends_on=None
def upgrade():
    json_type=sa.JSON().with_variant(postgresql.JSONB(),"postgresql")
    op.create_table("user_column_presets",
        sa.Column("id",sa.String(36),primary_key=True),
        sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("workspace_id",sa.String(64),nullable=False),
        sa.Column("scope",sa.String(16),nullable=False),
        sa.Column("name",sa.String(80),nullable=False),
        sa.Column("config_json",json_type,nullable=False),
        sa.Column("version",sa.Integer(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_column_presets_owner_scope","user_column_presets",["user_id","workspace_id","scope"])
    op.create_table("user_table_preferences",
        sa.Column("user_id",sa.String(36),sa.ForeignKey("users.id",ondelete="CASCADE"),primary_key=True),
        sa.Column("workspace_id",sa.String(64),primary_key=True),
        sa.Column("scope",sa.String(16),primary_key=True),
        sa.Column("active_id",sa.String(64),nullable=False),
        sa.Column("default_id",sa.String(64),nullable=False),
        sa.Column("config_json",json_type,nullable=False),
        sa.Column("version",sa.Integer(),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
def downgrade():
    op.drop_table("user_table_preferences")
    op.drop_table("user_column_presets")
