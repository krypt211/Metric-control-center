"""Explainable, deterministic signals. No queue, writer, or AI dependencies."""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from services.storage.models import AdAccount, RecommendationSettings
from services.sync.engine import aware, utc_now
from .dashboard import aggregate
from .table import Filters, table_data


class DetectorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: Literal["campaign", "adset", "ad", "creative"] = "adset"
    window: Literal["today", "yesterday", "last3", "last7", "last14", "last30"] = "today"
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    minimum_spend: Decimal = Field(default=Decimal("50"), ge=0, allow_inf_nan=False, max_digits=24, decimal_places=8)
    minimum_conversions: int = Field(default=5, ge=1, le=2**63-1)
    target_roi: Decimal = Field(default=Decimal("100"), allow_inf_nan=False, max_digits=24, decimal_places=8)
    target_cpl: Decimal = Field(default=Decimal("10"), gt=0, allow_inf_nan=False, max_digits=24, decimal_places=8)
    loser_spend_multiplier: Decimal = Field(default=Decimal("2"), ge=1, le=100, allow_inf_nan=False)
    fatigue_days: int = Field(default=5, ge=3, le=14)
    ctr_decline_percent: Decimal = Field(default=Decimal("20"), gt=0, le=100, allow_inf_nan=False)
    cpc_increase_percent: Decimal = Field(default=Decimal("20"), gt=0, le=1000, allow_inf_nan=False)
    frequency_increase_percent: Decimal = Field(default=Decimal("10"), gt=0, le=1000, allow_inf_nan=False)
    cpl_increase_percent: Decimal = Field(default=Decimal("20"), gt=0, le=1000, allow_inf_nan=False)
    minimum_daily_impressions: int = Field(default=100, ge=1, le=2**63-1)
    minimum_daily_clicks: int = Field(default=10, ge=1, le=2**63-1)
    current_max_age_minutes: int = Field(default=30, ge=1, le=1440)
    historical_max_age_hours: int = Field(default=36, ge=1, le=168)


class SettingsConflict(ValueError):
    pass


def read_settings(session, workspace):
    stored = session.get(RecommendationSettings, workspace)
    return (DetectorConfig.model_validate(stored.payload), stored.revision) if stored else (DetectorConfig(), 0)


def save_settings(sessions, workspace, config: DetectorConfig, revision: int, *, now=None):
    try:
        with sessions.begin() as session:
            if revision == 0:
                session.add(RecommendationSettings(workspace_id=workspace, revision=1,
                    payload=config.model_dump(mode="json"), updated_at=now or utc_now()))
            else:
                changed = session.execute(update(RecommendationSettings).where(
                    RecommendationSettings.workspace_id == workspace, RecommendationSettings.revision == revision
                ).values(revision=revision + 1, payload=config.model_dump(mode="json"), updated_at=now or utc_now()))
                if changed.rowcount != 1:
                    raise SettingsConflict("Settings changed; reload before saving")
    except IntegrityError:
        raise SettingsConflict("Settings changed; reload before saving") from None
    return revision + 1


def winner(metrics, config):
    required = ("spend", "conversions", "roi", "cpl")
    if any(metrics.get(key) is None for key in required):
        return {"matched": False, "reason": "unknown_metrics", "missing": [key for key in required if metrics.get(key) is None]}
    checks = [
        {"metric": "spend", "value": metrics["spend"], "operator": ">=", "target": str(config.minimum_spend)},
        {"metric": "conversions", "value": metrics["conversions"], "operator": ">=", "target": str(config.minimum_conversions)},
        {"metric": "roi", "value": metrics["roi"], "operator": ">=", "target": str(config.target_roi)},
        {"metric": "cpl", "value": metrics["cpl"], "operator": "<=", "target": str(config.target_cpl)},
    ]
    for check in checks:
        value, target = Decimal(str(check["value"])), Decimal(check["target"])
        check["passed"] = value <= target if check["operator"] == "<=" else value >= target
    matched = all(check["passed"] for check in checks)
    return {"matched": matched, "reason": "winner" if matched else "thresholds_not_met", "checks": checks}


def loser(metrics, config):
    if metrics.get("spend") is None or metrics.get("leads") is None:
        return {"matched": False, "reason": "unknown_metrics", "missing": [key for key in ("spend", "leads") if metrics.get(key) is None]}
    threshold = config.loser_spend_multiplier * config.target_cpl
    checks = [{"metric": "spend", "value": metrics["spend"], "operator": ">=", "target": str(threshold),
               "passed": Decimal(str(metrics["spend"])) >= threshold},
              {"metric": "leads", "value": metrics["leads"], "operator": "=", "target": "0", "passed": metrics["leads"] == 0}]
    matched = all(check["passed"] for check in checks)
    return {"matched": matched, "reason": "stop_candidate" if matched else "thresholds_not_met", "checks": checks}


def fresh(timestamp, now, seconds):
    return bool(timestamp and -60 <= (now - aware(datetime.fromisoformat(timestamp))).total_seconds() <= seconds)


def fatigue(daily, config, now, zone):
    end = now.astimezone(ZoneInfo(zone)).date() - timedelta(days=1)
    dates = [(end - timedelta(days=offset)).isoformat() for offset in reversed(range(config.fatigue_days))]
    lookup = {row["date"]: row for row in daily}
    if any(day not in lookup for day in dates):
        return {"matched": False, "reason": "incomplete_history", "missing_dates": [day for day in dates if day not in lookup], "series": []}
    rows = [lookup[day] for day in dates]
    series = [{key: row.get(key) for key in ("date", "ctr", "cpc", "frequency", "cpl", "impressions", "clicks", "leads")} for row in rows]
    result = {"matched": False, "series": series, "window": [dates[0], dates[-1]]}
    if any(not fresh(row["oldest_observation"], now, config.historical_max_age_hours * 3600) for row in rows):
        return {**result, "reason": "stale_history"}
    if any(row.get("frequency") is None for row in rows):
        return {**result, "reason": "frequency_unavailable"}
    if any(not fresh(row.get("frequency_observed_at"), now, config.historical_max_age_hours * 3600) for row in rows):
        return {**result, "reason": "stale_frequency"}
    if any(row.get("impressions") is None or row.get("clicks") is None or
           row["impressions"] < config.minimum_daily_impressions or row["clicks"] < config.minimum_daily_clicks for row in rows):
        return {**result, "reason": "insufficient_daily_volume"}
    if any(row.get(key) is None for row in rows for key in ("ctr", "cpc", "cpl")):
        return {**result, "reason": "unknown_metrics"}
    if len({row["conversion_source"] for row in rows}) != 1 or any(row.get("tracker_complete") is False for row in rows):
        return {**result, "reason": "conversion_source_changed"}
    if any(row["ad_ids"] != rows[0]["ad_ids"] for row in rows):
        return {**result, "reason": "delivery_cohort_changed"}
    changes, checks = {}, []
    thresholds = {"ctr": config.ctr_decline_percent, "cpc": config.cpc_increase_percent,
                  "frequency": config.frequency_increase_percent, "cpl": config.cpl_increase_percent}
    for metric, threshold in thresholds.items():
        values = [Decimal(str(row[metric])) for row in rows]
        if values[0] <= 0:
            return {**result, "reason": "zero_baseline"}
        change = (values[-1] - values[0]) / values[0] * 100
        downward = metric == "ctr"
        monotonic = all(b <= a if downward else b >= a for a, b in zip(values, values[1:]))
        passed = monotonic and (-change >= threshold if downward else change >= threshold)
        changes[metric] = str(change)
        checks.append({"metric": metric, "change_percent": str(change), "target_percent": str(-threshold if downward else threshold),
                       "monotonic": monotonic, "passed": passed})
    matched = all(check["passed"] for check in checks)
    return {**result, "matched": matched, "reason": "creative_fatigue" if matched else "trend_not_confirmed", "changes": changes, "checks": checks}


def recommendations(session, workspace, *, now=None, offset=0, limit=100, category=None):
    now = now or utc_now()
    config, revision = read_settings(session, workspace)
    zones = session.scalars(select(AdAccount.timezone).where(AdAccount.workspace_id == workspace,
        AdAccount.currency == config.currency).distinct()).all()
    all_rows = []
    for zone in sorted(zones):
        today = now.astimezone(ZoneInfo(zone)).date()
        if config.window == "yesterday":
            first = last = today - timedelta(days=1)
        else:
            days = 1 if config.window == "today" else int(config.window[4:])
            first, last = today - timedelta(days=days-1), today
        history_start = today - timedelta(days=config.fatigue_days)
        rows = table_data(session, workspace, Filters(min(first, history_start), last),
            level=config.level, limit=1_000_000, exact_ratios=True, include_daily=True)["rows"]
        for row in rows:
            if row["currency"] != config.currency or row["timezone"] != zone:
                continue
            period = [day for day in row["daily"] if first.isoformat() <= day["date"] <= last.isoformat()]
            # Sum base facts, then derive ratios. Do not average daily ratios.
            pairs = []
            for day in period:
                values = {key: (Decimal(str(day[key])) if key in ("spend", "revenue") else int(day[key])) if day[key] is not None else None
                    for key in ("spend", "revenue", "impressions", "clicks", "conversions", "leads", "sales")}
                metric = SimpleNamespace(**values)
                tracker = SimpleNamespace(**{key: values[key] for key in ("revenue", "conversions", "leads", "sales")},
                    clicks=day["conversion_clicks"], currency=config.currency, timezone=zone) if day["conversion_source"] == "tracker" else None
                pairs.append((metric, tracker))
            metrics = aggregate(pairs, config.currency, zone, exact_ratios=True)
            # Preserve incomplete/mixed conversion-source information even though
            # per-day tracker values have already been selected by aggregation.
            source_changed = len({day["conversion_source"] for day in period}) > 1 or any(day["tracker_complete"] is False for day in period)
            if source_changed:
                for key in ("conversions", "leads", "sales", "revenue", "profit", "roi", "cpl", "cpa", "cr", "epc"):
                    metrics[key] = None
            current_complete = len(period) == (last - first).days + 1
            current_fresh = current_complete and all(fresh(day["oldest_observation"], now,
                config.current_max_age_minutes * 60 if day["date"] == today.isoformat() else config.historical_max_age_hours * 3600
            ) for day in period)
            win, stop = winner(metrics, config), loser(metrics, config)
            if not current_fresh:
                for signal in (win, stop):
                    signal.update(matched=False, reason="stale_metrics" if current_complete else "incomplete_period")
            tired = fatigue(row["daily"], config, now, zone)
            account = session.get(AdAccount, row["account_id"])
            if account.currency != config.currency or account.timezone != zone:
                for signal in (win, stop, tired):
                    signal.update(matched=False, reason="account_units_mismatch")
            classification = "stop" if stop["matched"] else "fatigue" if tired["matched"] else "scale" if win["matched"] else "watch"
            all_rows.append({"id": row["id"], "external_id": row["external_id"], "name": row["name"],
                "level": row["level"], "account_id": row["account_id"], "currency": row["currency"], "timezone": zone,
                "status": row["status"], "category": classification, "metrics": metrics,
                "window": [first.isoformat(), last.isoformat()], "current_fresh": current_fresh,
                "signals": {"winner": win, "loser": stop, "fatigue": tired}})
    priority = {"stop": 0, "fatigue": 1, "scale": 2, "watch": 3}
    all_rows.sort(key=lambda row: (priority[row["category"]], row["name"], row["id"]))
    counts = {name: sum(row["category"] == name for row in all_rows) for name in priority}
    filtered = [row for row in all_rows if not category or row["category"] == category]
    return {"settings": config.model_dump(mode="json"), "revision": revision, "as_of": now.isoformat(),
        "counts": counts, "rows": filtered[offset:offset + limit], "total": len(filtered),
        "next_offset": offset + limit if len(filtered) > offset + limit else None}
