"""Additive provider configuration; existing advertising facts are preserved."""
from datetime import date,datetime
from typing import Any
from sqlalchemy import String,Integer,Boolean,Text,DateTime,Date,ForeignKey,UniqueConstraint,CheckConstraint,Index
from sqlalchemy.orm import Mapped,mapped_column
from services.storage.models import Base,JSON_TYPE

class ProviderConnection(Base):
    __tablename__="provider_connections"
    workspace_id:Mapped[str]=mapped_column(String(64),primary_key=True)
    provider:Mapped[str]=mapped_column(String(32),primary_key=True)
    enabled:Mapped[bool]=mapped_column(Boolean,default=False)
    credential_source:Mapped[str]=mapped_column(String(16),default="server")
    revision:Mapped[int]=mapped_column(Integer,default=1)
    config:Mapped[dict[str,Any]]=mapped_column(JSON_TYPE,default=dict)
    checked_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    last_success_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    status:Mapped[str]=mapped_column(String(32),default="unverified")
    error_code:Mapped[str|None]=mapped_column(String(64))
    permissions:Mapped[dict[str,Any]]=mapped_column(JSON_TYPE,default=dict)
    capabilities:Mapped[dict[str,Any]]=mapped_column(JSON_TYPE,default=dict)
    quota:Mapped[dict[str,Any]]=mapped_column(JSON_TYPE,default=dict)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    __table_args__=(CheckConstraint("provider IN ('metricflow','meta')"),)

class ProviderCredential(Base):
    __tablename__="provider_credentials"
    workspace_id:Mapped[str]=mapped_column(String(64),primary_key=True)
    provider:Mapped[str]=mapped_column(String(32),primary_key=True)
    encrypted:Mapped[str]=mapped_column(Text)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))

class ProviderAccountMapping(Base):
    __tablename__="provider_account_mappings"
    account_id:Mapped[str]=mapped_column(ForeignKey("ad_accounts.id"),primary_key=True)
    workspace_id:Mapped[str]=mapped_column(String(64),index=True)
    canonical_id:Mapped[str]=mapped_column(String(36),index=True)
    meta_account_id:Mapped[str|None]=mapped_column(String(64))
    proof:Mapped[str]=mapped_column(String(32))
    confirmed_by:Mapped[str|None]=mapped_column(String(36))
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))

class ProviderRoutingSetting(Base):
    __tablename__="provider_routing_settings"
    workspace_id:Mapped[str]=mapped_column(String(64),primary_key=True)
    scope:Mapped[str]=mapped_column(String(36),primary_key=True) # workspace or canonical ID
    primary_provider:Mapped[str]=mapped_column(String(32),default="metricflow")
    fallback_provider:Mapped[str|None]=mapped_column(String(32))
    action_provider:Mapped[str]=mapped_column(String(16),default="disabled")
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    __table_args__=(CheckConstraint("action_provider = 'disabled'"),CheckConstraint("primary_provider IN ('meta','metricflow')"),CheckConstraint("fallback_provider IS NULL OR fallback_provider IN ('meta','metricflow')"),)

class ProviderWindow(Base):
    __tablename__="provider_windows"
    account_id:Mapped[str]=mapped_column(ForeignKey("ad_accounts.id"),primary_key=True)
    start_day:Mapped[date]=mapped_column(Date,primary_key=True)
    end_day:Mapped[date]=mapped_column(Date,primary_key=True)
    imported_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    source_timestamp:Mapped[str|None]=mapped_column(String(64))
    attribution:Mapped[dict[str,Any]|None]=mapped_column(JSON_TYPE)
    hierarchy_hash:Mapped[str|None]=mapped_column(String(64))
    complete:Mapped[bool]=mapped_column(Boolean)
    run_id:Mapped[str]=mapped_column(ForeignKey("sync_runs.id"))
    credential_revision:Mapped[int]=mapped_column(Integer)

class ProviderCatalog(Base):
    __tablename__="provider_catalog"
    account_id:Mapped[str]=mapped_column(ForeignKey("ad_accounts.id"),primary_key=True)
    kind:Mapped[str]=mapped_column(String(16),primary_key=True)
    external_id:Mapped[str]=mapped_column(String(128),primary_key=True)
    observed_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    payload:Mapped[dict[str,Any]]=mapped_column(JSON_TYPE)

class ProviderSwitchEvent(Base):
    __tablename__="provider_switch_events"
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    workspace_id:Mapped[str]=mapped_column(String(64),index=True)
    canonical_id:Mapped[str]=mapped_column(String(36))
    previous_provider:Mapped[str|None]=mapped_column(String(32))
    active_provider:Mapped[str|None]=mapped_column(String(32))
    reason:Mapped[str]=mapped_column(String(64))
    period_start:Mapped[date|None]=mapped_column(Date)
    period_end:Mapped[date|None]=mapped_column(Date)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    actor_id:Mapped[str|None]=mapped_column(String(36))

class ProviderJob(Base):
    __tablename__="provider_jobs"
    started_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    kind:Mapped[str]=mapped_column(String(16),default="sync")
    id:Mapped[str]=mapped_column(String(36),primary_key=True)
    workspace_id:Mapped[str]=mapped_column(String(64),index=True)
    provider:Mapped[str]=mapped_column(String(32))
    start_day:Mapped[date]=mapped_column(Date)
    end_day:Mapped[date]=mapped_column(Date)
    status:Mapped[str]=mapped_column(String(32),index=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    finished_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    error_code:Mapped[str|None]=mapped_column(String(64))
