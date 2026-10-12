"""Shared provider telemetry and independently versioned WRITE credentials."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from services.storage.models import JSON_TYPE, Base


class WriteCredentialState(Base):
    __tablename__ = "write_credential_states"
    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    encrypted: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str | None] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(40), default="NOT_CONFIGURED")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    access_state: Mapped[str | None] = mapped_column(String(40))


class WriteCredentialAudit(Base):
    __tablename__ = "write_credential_audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    operation: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MetaRateState(Base):
    __tablename__ = "meta_rate_states"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    usage: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MetaRequestQueue(Base):
    __tablename__ = "meta_request_queue"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MetaOperation(Base):
    __tablename__ = "meta_operations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    app_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="STARTED")


class MetaRequestAttempt(Base):
    __tablename__ = "meta_request_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64))
    app_id: Mapped[str] = mapped_column(String(64))
    account_id: Mapped[str | None] = mapped_column(String(36))
    endpoint: Mapped[str] = mapped_column(String(32))
    method: Mapped[str] = mapped_column(String(8), default="GET")
    operation: Mapped[str] = mapped_column(String(32))
    run_id: Mapped[str] = mapped_column(String(36))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer)
    http_status: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[int | None] = mapped_column(Integer)
    error_subcode: Mapped[int | None] = mapped_column(Integer)
    retry_reason: Mapped[str | None] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(32), default="STARTED")
    usage: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    complexity: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(64))
    __table_args__ = (
        Index("ix_meta_attempt_workspace_time", "workspace_id", "started_at"),
    )
