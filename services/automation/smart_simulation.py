"""Bounded database-only EconomicsAdapter and immutable DRY RUN execution."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal as D
from time import monotonic
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from services.analytics.table import Filters
from services.automation.smart_core import decision
from services.automation.smart_models import RuleSimulation
from services.automation.smart_schema import SmartRuleInput, period
from services.automation.smart_store import audit, get_rule, require_editor
from services.economics.core import Evidence, calculate
from services.economics.evaluation import chain_for, evaluate, select_profile
from services.economics.models import EconomicsEvaluation, EconomicsProfile
from services.economics.schema import ProfileInput
from services.economics.store import lock, utcnow
from services.providers.matching import identity_maps
from services.storage.models import AdAccount, Entity, EntityCurrentState

MAX_ADS = 500
MAX_SECONDS = 10


def economics_adapter(
    s: Session, workspace: str, config: SmartRuleInput, now: datetime
) -> dict[str, Any]:
    """Read routed Phase 2 facts and provenance, without constructing a provider."""
    first, last = period(config, now)
    count = (
        s.scalar(
            select(func.count())
            .select_from(Entity)
            .join(AdAccount)
            .where(AdAccount.workspace_id == workspace, Entity.kind == "ad")
        )
        or 0
    )
    if count > 2000:
        raise HTTPException(422, "SIMULATION_CATALOG_TOO_LARGE")
    selected = config.selection
    table = evaluate(
        s,
        workspace,
        Filters(
            first,
            last,
            campaign=selected.campaign,
            adset=selected.adset,
            ad=selected.ad,
            status=selected.status,
            offer=selected.offer,
            geo=selected.geo,
        ),
        level="ad",
        selected=config.profile_id,
        now=now,
        limit=2000,
    )
    sources = {r["canonical_id"]: r for r in table["sources"]}
    account_map, entity_map = identity_maps(s, workspace)
    seen = {r["id"] for r in table["rows"]}
    # Missing statistics remain visible for real catalog ads without invented zeros.
    catalog = s.execute(
        select(Entity, AdAccount)
        .join(AdAccount)
        .where(AdAccount.workspace_id == workspace, Entity.kind == "ad")
    ).all()
    for entity, account in catalog:
        canonical = account_map.get(account.id, account.id)
        source = sources.get(canonical, {})
        ad_id = entity_map.get(entity.id, entity.id)
        if source.get("account_id") != account.id or ad_id in seen:
            continue
        if selected.account_ids and canonical not in selected.account_ids:
            continue
        if selected.provider and selected.provider != source.get("provider"):
            continue
        chain = chain_for(
            s, {"id": entity.id, "account_id": canonical}, "ad", workspace
        )
        context = {**dict(chain), "ad": ad_id}
        if any(
            getattr(selected, k) and getattr(selected, k) != context.get(k)
            for k in ("campaign", "adset", "ad")
        ):
            continue
        state = s.get(EntityCurrentState, entity.id)
        if selected.status and (not state or state.status != selected.status):
            continue
        if selected.geo or (
            selected.offer and (entity.labels or {}).get("offer") != selected.offer
        ):
            continue
        p, assigned = select_profile(
            s,
            workspace,
            chain,
            first,
            last,
            config.profile_id,
            selected.offer,
            selected.geo,
        )
        values = (
            calculate(
                ProfileInput.model_validate(p.payload), Evidence(None, None, None)
            )
            if p
            else {}
        )
        table["rows"].append(
            {
                **values,
                "id": ad_id,
                "external_id": entity.external_id,
                "name": entity.name or entity.external_id,
                "account_id": canonical,
                "currency": account.currency,
                "timezone": account.timezone,
                "source_provider": account.provider,
                "source_stale": source.get("stale", True),
                "source_attribution": None,
                "spend": None,
                "leads": None,
                "observed_meta_purchases": None,
                "status": state.status if state else None,
                "profile_id": p.id if p else None,
                "profile_version": p.version if p else None,
                "profile_name": p.payload["name"] if p else None,
                "profile_currency": p.payload["currency"] if p else None,
                "period_start": first.isoformat(),
                "period_end": last.isoformat(),
                "eligible_for_rule_evaluation": False,
                "reason_codes": ["UNKNOWN_FACTS", assigned],
                "has_facts": False,
            }
        )
        seen.add(ad_id)
    rows = []
    for base in table["rows"]:
        if selected.account_ids and base["account_id"] not in selected.account_ids:
            continue
        if selected.provider and base.get("source_provider") != selected.provider:
            continue
        source = sources.get(base["account_id"], {})
        row = {k: v for k, v in base.items() if k != "daily"}
        row["ad_status"] = row.get("status")
        row["window_complete"] = bool(
            source.get("window_status") == "complete"
            and source.get("facts_readable")
            and last < now.astimezone(ZoneInfo(row["timezone"])).date()
        )
        row["credential_revision"] = source.get("credential_revision")
        row["source_facts_timestamp"] = source.get("source_timestamp") or row.get(
            "oldest_observation"
        )
        row["account_name"] = source.get("account_name") or row["account_id"]
        row["source_window_status"] = source.get("window_status", "missing")
        row["campaign"] = row["adset"] = None
        for kind, key in chain_for(s, row, "ad", workspace):
            if kind in ("campaign", "adset"):
                row[kind] = key
        snap = (
            s.get(EconomicsEvaluation, row.get("evaluation_id"))
            if row.get("evaluation_id")
            else None
        )
        row["economics_inputs"] = snap.payload["inputs"] if snap else None
        rows.append(row)
    if len(rows) > MAX_ADS:
        raise HTTPException(422, "SIMULATION_TOO_MANY_ADS_SELECT_SCOPE")
    table["rows"] = rows
    table["start"], table["end"] = first.isoformat(), last.isoformat()
    table["total"] = len(rows)
    return table


def simulation_json(row: RuleSimulation, *, summary: bool = False) -> dict[str, Any]:
    payload = {k: v for k, v in row.payload.items() if not summary or k != "rows"}
    return {
        "id": row.id,
        "rule_id": row.rule_id,
        "rule_revision": row.revision,
        "actor_id": row.actor_id,
        "created_at": row.created_at.isoformat(),
        **payload,
    }


def simulate(
    s: Session,
    actor: dict[str, Any],
    key: str,
    revision: int,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    started = monotonic()
    if s.bind is not None and s.bind.dialect.name == "postgresql":
        s.execute(text("SET LOCAL statement_timeout = '10s'"))
        s.execute(text("SET LOCAL lock_timeout = '2s'"))
    lock(s, actor["workspace"])
    require_editor(s, actor)
    row = get_rule(s, actor["workspace"], key)
    if row.revision != revision:
        raise HTTPException(409, "RULE_VERSION_CONFLICT")
    if row.status == "SMART_ARCHIVED":
        raise HTTPException(409, "RULE_ARCHIVED")
    now = now or utcnow()
    config = SmartRuleInput.model_validate(row.payload)
    today = now.astimezone(ZoneInfo("Europe/Moscow")).date()
    if (config.effective_start and today < config.effective_start) or (
        config.effective_end and today > config.effective_end
    ):
        raise HTTPException(409, "RULE_OUTSIDE_EFFECTIVE_DATES")
    data = economics_adapter(s, actor["workspace"], config, now)
    previous = s.scalar(
        select(RuleSimulation)
        .where(
            RuleSimulation.workspace_id == actor["workspace"],
            RuleSimulation.rule_id == key,
        )
        .order_by(RuleSimulation.created_at.desc())
        .limit(1)
    )
    old = (
        {r["id"]: r for r in previous.payload["rows"]}
        if previous
        and previous.payload.get("start") == data["start"]
        and previous.payload.get("end") == data["end"]
        else {}
    )
    output = []
    for fact in data["rows"]:
        if monotonic() - started > MAX_SECONDS:
            raise HTTPException(422, "SIMULATION_TIME_LIMIT_SELECT_SCOPE")
        profile = (
            s.get(EconomicsProfile, fact["profile_id"])
            if fact.get("profile_id")
            else None
        )
        assessed = {
            **fact,
            **decision(config, fact, profile.payload if profile else {}, now),
        }
        changes = {}
        for metric in (
            "leads",
            "observed_meta_purchases",
            "approved_sales",
            "rejected_sales",
            "pending_sales",
            "actual_cpl",
            "estimated_roi",
            "actual_roi",
            "applied_approval_rate",
            "profile_version",
            "status",
        ):
            before = old.get(fact["id"], {}).get(metric)
            after = assessed.get(metric)
            if fact["id"] in old and before != after:
                changes[metric] = {
                    "before": before,
                    "after": after,
                    "delta": str(D(str(after)) - D(str(before)))
                    if before is not None and after is not None and metric != "status"
                    else None,
                }
        assessed["changes_since_previous"] = changes
        output.append(assessed)
    record = RuleSimulation(
        id=str(uuid4()),
        workspace_id=actor["workspace"],
        rule_id=key,
        revision=row.revision,
        actor_id=actor["id"],
        created_at=now,
        payload={
            "mode": "DRY_RUN",
            "status": "COMPLETED",
            "action_eligibility": False,
            "start": data["start"],
            "end": data["end"],
            "reporting_timezone": "Europe/Moscow",
            "definition": row.payload,
            "sources": data["sources"],
            "rows": output,
            "counts": dict(Counter(r["status"] for r in output)),
            "total": len(output),
            "missing_profiles": sum(not r.get("profile_id") for r in output),
            "previous_simulation_id": previous.id if previous else None,
        },
    )
    s.add(record)
    audit(
        s,
        actor,
        key,
        "SIMULATE",
        {
            "simulation_id": record.id,
            "revision": row.revision,
            "total": len(output),
            "mode": "DRY_RUN",
        },
    )
    s.flush()
    return simulation_json(record)
