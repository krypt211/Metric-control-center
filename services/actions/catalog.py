"""Entity catalog with routed Phase 2 economics; no external HTTP or persisted facts."""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select

from services.actions.manual import snapshot
from services.analytics.table import Filters
from services.automation.smart_models import RuleSimulation
from services.economics.evaluation import evaluate
from services.providers.matching import identity_maps
from services.storage.models import AdAccount, Entity, Rule


def catalog(
    s, workspace: str, now, account_id: str | None = None, offset: int = 0, q: str = "", campaign: str | None = None, adset: str | None = None, level: str = "ad"
) -> dict:
    if level not in ("campaign", "adset", "ad"):
        raise HTTPException(422, "UNSUPPORTED_ENTITY_LEVEL")
    today = now.astimezone(ZoneInfo("Europe/Moscow")).date()
    first, last = today - timedelta(days=7), today - timedelta(days=1)
    query = (
        select(Entity, AdAccount)
        .join(AdAccount)
        .where(AdAccount.workspace_id == workspace, Entity.kind == level)
    )
    if level != "ad":
        query = query.where(AdAccount.provider == "metricflow")
    if account_id:
        query = query.where(AdAccount.id == account_id)
    count = s.scalar(select(func.count()).select_from(query.subquery())) or 0
    if count > 2000:
        raise HTTPException(422, "SELECT_SMALLER_ACCOUNT_SCOPE")
    accounts, identities = identity_maps(s, workspace)
    economics = evaluate(
        s,
        workspace,
        Filters(first, last, account=accounts.get(account_id, account_id)),
        level=level,
        now=now,
        limit=2000,
        persist_snapshot=False,
    )
    facts = {(r["id"], r.get("source_provider")): r for r in economics["rows"]}
    latest = (
        select(RuleSimulation.id)
        .where(
            RuleSimulation.rule_id == Rule.id, RuleSimulation.workspace_id == workspace
        )
        .order_by(RuleSimulation.created_at.desc(), RuleSimulation.id.desc())
        .limit(1)
        .correlate(Rule)
        .scalar_subquery()
    )
    recs = {}
    for sim in s.scalars(
        select(RuleSimulation)
        .join(Rule, RuleSimulation.id == latest)
        .where(Rule.workspace_id == workspace, Rule.status == "SMART_DRY_RUN")
        .limit(200)
    ):
        for r in sim.payload["rows"]:
            if r["status"] == "WOULD_PAUSE":
                recs[(r["id"], r.get("source_provider"))] = {
                    "simulation_id": sim.id,
                    "rule_revision": sim.revision,
                    "status": r["status"],
                    "reason_codes": r.get("reason_codes", []),
                }
    from services.automation.smart_targets import catalog as target_catalog
    scope = {
        r["source_id"] for r in target_catalog(s, workspace)
        if r["scope_type"] == level.upper()
        and (not campaign or r["campaign_id"] == campaign)
        and (not adset or r["adset_id"] == adset)
        and all(word in f'{r["name"]} {r["external_id"]} {r["id"]}'.casefold() for word in q.casefold().split())
    }
    found = [(e, a) for e, a in s.execute(query.order_by(Entity.name, Entity.id)) if e.id in scope]
    count = len(found)
    output = []
    for entity, account in found[offset:offset+100]:
        captured = snapshot(s, entity, account)
        identity = identities.get(entity.id, entity.id)
        row = facts.get((identity, account.provider), {})
        output.append(
            {
                **captured,
                "id": entity.id,
                "currency": account.currency,
                "timezone": account.timezone,
                "external_id": entity.external_id,
                "spend": row.get("spend"),
                "leads": row.get("leads"),
                "observed_meta_purchases": row.get("observed_meta_purchases"),
                "actual_cpl": row.get("actual_cpl", row.get("cpl")),
                "estimated_roi": row.get("estimated_roi"),
                "actual_roi": row.get("actual_roi"),
                "source_provider": account.provider,
                "last_synced": captured["status_refreshed_at"],
                "recommendation": recs.get((identity, account.provider)) if level == "ad" else None,
                "has_facts": bool(row),
            }
        )
    return {
        "rows": output,
        "total": count,
        "offset": offset,
        "next_offset": offset + 100 if offset + 100 < count else None,
        "start": str(first),
        "end": str(last),
        "timezone": "Europe/Moscow",
    }
