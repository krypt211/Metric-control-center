"""Authenticated local simulation routes; existing advertising guards stay enabled."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from backend.auth import csrf_check, factory, identity
from services.analytics.table import filter_options
from services.automation.smart_models import (
    RuleAuditLog,
    RuleGrant,
    RuleSimulation,
    RuleVersion,
)
from services.automation.smart_recommendations import recommendation_summary
from services.automation.smart_schema import SmartRuleInput, SmartRuleUpdate
from services.automation.smart_simulation import simulate, simulation_json
from services.automation.smart_store import (
    STATES,
    editor,
    get_rule,
    grant,
    rule_json,
    save,
)
from services.automation.smart_templates import templates
from services.economics.models import EconomicsProfile
from services.economics.schema import GrantInput, RestoreInput, VersionInput
from services.economics.store import profile_json
from services.storage.models import Rule, User

router = APIRouter(prefix="/api/smart-rules")


def actor(request: Request, write: bool = False) -> dict:
    a = identity(request)
    if write:
        csrf_check(request, a)
    return a


@router.get("")
def listing(request: Request) -> dict:
    a = actor(request)
    with factory()() as s:
        rules = s.scalars(
            select(Rule)
            .where(Rule.workspace_id == a["workspace"], Rule.status.in_(STATES))
            .order_by(Rule.created_at.desc())
            .limit(200)
        ).all()
        output = []
        for rule in rules:
            latest = s.scalar(
                select(RuleSimulation.created_at)
                .where(
                    RuleSimulation.workspace_id == a["workspace"],
                    RuleSimulation.rule_id == rule.id,
                )
                .order_by(RuleSimulation.created_at.desc())
                .limit(1)
            )
            version = s.scalar(
                select(RuleVersion).where(
                    RuleVersion.rule_id == rule.id,
                    RuleVersion.revision == rule.revision,
                )
            )
            output.append(
                {
                    **rule_json(rule),
                    "updated_at": version.created_at.isoformat() if version else None,
                    "last_simulation_at": latest.isoformat() if latest else None,
                }
            )
        return {"rules": output, "can_edit": editor(s, a), "mode": "DRY_RUN"}


@router.get("/recommendations")
def recommendations(
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict:
    a = actor(request)
    with factory()() as s:
        return recommendation_summary(s, a["workspace"], offset=offset, limit=limit)


@router.get("/available-scopes")
def scopes(request: Request) -> dict:
    a = actor(request)
    with factory()() as s:
        operators = (
            s.scalars(
                select(User).where(
                    User.workspace_id == a["workspace"],
                    User.role == "operator",
                    User.is_active.is_(True),
                )
            ).all()
            if a["role"] == "admin"
            else []
        )
        return {
            **filter_options(s, a["workspace"]),
            "profiles": [
                profile_json(p)
                for p in s.scalars(
                    select(EconomicsProfile).where(
                        EconomicsProfile.workspace_id == a["workspace"],
                        EconomicsProfile.deleted.is_(False),
                    )
                )
            ],
            "templates": templates(),
            "can_edit": editor(s, a),
            "is_admin": a["role"] == "admin",
            "operators": [
                {
                    "id": u.id,
                    "login": u.email,
                    "can_edit": bool(
                        (g := s.get(RuleGrant, (a["workspace"], u.id))) and g.can_edit
                    ),
                }
                for u in operators
            ],
        }


@router.put("/grants")
def change_grant(body: GrantInput, request: Request) -> dict:
    a = actor(request, True)
    with factory().begin() as s:
        grant(s, a, body.user_id, body.can_edit)
    return {"ok": True}


@router.post("", status_code=201)
def create(body: SmartRuleInput, request: Request) -> dict:
    a = actor(request, True)
    with factory().begin() as s:
        return save(s, a, body)


@router.get("/simulations/{key}")
def simulation(key: str, request: Request) -> dict:
    a = actor(request)
    with factory()() as s:
        row = s.get(RuleSimulation, key)
        if not row or row.workspace_id != a["workspace"]:
            raise HTTPException(404, "SIMULATION_NOT_FOUND")
        return simulation_json(row)


@router.get("/{key}")
def read(key: str, request: Request) -> dict:
    a = actor(request)
    with factory()() as s:
        return rule_json(get_rule(s, a["workspace"], key))


@router.put("/{key}")
def update(key: str, body: SmartRuleUpdate, request: Request) -> dict:
    a = actor(request, True)
    config = SmartRuleInput.model_validate(body.model_dump(exclude={"revision"}))
    with factory().begin() as s:
        return save(s, a, config, key, body.revision)


@router.post("/{key}/copy", status_code=201)
def copy(key: str, body: VersionInput, request: Request) -> dict:
    a = actor(request, True)
    with factory().begin() as s:
        row = get_rule(s, a["workspace"], key)
        if row.revision != body.version:
            raise HTTPException(409, "RULE_VERSION_CONFLICT")
        config = SmartRuleInput.model_validate(
            {**row.payload, "name": row.payload["name"][:110] + " — копия"}
        )
        return save(s, a, config)


@router.delete("/{key}")
def archive(key: str, body: VersionInput, request: Request) -> dict:
    a = actor(request, True)
    with factory().begin() as s:
        return save(s, a, None, key, body.version, deleted=True)


@router.post("/{key}/restore")
def restore(key: str, body: RestoreInput, request: Request) -> dict:
    a = actor(request, True)
    with factory().begin() as s:
        return save(
            s, a, None, key, body.version, restore_revision=body.restore_version
        )


@router.post("/{key}/simulate")
def run(key: str, body: VersionInput, request: Request) -> dict:
    a = actor(request, True)
    with factory().begin() as s:
        return simulate(s, a, key, body.version)


@router.get("/{key}/history")
def history(
    key: str, request: Request, limit: int = Query(default=50, ge=1, le=100)
) -> dict:
    a = actor(request)
    with factory()() as s:
        get_rule(s, a["workspace"], key)
        return {
            "versions": [
                {
                    "revision": v.revision,
                    "actor_id": v.actor_id,
                    "at": v.created_at.isoformat(),
                    "snapshot": v.payload,
                }
                for v in s.scalars(
                    select(RuleVersion)
                    .where(
                        RuleVersion.workspace_id == a["workspace"],
                        RuleVersion.rule_id == key,
                    )
                    .order_by(RuleVersion.revision.desc())
                    .limit(limit)
                )
            ],
            "simulations": [
                simulation_json(v, summary=True)
                for v in s.scalars(
                    select(RuleSimulation)
                    .where(
                        RuleSimulation.workspace_id == a["workspace"],
                        RuleSimulation.rule_id == key,
                    )
                    .order_by(RuleSimulation.created_at.desc())
                    .limit(limit)
                )
            ],
            "audit": [
                {
                    "event": v.event,
                    "actor_id": v.actor_id,
                    "at": v.created_at.isoformat(),
                }
                for v in s.scalars(
                    select(RuleAuditLog)
                    .where(
                        RuleAuditLog.workspace_id == a["workspace"],
                        RuleAuditLog.resource_id == key,
                    )
                    .order_by(RuleAuditLog.created_at.desc())
                    .limit(limit)
                )
            ],
        }
