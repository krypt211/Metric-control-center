"""User-agreed, exact-scope reported-spend experiment; no financial certification."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

STRICT = "STRICT_FINANCIAL"
POLICY = "CREO03_REPORTED_SPEND15_V1"
ACK = "PREPARE_ONE_CREO03_SPEND_TEST_WITHOUT_FINANCIAL_CERTIFICATION"
STATEMENT = "AUTHORIZE_ONE_EXPERIMENTAL_REPORTED_SPEND_PAUSE_WITH_UNVERIFIED_ID"
ACCOUNT = "act_1047962734516123"
AD = "120247730105960571"
ADSET = "120247730105950571"
CAMPAIGN = "120247730079240571"
DAY = date(2026, 9, 28)


def held(code: str) -> None:
    raise HTTPException(409, "REPORTED_SPEND_TEST_" + code)


def require_config(session, rule, config, entity_id: str) -> None:
    """Reject broader rules even if their current result contains only one AD."""
    from services.actions.experimental import identity_for
    from services.actions.manual import snapshot
    from services.automation.smart_schema import Condition
    from services.economics.models import EconomicsProfile
    from services.storage.models import AdAccount, Entity

    entity = session.get(Entity, entity_id)
    account = session.get(AdAccount, entity.account_id) if entity else None
    if (
        rule.workspace_id != "default"
        or rule.status != "SMART_DRY_RUN"
        or rule.next_evaluation_at is not None
        or config.enabled
        or config.allow_reenable
        or config.action != "PAUSE_AD"
        or config.period != "custom"
        or config.start != DAY
        or config.end != DAY
        or not entity
        or entity.kind != "ad"
        or not account
        or account.workspace_id != rule.workspace_id
        or account.provider != "metricflow"
        or account.timezone != "America/Los_Angeles"
    ):
        held("SCOPE_CHANGED")
    captured = snapshot(session, entity, account)
    if (
        not captured["account_confirmed"]
        or not captured["hierarchy_confirmed"]
        or identity_for(captured)
        != {
            "account_id": ACCOUNT,
            "ad_id": AD,
            "adset_id": ADSET,
            "campaign_id": CAMPAIGN,
        }
    ):
        held("IDENTITY_CHANGED")
    selection = config.selection
    if (
        not selection.target_mode
        or len(selection.targets) != 1
        or selection.account_ids
        or any(
            getattr(selection, k)
            for k in ("provider", "campaign", "adset", "ad", "offer", "geo", "status")
        )
    ):
        held("TARGET_CHANGED")
    target = selection.targets[0]
    if (
        target.scope_type != "AD"
        or target.scope_id != entity.id
        or target.account_id != captured["canonical_account_id"]
        or target.provider != "metricflow"
        or target.effective_start is not None
        or target.effective_end is not None
    ):
        held("TARGET_CHANGED")
    profile = (
        session.get(EconomicsProfile, config.profile_id) if config.profile_id else None
    )
    if (
        not profile
        or profile.deleted
        or profile.workspace_id != rule.workspace_id
        or profile.payload.get("currency") != "USD"
        or profile.payload.get("timezone") != "America/Los_Angeles"
    ):
        held("PROFILE_CHANGED")
    tree = config.expression
    if (
        tree.operator != "AND"
        or len(tree.children) != 1
        or not isinstance(tree.children[0], Condition)
    ):
        held("CONDITION_CHANGED")
    c = tree.children[0]
    if (
        c.type != "SPEND_THRESHOLD"
        or c.source != "actual"
        or c.limit != "custom"
        or c.value != Decimal(15)
        or c.multiplier != 1
        or c.currency != "USD"
    ):
        held("CONDITION_CHANGED")


def require_card(
    session,
    rule,
    config,
    entity_id: str,
    card: dict,
    now: datetime,
    *,
    current_request_id: str | None = None,
) -> dict:
    """Attest only the agreed spend experiment, retaining the strict result unchanged."""
    from services.storage.models import ActionRequest, Rule
    from services.sync.engine import aware

    require_config(session, rule, config, entity_id)
    if (
        card.get("source_entity_id") != entity_id
        or card.get("source_provider") != "metricflow"
        or card.get("external_id") != AD
        or card.get("currency") != "USD"
        or card.get("profile_currency") != "USD"
        or card.get("evaluation_timezone") != "America/Los_Angeles"
        or card.get("period_start") != DAY.isoformat()
        or card.get("period_end") != DAY.isoformat()
        or card.get("source_stale") is not False
        or card.get("window_complete") is not True
        or not card.get("credential_revision")
        or card.get("condition_matched") != "TRUE"
        or card.get("status") not in ("REVIEW", "WOULD_PAUSE")
        or set(card.get("reason_codes", [])) - {"ATTRIBUTION_UNVERIFIED"}
        or card.get("manual_blocked")
        or card.get("unresolved_action")
        or card.get("status_fresh") is not True
        or card.get("ad_status") not in ("ACTIVE", "CAMPAIGN_PAUSED", "ADSET_PAUSED")
    ):
        held("EVIDENCE_HELD")
    for previous in session.scalars(
        select(ActionRequest).where(
            ActionRequest.workspace_id == rule.workspace_id,
            ActionRequest.entity_id == entity_id,
        )
    ):
        if (
            previous.id != current_request_id
            and (previous.provenance.get("rule_source") or {}).get("evidence_policy")
            == POLICY
            and (previous.provenance.get("controlled") or {}).get("authorization")
        ):
            held("ALREADY_AUTHORIZED")
    # Stronger than normal peer arbitration: this one-off test admits no other
    # enabled rule anywhere in the workspace. Never reinterpret a peer REVIEW.
    if session.scalar(
        select(Rule.id)
        .where(
            Rule.workspace_id == rule.workspace_id,
            Rule.id != rule.id,
            Rule.status != "SMART_ARCHIVED",
            Rule.payload["enabled"].as_boolean().is_(True),
        )
        .limit(1)
    ):
        held("ENABLED_PEER_RULE")
    recent = session.scalars(
        select(ActionRequest).where(
            ActionRequest.workspace_id == rule.workspace_id,
            ActionRequest.entity_id == entity_id,
            ActionRequest.action.in_(("ENABLE_AD", "enable")),
            ActionRequest.status.notin_(("CANCELLED", "EXPIRED", "FAILED", "failed")),
            ActionRequest.created_at > now - timedelta(days=7),
        )
    ).all()
    if any(
        (now - aware(r.created_at)).total_seconds()
        < max(
            config.cooldown_seconds,
            (r.provenance.get("rule_source") or {}).get("cooldown_seconds", 3600),
        )
        for r in recent
    ):
        held("ANTI_LOOP_COOLDOWN")
    return {
        **card,
        "reported_spend_test_eligible": True,
        "reported_spend_test_policy": POLICY,
    }
