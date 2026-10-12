"""Workspace-local catalog and assignments inside existing immutable rule revisions."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.providers.matching import identity_maps
from services.providers.models import ProviderConnection
from services.storage.models import Ad, AdAccount, AdSet, Campaign, Entity

MAX_TARGETS = 200


def target_key(row: Any) -> tuple[str, str, str, str]:
    value = row.model_dump() if hasattr(row, "model_dump") else row
    return (
        value["provider"],
        value["account_id"],
        value["scope_type"],
        value["scope_id"],
    )


def catalog(s: Session, workspace: str) -> list[dict[str, Any]]:
    """Resolve identifiers and parents from local foreign keys, never names."""
    accounts = {
        a.id: a
        for a in s.scalars(select(AdAccount).where(AdAccount.workspace_id == workspace))
    }
    account_map, entity_map = identity_maps(s, workspace)
    entities = {
        e.id: e
        for e in s.scalars(select(Entity).where(Entity.account_id.in_(accounts)))
    }
    campaigns = set(
        s.scalars(select(Campaign.entity_id).where(Campaign.entity_id.in_(entities)))
    )
    adsets = {
        a.entity_id: a
        for a in s.scalars(select(AdSet).where(AdSet.entity_id.in_(entities)))
    }
    ads = {
        a.entity_id: a for a in s.scalars(select(Ad).where(Ad.entity_id.in_(entities)))
    }
    connections = {
        c.provider: c
        for c in s.scalars(
            select(ProviderConnection).where(
                ProviderConnection.workspace_id == workspace
            )
        )
    }
    result = []
    for account in accounts.values():
        connection = connections.get(account.provider)
        mapped_account = account_map.get(account.id, account.id)
        mapping_valid = mapped_account in accounts
        common = {
            "provider": account.provider,
            "account_id": mapped_account if mapping_valid else account.id,
            "account_name": account.name or account.external_id,
            "account_external_id": account.external_id,
            "credential_revision": connection.revision if connection else None,
        }
        result.append(
            {
                **common,
                "id": common["account_id"],
                "scope_id": common["account_id"],
                "scope_type": "ACCOUNT",
                "name": account.name or account.external_id,
                "external_id": account.external_id,
                "source_id": account.id,
                "campaign_id": None,
                "adset_id": None,
                "hierarchy_verified": mapping_valid,
            }
        )
        for entity in entities.values():
            if entity.account_id != account.id or entity.kind not in (
                "campaign",
                "adset",
                "ad",
            ):
                continue
            ad = ads.get(entity.id)
            aset = adsets.get(
                entity.id
                if entity.kind == "adset"
                else (ad.adset_id or "")
                if ad
                else ""
            )
            campaign = entities.get(aset.campaign_id or "") if aset else None
            aset_entity = entities.get(aset.entity_id) if aset else None
            valid = (entity.kind == "campaign" and entity.id in campaigns) or bool(
                aset
                and campaign
                and campaign.kind == "campaign"
                and campaign.id in campaigns
                and campaign.account_id == account.id
                and aset_entity
                and aset_entity.account_id == account.id
            )
            if entity.kind == "ad":
                valid = valid and bool(
                    ad and aset_entity and aset_entity.kind == "adset"
                )
            result.append(
                {
                    **common,
                    "id": entity_map.get(entity.id, entity.id),
                    "scope_id": entity_map.get(entity.id, entity.id),
                    "scope_type": entity.kind.upper(),
                    "name": entity.name or entity.external_id,
                    "external_id": entity.external_id,
                    "source_id": entity.id,
                    "campaign_id": entity_map.get(campaign.id, campaign.id)
                    if campaign
                    else entity_map.get(entity.id, entity.id)
                    if entity.kind == "campaign"
                    else None,
                    "adset_id": entity_map.get(aset.entity_id, aset.entity_id)
                    if aset
                    else None,
                    "hierarchy_verified": bool(valid and mapping_valid),
                }
            )
    unique = {target_key(r): r for r in result}
    return sorted(unique.values(), key=lambda r: (r["name"].casefold(), target_key(r)))


def search_catalog(
    s: Session,
    workspace: str,
    kind: str,
    q: str = "",
    *,
    accounts: list[str] | None = None,
    campaigns: list[str] | None = None,
    adsets: list[str] | None = None,
    offset: int = 0,
    limit: int = 20,
) -> dict[str, Any]:
    """AND tokens over the entire local catalog, including Unicode names and IDs."""
    words = q.casefold().split()
    rows = [
        r
        for r in catalog(s, workspace)
        if r["scope_type"] == kind.upper()
        and (not accounts or r["account_id"] in accounts)
        and (not campaigns or r["campaign_id"] in campaigns)
        and (not adsets or r["adset_id"] in adsets)
        and all(
            word in f"{r['name']} {r['external_id']} {r['id']}".casefold()
            for word in words
        )
    ]
    return {
        "rows": rows[offset : offset + limit],
        "total": len(rows),
        "next_offset": offset + limit if offset + limit < len(rows) else None,
        "max_targets": MAX_TARGETS,
    }


def validated_targets(
    s: Session, actor: dict, targets: list, previous: list | None = None
) -> list:
    """Validate all or reject all; server stamps provenance and effective dates."""
    from services.automation.smart_schema import RuleTarget
    from services.economics.store import utcnow

    available = {target_key(r): r for r in catalog(s, actor["workspace"])}
    old = {target_key(r): r for r in (previous or [])}
    result, problems = [], []
    for target in targets:
        key = target_key(target)
        row = available.get(key)
        if (row is None or not row["hierarchy_verified"]) and key in old:
            saved = old[key]
            result.append(
                RuleTarget.model_validate(
                    saved.model_dump() if hasattr(saved, "model_dump") else saved
                )
            )
            continue
        if row is None or not row["hierarchy_verified"]:
            problems.append(
                {
                    "scope_type": target.scope_type,
                    "scope_id": target.scope_id,
                    "reason_code": "TARGET_NOT_FOUND"
                    if row is None
                    else "HIERARCHY_UNVERIFIED",
                }
            )
            continue
        saved = old.get(key, {})
        if hasattr(saved, "model_dump"):
            saved = saved.model_dump()
        data = target.model_dump()
        result.append(
            RuleTarget.model_validate(
                {
                    **data,
                    "name": row["name"],
                    "external_id": row["external_id"],
                    "account_name": row["account_name"],
                    "campaign_id": row["campaign_id"],
                    "adset_id": row["adset_id"],
                    "credential_revision": row["credential_revision"],
                    "actor_id": saved.get("actor_id") or actor["id"],
                    "created_at": saved.get("created_at") or utcnow(),
                }
            )
        )
    if problems:
        raise HTTPException(422, {"code": "INVALID_RULE_TARGETS", "targets": problems})
    return result


def resolve_targets(
    s: Session, workspace: str, targets: list, today: date
) -> dict[str, Any]:
    """Deterministic union per canonical account/provider/ad; retain every origin."""
    rows = catalog(s, workspace)
    available = {target_key(r): r for r in rows}
    provenance: dict[tuple[str, str, str], list[dict]] = {}
    issues = []
    for target in targets:
        data = (
            target.model_dump(mode="json") if hasattr(target, "model_dump") else target
        )
        if (
            data.get("effective_start")
            and today.isoformat() < str(data["effective_start"])
        ) or (
            data.get("effective_end") and today.isoformat() > str(data["effective_end"])
        ):
            continue
        scope = available.get(target_key(data))
        reason = (
            "TARGET_NOT_FOUND"
            if scope is None
            else "HIERARCHY_UNVERIFIED"
            if not scope["hierarchy_verified"]
            else "PROVIDER_REVISION_CHANGED"
            if data.get("credential_revision") != scope["credential_revision"]
            else None
        )
        if reason:
            issues.append(
                {
                    "scope_type": data["scope_type"],
                    "scope_id": data["scope_id"],
                    "reason_code": reason,
                }
            )
            continue
        found = []
        for ad in rows:
            if (
                ad["scope_type"] != "AD"
                or ad["provider"] != data["provider"]
                or ad["account_id"] != data["account_id"]
            ):
                continue
            kind = data["scope_type"]
            belongs = kind == "ACCOUNT" or (
                (
                    ad["campaign_id"]
                    if kind == "CAMPAIGN"
                    else ad["adset_id"]
                    if kind == "ADSET"
                    else ad["id"]
                )
                == data["scope_id"]
            )
            if not belongs:
                continue
            if not ad["hierarchy_verified"]:
                issues.append(
                    {
                        "scope_id": data["scope_id"],
                        "reason_code": "HIERARCHY_UNVERIFIED",
                    }
                )
                continue
            found.append(ad)
            key = (ad["provider"], ad["account_id"], ad["id"])
            provenance.setdefault(key, []).append(data)
        if not found:
            issues.append(
                {
                    "scope_type": data["scope_type"],
                    "scope_id": data["scope_id"],
                    "reason_code": "NO_MATCHING_ADS",
                }
            )
    return {"provenance": provenance, "issues": issues, "total": len(provenance)}
