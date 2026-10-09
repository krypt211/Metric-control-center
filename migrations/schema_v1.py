"""Current state and historical observations have separate identities/tables."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, Date, DateTime, ForeignKey,
    Index, Integer, JSON, Numeric, String, Table, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")
MONEY = Numeric(24, 8)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(32), default="viewer")
    __table_args__ = (UniqueConstraint("workspace_id", "email"),)


class AdAccount(Base):
    __tablename__ = "ad_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(128))
    name: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    currency: Mapped[str] = mapped_column(String(3))
    timezone: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("workspace_id", "provider", "external_id"),)


class Entity(Base):
    __tablename__ = "entities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("ad_accounts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(128))
    name: Mapped[str | None] = mapped_column(Text)
    labels: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict)
    __table_args__ = (
        UniqueConstraint("account_id", "kind", "external_id"),
        CheckConstraint("kind IN ('campaign', 'adset', 'ad', 'creative')"),
    )


class Campaign(Base):
    __tablename__ = "campaigns"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)


class AdSet(Base):
    __tablename__ = "adsets"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaigns.entity_id"))


class Creative(Base):
    __tablename__ = "creatives"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    media_url: Mapped[str | None] = mapped_column(Text)


class Ad(Base):
    __tablename__ = "ads"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    adset_id: Mapped[str | None] = mapped_column(ForeignKey("adsets.entity_id"))
    creative_id: Mapped[str | None] = mapped_column(ForeignKey("creatives.entity_id"))


class EntityCurrentState(Base):
    __tablename__ = "entity_current_state"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    status: Mapped[str | None] = mapped_column(String(64))
    budget: Mapped[Decimal | None] = mapped_column(MONEY)
    bid: Mapped[Decimal | None] = mapped_column(MONEY)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE)


class DailyMetric(Base):
    __tablename__ = "daily_metrics"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3))
    timezone: Mapped[str] = mapped_column(String(64))
    spend: Mapped[Decimal | None] = mapped_column(MONEY)
    impressions: Mapped[int | None] = mapped_column(BigInteger)
    clicks: Mapped[int | None] = mapped_column(BigInteger)
    conversions: Mapped[int | None] = mapped_column(BigInteger)
    leads: Mapped[int | None] = mapped_column(BigInteger)
    sales: Mapped[int | None] = mapped_column(BigInteger)
    revenue: Mapped[Decimal | None] = mapped_column(MONEY)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE)
    __table_args__ = (
        Index("ix_daily_period_source", "day", "source"),
        CheckConstraint("spend IS NULL OR spend >= 0"),
    )


class HourlyMetric(Base):
    __tablename__ = "hourly_metrics"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    hour_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TrackerMetric(Base):
    __tablename__ = "tracker_metrics"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3))
    timezone: Mapped[str] = mapped_column(String(64))
    clicks: Mapped[int | None] = mapped_column(BigInteger)
    conversions: Mapped[int | None] = mapped_column(BigInteger)
    leads: Mapped[int | None] = mapped_column(BigInteger)
    sales: Mapped[int | None] = mapped_column(BigInteger)
    revenue: Mapped[Decimal | None] = mapped_column(MONEY)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE)


class Breakdown(Base):
    __tablename__ = "breakdowns"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    dimension_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    job: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), index=True)
    start_day: Mapped[date] = mapped_column(Date)
    end_day: Mapped[date] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pages: Mapped[int] = mapped_column(Integer, default=0)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))


class RawSnapshot(Base):
    __tablename__ = "raw_snapshots"
    run_id: Mapped[str] = mapped_column(ForeignKey("sync_runs.id"), primary_key=True)
    page: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSON_TYPE)


class ApiQuota(Base):
    __tablename__ = "api_quotas"
    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    utc_day: Mapped[date] = mapped_column(Date, primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SyncLease(Base):
    __tablename__ = "sync_leases"
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner: Mapped[str] = mapped_column(String(36))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ActionRequest(Base):
    __tablename__ = "action_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"))
    initiator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(32))
    value: Mapped[Decimal | None] = mapped_column(MONEY)
    baseline_status: Mapped[str | None] = mapped_column(String(64))
    baseline_budget: Mapped[Decimal | None] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("workspace_id", "initiator_id", "idempotency_key"),
        Index("uq_pending_action_entity", "entity_id", unique=True,
              postgresql_where=text("status IN ('queued','executing','verifying','unknown')"),
              sqlite_where=text("status IN ('queued','executing','verifying','unknown')")),
    )


class ActionExecution(Base):
    __tablename__ = "action_executions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("action_requests.id"), unique=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64))


class ActionLog(Base):
    __tablename__ = "action_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("action_requests.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE)


# Future workflow tables retain explicit links, without enabling rules/AI.
def workflow_table(name: str, links: dict[str, str] | None = None) -> Table:
    columns = [
        Column("id", String(36), primary_key=True),
        Column("workspace_id", String(64), nullable=False, index=True),
        Column("status", String(32), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("payload", JSON_TYPE, nullable=False),
    ]
    columns.extend(Column(key, String(36), ForeignKey(target), nullable=True) for key, target in (links or {}).items())
    return Table(name, Base.metadata, *columns)


workflow_table("rules")
workflow_table("rule_runs", {"rule_id": "rules.id", "request_id": "action_requests.id"})
workflow_table("ai_decisions")
workflow_table("ai_actions", {"decision_id": "ai_decisions.id", "request_id": "action_requests.id"})
workflow_table("telegram_users", {"user_id": "users.id"})
workflow_table("telegram_commands", {"telegram_user_id": "telegram_users.id", "request_id": "action_requests.id"})
