"""Python computes weighted metrics and trends; missing days remain unknown."""
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from services.analytics.dashboard import aggregate
from services.analytics.recommendations import fatigue, fresh, read_settings, winner, loser
from services.analytics.table import Filters, table_data
from services.storage.models import Ad, AdSet, AdAccount, Entity, EntityCurrentState
from services.sync.engine import aware
from sqlalchemy import select

BASE = ("spend", "revenue", "impressions", "clicks", "conversions", "leads", "sales")
TRENDS = ("spend", "ctr", "cpc", "cpm", "leads", "sales", "conversions", "cpl", "revenue", "profit", "roi")


def period(daily, first, last, currency, zone, now, detector):
    days = [r for r in daily if first.isoformat() <= r["date"] <= last.isoformat()]
    complete = len(days) == (last - first).days + 1
    today = now.astimezone(ZoneInfo(zone)).date().isoformat()
    timely = complete and all(fresh(r["oldest_observation"], now,
        detector.current_max_age_minutes * 60 if r["date"] == today else detector.historical_max_age_hours * 3600) for r in days)
    pairs = []
    for day in days:
        values = {k: None if day[k] is None else Decimal(str(day[k])) if k in ("spend", "revenue") else day[k] for k in BASE}
        metric = SimpleNamespace(**values)
        tracker = SimpleNamespace(**{k: values[k] for k in ("revenue", "conversions", "leads", "sales")},
            clicks=day["conversion_clicks"], currency=currency, timezone=zone) if day["conversion_source"] == "tracker" else None
        pairs.append((metric, tracker))
    metrics = aggregate(pairs, currency, zone, exact_ratios=True)
    mixed = len({r["conversion_source"] for r in days}) > 1 or any(r["tracker_complete"] is False for r in days)
    if not complete:
        metrics = {k: None for k in metrics}
    elif mixed:
        for key in ("conversions", "leads", "sales", "revenue", "profit", "roi", "cpl", "cps", "cpa", "cr", "epc"):
            metrics[key] = None
    signals = {"winner": winner(metrics, detector), "loser": loser(metrics, detector)}
    if not timely:
        for signal in signals.values():
            signal.update(matched=False, reason="stale_metrics" if complete else "incomplete_period")
    return {"window": [first.isoformat(), last.isoformat()], "complete": complete, "fresh": timely, "metrics": metrics, "signals": signals}


def percent(current, previous):
    if current is None or previous is None or Decimal(str(previous)) <= 0:
        return None
    return str((Decimal(str(current)) - Decimal(str(previous))) / Decimal(str(previous)) * 100)


def build_snapshot(session, workspace, entity_ids, now):
    detector, detector_revision = read_settings(session, workspace)
    results = []
    for entity_id in entity_ids:
        entity = session.get(Entity, entity_id)
        account = session.get(AdAccount, entity.account_id) if entity else None
        if not entity or not account or account.workspace_id != workspace:
            raise ValueError("Entity does not exist in this workspace")
        today = now.astimezone(ZoneInfo(account.timezone)).date()
        first = today - timedelta(days=max(14, detector.fatigue_days))
        # Use the same ad fact aggregation as the dashboard for all levels.
        report = table_data(session, workspace, Filters(first, today, account=account.id),
            level=entity.kind, limit=1_000_000, exact_ratios=True, include_daily=True)
        candidates = [r for r in report["rows"] if r["id"] == entity.id and r["currency"] == account.currency and r["timezone"] == account.timezone]
        if len(candidates) != 1:
            raise ValueError("Entity has no unambiguous statistics")
        row = candidates[0]
        daily = row["daily"]
        windows = {"today": period(daily, today, today, account.currency, account.timezone, now, detector)}
        trends = {}
        for count in (1, 3, 7):
            end = today - timedelta(days=1)
            start = today - timedelta(days=count)
            current = period(daily, start, end, account.currency, account.timezone, now, detector)
            prior = period(daily, start-timedelta(days=count), end-timedelta(days=count), account.currency, account.timezone, now, detector)
            windows[f"last{count}"] = current
            comparable = current["fresh"] and prior["fresh"] and current["metrics"].get("conversion_source") == prior["metrics"].get("conversion_source")
            trends[f"{count}d"] = {"window": current["window"], "previous_window": prior["window"],
                "comparable": comparable, "change_percent": {k: percent(current["metrics"][k], prior["metrics"][k]) if comparable else None for k in TRENDS}}
        # The account baseline is aggregated from all ads, not average ad CPL.
        baseline = table_data(session, workspace, Filters(today, today, account=account.id),
            level="account", limit=10, exact_ratios=True, include_daily=True)["rows"]
        baseline = next((r for r in baseline if r["currency"] == account.currency and r["timezone"] == account.timezone), None)
        baseline_period = period(baseline["daily"] if baseline else [], today, today, account.currency, account.timezone, now, detector)
        tired = fatigue(daily, detector, now, account.timezone)
        state = session.get(EntityCurrentState, entity.id)
        state_fresh = bool(state and -60 <= (now - aware(state.observed_at)).total_seconds() <= 900)
        ads = session.scalars(select(Ad).join(Entity).where(Entity.account_id == account.id)).all()
        sets = {s.entity_id: s for s in session.scalars(select(AdSet).join(Entity).where(Entity.account_id == account.id))}
        included = [ad for ad in ads if (entity.kind == "ad" and ad.entity_id == entity.id) or
            (entity.kind == "adset" and ad.adset_id == entity.id) or (entity.kind == "creative" and ad.creative_id == entity.id) or
            (entity.kind == "campaign" and ad.adset_id in sets and sets[ad.adset_id].campaign_id == entity.id)]
        hierarchy = {"campaign_ids": sorted({sets[ad.adset_id].campaign_id for ad in included if ad.adset_id in sets and sets[ad.adset_id].campaign_id}),
            "adset_ids": sorted({ad.adset_id for ad in included if ad.adset_id}),
            "ad_ids": sorted(ad.entity_id for ad in included), "creative_ids": sorted({ad.creative_id for ad in included if ad.creative_id})}
        # Names are excluded from LLM context: provider text is untrusted and
        # unnecessary for decisions. The UI resolves display names separately.
        subject = {"entity_id": entity.id, "level": entity.kind, "account_id": account.id,
            "currency": account.currency, "timezone": account.timezone, "hierarchy": hierarchy,
            "state": {"status": state.status if state else None, "budget": str(state.budget) if state and state.budget is not None else None,
                "fresh": state_fresh}, "windows": windows, "trends": trends,
            "account_baseline": {"fresh": baseline_period["fresh"], "cpl": baseline_period["metrics"]["cpl"],
                "cpl_difference_percent": percent(windows["today"]["metrics"]["cpl"], baseline_period["metrics"]["cpl"]) if baseline_period["fresh"] else None},
            "fatigue": tired,
            "evidence_ids": ["today", "last1", "last3", "last7", "trend_1d", "trend_3d", "trend_7d", "account_baseline", "fatigue", "state"]}
        from .profiles import snapshot_profiles
        subject["profiles"] = snapshot_profiles(session, workspace, entity, now)
        subject["fingerprint"] = fingerprint(subject)
        results.append(subject)
    return {"version": 1, "as_of": now.isoformat(), "detector_revision": detector_revision,
        "targets": detector.model_dump(mode="json"), "entities": results}


def fingerprint(subject):
    # As-of timestamps are outside this object; freshness, dates, policy and
    # metric values are inside it and must still agree before execution.
    return hashlib.sha256(json.dumps({k: v for k, v in subject.items() if k != "fingerprint"}, sort_keys=True).encode()).hexdigest()
