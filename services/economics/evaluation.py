"""Financial evaluations over existing routed facts; never modifies ad statistics."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal as D
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.analytics.table import Filters, table_data
from services.economics.core import Evidence, calculate, serial
from services.economics.models import (
    ApprovalObservation,
    EconomicsAssignment,
    EconomicsEvaluation,
    EconomicsProfile,
)
from services.economics.schema import ProfileInput
from services.economics.store import profile_row, utcnow
from services.preferences.registry import sort_rows
from services.providers.matching import identity_maps
from services.storage.models import Ad, AdSet, Entity
from services.sync.engine import aware


def chain_for(
    session: Session, row: dict[str, Any], level: str, workspace: str
) -> list[tuple[str, str]]:
    """Use real hierarchy and canonical IDs, never infer parents from names."""
    chain = [("profile", ""), ("account", row["account_id"])]
    if level == "account":
        return chain
    entity = session.get(Entity, row["id"])
    _account_map, entity_map = identity_maps(session, workspace)
    if entity is None:
        return chain + [(level, row["id"])]
    campaign = None
    adset = None
    if level == "ad":
        ad = session.get(Ad, entity.id)
        adset = session.get(AdSet, ad.adset_id) if ad and ad.adset_id else None
    elif level == "adset":
        adset = session.get(AdSet, entity.id)
    if adset:
        campaign = adset.campaign_id
    elif level == "campaign":
        campaign = entity.id
    if campaign:
        chain.append(("campaign", entity_map.get(campaign, campaign)))
    if adset:
        chain.append(("adset", entity_map.get(adset.entity_id, adset.entity_id)))
    if level == "ad":
        chain.append(("ad", row["id"]))
    return list(dict.fromkeys(chain))


def observations(
    session: Session,
    profile: EconomicsProfile,
    chain: list[tuple[str, str]],
    start: date,
    end: date,
) -> tuple[list[ApprovalObservation], bool, list[str]]:
    candidates = session.scalars(
        select(ApprovalObservation).where(
            ApprovalObservation.workspace_id == profile.workspace_id,
            ApprovalObservation.profile_id == profile.id,
            ApprovalObservation.start_day <= end,
            ApprovalObservation.end_day >= start,
        )
    ).all()
    for scope in reversed(chain):
        rows = [x for x in candidates if (x.scope_type, x.scope_id) == scope]
        if not rows:
            continue
        inherited = scope != chain[-1]
        if any(x.start_day < start or x.end_day > end for x in rows):
            return [], inherited, ["OBSERVATION_WINDOW_MISMATCH"]
        rows.sort(key=lambda x: x.start_day)
        cursor = start
        for row in rows:
            if row.start_day != cursor:
                return rows, inherited, ["OBSERVATION_COVERAGE_INCOMPLETE"]
            cursor = row.end_day + timedelta(days=1)
        if cursor != end + timedelta(days=1):
            return rows, inherited, ["OBSERVATION_COVERAGE_INCOMPLETE"]
        return rows, inherited, []
    return [], False, ["APPROVAL_UNKNOWN"]


def row_evidence(
    row: dict[str, Any],
    config: ProfileInput,
    obs: list[ApprovalObservation],
    inherited: bool,
    start: date,
    end: date,
    now: datetime,
    problems: list[str],
) -> Evidence:
    leads = row.get("meta_leads" if config.lead_source == "meta" else "tracker_leads")
    spend = (
        D(row["spend"])
        if row.get("spend") is not None and row["currency"] == config.currency
        else None
    )
    reasons = list(problems)
    if row["currency"] != config.currency:
        reasons.append("CURRENCY_MISMATCH")
    mature = now >= datetime.combine(
        end + timedelta(days=1), time.min, tzinfo=ZoneInfo(row["timezone"])
    ) + timedelta(hours=config.maturation_hours)
    if row.get("source_stale"):
        reasons.append("SOURCE_STALE")
    fact_source = row.get("source_provider", "unknown")
    facts = Evidence(
        spend,
        leads,
        row.get("meta_purchases"),
        mature=mature,
        facts_source=fact_source,
        reason_codes=tuple(reasons),
    )
    if not obs:
        return facts
    payloads = [x.payload for x in obs]
    approved = sum(x["approved"] for x in payloads)
    rejected = sum(x["rejected"] for x in payloads)
    pending = sum(x["pending"] for x in payloads)
    matching = all(
        x["currency"] == config.currency
        and x["timezone"] == row["timezone"]
        and x["source_provider"] == fact_source
        and x.get("lead_source", "meta") == config.lead_source
        for x in payloads
    )
    if not matching:
        reasons.append("OBSERVATION_SOURCE_MISMATCH")
    cohort_match = (
        not inherited and leads is not None and approved + rejected + pending == leads
    )
    if not cohort_match and not inherited:
        reasons.append("COHORT_BASE_MISMATCH")
    attribution = all(x["attribution_confirmed"] for x in payloads)
    if not attribution and not inherited:
        reasons.append("ATTRIBUTION_UNCONFIRMED")
    if inherited:
        reasons.append("INHERITED_GROUP_ESTIMATE")
    actual_compatible = bool(
        matching and cohort_match and attribution and not problems and not inherited
    )
    revenue_confirmed = all(x["revenue_confirmed"] for x in payloads)
    actual_revenue = (
        sum(
            (
                D(x["actual_revenue"])
                if x.get("actual_revenue") is not None
                else D(x["payout"]) * x["approved"]
                for x in payloads
            ),
            D(0),
        )
        if actual_compatible and revenue_confirmed
        else None
    )
    if not revenue_confirmed:
        reasons.append("REVENUE_NOT_CONFIRMED")
    processed = approved + rejected
    observed = D(approved) / D(processed) if processed else None
    usable = matching and not problems and (inherited or (cohort_match and attribution))
    return replace(
        facts,
        approved=approved,
        rejected=rejected,
        pending=pending,
        actual_revenue=actual_revenue,
        compatible=actual_compatible,
        mature=mature and pending == 0,
        inherited=inherited,
        observed_rate=observed if usable else None,
        processed=processed,
        source="ACTUAL_MANUAL",
        reason_codes=tuple(reasons),
    )


def select_profile(
    session: Session,
    workspace: str,
    chain: list[tuple[str, str]],
    start: date,
    end: date,
    selected: str | None,
    offer: str | None,
    geo: str | None,
) -> tuple[EconomicsProfile | None, str]:
    if selected:
        return profile_row(session, workspace, selected), "SELECTED_PREVIEW"
    assignments = session.scalars(
        select(EconomicsAssignment).where(
            EconomicsAssignment.workspace_id == workspace,
            EconomicsAssignment.effective_start <= end,
        )
    ).all()
    for scope in reversed(chain):
        matches = [
            a
            for a in assignments
            if (a.scope_type, a.scope_id) == scope
            and a.effective_start <= start
            and (a.effective_end is None or a.effective_end >= end)
        ]
        profiles = []
        for assignment in matches:
            p = profile_row(session, workspace, assignment.profile_id, deleted=True)
            if p.deleted:
                continue
            if scope[0] == "profile" and (
                p.payload["offer"] != (offer or "") or p.payload["geo"] != (geo or "")
            ):
                continue
            profiles.append(p)
        if len(profiles) == 1:
            return profiles[0], scope[0]
        if len(profiles) > 1:
            return None, "AMBIGUOUS_ASSIGNMENT"
    return None, "NO_PROFILE_ASSIGNED"


def snapshot(
    session: Session,
    profile: EconomicsProfile,
    row: dict[str, Any],
    obs: list[ApprovalObservation],
    start: date,
    end: date,
    selection: dict[str, Any],
) -> dict[str, Any]:
    """Freeze all inputs and detect revisions without summing overlapping snapshots."""
    facts = {
        k: row.get(k)
        for k in (
            "spend",
            "meta_leads",
            "meta_purchases",
            "meta_conversions",
            "tracker_leads",
            "tracker_sales",
            "source_provider",
            "source_attribution",
            "currency",
            "timezone",
        )
    }
    inputs = {
        "profile_id": profile.id,
        "profile_version": profile.version,
        "profile": profile.payload,
        "observations": [
            {"id": o.id, "version": o.version, "payload": o.payload} for o in obs
        ],
        "facts": facts,
        "selection": selection,
        "assessment": {
            key: row.get(key)
            for key in (
                "maturity_status",
                "economics_status",
                "source_stale",
                "reason_codes",
            )
        },
    }
    digest = hashlib.sha256(
        json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    query = select(EconomicsEvaluation).where(
        EconomicsEvaluation.workspace_id == profile.workspace_id,
        EconomicsEvaluation.profile_id == profile.id,
        EconomicsEvaluation.entity_id == row["id"],
        EconomicsEvaluation.start_day == start,
        EconomicsEvaluation.end_day == end,
    )
    previous = session.scalar(
        query.order_by(EconomicsEvaluation.created_at.desc()).limit(1)
    )
    changes = {}
    if previous:
        for field in ("meta_leads", "meta_purchases", "tracker_leads", "tracker_sales"):
            old = previous.payload["inputs"]["facts"].get(field)
            new = facts.get(field)
            if old is not None and new is not None and old != new:
                changes[field] = {"before": old, "after": new, "delta": new - old}
    existing = session.scalar(query.where(EconomicsEvaluation.digest == digest))
    if existing is None:
        existing = EconomicsEvaluation(
            id=str(uuid4()),
            workspace_id=profile.workspace_id,
            profile_id=profile.id,
            entity_id=row["id"],
            start_day=start,
            end_day=end,
            digest=digest,
            payload={
                "inputs": inputs,
                "result": {k: v for k, v in row.items() if k != "daily"},
                "event_changes": changes,
            },
            created_at=utcnow(),
        )
        session.add(existing)
        session.flush()
    return {
        "evaluation_id": existing.id,
        "evaluation_at": existing.created_at.isoformat(),
        "event_changes": changes or existing.payload.get("event_changes", {}),
        "profile_version": profile.version,
        "profile_id": profile.id,
        "profile_name": profile.payload["name"],
    }


def evaluate(
    session: Session,
    workspace: str,
    filters: Filters,
    *,
    level: str = "account",
    selected: str | None = None,
    now: datetime | None = None,
    offset: int = 0,
    limit: int = 100,
    sort_key: str | None = None,
    sort_direction: str = "asc",
) -> dict[str, Any]:
    now = now or utcnow()
    table = table_data(
        session, workspace, filters, level=level, limit=100000, include_daily=True
    )
    output = []
    if selected:
        profile_row(session, workspace, selected)
    for base in table["rows"]:
        chain = chain_for(session, base, level, workspace)
        p, assigned = select_profile(
            session,
            workspace,
            chain,
            filters.start,
            filters.end,
            selected,
            filters.offer,
            filters.geo,
        )
        row = {
            **base,
            "economics_status": "UNKNOWN",
            "economics_data_quality": "UNKNOWN",
            "eligible_for_rule_evaluation": False,
            "reason_codes": [assigned],
            "assignment_source": assigned,
            "actions_enabled": False,
        }
        row["period_start"] = filters.start.isoformat()
        row["period_end"] = filters.end.isoformat()
        row["leads"] = base.get(
            "meta_leads"
            if not p or p.payload.get("lead_source", "meta") == "meta"
            else "tracker_leads"
        )
        row["observed_meta_purchases"] = base.get("meta_purchases")
        if p:
            config = ProfileInput.model_validate(p.payload)
            obs, inherited, problems = observations(
                session, p, chain, filters.start, filters.end
            )
            evidence = row_evidence(
                base, config, obs, inherited, filters.start, filters.end, now, problems
            )
            calculated = calculate(config, evidence)
            calculated.pop("currency", None)
            row.update(calculated)
            row["profile_currency"] = config.currency
            if base["currency"] != config.currency:
                for field in (
                    "payout",
                    "expected_revenue_per_lead",
                    "target_cpl",
                    "maximum_cpl",
                    "target_approved_cps",
                    "maximum_approved_cps",
                    "estimated_revenue",
                    "estimated_roi",
                    "actual_revenue",
                    "actual_roi",
                    "approved_cps",
                    "cpl_deviation",
                ):
                    row[field] = None
                row["economics_status"] = "INCOMPATIBLE"
            row["last_updated"] = max(
                [aware(o.updated_at).isoformat() for o in obs]
                + [row.get("oldest_observation") or ""]
            )
            row["applied_approval_percent"] = serial(
                D(row["applied_approval_rate"]) * 100
            )
            row["planned_approval_percent"] = serial(config.planned_approval_rate * 100)
            row["observed_approval_percent"] = (
                serial(D(row["observed_approval_rate"]) * 100)
                if row.get("observed_approval_rate") is not None
                else None
            )
            row.update(
                {
                    "profile_id": p.id,
                    "profile_version": p.version,
                    "profile_name": p.payload["name"],
                }
            )
            row.update(
                snapshot(
                    session,
                    p,
                    row,
                    obs,
                    filters.start,
                    filters.end,
                    {
                        "level": level,
                        "assignment_source": assigned,
                        "account": filters.account,
                        "campaign": filters.campaign,
                        "adset": filters.adset,
                        "ad": filters.ad,
                        "offer": filters.offer,
                        "geo": filters.geo,
                    },
                )
            )
        row["economics_reasons"] = ", ".join(row["reason_codes"])
        row["late_event_changes"] = (
            json.dumps(row.get("event_changes", {}), ensure_ascii=False)
            if row.get("event_changes")
            else None
        )
        output.append(row)
    if sort_key:
        output = sort_rows(output, sort_key, sort_direction, "eco_" + level)
    total = len(output)
    return {
        "rows": output[offset : offset + limit],
        "total": total,
        "next_offset": offset + limit if offset + limit < total else None,
        "sources": table["sources"],
        "start": filters.start.isoformat(),
        "end": filters.end.isoformat(),
        "calendar_model": "Europe/Moscow dates; account-local calendar days; inclusive",
        "as_of": now.isoformat(),
        "actions_enabled": False,
    }
