"""User credentials and persistent, revocable server sessions."""
from alembic import op
import sqlalchemy as sa

revision = "0007_auth"
down_revision = "0006_read_statistics"
branch_labels = depends_on = None

def upgrade():
    op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    # Existing users cannot log in until explicitly provisioned with a password.
    op.create_table("user_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])

def downgrade():
    op.drop_table("user_sessions")
    op.drop_column("users", "is_active")
    op.drop_column("users", "password_hash")
