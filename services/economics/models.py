"""Additive economics storage; monetary payloads retain Decimal strings."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from services.storage.models import JSON_TYPE, Base


class EconomicsProfile(Base):
    __tablename__ = "economics_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(36))
    version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EconomicsAssignment(Base):
    __tablename__ = "economics_assignments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("economics_profiles.id"))
    scope_type: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[str] = mapped_column(String(36))
    effective_start: Mapped[date] = mapped_column(Date)
    effective_end: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApprovalObservation(Base):
    __tablename__ = "approval_observations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("economics_profiles.id"))
    scope_type: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[str] = mapped_column(String(36))
    cohort: Mapped[str] = mapped_column(String(120))
    start_day: Mapped[date] = mapped_column(Date)
    end_day: Mapped[date] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "profile_id", "scope_type", "scope_id", "cohort"
        ),
    )


class EconomicsEvaluation(Base):
    __tablename__ = "economics_evaluations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("economics_profiles.id"))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    start_day: Mapped[date] = mapped_column(Date)
    end_day: Mapped[date] = mapped_column(Date)
    digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "profile_id", "entity_id", "start_day", "end_day", "digest"
        ),
    )


class EconomicsAuditLog(Base):
    __tablename__ = "economics_audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    resource_id: Mapped[str] = mapped_column(String(36), index=True)
    event: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EconomicsGrant(Base):
    __tablename__ = "economics_grants"
    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    can_edit: Mapped[bool] = mapped_column(Boolean)
