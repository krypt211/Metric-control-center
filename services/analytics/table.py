"""One set of ad facts feeds all hierarchy levels and creative aggregation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from services.storage.models import Ad, AdAccount, AdSet, Breakdown, Creative, DailyMetric, Entity, EntityCurrentState, TrackerMetric
from services.sync.schema import decimal_value
from services.sync.engine import aware

from .dashboard import aggregate


@dataclass(frozen=True)
class Filters:
    start: date
    end: date
    account: str | None = None
    campaign: str | None = None
    adset: str | None = None
    ad: str | None = None
    creative: str | None = None
    status: str | None = None
    buyer: str | None = None
    offer: str | None = None
    tracker_campaign: str | None = None
    geo: str | None = None


def table_data(session, workspace: str, filters: Filters, *, level: str = "account", offset: int = 0, limit: int = 100, exact_ratios: bool = False, include_daily: bool = False, sort_key: str | None = None, sort_direction: str = "asc", provider_override: str | None = None):
    if level not in ("account", "campaign", "adset", "ad", "creative"):
        raise ValueError("Unsupported hierarchy level")
    if filters.start > filters.end:
        raise ValueError("Invalid date range")
    if sort_key:
        from services.preferences.registry import sort_rows
        sort_rows([],sort_key,sort_direction,level)
    from services.providers.router import DataSourceRouter
    from services.providers.matching import identity_maps
    routes = DataSourceRouter(session, workspace).resolve(filters.start, filters.end, provider_override=provider_override)
    account_ids = [r["account_id"] for r in routes.values() if r["account_id"]]
    readable_ids = [r["account_id"] for r in routes.values() if r.get("facts_readable",True)]
    account_map, entity_map = identity_maps(session, workspace)
    source_by_account = {r["account_id"]: r for r in routes.values()}
    accounts = {r.id: r for r in session.scalars(select(AdAccount).where(AdAccount.id.in_(account_ids)))}
    if not accounts:
        return {"rows": [], "total": 0, "next_offset": None, "sources": list(routes.values())}
    entity_scope = select(Entity.id).join(AdAccount).where(AdAccount.workspace_id == workspace, AdAccount.id.in_(account_ids))
    ad_scope = select(Ad.entity_id).where(Ad.entity_id.in_(entity_scope))
    entities = {r.id: r for r in session.scalars(select(Entity).where(Entity.id.in_(entity_scope)))}
    ads = {r.entity_id: r for r in session.scalars(select(Ad).where(Ad.entity_id.in_(entity_scope)))}
    adsets = {r.entity_id: r for r in session.scalars(select(AdSet).where(AdSet.entity_id.in_(entity_scope)))}
    states = {r.entity_id: r for r in session.scalars(select(EntityCurrentState).where(EntityCurrentState.entity_id.in_(entity_scope)))}
    creatives = {r.entity_id: r for r in session.scalars(select(Creative).where(Creative.entity_id.in_(entity_scope)))}
    trackers = {(r.entity_id, r.day): r for r in session.scalars(select(TrackerMetric).where(
        TrackerMetric.entity_id.in_(ad_scope), TrackerMetric.source.in_({a.provider for a in accounts.values()}),
        TrackerMetric.day >= filters.start, TrackerMetric.day <= filters.end,
    ))}
    groups = {}
    facts = session.scalars(select(DailyMetric).where(
        DailyMetric.entity_id.in_(ad_scope), DailyMetric.source.in_({a.provider for a in accounts.values()}),
        DailyMetric.day >= filters.start, DailyMetric.day <= filters.end,
    ))
    if filters.geo:
        slices = session.scalars(select(Breakdown).where(
            Breakdown.entity_id.in_(ad_scope), Breakdown.source.in_({a.provider for a in accounts.values()}),
            Breakdown.day >= filters.start, Breakdown.day <= filters.end,
            Breakdown.dimensions["country"].as_string() == filters.geo,
        )).all()
        slices = [row for row in slices if set(row.dimensions) == {"country"}]
        facts = [DailyMetric(
            entity_id=row.entity_id, day=row.day, source=row.source,
            currency=row.metrics["currency"], timezone=row.metrics["timezone"],
            observed_at=row.observed_at, raw=row.metrics, **{
                name: decimal_value(row.metrics.get(name), count=name not in ("spend", "revenue"))
                for name in ("spend", "revenue", "impressions", "clicks", "conversions", "leads", "sales")
            },
        ) for row in slices]
        trackers = {}
    for metric in facts:
        ad, entity = ads[metric.entity_id], entities[metric.entity_id]
        account = accounts[entity.account_id]
        if account.id not in readable_ids:
            continue
        adset = adsets.get(ad.adset_id)
        chain = {"account": account.id, "campaign": adset.campaign_id if adset else None, "adset": ad.adset_id, "ad": ad.entity_id, "creative": ad.creative_id}
        if metric.source != account.provider:
            continue
        if any(getattr(filters, name) and getattr(filters, name) not in (value, (account_map if name == "account" else entity_map).get(value, value)) for name, value in chain.items()):
            continue
        if any(getattr(filters, name) and entity.labels.get(name) != getattr(filters, name) for name in ("buyer", "offer", "tracker_campaign")):
            continue
        selected = chain[level]
        if selected is None:
            continue
        state = states.get(selected)
        selected_status = accounts[selected].labels.get("status") if level == "account" else state.status if state else None
        if filters.status and selected_status != filters.status:
            continue
        key = (selected, metric.currency, metric.timezone)
        groups.setdefault(key, []).append((metric, trackers.get((metric.entity_id, metric.day))))
    result = []
    direct = {(r.entity_id, r.day): r for r in session.scalars(select(DailyMetric).where(
        DailyMetric.entity_id.in_(entity_scope), DailyMetric.source.in_({a.provider for a in accounts.values()}),
        DailyMetric.day >= filters.start, DailyMetric.day <= filters.end,
    ))} if include_daily and not filters.geo else {}
    for (selected, currency, zone), rows in groups.items():
        subject = accounts[selected] if level == "account" else entities[selected]
        state = states.get(selected)
        item = {
            "id": (account_map if level == "account" else entity_map).get(selected, selected), "external_id": subject.external_id, "name": subject.name or subject.external_id,
            "level": level, "currency": currency, "timezone": zone,
            "account_id": account_map.get(subject.id if level == "account" else subject.account_id, subject.id if level == "account" else subject.account_id),
            "source_provider": source_by_account[subject.id if level == "account" else subject.account_id]["provider"],
            "data_status": "available", "has_facts": True,
            "source_attribution": next((pair[0].raw.get("_provider",{}).get("attribution") for pair in rows if pair[0].raw), None),
            "source_mode": source_by_account[subject.id if level == "account" else subject.account_id]["mode"],
            "source_stale": source_by_account[subject.id if level == "account" else subject.account_id]["stale"],
            "oldest_observation": min(aware(observation.observed_at) for pair in rows for observation in pair if observation is not None).isoformat(),
            "status": subject.labels.get("status") if level == "account" else state.status if state else None, "budget": str(state.budget) if state and state.budget is not None else None,
            "bid": str(state.bid) if state and state.bid is not None else None,
            "media_url": creatives[selected].media_url if level == "creative" and selected in creatives else None,
            **aggregate(rows, currency, zone, exact_ratios=exact_ratios),
            **{target: sum(getattr(pair[0], field) for pair in rows) if all(getattr(pair[0], field) is not None for pair in rows) else None
               for target, field in (("meta_leads", "leads"), ("meta_purchases", "sales"), ("meta_conversions", "conversions"))},
            **{target: sum(getattr(pair[1], field) for pair in rows) if all(pair[1] is not None and pair[1].currency == currency and pair[1].timezone == zone and getattr(pair[1], field) is not None for pair in rows) else None
               for target, field in (("tracker_leads", "leads"), ("tracker_sales", "sales"), ("tracker_conversions", "conversions"))},
        }
        if include_daily:
            by_day = {}
            for pair in rows:
                by_day.setdefault(pair[0].day, []).append(pair)
            item["daily"] = []
            for day, pairs in sorted(by_day.items()):
                totals = aggregate(pairs, currency, zone, exact_ratios=True)
                # Reach is unique audience size; summing reaches or averaging
                # frequency across ads gives a different population.
                source = direct.get((selected, day))
                frequency_source = "entity_daily"
                if source is None and len(pairs) == 1:
                    source = pairs[0][0]
                    frequency_source = "single_ad"
                frequency, reach, frequency_at = None, None, None
                if source and source.currency == currency and source.timezone == zone and source.impressions == totals["impressions"]:
                    frequency = source.frequency
                    reach = source.reach
                    if frequency is None and source.impressions is not None and reach:
                        frequency = Decimal(source.impressions) / Decimal(reach)
                    if frequency is not None:
                        frequency_at = aware(source.observed_at).isoformat()
                item["daily"].append({"date": day.isoformat(), **totals,
                    "frequency": str(frequency) if frequency is not None else None,
                    "frequency_source": frequency_source if frequency is not None else None,
                    "frequency_observed_at": frequency_at, "reach": reach,
                    "ad_ids": sorted(pair[0].entity_id for pair in pairs),
                    "oldest_observation": min(aware(observation.observed_at) for pair in pairs for observation in pair if observation is not None).isoformat()})
        result.append(item)
    # Catalog LEFT JOIN equivalent: identity exists independently of facts.
    if level == "account" and not any(getattr(filters, key) for key in (
        "campaign", "adset", "ad", "creative", "geo", "buyer", "offer", "tracker_campaign"
    )):
        present = {row["account_id"] for row in result}
        for account in accounts.values():
            canonical = account_map.get(account.id, account.id)
            status = (account.labels or {}).get("status")
            if canonical in present or (filters.account and filters.account not in (account.id, canonical)) or (filters.status and filters.status != status):
                continue
            source = source_by_account[account.id]
            result.append({
                "id": canonical, "account_id": canonical, "external_id": account.external_id,
                "name": account.name or account.external_id, "level": "account",
                "currency": account.currency, "timezone": account.timezone, "status": status,
                "source_provider": source["provider"], "source_mode": source["mode"],
                "source_stale": source["stale"], "source_attribution": None,
                "data_status": source["coverage"], "has_facts": False,
                "oldest_observation": None, "budget": None, "bid": None, "media_url": None,
                **aggregate([], account.currency, account.timezone, exact_ratios=exact_ratios),
                **({"daily": []} if include_daily else {}),
            })
    result.sort(key=lambda row: (row["name"], row["id"], row["currency"], row["timezone"]))
    if sort_key:
        from services.preferences.registry import sort_rows
        result = sort_rows(result, sort_key, sort_direction, level)
    return {"rows": result[offset:offset + limit], "total": len(result), "next_offset": offset + limit if len(result) > offset + limit else None, "sources": list(routes.values())}


def filter_options(session, workspace: str):
    from services.providers.router import DataSourceRouter
    from services.providers.matching import identity_maps
    from services.sync.engine import utc_now
    today=utc_now().date()
    routes=DataSourceRouter(session,workspace).resolve(today,today)
    account_map,entity_map=identity_maps(session,workspace)
    accounts = session.scalars(select(AdAccount).where(AdAccount.workspace_id == workspace, AdAccount.id.in_([r["account_id"] for r in routes.values()]))).all()
    entities = session.scalars(select(Entity).where(Entity.account_id.in_([r.id for r in accounts]))).all() if accounts else []
    options = {"account": [{"id": account_map.get(r.id,r.id), "name": r.name or r.external_id} for r in accounts]}
    for kind in ("campaign", "adset", "ad", "creative"):
        options[kind] = [{"id": entity_map.get(r.id,r.id), "name": r.name or r.external_id} for r in entities if r.kind == kind]
    for label in ("buyer", "offer", "tracker_campaign"):
        options[label] = [{"id": value, "name": value} for value in sorted({r.labels[label] for r in entities if r.labels and r.labels.get(label)})]
    slices = session.scalars(select(Breakdown).where(Breakdown.entity_id.in_([r.id for r in entities]))).all() if entities else []
    countries = sorted({r.dimensions["country"] for r in slices if set(r.dimensions) == {"country"}})
    options["geo"] = [{"id": country, "name": country} for country in countries]
    return {"options": options, "unavailable": {} if countries else {"geo": "Нужно подключить загрузку breakdowns"}}
