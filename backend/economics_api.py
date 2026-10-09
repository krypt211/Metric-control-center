"""Authenticated economics routes; writes are limited to local economics tables."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from backend.auth import csrf_check, factory, identity
from services.analytics.table import Filters, filter_options
from services.economics.core import Evidence, calculate
from services.economics.evaluation import evaluate
from services.economics.models import (
    ApprovalObservation,
    EconomicsAssignment,
    EconomicsAuditLog,
    EconomicsEvaluation,
    EconomicsGrant,
    EconomicsProfile,
)
from services.economics.schema import (
    AssignmentInput,
    GrantInput,
    ObservationInput,
    ProfileInput,
    ProfileUpdate,
    RestoreInput,
    VersionInput,
)
from services.economics.store import (
    assign,
    audit,
    change_profile,
    create_profile,
    editor,
    grant_edit,
    lock,
    observe,
    profile_json,
    profile_row,
    require_editor,
)
from services.storage.models import User

router = APIRouter()
BASE = "/api/economics"


def actor(request: Request, mutation: bool = False) -> dict:
    value = identity(request)
    if mutation:
        csrf_check(request, value)
    return value


@router.get(BASE + "/settings")
def settings(request: Request) -> dict:
    a = actor(request)
    with factory()() as s:
        profiles = s.scalars(
            select(EconomicsProfile)
            .where(EconomicsProfile.workspace_id == a["workspace"])
            .order_by(EconomicsProfile.created_at)
        ).all()
        assignments = s.scalars(
            select(EconomicsAssignment).where(
                EconomicsAssignment.workspace_id == a["workspace"]
            )
        ).all()
        observations = s.scalars(
            select(ApprovalObservation)
            .where(ApprovalObservation.workspace_id == a["workspace"])
            .order_by(ApprovalObservation.updated_at.desc())
            .limit(200)
        ).all()
        grants = (
            s.scalars(
                select(EconomicsGrant).where(
                    EconomicsGrant.workspace_id == a["workspace"]
                )
            ).all()
            if a["role"] == "admin"
            else []
        )
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
            "profiles": [profile_json(p) for p in profiles],
            "can_edit": editor(s, a),
            "is_admin": a["role"] == "admin",
            "assignments": [
                {
                    "id": x.id,
                    "profile_id": x.profile_id,
                    "scope_type": x.scope_type,
                    "scope_id": x.scope_id,
                    "effective_start": x.effective_start.isoformat(),
                    "effective_end": x.effective_end.isoformat()
                    if x.effective_end
                    else None,
                }
                for x in assignments
            ],
            "observations": [
                {
                    "id": x.id,
                    "version": x.version,
                    "updated_at": x.updated_at.isoformat(),
                    "quality": "ACTUAL_MANUAL",
                    **x.payload,
                }
                for x in observations
            ],
            "options": filter_options(s, a["workspace"]),
            "operators": [
                {
                    "id": u.id,
                    "login": u.email,
                    "can_edit": any(g.user_id == u.id and g.can_edit for g in grants),
                }
                for u in operators
            ],
            "actions_enabled": False,
        }


@router.post(BASE + "/preview")
def preview(command: ProfileInput, request: Request) -> dict:
    actor(request, True)
    return calculate(command, Evidence(None, None, None))


@router.post(BASE + "/profiles", status_code=201)
def create(command: ProfileInput, request: Request) -> dict:
    a = actor(request, True)
    with factory().begin() as s:
        lock(s, a["workspace"])
        require_editor(s, a)
        return create_profile(s, a, command)


@router.put(BASE + "/profiles/{key}")
def edit(key: str, command: ProfileUpdate, request: Request) -> dict:
    a = actor(request, True)
    with factory().begin() as s:
        lock(s, a["workspace"])
        require_editor(s, a)
        config = ProfileInput.model_validate(command.model_dump(exclude={"version"}))
        return change_profile(s, a, key, command.version, config)


@router.post(BASE + "/profiles/{key}/copy", status_code=201)
def copy_profile(key: str, command: VersionInput, request: Request) -> dict:
    a = actor(request, True)
    with factory().begin() as s:
        lock(s, a["workspace"])
        require_editor(s, a)
        row = profile_row(s, a["workspace"], key)
        if row.version != command.version:
            raise HTTPException(409, "ECONOMICS_VERSION_CONFLICT")
        return create_profile(
            s,
            a,
            ProfileInput.model_validate(
                {**row.payload, "name": row.payload["name"][:108] + " (copy)"}
            ),
        )


@router.delete(BASE + "/profiles/{key}")
def remove(key: str, command: VersionInput, request: Request) -> dict:
    a = actor(request, True)
    with factory().begin() as s:
        lock(s, a["workspace"])
        require_editor(s, a)
        return change_profile(s, a, key, command.version, None, delete=True)


@router.post(BASE + "/profiles/{key}/restore")
def restore(key: str, command: RestoreInput, request: Request) -> dict:
    a = actor(request, True)
    with factory().begin() as s:
        lock(s, a["workspace"])
        require_editor(s, a)
        return change_profile(
            s, a, key, command.version, None, restore_version=command.restore_version
        )


@router.post(BASE + "/assignments", status_code=201)
def assignment(command: AssignmentInput, request: Request) -> dict:
    a = actor(request, True)
    with factory().begin() as s:
        lock(s, a["workspace"])
        require_editor(s, a)
        return assign(s, a, command)


@router.delete(BASE + "/assignments/{key}")
def remove_assignment(key: str, request: Request) -> dict:
    a = actor(request, True)
    with factory().begin() as s:
        lock(s, a["workspace"])
        require_editor(s, a)
        row = s.get(EconomicsAssignment, key)
        if not row or row.workspace_id != a["workspace"]:
            raise HTTPException(404, "ECONOMICS_ASSIGNMENT_NOT_FOUND")
        audit(
            s,
            a,
            key,
            "ASSIGNMENT_REMOVE",
            {
                "profile_id": row.profile_id,
                "scope_type": row.scope_type,
                "scope_id": row.scope_id,
            },
            None,
        )
        s.delete(row)
        return {"status": "removed"}


@router.post(BASE + "/observations")
def observation(command: ObservationInput, request: Request) -> dict:
    a = actor(request, True)
    with factory().begin() as s:
        lock(s, a["workspace"])
        require_editor(s, a)
        return observe(s, a, command)


@router.put(BASE + "/grants")
def grant(command: GrantInput, request: Request) -> dict:
    a = actor(request, True)
    with factory().begin() as s:
        lock(s, a["workspace"])
        return grant_edit(s, a, command.user_id, command.can_edit)


@router.get(BASE + "/audit")
def history(request: Request, resource_id: str | None = None) -> dict:
    a = actor(request)
    with factory()() as s:
        q = select(EconomicsAuditLog).where(
            EconomicsAuditLog.workspace_id == a["workspace"]
        )
        if resource_id:
            q = q.where(EconomicsAuditLog.resource_id == resource_id)
        return {
            "rows": [
                {
                    "id": x.id,
                    "actor_id": x.actor_id,
                    "event": x.event,
                    "created_at": x.created_at.isoformat(),
                    "resource_id": x.resource_id,
                    "payload": x.payload,
                }
                for x in s.scalars(
                    q.order_by(EconomicsAuditLog.created_at.desc()).limit(200)
                )
            ]
        }


@router.get(BASE + "/evaluations")
def evaluations(request: Request, entity_id: str | None = None) -> dict:
    a = actor(request)
    with factory()() as s:
        q = select(EconomicsEvaluation).where(
            EconomicsEvaluation.workspace_id == a["workspace"]
        )
        if entity_id:
            q = q.where(EconomicsEvaluation.entity_id == entity_id)
        return {
            "rows": [
                {
                    "id": x.id,
                    "created_at": x.created_at.isoformat(),
                    "start": x.start_day.isoformat(),
                    "end": x.end_day.isoformat(),
                    "entity_id": x.entity_id,
                    "payload": x.payload,
                }
                for x in s.scalars(
                    q.order_by(EconomicsEvaluation.created_at.desc()).limit(100)
                )
            ]
        }


@router.get(BASE + "/evaluate")
def evaluation(
    request: Request,
    start: date | None = None,
    end: date | None = None,
    profile_id: str | None = None,
    level: Literal["account", "campaign", "adset", "ad"] = "account",
    account: str | None = None,
    campaign: str | None = None,
    adset: str | None = None,
    ad: str | None = None,
    offer: str | None = None,
    geo: str | None = Query(default=None, pattern=r"^[A-Z]{2}$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    sort_key: str | None = None,
    sort_direction: Literal["asc", "desc"] = "asc",
) -> dict:
    a = actor(request)
    if start is None and end is None:
        end = datetime.now(ZoneInfo("Europe/Moscow")).date() - timedelta(days=1)
        start = end - timedelta(days=6)
    if start is None or end is None or start > end or (end - start).days > 365:
        raise HTTPException(422, "ECONOMICS_INVALID_PERIOD")
    with factory().begin() as s:
        lock(s, a["workspace"])
        try:
            return evaluate(
                s,
                a["workspace"],
                Filters(
                    start,
                    end,
                    account=account,
                    campaign=campaign,
                    adset=adset,
                    ad=ad,
                    offer=offer,
                    geo=geo,
                ),
                level=level,
                selected=profile_id,
                offset=offset,
                limit=limit,
                sort_key=sort_key,
                sort_direction=sort_direction,
            )
        except ValueError:
            raise HTTPException(422, "ECONOMICS_INVALID_FILTER") from None
