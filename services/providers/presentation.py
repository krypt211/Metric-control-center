"""Safe provider metadata, separate from connection health."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.providers.models import ProviderWindow
from services.storage.models import AdAccount, DailyMetric, Entity, SyncRun
from services.sync.engine import aware


def quota_numbers(payload: dict[str, Any]) -> dict[str, int | float | None]:
    """Normalize only the known legacy summary and discard other fields."""
    data = payload.get("summary", payload)
    if isinstance(data, str) and len(data) <= 4096:
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    if isinstance(data.get("data"), dict):
        data = data["data"]
    result = {}
    for target, names in {
        "used": ("daily_used", "used", "requests_used", "requests"),
        "limit": ("daily_limit", "limit"),
        "remaining": ("daily_remaining", "remaining"),
    }.items():
        result[target] = next(
            (
                data[name]
                for name in names
                if isinstance(data.get(name), (int, float))
                and not isinstance(data[name], bool)
                and 0 <= data[name] < float("inf")
            ),
            None,
        )
    return result


def period_evidence(
    session: Session,
    account: AdAccount,
    start: date,
    end: date,
    now: datetime,
    revision: int | None,
) -> dict[str, Any]:
    """Report coverage without turning absent facts into zero metrics."""
    from services.providers.router import windows_for

    windows = session.scalars(
        select(ProviderWindow).where(
            ProviderWindow.account_id == account.id,
            ProviderWindow.start_day <= end,
            ProviderWindow.end_day >= start,
        )
    ).all()
    complete = windows_for(session, account, start, end, revision=revision)
    # Preserve verified historical MetricFlow facts that predate windows.
    legacy = account.provider == "metricflow" and revision in (None, 1)
    day = start
    while legacy and day <= end:
        covering = [w for w in windows if w.start_day <= day <= w.end_day]
        if covering and not any(
            w.complete and (revision is None or w.credential_revision == revision)
            for w in covering
        ):
            legacy = False
        day += timedelta(days=1)
    readable = bool(complete or legacy)
    count = (
        session.scalar(
            select(func.count())
            .select_from(DailyMetric)
            .join(Entity)
            .where(
                Entity.account_id == account.id,
                Entity.kind == "ad",
                DailyMetric.source == account.provider,
                DailyMetric.day >= start,
                DailyMetric.day <= end,
            )
        )
        if readable
        else 0
    )
    local_day = now.astimezone(ZoneInfo(account.timezone)).date()
    if start > local_day:
        coverage = "not_started"
    elif not readable:
        coverage = "not_synced"
    else:
        coverage = "available" if count else "no_data"
    run = session.scalar(
        select(SyncRun)
        .where(
            SyncRun.workspace_id == account.workspace_id,
            SyncRun.provider == account.provider,
            SyncRun.job != "optional_read",
        )
        .order_by(SyncRun.started_at.desc())
        .limit(1)
    )
    return {
        "facts_readable": readable,
        "facts_count": count or 0,
        "coverage": coverage,
        "window_status": "complete"
        if complete
        else "legacy"
        if legacy
        else "revision_mismatch"
        if any(w.complete for w in windows)
        else "incomplete"
        if windows
        else "missing",
        "credential_revision": revision,
        "source_timestamp": min(
            (w.source_timestamp for w in complete if w.source_timestamp),
            default=None,
        ),
        "account_name": account.name or account.external_id,
        "timezone": account.timezone,
        "local_date": local_day.isoformat(),
        "sync_status": run.status if run else "not_run",
        "sync_at": aware(run.finished_at).isoformat()
        if run and run.finished_at
        else None,
        "sync_error": run.error_code if run else None,
    }
