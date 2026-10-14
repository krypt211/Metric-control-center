"""Bounded database-only EconomicsAdapter and immutable DRY RUN execution."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal as D
from time import monotonic
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from services.analytics.table import Filters
from services.automation.smart_core import arbitrate, decision, leaves
from services.automation.smart_models import RuleSimulation
from services.automation.smart_schema import SmartRuleInput, period
from services.automation.smart_store import audit, get_rule, require_editor
from services.economics.core import Evidence, calculate
from services.economics.evaluation import chain_for, evaluate, select_profile
from services.economics.models import EconomicsEvaluation, EconomicsProfile
from services.economics.schema import ProfileInput
from services.economics.store import lock, utcnow
from services.providers.matching import identity_maps
from services.storage.models import (
    ActionLog,
    ActionRequest,
    AdAccount,
    Entity,
    EntityCurrentState,
    Rule,
    RuleCooldown,
)

MAX_ADS = 500
MAX_SECONDS = 10


def economics_adapter(
    s: Session,
    workspace: str,
    config: SmartRuleInput,
    now: datetime,
    *,
    _timezone: str | None = None,
) -> dict[str, Any]:
    """Read routed Phase 2 facts and provenance, without constructing a provider."""
    profile = s.get(EconomicsProfile, config.profile_id) if config.profile_id else None
    if not config.profile_id and _timezone is None:
        # Assigned profiles may use different calendars. Reuse the same adapter
        # per bounded zone, retaining only rows whose resolved profile uses it.
        zones = {"Europe/Moscow"} | {
            p.payload.get("timezone", "Europe/Moscow")
            for p in s.scalars(
                select(EconomicsProfile).where(
                    EconomicsProfile.workspace_id == workspace,
                    EconomicsProfile.deleted.is_(False),
                )
            )
        }
        if len(zones) > 8:
            raise HTTPException(422, "SELECT_EXPLICIT_PROFILE_FOR_TIMEZONE_SCOPE")
        if len(zones) > 1:
            groups = []
            for zone in sorted(zones):
                today = now.astimezone(ZoneInfo(zone)).date()
                if (config.effective_start and today < config.effective_start) or (
                    config.effective_end and today > config.effective_end
                ):
                    continue
                group = economics_adapter(s, workspace, config, now, _timezone=zone)
                selected_rows = []
                for row in group["rows"]:
                    p = (
                        s.get(EconomicsProfile, row.get("profile_id"))
                        if row.get("profile_id")
                        else None
                    )
                    if (p.payload if p else {}).get(
                        "timezone", "Europe/Moscow"
                    ) == zone:
                        selected_rows.append(row)
                group["rows"] = selected_rows
                groups.append(group)
            if not groups:
                raise HTTPException(409, "RULE_OUTSIDE_EFFECTIVE_DATES")
            merged = {}
            for group in groups:
                for row in group["rows"]:
                    key = (row["id"], row.get("source_provider"))
                    if key in merged:
                        # Date-dependent assignments resolving different profiles
                        # across calendars are ambiguous, never silently chosen.
                        row["source_stale"] = True
                        row["reason_codes"] = list(row.get("reason_codes", [])) + [
                            "PROFILE_PERIOD_AMBIGUOUS"
                        ]
                    merged[key] = row
            rows = list(merged.values())
            if len(rows) > MAX_ADS:
                raise HTTPException(422, "SIMULATION_TOO_MANY_ADS_SELECT_SCOPE")
            starts = [r["period_start"] for r in rows] or [g["start"] for g in groups]
            ends = [r["period_end"] for r in rows] or [g["end"] for g in groups]
            row_zones = {r["evaluation_timezone"] for r in rows}
            return {
                **groups[0],
                "rows": rows,
                "total": len(rows),
                "start": min(starts),
                "end": max(ends),
                "reporting_timezone": next(iter(row_zones))
                if len(row_zones) == 1
                else "PROFILE_SCOPED",
                "sources": [v for g in groups for v in g["sources"]],
                "target_issues": [
                    v for g in groups for v in g.get("target_issues", [])
                ],
            }
    zone = _timezone or (profile.payload if profile else {}).get(
        "timezone", "Europe/Moscow"
    )
    today = now.astimezone(ZoneInfo(zone)).date()
    if (config.effective_start and today < config.effective_start) or (
        config.effective_end and today > config.effective_end
    ):
        raise HTTPException(409, "RULE_OUTSIDE_EFFECTIVE_DATES")
    first, last = period(config, now, zone)
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
    resolution = None
    if selected.target_mode:
        from services.automation.smart_targets import resolve_targets

        resolution = resolve_targets(
            s,
            workspace,
            selected.targets,
            now.astimezone(ZoneInfo(zone)).date(),
        )
    table = evaluate(
        s,
        workspace,
        Filters(
            first,
            last,
            account=selected.account_ids[0] if len(selected.account_ids) == 1 else None,
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
            s, {"id": entity.id, "account_id": canonical}, "ad", workspace, entity_map
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
        row["evaluation_timezone"] = zone
        if row.get("timezone") != zone:
            row["source_stale"] = True
            row["reason_codes"] = list(row.get("reason_codes", [])) + [
                "PROFILE_SOURCE_TIMEZONE_MISMATCH"
            ]
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
        for kind, key in chain_for(s, row, "ad", workspace, entity_map):
            if kind in ("campaign", "adset"):
                row[kind] = key
        snap = (
            s.get(EconomicsEvaluation, row.get("evaluation_id"))
            if row.get("evaluation_id")
            else None
        )
        row["economics_inputs"] = snap.payload["inputs"] if snap else None
        rows.append(row)
    if resolution is not None:
        selected_rows = []
        seen_targets = set()
        for row in rows:
            key = (row.get("source_provider"), row["account_id"], row["id"])
            origins = resolution["provenance"].get(key)
            if not origins or key in seen_targets:
                continue
            seen_targets.add(key)
            row["target_provenance"] = origins
            selected_rows.append(row)
        for key, origins in resolution["provenance"].items():
            if key not in seen_targets:
                resolution["issues"].append(
                    {"scope_id": key[2], "reason_code": "PROVIDER_UNAVAILABLE"}
                )
        rows = selected_rows
        table["target_issues"] = resolution["issues"] or (
            [] if rows else [{"reason_code": "NO_MATCHING_ADS"}]
        )
    if len(rows) > MAX_ADS:
        raise HTTPException(422, "SIMULATION_TOO_MANY_ADS_SELECT_SCOPE")
    table["rows"] = rows
    table["start"], table["end"] = first.isoformat(), last.isoformat()
    table["reporting_timezone"] = zone
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
    targets: list | None = None,
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
    if targets is not None:
        from services.automation.smart_targets import validated_targets

        config.selection.target_mode = True
        config.selection.targets = validated_targets(s, actor, targets)
        config.selection.account_ids = []
        config.selection.campaign = config.selection.adset = config.selection.ad = None
        config.selection.provider = None
    profile = s.get(EconomicsProfile, config.profile_id) if config.profile_id else None
    zone = (profile.payload if profile else {}).get("timezone", "Europe/Moscow")
    today = now.astimezone(ZoneInfo(zone)).date()
    if config.profile_id and (
        (config.effective_start and today < config.effective_start)
        or (config.effective_end and today > config.effective_end)
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
    assessed_rows = assess_scope(s, actor["workspace"], row, config, data, now)
    output = []
    for fact in assessed_rows:
        if monotonic() - started > MAX_SECONDS:
            raise HTTPException(422, "SIMULATION_TIME_LIMIT_SELECT_SCOPE")
        profile = (
            s.get(EconomicsProfile, fact["profile_id"])
            if fact.get("profile_id")
            else None
        )
        assessed = fact
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
            "reporting_timezone": data.get("reporting_timezone", zone),
            "definition": config.model_dump(mode="json"),
            "sources": data["sources"],
            "target_issues": data.get("target_issues", []),
            "rows": output,
            "counts": dict(Counter(r["status"] for r in output)),
            "total": len(output),
            "missing_profiles": sum(not r.get("profile_id") for r in output),
            "previous_simulation_id": previous.id if previous else None,
        },
    )
    s.add(record)
    record_decisions(s, actor, row, config, record, output, now)
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


def profile_zone(s: Session, config: SmartRuleInput) -> str:
    profile = s.get(EconomicsProfile, config.profile_id) if config.profile_id else None
    return (profile.payload if profile else {}).get("timezone", "Europe/Moscow")


def action_context(
    s: Session, workspace: str, fact: dict, rule_id: str, now: datetime
) -> dict:
    """Only durable READ/verified ActionLog evidence; a simulation never proves ownership."""
    from services.actions.manual import IN_FLIGHT, snapshot
    from services.providers.models import ProviderAccountMapping
    from services.sync.engine import aware

    candidates = s.scalars(
        select(Entity)
        .join(AdAccount)
        .outerjoin(
            ProviderAccountMapping, ProviderAccountMapping.account_id == AdAccount.id
        )
        .where(
            AdAccount.workspace_id == workspace,
            Entity.kind == "ad",
            Entity.external_id == fact.get("external_id"),
            AdAccount.provider == fact.get("source_provider"),
            func.coalesce(ProviderAccountMapping.canonical_id, AdAccount.id)
            == fact.get("account_id"),
        )
    ).all()
    if len(candidates) != 1:
        return {
            "source_entity_id": None,
            "parents_active": False,
            "paused_by_system": False,
        }
    entity = candidates[0]
    captured = snapshot(s, entity, s.get(AdAccount, entity.account_id))
    from services.storage.models import Ad, AdSet

    ad = s.get(Ad, entity.id)
    aset = s.get(AdSet, ad.adset_id) if ad and ad.adset_id else None
    parents = [
        s.get(EntityCurrentState, key)
        for key in (ad.adset_id if ad else None, aset.campaign_id if aset else None)
        if key
    ]
    parents_active = len(parents) == 2 and all(
        p
        and p.status == "ACTIVE"
        and timedelta(0) <= now - aware(p.observed_at) <= timedelta(minutes=15)
        for p in parents
    )
    last = s.scalar(
        select(ActionRequest)
        .where(
            ActionRequest.workspace_id == workspace,
            ActionRequest.entity_id == entity.id,
            ActionRequest.status.in_(("succeeded", "SUCCEEDED")),
        )
        .order_by(ActionRequest.created_at.desc(), ActionRequest.id)
        .limit(1)
    )
    verified = (
        s.scalar(
            select(ActionLog)
            .where(ActionLog.request_id == last.id, ActionLog.event == "verified")
            .order_by(ActionLog.created_at.desc())
            .limit(1)
        )
        if last
        else None
    )
    unresolved = bool(
        s.scalar(
            select(ActionRequest.id)
            .where(
                ActionRequest.workspace_id == workspace,
                ActionRequest.entity_id == entity.id,
                ActionRequest.status.in_(IN_FLIGHT),
            )
            .limit(1)
        )
    )
    ownership = bool(
        last
        and last.action in ("pause", "PAUSE_AD")
        and verified
        and verified.details.get("observed_status") == "PAUSED"
    )
    states = s.scalars(
        select(RuleCooldown)
        .join(Rule, Rule.id == RuleCooldown.rule_id)
        .where(Rule.workspace_id == workspace, RuleCooldown.entity_id == entity.id)
    ).all()
    controls = next(
        (dict(v.smart_state or {}) for v in states if v.rule_id == rule_id), {}
    )
    return {
        "source_entity_id": entity.id,
        "ad_status": captured["status"],
        "manual_blocked": any(
            (v.smart_state or {}).get("manual_blocked") is True for v in states
        ),
        "reenable_allowed": controls.get("reenable_allowed") is True,
        "control_revision": controls.get("control_revision", 0),
        "paused_by_system": ownership,
        "verified_pause_at": aware(verified.created_at).isoformat()
        if ownership
        else None,
        "unresolved_action": unresolved,
        "parents_active": parents_active,
        "status_fresh": bool(
            captured["status_refreshed_at"]
            and timedelta(0)
            <= now - datetime.fromisoformat(captured["status_refreshed_at"])
            <= timedelta(minutes=15)
        ),
    }


def assess_rule(
    s: Session,
    workspace: str,
    rule: Rule,
    config: SmartRuleInput,
    data: dict,
    now: datetime,
) -> list[dict]:
    from services.sync.engine import aware

    result = []
    for fact in data["rows"]:
        context = action_context(s, workspace, fact, rule.id, now)
        profile = (
            s.get(EconomicsProfile, fact.get("profile_id"))
            if fact.get("profile_id")
            else None
        )
        assessment = {
            **fact,
            **context,
            **decision(
                config, {**fact, **context}, profile.payload if profile else {}, now
            ),
            "rule_id": rule.id,
            "rule_revision": rule.revision,
        }
        assessment["pause_condition_active"] = (
            config.action == "PAUSE_AD" and assessment["status"] == "WOULD_PAUSE"
        )
        # Old PAUSE-only dry runs remain readable, but concrete preparation checks
        # status, ownership, parent evidence and current rule conflicts again.
        if assessment["status"] in ("WOULD_PAUSE", "WOULD_ENABLE"):
            hold = None
            if context.get("manual_blocked"):
                hold = "MANUAL_OVERRIDE"
            elif context.get("unresolved_action"):
                hold = "ACTION_OUTCOME_UNRESOLVED"
            elif context.get("ad_status") not in (
                "ACTIVE",
                "PAUSED",
            ) or not context.get("status_fresh"):
                hold = "AD_STATE_UNVERIFIED"
            elif config.action == "PAUSE_AD" and context.get("ad_status") == "PAUSED":
                assessment["status"] = "KEEP"
                assessment["reason_codes"] = sorted(
                    set(assessment["reason_codes"] + ["ALREADY_PAUSED"])
                )
            if context.get("source_entity_id"):
                previous = s.scalars(
                    select(ActionRequest).where(
                        ActionRequest.workspace_id == workspace,
                        ActionRequest.entity_id == context["source_entity_id"],
                        ActionRequest.status.notin_(
                            ("CANCELLED", "EXPIRED", "FAILED", "failed")
                        ),
                        ActionRequest.created_at > now - timedelta(days=7),
                    )
                ).all()
                if any(
                    r.action
                    in (
                        {"ENABLE_AD", "enable"}
                        if config.action == "PAUSE_AD"
                        else {"PAUSE_AD", "pause"}
                    )
                    and (now - aware(r.created_at)).total_seconds()
                    < max(
                        config.cooldown_seconds,
                        (r.provenance.get("rule_source") or {}).get(
                            "cooldown_seconds", 3600
                        ),
                    )
                    for r in previous
                ):
                    hold = "ANTI_LOOP_COOLDOWN"
            if hold:
                assessment["status"] = "REVIEW"
                assessment["reason_codes"] = sorted(
                    set(assessment["reason_codes"] + [hold])
                )
                assessment["safe_to_consider_for_future_action"] = False
        assessment["simulated_decision"] = assessment["status"]
        result.append(assessment)
    return result


def assess_scope(
    s: Session,
    workspace: str,
    rule: Rule,
    config: SmartRuleInput,
    data: dict,
    now: datetime,
) -> list[dict]:
    own = assess_rule(s, workspace, rule, config, data, now)
    grouped = {}
    for item in own:
        grouped.setdefault(item["id"], []).append(item)
    started = None
    peers = s.scalars(
        select(Rule)
        .where(
            Rule.workspace_id == workspace,
            Rule.status == "SMART_DRY_RUN",
            Rule.id != rule.id,
        )
        .order_by(Rule.id)
    ).all()
    for peer in peers:
        cfg = SmartRuleInput.model_validate(peer.payload)
        if not cfg.enabled:
            continue
        today = now.astimezone(ZoneInfo(profile_zone(s, cfg))).date()
        if cfg.profile_id and (
            (cfg.effective_start and today < cfg.effective_start)
            or (cfg.effective_end and today > cfg.effective_end)
        ):
            continue
        if started is None:
            started = monotonic()
        elif monotonic() - started > MAX_SECONDS:
            raise HTTPException(422, "CONFLICT_EVALUATION_TIME_LIMIT")
        try:
            peer_data = economics_adapter(s, workspace, cfg, now)
        except HTTPException as error:
            if error.detail == "RULE_OUTSIDE_EFFECTIVE_DATES":
                continue
            raise
        for item in assess_rule(s, workspace, peer, cfg, peer_data, now):
            if item["id"] in grouped:
                grouped[item["id"]].append(item)
    for values in grouped.values():
        arbitrate(values)
    for item in own:
        fingerprint = {
            "rule": rule.id,
            "revision": rule.revision,
            "entity": item.get("source_entity_id"),
            "start": item.get("period_start", data["start"]),
            "end": item.get("period_end", data["end"]),
            "action": config.action,
            "profile_version": item.get("profile_version"),
            "conditions": item["expression_result"],
            "status": item["status"],
        }
        item["decision_key"] = hashlib.sha256(
            json.dumps(fingerprint, sort_keys=True, default=str).encode()
        ).hexdigest()
    return own


def record_decisions(
    s: Session,
    actor: dict,
    rule: Rule,
    config: SmartRuleInput,
    run: RuleSimulation,
    rows: list[dict],
    now: datetime,
) -> None:
    for card in rows:
        entity_id = card.get("source_entity_id")
        if not entity_id:
            continue
        state = s.get(RuleCooldown, (rule.id, entity_id))
        if not state:
            state = RuleCooldown(
                rule_id=rule.id, entity_id=entity_id, last_queued_at=now, smart_state={}
            )
            s.add(state)
        payload = dict(state.smart_state or {})
        # Notify once per unchanged truth/threshold state; refreshed timestamps or
        # spend drift within the same threshold state do not produce repeat alerts.
        signal = {
            "revision": rule.revision,
            "action": config.action,
            "status": card["status"],
            "reasons": card["reason_codes"],
            "checks": [
                {k: c.get(k) for k in ("type", "truth", "threshold")}
                for c in leaves(card["expression_result"])
            ],
        }
        fingerprint = hashlib.sha256(
            json.dumps(signal, sort_keys=True).encode()
        ).hexdigest()
        if (
            card["status"] == "NOTIFY"
            and payload.get("notification_fingerprint") != fingerprint
        ):
            audit(
                s,
                actor,
                rule.id,
                "NOTIFY",
                {
                    "entity_id": entity_id,
                    "object": card.get("name"),
                    "rule": config.name,
                    "decision": card["status"],
                    "metrics": leaves(card["expression_result"]),
                    "time": now.isoformat(),
                    "channel": "MCC",
                    "simulation_id": run.id,
                    "history_url": "/rules?rule=" + rule.id + "#history",
                },
            )
        payload.update(
            notification_fingerprint=fingerprint,
            last_decision=card["status"],
            last_reason=card["reason_codes"],
            last_evaluated_at=now.isoformat(),
            decision_key=card["decision_key"],
            simulation_id=run.id,
        )
        state.smart_state = payload


def check_preparation(
    s: Session,
    workspace: str,
    run: RuleSimulation,
    entity_id: str,
    operation: str,
    now: datetime,
) -> dict:
    """Recompute current conditions/conflicts locally before entering ActionEngine."""
    rule = get_rule(s, workspace, run.rule_id)
    if rule.revision != run.revision or rule.status == "SMART_ARCHIVED":
        raise HTTPException(409, "RULE_VERSION_CONFLICT")
    config = SmartRuleInput.model_validate(rule.payload)
    today = now.astimezone(ZoneInfo(profile_zone(s, config))).date()
    if config.profile_id and (
        (config.effective_start and today < config.effective_start)
        or (config.effective_end and today > config.effective_end)
    ):
        raise HTTPException(409, "RULE_OUTSIDE_EFFECTIVE_DATES")
    data = economics_adapter(s, workspace, config, now)
    cards = [
        c
        for c in assess_scope(s, workspace, rule, config, data, now)
        if c.get("source_entity_id") == entity_id
    ]
    wanted = "WOULD_ENABLE" if operation == "ENABLE_AD" else "WOULD_PAUSE"
    if len(cards) != 1 or cards[0]["status"] != wanted or config.action != operation:
        raise HTTPException(409, "RULE_CURRENT_DECISION_HELD")
    return cards[0]
