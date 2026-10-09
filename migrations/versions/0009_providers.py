"""Independent provider configuration, encrypted credentials and sync coverage."""
from alembic import op
revision="0009_providers"
down_revision="0008_column_preferences"
branch_labels=depends_on=None
NAMES=("provider_connections","provider_credentials","provider_account_mappings","provider_routing_settings","provider_windows","provider_catalog","provider_switch_events","provider_jobs")
def upgrade():
    # This migration is additive and frozen independently of future model changes.
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import JSONB
    j=sa.JSON().with_variant(JSONB(),"postgresql")
    def c(n,t,*args,**k): return sa.Column(n,t,*args,**k)
    dt=sa.DateTime(timezone=True)
    op.create_table(NAMES[0],c("workspace_id",sa.String(64),primary_key=True),c("provider",sa.String(32),primary_key=True),c("enabled",sa.Boolean(),nullable=False),c("credential_source",sa.String(16),nullable=False),c("revision",sa.Integer(),nullable=False),c("config",j,nullable=False),c("checked_at",dt),c("last_success_at",dt),c("status",sa.String(32),nullable=False),c("error_code",sa.String(64)),c("permissions",j,nullable=False),c("capabilities",j,nullable=False),c("quota",j,nullable=False),c("updated_at",dt,nullable=False),sa.CheckConstraint("provider IN ('metricflow','meta')"))
    op.create_table(NAMES[1],c("workspace_id",sa.String(64),primary_key=True),c("provider",sa.String(32),primary_key=True),c("encrypted",sa.Text(),nullable=False),c("updated_at",dt,nullable=False))
    op.create_table(NAMES[2],c("account_id",sa.String(36),sa.ForeignKey("ad_accounts.id"),primary_key=True),c("workspace_id",sa.String(64),nullable=False),c("canonical_id",sa.String(36),nullable=False),c("meta_account_id",sa.String(64)),c("proof",sa.String(32),nullable=False),c("confirmed_by",sa.String(36)),c("updated_at",dt,nullable=False))
    op.create_index("ix_provider_account_mappings_workspace_id",NAMES[2],["workspace_id"]);op.create_index("ix_provider_account_mappings_canonical_id",NAMES[2],["canonical_id"])
    op.create_table(NAMES[3],c("workspace_id",sa.String(64),primary_key=True),c("scope",sa.String(36),primary_key=True),c("primary_provider",sa.String(32),nullable=False),c("fallback_provider",sa.String(32)),c("action_provider",sa.String(16),nullable=False),c("updated_at",dt,nullable=False),sa.CheckConstraint("action_provider = 'disabled'"),sa.CheckConstraint("primary_provider IN ('meta','metricflow')"),sa.CheckConstraint("fallback_provider IS NULL OR fallback_provider IN ('meta','metricflow')"))
    op.create_table(NAMES[4],c("account_id",sa.String(36),sa.ForeignKey("ad_accounts.id"),primary_key=True),c("start_day",sa.Date(),primary_key=True),c("end_day",sa.Date(),primary_key=True),c("imported_at",dt,nullable=False),c("source_timestamp",sa.String(64)),c("attribution",j),c("hierarchy_hash",sa.String(64)),c("complete",sa.Boolean(),nullable=False),c("run_id",sa.String(36),sa.ForeignKey("sync_runs.id"),nullable=False),c("credential_revision",sa.Integer(),nullable=False))
    op.create_table(NAMES[5],c("account_id",sa.String(36),sa.ForeignKey("ad_accounts.id"),primary_key=True),c("kind",sa.String(16),primary_key=True),c("external_id",sa.String(128),primary_key=True),c("observed_at",dt,nullable=False),c("payload",j,nullable=False))
    op.create_table(NAMES[6],c("id",sa.String(36),primary_key=True),c("workspace_id",sa.String(64),nullable=False),c("canonical_id",sa.String(36),nullable=False),c("previous_provider",sa.String(32)),c("active_provider",sa.String(32)),c("reason",sa.String(64),nullable=False),c("period_start",sa.Date()),c("period_end",sa.Date()),c("created_at",dt,nullable=False),c("actor_id",sa.String(36)))
    op.create_index("ix_provider_switch_events_workspace_id",NAMES[6],["workspace_id"])
    op.create_table(NAMES[7],c("started_at",dt),c("kind",sa.String(16),nullable=False),c("id",sa.String(36),primary_key=True),c("workspace_id",sa.String(64),nullable=False),c("provider",sa.String(32),nullable=False),c("start_day",sa.Date(),nullable=False),c("end_day",sa.Date(),nullable=False),c("status",sa.String(32),nullable=False),c("created_at",dt,nullable=False),c("finished_at",dt),c("error_code",sa.String(64)))
    op.create_index("ix_provider_jobs_workspace_id",NAMES[7],["workspace_id"]);op.create_index("ix_provider_jobs_status",NAMES[7],["status"])
def downgrade():
    for name in reversed(NAMES): op.drop_table(name)
