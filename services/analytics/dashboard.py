"""Dashboard reads the database only; ratios use totals, not averaged percentages."""

from datetime import date, datetime, timezone
import json
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from services.storage.models import AdAccount, DailyMetric, Entity, SyncRun, TrackerMetric
from services.sync.engine import aware


def _sum(values) -> Decimal | int | None:
    values = list(values)
    # A partially unknown total is unknown, not an understated sum.
    return sum(values) if values and all(v is not None for v in values) else None


def _ratio(numerator, denominator, multiplier=1) -> str | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return str((Decimal(numerator) / Decimal(denominator) * multiplier).quantize(Decimal("0.0001")))



# Event counters are additive on the proven ad/day facts. Unique audience counters
# and frequency only have a valid population when displaying one ad/day.
EXTRA_COUNTS = ("inline_link_clicks", "registrations", "video_views", "app_installs",
                "landing_page_views", "video_3s_views", "video_p100_views", "video_starts")
def extra_metrics(rows):
    from services.sync.schema import decimal_value, SchemaError
    out = {}
    for name in EXTRA_COUNTS:
        try:
            out[name] = _sum(decimal_value((getattr(metric, "raw", None) or {}).get(name), count=True) for metric, _ in rows)
        except SchemaError:
            out[name] = None
    single = rows[0][0] if len(rows) == 1 else None
    out["reach"] = getattr(single, "reach", None)
    frequency = getattr(single, "frequency", None)
    out["frequency"] = str(frequency) if frequency is not None else None
    for name in ("unique_clicks", "unique_inline_link_clicks"):
        try:
            out[name] = decimal_value((getattr(single, "raw", None) or {}).get(name), count=True) if single is not None else None
        except SchemaError:
            out[name] = None
    return out


def aggregate(rows, currency: str, timezone_name: str, *, exact_ratios: bool = False):
    def ratio(numerator, denominator, multiplier=1):
        if not exact_ratios:
            return _ratio(numerator, denominator, multiplier)
        if numerator is None or denominator is None or denominator == 0:
            return None
        return str(Decimal(numerator) / Decimal(denominator) * multiplier)
    spend = _sum(metric.spend for metric, _ in rows)
    impressions = _sum(metric.impressions for metric, _ in rows)
    clicks = _sum(metric.clicks for metric, _ in rows)
    has_tracker = any(tracker is not None for _, tracker in rows)
    complete = has_tracker and all(tracker is not None and tracker.currency == currency and tracker.timezone == timezone_name for _, tracker in rows)
    values = {}
    for name in ("leads", "sales", "conversions", "revenue"):
        values[name] = (_sum(getattr(tracker, name) for _, tracker in rows) if complete else None) if has_tracker else _sum(getattr(metric, name) for metric, _ in rows)
    revenue = values["revenue"]
    profit = revenue - spend if revenue is not None and spend is not None else None
    conversion_clicks = _sum(tracker.clicks for _, tracker in rows) if complete else None if has_tracker else clicks
    return {
        "spend": str(spend) if spend is not None else None,
        "revenue": str(revenue) if revenue is not None else None,
        "profit": str(profit) if profit is not None else None, "roi": ratio(profit, spend, 100),
        "impressions": impressions, "clicks": clicks, "leads": values["leads"], "sales": values["sales"], "conversions": values["conversions"],
        "ctr": ratio(clicks, impressions, 100), "cpc": ratio(spend, clicks), "cpm": ratio(spend, impressions, 1000),
        "cpl": ratio(spend, values["leads"]), "cps": ratio(spend, values["sales"]),
        "cpa": ratio(spend, values["conversions"]), "cr": ratio(values["conversions"], conversion_clicks, 100), "epc": ratio(revenue, conversion_clicks),
        "conversion_source": "tracker" if has_tracker else "advertising", "tracker_complete": complete if has_tracker else None,
        "conversion_clicks": conversion_clicks, **extra_metrics(rows),
    }


def summary(session, workspace: str, start: date, end: date, *, level: str = "ad", provider: str | None = None, zone: str | None = None) -> list[dict[str, Any]]:
    from services.providers.router import DataSourceRouter
    routes = DataSourceRouter(session,workspace).resolve(start,end,provider_override=provider)
    account_ids=[r["account_id"] for r in routes.values() if r["account_id"] and r.get("facts_readable",True)]
    query = select(DailyMetric, Entity.external_id, AdAccount.external_id).join(
        Entity, DailyMetric.entity_id == Entity.id
    ).join(AdAccount, Entity.account_id == AdAccount.id).where(
        AdAccount.workspace_id == workspace, AdAccount.id.in_(account_ids),
        Entity.kind == level, DailyMetric.source == AdAccount.provider,
        DailyMetric.day >= start, DailyMetric.day <= end,
    )
    if zone:
        query = query.where(DailyMetric.timezone == zone)
    observations = session.execute(query).all()
    tracker_rows = session.scalars(select(TrackerMetric).join(Entity).join(AdAccount).where(
        AdAccount.workspace_id == workspace, AdAccount.id.in_(account_ids),
        Entity.kind == level, TrackerMetric.source == AdAccount.provider,
        TrackerMetric.day >= start, TrackerMetric.day <= end,
    )).all()
    trackers = {(row.entity_id, row.day): row for row in tracker_rows}
    groups = {}
    for metric, entity_external, account_external in observations:
        groups.setdefault((metric.currency, metric.timezone, metric.source, json.dumps((metric.raw or {}).get("_provider",{}).get("attribution"),sort_keys=True)), []).append((metric, trackers.get((metric.entity_id, metric.day))))
    result = []
    for (currency, timezone_name, source, attribution), rows in sorted(groups.items()):
        spend = _sum(row.spend for row, _ in rows)
        impressions = _sum(row.impressions for row, _ in rows)
        clicks = _sum(row.clicks for row, _ in rows)
        # Conversion source is fixed per group. Never mix tracker and FB silently.
        has_tracker = any(tracker is not None for _, tracker in rows)
        tracker_complete = has_tracker and all(
            tracker is not None and tracker.currency == currency and tracker.timezone == timezone_name
            for _, tracker in rows
        )
        if has_tracker:
            leads = _sum(tracker.leads for _, tracker in rows) if tracker_complete else None
            sales = _sum(tracker.sales for _, tracker in rows) if tracker_complete else None
            revenue = _sum(tracker.revenue for _, tracker in rows) if tracker_complete else None
        else:
            leads = _sum(row.leads for row, _ in rows)
            sales = _sum(row.sales for row, _ in rows)
            revenue = _sum(row.revenue for row, _ in rows)
        profit = revenue - spend if revenue is not None and spend is not None else None
        result.append({
            "currency": currency, "timezone": timezone_name, "source_provider": source, "attribution": json.loads(attribution),
            "start": start.isoformat(), "end": end.isoformat(), "level": level,
            "conversion_source": "tracker" if has_tracker else "advertising",
            "tracker_complete": tracker_complete if has_tracker else None,
            "rows": len(rows), "spend": str(spend) if spend is not None else None,
            "revenue": str(revenue) if revenue is not None else None,
            "profit": str(profit) if profit is not None else None,
            "roi": _ratio(profit, spend, 100), "leads": leads, "sales": sales,
            "cpl": _ratio(spend, leads), "cps": _ratio(spend, sales),
            "impressions": impressions, "clicks": clicks,
            "ctr": _ratio(clicks, impressions, 100), "cpc": _ratio(spend, clicks),
            "cpm": _ratio(spend, impressions, 1000),
            "oldest_observation": min(aware(row.observed_at) for row, _ in rows).isoformat(),
        })
    return result


def dashboard_today(session, workspace: str, *, level: str = "ad", now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    zones = session.scalars(select(AdAccount.timezone).where(
        AdAccount.workspace_id == workspace,
    ).distinct()).all()
    groups = []
    for zone in sorted(zones):
        day = now.astimezone(ZoneInfo(zone)).date()
        groups.extend(summary(session, workspace, day, day, level=level, zone=zone))
    runs = session.scalars(select(SyncRun).where(
        SyncRun.workspace_id == workspace,
    ).order_by(SyncRun.started_at.desc()).limit(20)).all()
    last_success = next((run for run in runs if run.status == "succeeded"), None)
    # Last 20 failed runs must not hide an older successful load.
    if last_success is None:
        last_success = session.scalar(select(SyncRun).where(
            SyncRun.workspace_id == workspace, SyncRun.status == "succeeded",
        ).order_by(SyncRun.finished_at.desc()).limit(1))
    for group in groups:
        group["stale"] = (now - datetime.fromisoformat(group["oldest_observation"])).total_seconds() > 1800
    from services.providers.router import DataSourceRouter
    sources=[]
    for zone in sorted(zones):
        day=now.astimezone(ZoneInfo(zone)).date()
        sources.extend(r for r in DataSourceRouter(session,workspace,now).resolve(day,day).values() if r.get("timezone")==zone)
    sources=list({r["canonical_id"]:r for r in sources}.values())
    for group in groups:
        group["stale"] = group["stale"] or any(r["stale"] for r in sources if r["provider"]==group["source_provider"])
    return {
        "sources": sources,
        "status": "ready" if groups else "empty", "level": level, "groups": groups,
        "last_success_sync": aware(last_success.finished_at).isoformat() if last_success and last_success.finished_at else None,
        "last_run": {"status": runs[0].status, "error_code": runs[0].error_code} if runs else None,
        "as_of": now.isoformat(),
    }
