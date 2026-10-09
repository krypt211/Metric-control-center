"""Additive, frozen economics schema; existing advertising facts are untouched."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010_economics"
down_revision = "0009_providers"
branch_labels = depends_on = None


def upgrade():
    j = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "economics_profiles",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.String(64), primary_key=False, nullable=False),
        sa.Column("created_by", sa.String(36), primary_key=False, nullable=False),
        sa.Column("version", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("payload", j, primary_key=False, nullable=False),
        sa.Column("deleted", sa.Boolean(), primary_key=False, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), primary_key=False, nullable=False
        ),
    )
    op.create_index(
        "ix_economics_profiles_workspace_id", "economics_profiles", ["workspace_id"]
    )
    op.create_table(
        "economics_assignments",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.String(64), primary_key=False, nullable=False),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("economics_profiles.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("scope_type", sa.String(16), primary_key=False, nullable=False),
        sa.Column("scope_id", sa.String(36), primary_key=False, nullable=False),
        sa.Column("effective_start", sa.Date(), primary_key=False, nullable=False),
        sa.Column("effective_end", sa.Date(), primary_key=False, nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), primary_key=False, nullable=False
        ),
    )
    op.create_index(
        "ix_economics_assignments_workspace_id",
        "economics_assignments",
        ["workspace_id"],
    )
    op.create_table(
        "approval_observations",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.String(64), primary_key=False, nullable=False),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("economics_profiles.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("scope_type", sa.String(16), primary_key=False, nullable=False),
        sa.Column("scope_id", sa.String(36), primary_key=False, nullable=False),
        sa.Column("cohort", sa.String(120), primary_key=False, nullable=False),
        sa.Column("start_day", sa.Date(), primary_key=False, nullable=False),
        sa.Column("end_day", sa.Date(), primary_key=False, nullable=False),
        sa.Column("version", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("payload", j, primary_key=False, nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), primary_key=False, nullable=False
        ),
        sa.UniqueConstraint(
            "workspace_id", "profile_id", "scope_type", "scope_id", "cohort"
        ),
    )
    op.create_index(
        "ix_approval_observations_workspace_id",
        "approval_observations",
        ["workspace_id"],
    )
    op.create_table(
        "economics_evaluations",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.String(64), primary_key=False, nullable=False),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("economics_profiles.id"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("entity_id", sa.String(36), primary_key=False, nullable=False),
        sa.Column("start_day", sa.Date(), primary_key=False, nullable=False),
        sa.Column("end_day", sa.Date(), primary_key=False, nullable=False),
        sa.Column("digest", sa.String(64), primary_key=False, nullable=False),
        sa.Column("payload", j, primary_key=False, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False
        ),
        sa.UniqueConstraint(
            "workspace_id", "profile_id", "entity_id", "start_day", "end_day", "digest"
        ),
    )
    op.create_index(
        "ix_economics_evaluations_entity_id", "economics_evaluations", ["entity_id"]
    )
    op.create_index(
        "ix_economics_evaluations_workspace_id",
        "economics_evaluations",
        ["workspace_id"],
    )
    op.create_table(
        "economics_audit_log",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.String(64), primary_key=False, nullable=False),
        sa.Column("actor_id", sa.String(36), primary_key=False, nullable=False),
        sa.Column("resource_id", sa.String(36), primary_key=False, nullable=False),
        sa.Column("event", sa.String(32), primary_key=False, nullable=False),
        sa.Column("payload", j, primary_key=False, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), primary_key=False, nullable=False
        ),
    )
    op.create_index(
        "ix_economics_audit_log_resource_id", "economics_audit_log", ["resource_id"]
    )
    op.create_index(
        "ix_economics_audit_log_workspace_id", "economics_audit_log", ["workspace_id"]
    )
    op.create_table(
        "economics_grants",
        sa.Column("workspace_id", sa.String(64), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("can_edit", sa.Boolean(), primary_key=False, nullable=False),
    )


def downgrade():
    raise RuntimeError(
        "Economics history is retained; destructive downgrade is disabled"
    )
