"""Durable bounded sessions; credentials stay in the existing READ vault."""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from services.storage.models import JSON_TYPE, Base


class MetaPilotSession(Base):
    __tablename__ = "meta_pilot_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    account_id: Mapped[str] = mapped_column(String(80))
    start_day: Mapped[date] = mapped_column(Date)
    end_day: Mapped[date] = mapped_column(Date)
    max_attempts: Mapped[int] = mapped_column(Integer)
    used_attempts: Mapped[int] = mapped_column(Integer, default=0)
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    credential_revision: Mapped[int] = mapped_column(Integer)
    job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("provider_jobs.id"), unique=True
    )
    result: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    __table_args__ = (
        CheckConstraint("max_attempts BETWEEN 1 AND 20"),
        CheckConstraint("used_attempts BETWEEN 0 AND max_attempts"),
        CheckConstraint("timeout_seconds BETWEEN 30 AND 900"),
        CheckConstraint("start_day <= end_day"),
    )
