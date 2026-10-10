"""Local lifecycle extensions of ActionEngine; never constructs a provider client."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from services.actions.capabilities import ActionCapabilityRegistry
from services.actions.manual_models import ManualActionGrant
from services.actions.manual_schema import ManualDraftInput
from services.actions.safety import ActionSafetyGate
from services.automation.smart_models import RuleSimulation
from services.providers.models import (
    ProviderAccountMapping,
    ProviderConnection,
    ProviderRoutingSetting,
)
from services.storage.models import (
    ActionLog,
    ActionRequest,
    Ad,
    AdAccount,
    AdSet,
    Entity,
    EntityCurrentState,
    User,
)
from services.sync.engine import aware

PENDING = (
    "DRAFT",
    "PREFLIGHT_PENDING",
    "PREFLIGHT_PASSED",
    "PREFLIGHT_FAILED",
    "AWAITING_CONFIRMATION",
    "CONFIRMED",
    "BLOCKED",
)
TERMINAL = ("SIMULATED", "EXPIRED", "CANCELLED")
FUTURE = (
    "EXECUTING",
    "SUCCEEDED",
    "FAILED",
    "OUTCOME_UNKNOWN",
    "RECONCILIATION_REQUIRED",
)


def permitted(s, actor: dict) -> bool:
    user = s.get(User, actor["id"])
    if not user or user.workspace_id != actor["workspace"] or not user.is_active:
        return False
    grant = s.get(ManualActionGrant, (actor["workspace"], actor["id"]))
    return user.role == "admin" or bool(
        user.role == "operator" and grant and grant.can_control
    )


def require_permission(s, actor: dict) -> None:
    # Serialize permission revocation with local mutation on the same user.
    s.scalar(select(User).where(User.id == actor["id"]).with_for_update())
    if not permitted(s, actor):
        raise HTTPException(403, "MANUAL_CONTROL_PERMISSION_REQUIRED")


def routing(s, workspace: str, account_id: str) -> dict:
    mapping = s.get(ProviderAccountMapping, account_id)
    canonical = mapping.canonical_id if mapping else account_id
    setting = s.get(ProviderRoutingSetting, (workspace, canonical)) or s.get(
        ProviderRoutingSetting, (workspace, "workspace")
    )
    return {
        "primary_provider": setting.primary_provider if setting else "metricflow",
        "action_provider": setting.action_provider if setting else "disabled",
        "revision": aware(setting.updated_at).isoformat() if setting else None,
    }


def snapshot(s, entity: Entity, account: AdAccount) -> dict:
    state = s.get(EntityCurrentState, entity.id)
    connection = s.get(ProviderConnection, (account.workspace_id, account.provider))
    ad = s.get(Ad, entity.id)
    aset = s.get(AdSet, ad.adset_id) if ad and ad.adset_id else None
    parent = s.get(Entity, ad.adset_id) if ad and ad.adset_id else None
    campaign = s.get(Entity, aset.campaign_id) if aset and aset.campaign_id else None
    mapping = s.get(ProviderAccountMapping, account.id)
    return {
        "entity_id": entity.id,
        "meta_ad_id": entity.external_id,
        "account_id": account.id,
        "meta_account_id": account.external_id,
        "canonical_account_id": mapping.canonical_id if mapping else account.id,
        "account_confirmed": bool(
            mapping and mapping.meta_account_id == account.external_id
        ),
        "hierarchy": [
            parent.external_id if parent else None,
            campaign.external_id if campaign else None,
        ],
        "hierarchy_confirmed": bool(
            parent
            and campaign
            and parent.kind == "adset"
            and campaign.kind == "campaign"
            and parent.account_id == account.id
            and campaign.account_id == account.id
            and all(
                re.fullmatch(r"[0-9]+", e.external_id)
                for e in (entity, parent, campaign)
            )
        ),
        "provider": account.provider,
        "credential_revision": connection.revision if connection else None,
        "routing": routing(s, account.workspace_id, account.id),
        "status": state.status if state else None,
        "status_refreshed_at": aware(state.observed_at).isoformat() if state else None,
        "effective_status": (state.raw or {}).get("effective_status")
        if state
        else None,
        "name": entity.name or entity.external_id,
        "account_name": account.name or account.external_id,
    }


class ActionAuditService:
    @staticmethod
    def append(
        s, request: ActionRequest, event: str, actor: dict, now: datetime, **details
    ) -> None:
        s.add(
            ActionLog(
                id=str(uuid4()),
                request_id=request.id,
                event=event,
                created_at=now,
                details={
                    "actor_id": actor["id"],
                    "state": request.status,
                    "revision": request.revision,
                    **details,
                },
            )
        )


def move(s, row, state: str, actor: dict, now: datetime, **details) -> None:
    previous = row.status
    row.status = state
    row.revision += 1
    ActionAuditService.append(s, row, state, actor, now, previous=previous, **details)


def action_json(s, row: ActionRequest, now: datetime) -> dict:
    events = s.scalars(
        select(ActionLog)
        .where(ActionLog.request_id == row.id)
        .order_by(ActionLog.created_at, ActionLog.id)
    ).all()
    actor = s.get(User, row.initiator_id)
    meta = row.provenance
    return {
        "id": row.id,
        "revision": row.revision,
        "status": row.status,
        "display_status": "EXPIRED"
        if row.status in PENDING and now >= datetime.fromisoformat(meta["expires_at"])
        else row.status,
        "operation": row.action,
        "created_at": row.created_at.isoformat(),
        "actor": actor.email if actor else row.initiator_id,
        **meta,
        "events": [
            {"event": e.event, "at": e.created_at.isoformat(), **e.details}
            for e in events
        ],
    }


def preflight(engine, s, row: ActionRequest, actor: dict, now: datetime) -> dict:
    m = row.provenance
    entity = s.get(Entity, row.entity_id)
    account = s.get(AdAccount, entity.account_id) if entity else None
    failures = []
    if (
        not entity
        or entity.kind != "ad"
        or not account
        or account.workspace_id != row.workspace_id
    ):
        failures.append("ENTITY_UNAVAILABLE")
    else:
        current = snapshot(s, entity, account)
        captured = m["captured"]
        for field, code in (
            ("meta_ad_id", "IDENTITY_CHANGED"),
            ("account_id", "ACCOUNT_CHANGED"),
            ("meta_account_id", "ACCOUNT_CHANGED"),
            ("canonical_account_id", "ACCOUNT_CHANGED"),
            ("hierarchy", "HIERARCHY_CHANGED"),
            ("provider", "PROVIDER_CHANGED"),
            ("credential_revision", "CREDENTIAL_CHANGED"),
            ("routing", "ROUTING_CHANGED"),
        ):
            if current[field] != captured[field]:
                failures.append(code)
        if current["meta_ad_id"] != m["meta_ad_id"]:
            failures.append("AD_ID_MISMATCH")
        if current["account_id"] != m["account_id"]:
            failures.append("ACCOUNT_MISMATCH")
        if current["provider"] != m["provider"]:
            failures.append("PROVIDER_MISMATCH")
        if not current["account_confirmed"] or not re.fullmatch(
            r"act_[0-9]+", current["meta_account_id"]
        ):
            failures.append("ACCOUNT_UNCONFIRMED")
        if not current["hierarchy_confirmed"]:
            failures.append("HIERARCHY_UNCONFIRMED")
        at = current["status_refreshed_at"]
        if (
            not at
            or not -60
            <= (now - datetime.fromisoformat(at)).total_seconds()
            <= engine.policy.max_state_age_seconds
        ):
            failures.append("STATUS_STALE")
        if current["status"] != m["expected_status"]:
            failures.append("STATUS_CHANGED")
        if current["status"] == m["target_status"]:
            failures.append("ALREADY_TARGET_STATE")
        capability = ActionCapabilityRegistry.inspect(
            s, row.workspace_id, m["provider"]
        )
        if not capability["connected"] or capability["health"] != "healthy":
            failures.append("PROVIDER_UNAVAILABLE")
        if current["routing"]["primary_provider"] != m["provider"]:
            failures.append("ROUTING_PROVIDER_MISMATCH")
    capability = ActionCapabilityRegistry.inspect(s, row.workspace_id, m["provider"])
    if not permitted(s, actor):
        failures.append("MANUAL_CONTROL_PERMISSION_REQUIRED")
    other = s.scalar(
        select(ActionRequest.id)
        .where(
            ActionRequest.entity_id == row.entity_id,
            ActionRequest.id != row.id,
            ActionRequest.status.in_(
                (*PENDING, "queued", "executing", "verifying", "unknown")
            ),
        )
        .limit(1)
    )
    if other:
        failures.append("PENDING_ACTION_CONFLICT")
    previous = s.scalars(
        select(ActionRequest).where(
            ActionRequest.entity_id == row.entity_id,
            ActionRequest.status.in_(("succeeded", "SUCCEEDED")),
        )
    ).all()
    if any(
        p.action in (row.action, "pause" if row.action == "PAUSE_AD" else "enable")
        and p.baseline_status == row.baseline_status
        for p in previous
    ):
        failures.append("IDENTICAL_OPERATION_COMPLETED")
    if now >= datetime.fromisoformat(m["expires_at"]):
        failures.append("REQUEST_EXPIRED")
    if m.get("rule_source"):
        source = m["rule_source"]
        if (
            source.get("ad_status") != m["expected_status"]
            or source.get("provider") != m["provider"]
        ):
            failures.append("RULE_SOURCE_CHANGED")
        if source.get("credential_revision") not in (
            None,
            m["captured"]["credential_revision"],
        ):
            failures.append("RULE_SOURCE_CHANGED")
    write_reasons = ["WRITE_DISABLED", *capability["reason_codes"]]
    return {
        "checked_at": now.isoformat(),
        "local_allowed": not failures,
        "live_allowed": False,
        "scope": "LOCAL_SIMULATION_ONLY",
        "reason_codes": list(dict.fromkeys(failures + write_reasons)),
        "blocking_reasons": list(dict.fromkeys(failures)),
        "capability": capability,
    }


def prepare(engine, actor: dict, command: ManualDraftInput, key: str) -> dict:
    if not key or len(key) > 128 or any(ord(c) < 33 for c in key):
        raise HTTPException(422, "INVALID_IDEMPOTENCY_KEY")
    fingerprint = hashlib.sha256(
        json.dumps(command.model_dump(), sort_keys=True).encode()
    ).hexdigest()
    now = engine.clock()
    try:
        with engine.sessions.begin() as s:
            require_permission(s, actor)
            # One lock order for create/check/confirm: entity, then request.
            entity = s.scalar(
                select(Entity)
                .join(AdAccount)
                .where(
                    Entity.id == command.entity_id,
                    AdAccount.workspace_id == actor["workspace"],
                )
                .with_for_update(of=Entity)
            )
            if not entity or entity.kind != "ad":
                raise HTTPException(404, "AD_NOT_FOUND")
            old = s.scalar(
                select(ActionRequest).where(
                    ActionRequest.workspace_id == actor["workspace"],
                    ActionRequest.initiator_id == actor["id"],
                    ActionRequest.idempotency_key == key,
                )
            )
            if old:
                if old.provenance.get("fingerprint") != fingerprint:
                    raise HTTPException(409, "IDEMPOTENCY_CONFLICT")
                return action_json(s, old, now)
            for pending in s.scalars(
                select(ActionRequest).where(
                    ActionRequest.entity_id == entity.id,
                    ActionRequest.status.in_(PENDING),
                )
            ):
                if now >= datetime.fromisoformat(pending.provenance["expires_at"]):
                    move(s, pending, "EXPIRED", actor, now)
                else:
                    raise HTTPException(409, "PENDING_ACTION_CONFLICT")
            s.flush()
            account = s.get(AdAccount, entity.account_id)
            captured = snapshot(s, entity, account)
            rule_source = None
            if command.simulation_id:
                sim = s.get(RuleSimulation, command.simulation_id)
                candidates = (
                    [
                        r
                        for r in sim.payload["rows"]
                        if r["id"] == entity.id
                        or r.get("external_id") == command.meta_ad_id
                    ]
                    if sim and sim.workspace_id == actor["workspace"]
                    else []
                )
                candidates = [
                    r
                    for r in candidates
                    if r.get("account_id") == captured["canonical_account_id"]
                ]
                if (
                    len(candidates) != 1
                    or candidates[0]["status"] != "WOULD_PAUSE"
                    or command.operation != "PAUSE_AD"
                ):
                    raise HTTPException(422, "RULE_RECOMMENDATION_MISMATCH")
                card = candidates[0]
                rule_source = {
                    "simulation_id": sim.id,
                    "rule_id": sim.rule_id,
                    "rule_revision": sim.revision,
                    "reasons": card.get("reason_codes", []),
                    "expression": card.get("expression"),
                    "ad_status": card.get("ad_status"),
                    "provider": card.get("source_provider"),
                    "credential_revision": card.get("credential_revision"),
                }
            m = {
                "phase": "4A",
                "source": "manual",
                "fingerprint": fingerprint,
                "provider": command.provider,
                "provider_entity_id": captured["meta_ad_id"],
                "entity_id": entity.id,
                "meta_ad_id": command.meta_ad_id,
                "account_id": command.account_id,
                "expected_status": command.expected_status,
                "target_status": "PAUSED"
                if command.operation == "PAUSE_AD"
                else "ACTIVE",
                "reason": command.reason,
                "captured": captured,
                "rule_source": rule_source,
                "expires_at": (now + timedelta(minutes=15)).isoformat(),
                "confirmation_actor": None,
                "confirmation_at": None,
                "preflight": None,
                "result": None,
                "reason_codes": [],
            }
            row = ActionRequest(
                id=str(uuid4()),
                workspace_id=actor["workspace"],
                initiator_id=actor["id"],
                entity_id=entity.id,
                idempotency_key=key,
                action=command.operation,
                baseline_status=command.expected_status,
                provenance=m,
                status="DRAFT",
                revision=1,
                created_at=now,
            )
            s.add(row)
            s.flush()
            ActionAuditService.append(s, row, "DRAFT", actor, now)
            return action_json(s, row, now)
    except IntegrityError:
        raise HTTPException(409, "PENDING_ACTION_CONFLICT") from None


def transition(engine, actor: dict, key: str, event: str, revision: int) -> dict:
    now = engine.clock()
    with engine.sessions.begin() as s:
        require_permission(s, actor)
        found = s.scalar(
            select(ActionRequest.entity_id).where(
                ActionRequest.id == key,
                ActionRequest.workspace_id == actor["workspace"],
            )
        )
        if not found:
            raise HTTPException(404, "ACTION_NOT_FOUND")
        s.scalar(select(Entity).where(Entity.id == found).with_for_update())
        row = s.scalar(
            select(ActionRequest).where(ActionRequest.id == key).with_for_update()
        )
        if row.provenance.get("phase") != "4A":
            raise HTTPException(409, "NOT_MANUAL_DRAFT")
        if row.revision != revision:
            raise HTTPException(409, "ACTION_REVISION_CONFLICT")
        if actor["role"] != "admin" and row.initiator_id != actor["id"]:
            raise HTTPException(403, "ACTION_OWNER_REQUIRED")
        if row.status in TERMINAL:
            raise HTTPException(409, "ACTION_TERMINAL")
        if row.status not in PENDING:
            raise HTTPException(409, "ACTION_STATE_UNSUPPORTED")
        if now >= datetime.fromisoformat(row.provenance["expires_at"]):
            move(s, row, "EXPIRED", actor, now)
            return action_json(s, row, now)
        if event == "cancel":
            move(s, row, "CANCELLED", actor, now)
        elif event in ("preflight", "confirm", "simulate"):
            m = dict(row.provenance)
            if event == "preflight" and row.status == "CONFIRMED":
                raise HTTPException(409, "ALREADY_CONFIRMED")
            if event == "confirm" and not (
                row.status == "BLOCKED" and m.get("preflight", {}).get("local_allowed")
            ):
                raise HTTPException(409, "PREFLIGHT_REQUIRED")
            if event == "simulate" and row.status != "CONFIRMED":
                raise HTTPException(409, "CONFIRMATION_REQUIRED")
            check = preflight(engine, s, row, actor, now)
            m["preflight"], m["reason_codes"] = check, check["reason_codes"]
            row.provenance = m
            if event == "preflight":
                move(s, row, "PREFLIGHT_PENDING", actor, now)
                move(
                    s,
                    row,
                    "PREFLIGHT_FAILED",
                    actor,
                    now,
                    scope="LIVE",
                    reason_codes=check["reason_codes"],
                )
                move(
                    s, row, "BLOCKED", actor, now, local_allowed=check["local_allowed"]
                )
            elif not check["local_allowed"]:
                move(
                    s,
                    row,
                    "BLOCKED",
                    actor,
                    now,
                    reason_codes=check["blocking_reasons"],
                )
            elif event == "confirm":
                m["confirmation_actor"], m["confirmation_at"] = (
                    actor["id"],
                    now.isoformat(),
                )
                row.provenance = dict(m)
                move(s, row, "AWAITING_CONFIRMATION", actor, now, scope="LOCAL")
                move(s, row, "CONFIRMED", actor, now, scope="LOCAL")
            else:
                m["result"] = "LOCAL_SIMULATION_ONLY"
                row.provenance = dict(m)
                move(s, row, "SIMULATED", actor, now, advertising_modified=False)
        else:
            raise HTTPException(404, "UNKNOWN_TRANSITION")
        s.flush()
        return action_json(s, row, now)


class ActionExecutionService:
    @staticmethod
    def execute(*args: Any, **kwargs: Any) -> None:
        ActionSafetyGate.require_write()
        # Even altered environment flags cannot activate this unfinished contract.
        raise HTTPException(409, "LIVE_EXECUTION_NOT_IMPLEMENTED")
