"""Session/CSRF-protected LOCAL manual control; no execution HTTP route."""

from __future__ import annotations

import os
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query, Request
from sqlalchemy import select

from backend.auth import csrf_check, factory, identity
from services.actions.capabilities import ActionCapabilityRegistry
from services.actions.catalog import catalog
from services.actions.engine import ActionEngine
from services.actions.manual import action_json, permitted
from services.actions.manual_models import ManualActionGrant, ManualGrantAudit
from services.actions.manual_schema import (
    ManualDraftInput,
    ManualTransitionInput,
    RuleDraftInput,
)
from services.actions.settings import policy_from_environment
from services.automation.smart_models import RuleSimulation
from services.economics.schema import GrantInput
from services.providers.models import ProviderAccountMapping
from services.storage.models import ActionRequest, AdAccount, Entity, User
from services.sync.engine import utc_now

router = APIRouter(prefix="/api/manual-control")


def actor(request: Request, write: bool = False) -> dict:
    a = identity(request)
    if write:
        csrf_check(request, a)
    return a


@router.get("/settings")
def settings(request: Request) -> dict:
    a = actor(request)
    with factory()() as s:
        return {
            "can_control": permitted(s, a),
            "is_admin": a["role"] == "admin",
            "write_enabled": False,
            "mode": "LOCAL_SIMULATION_ONLY",
            "actions_enabled": os.environ.get("ACTIONS_ENABLED", "false") == "true",
            "local_read_only": os.environ.get("LOCAL_READ_ONLY", "true") == "true",
            "providers": [
                ActionCapabilityRegistry.inspect(s, a["workspace"], p)
                for p in ("metricflow", "meta")
            ],
            "accounts": [
                {
                    "id": account.id,
                    "name": account.name or account.external_id,
                    "provider": account.provider,
                }
                for account in s.scalars(
                    select(AdAccount).where(AdAccount.workspace_id == a["workspace"])
                )
            ],
            "operators": [
                {
                    "id": u.id,
                    "login": u.email,
                    "can_control": bool(
                        (g := s.get(ManualActionGrant, (a["workspace"], u.id)))
                        and g.can_control
                    ),
                }
                for u in s.scalars(
                    select(User).where(
                        User.workspace_id == a["workspace"],
                        User.role == "operator",
                        User.is_active.is_(True),
                    )
                )
            ]
            if a["role"] == "admin"
            else [],
        }


@router.put("/grants")
def grant(body: GrantInput, request: Request) -> dict:
    a = actor(request, True)
    if a["role"] != "admin":
        raise HTTPException(403, "ADMIN_REQUIRED")
    with factory().begin() as s:
        user = s.scalar(select(User).where(User.id == body.user_id).with_for_update())
        if not user or user.workspace_id != a["workspace"] or user.role != "operator":
            raise HTTPException(404, "OPERATOR_NOT_FOUND")
        row = s.get(ManualActionGrant, (a["workspace"], user.id))
        before = bool(row and row.can_control)
        if row:
            row.can_control = body.can_edit
        else:
            s.add(
                ManualActionGrant(
                    workspace_id=a["workspace"],
                    user_id=user.id,
                    can_control=body.can_edit,
                )
            )
        s.add(
            ManualGrantAudit(
                id=str(uuid4()),
                workspace_id=a["workspace"],
                actor_id=a["id"],
                user_id=user.id,
                created_at=utc_now(),
                payload={"before": before, "after": body.can_edit},
            )
        )
    return {"ok": True}


@router.get("/ads")
def ads(
    request: Request,
    account_id: str | None = Query(None, max_length=36),
    offset: int = Query(0, ge=0),
) -> dict:
    a = actor(request)
    with factory()() as s:
        return catalog(s, a["workspace"], utc_now(), account_id, offset)


@router.get("/requests")
def history(request: Request) -> dict:
    a = actor(request)
    with factory()() as s:
        rows = s.scalars(
            select(ActionRequest)
            .where(
                ActionRequest.workspace_id == a["workspace"],
                ActionRequest.provenance["phase"].as_string() == "4A",
            )
            .order_by(ActionRequest.created_at.desc())
            .limit(100)
        ).all()
        return {"requests": [action_json(s, r, utc_now()) for r in rows]}


@router.get("/requests/{key}")
def detail(key: str, request: Request) -> dict:
    a = actor(request)
    with factory()() as s:
        row = s.get(ActionRequest, key)
        if (
            not row
            or row.workspace_id != a["workspace"]
            or row.provenance.get("phase") != "4A"
        ):
            raise HTTPException(404, "ACTION_NOT_FOUND")
        return action_json(s, row, utc_now())


@router.post("/requests", status_code=201)
def prepare(
    body: ManualDraftInput,
    request: Request,
    key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
) -> dict:
    a = actor(request, True)
    return ActionEngine(factory(), policy_from_environment()).prepare_manual(
        a, body, key
    )


@router.post("/from-rule", status_code=201)
def from_rule(
    body: RuleDraftInput,
    request: Request,
    key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
) -> dict:
    a = actor(request, True)
    with factory()() as s:
        sim = s.get(RuleSimulation, body.simulation_id)
        if not sim or sim.workspace_id != a["workspace"]:
            raise HTTPException(404, "SIMULATION_NOT_FOUND")
        cards = [
            r
            for r in sim.payload["rows"]
            if r["id"] == body.entity_id and r["status"] == "WOULD_PAUSE"
        ]
        if len(cards) != 1:
            raise HTTPException(422, "RULE_RECOMMENDATION_MISMATCH")
        card = cards[0]
        if card.get("ad_status") not in ("ACTIVE", "PAUSED"):
            raise HTTPException(422, "RULE_SOURCE_UNVERIFIED")
        entities = s.scalars(
            select(Entity)
            .join(AdAccount)
            .join(
                ProviderAccountMapping,
                ProviderAccountMapping.account_id == AdAccount.id,
            )
            .where(
                AdAccount.workspace_id == a["workspace"],
                AdAccount.provider == card["source_provider"],
                ProviderAccountMapping.canonical_id == card["account_id"],
                Entity.kind == "ad",
                Entity.external_id == card["external_id"],
            )
        ).all()
        if len(entities) != 1:
            raise HTTPException(422, "IDENTITY_UNCONFIRMED")
        entity = entities[0]
        command = ManualDraftInput(
            entity_id=entity.id,
            account_id=entity.account_id,
            meta_ad_id=entity.external_id,
            provider=card["source_provider"],
            operation="PAUSE_AD",
            expected_status=card["ad_status"],
            simulation_id=sim.id,
            reason=f"Рекомендация DRY RUN, версия правила {sim.revision}: "
            + ", ".join(card.get("reason_codes", [])),
        )
    return ActionEngine(factory(), policy_from_environment()).prepare_manual(
        a, command, key
    )


@router.post("/requests/{key}/{event}")
def transition(
    key: str, event: str, body: ManualTransitionInput, request: Request
) -> dict:
    a = actor(request, True)
    if event not in ("preflight", "confirm", "simulate", "cancel"):
        raise HTTPException(404, "UNKNOWN_TRANSITION")
    return ActionEngine(factory(), policy_from_environment()).transition_manual(
        a, key, event, body.revision
    )
