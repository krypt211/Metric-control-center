"""Workspace-scoped economics CRUD, audit, overlap protection and inheritance."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from services.economics.models import (
    ApprovalObservation,
    EconomicsAssignment,
    EconomicsAuditLog,
    EconomicsGrant,
    EconomicsProfile,
)
from services.economics.schema import AssignmentInput, ObservationInput, ProfileInput
from services.storage.models import AdAccount, Entity, User


def utcnow() -> datetime:
    return datetime.now(UTC)


def lock(session: Session, workspace: str) -> None:
    """Serialize local configuration changes, including overlap checks."""
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        key = int.from_bytes(
            hashlib.sha256(("economics:" + workspace).encode()).digest()[:8],
            "big",
            signed=True,
        )
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def editor(session: Session, actor: dict[str, Any]) -> bool:
    if actor["role"] == "admin":
        return True
    grant = session.get(EconomicsGrant, (actor["workspace"], actor["id"]))
    return bool(actor["role"] == "operator" and grant and grant.can_edit)


def require_editor(session: Session, actor: dict[str, Any]) -> None:
    if not editor(session, actor):
        raise HTTPException(403, "ECONOMICS_EDIT_REQUIRED")


def profile_row(
    session: Session, workspace: str, key: str, *, deleted: bool = False
) -> EconomicsProfile:
    row = session.get(EconomicsProfile, key)
    if not row or row.workspace_id != workspace or (row.deleted and not deleted):
        raise HTTPException(404, "ECONOMICS_PROFILE_NOT_FOUND")
    return row


def profile_json(row: EconomicsProfile) -> dict[str, Any]:
    return {
        "id": row.id,
        "version": row.version,
        "deleted": row.deleted,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        **row.payload,
    }


def audit(
    session: Session,
    actor: dict[str, Any],
    resource: str,
    event: str,
    before: object,
    after: object,
) -> None:
    session.add(
        EconomicsAuditLog(
            id=str(uuid4()),
            workspace_id=actor["workspace"],
            actor_id=actor["id"],
            resource_id=resource,
            event=event,
            payload={"before": before, "after": after},
            created_at=utcnow(),
        )
    )


def create_profile(
    session: Session, actor: dict[str, Any], config: ProfileInput
) -> dict[str, Any]:
    row = EconomicsProfile(
        id=str(uuid4()),
        workspace_id=actor["workspace"],
        created_by=actor["id"],
        version=1,
        payload=config.model_dump(mode="json"),
        deleted=False,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(row)
    session.flush()
    audit(session, actor, row.id, "PROFILE_CREATE", None, profile_json(row))
    return profile_json(row)


def change_profile(
    session: Session,
    actor: dict[str, Any],
    key: str,
    version: int,
    payload: ProfileInput | None,
    *,
    delete: bool = False,
    restore_version: int | None = None,
) -> dict[str, Any]:
    row = profile_row(session, actor["workspace"], key, deleted=True)
    if row.version != version:
        raise HTTPException(409, "ECONOMICS_VERSION_CONFLICT")
    before = profile_json(row)
    if restore_version is not None:
        history = session.scalars(
            select(EconomicsAuditLog)
            .where(
                EconomicsAuditLog.workspace_id == actor["workspace"],
                EconomicsAuditLog.resource_id == key,
            )
            .order_by(EconomicsAuditLog.created_at.desc())
        ).all()
        found = next(
            (
                x.payload["after"]
                for x in history
                if isinstance(x.payload.get("after"), dict)
                and x.payload["after"].get("version") == restore_version
            ),
            None,
        )
        if found is None:
            raise HTTPException(404, "ECONOMICS_VERSION_NOT_FOUND")
        row.payload = ProfileInput.model_validate(
            {k: v for k, v in found.items() if k in ProfileInput.model_fields}
        ).model_dump(mode="json")
        row.deleted = False
    elif payload is not None:
        row.payload = payload.model_dump(mode="json")
        row.deleted = False
    else:
        row.deleted = delete
    row.version += 1
    row.updated_at = utcnow()
    audit(
        session,
        actor,
        key,
        "PROFILE_RESTORE"
        if restore_version
        else "PROFILE_DELETE"
        if delete
        else "PROFILE_UPDATE",
        before,
        profile_json(row),
    )
    return profile_json(row)


def validate_scope(
    session: Session, workspace: str, scope_type: str, scope_id: str
) -> None:
    if scope_type == "profile":
        return
    if scope_type == "account":
        account_row = session.get(AdAccount, scope_id)
        valid = bool(account_row and account_row.workspace_id == workspace)
    else:
        entity_row = session.get(Entity, scope_id)
        account = session.get(AdAccount, entity_row.account_id) if entity_row else None
        valid = bool(
            entity_row
            and entity_row.kind == scope_type
            and account
            and account.workspace_id == workspace
        )
    if not valid:
        raise HTTPException(404, "ECONOMICS_SCOPE_NOT_FOUND")


def assign(
    session: Session, actor: dict[str, Any], command: AssignmentInput
) -> dict[str, Any]:
    profile_row(session, actor["workspace"], command.profile_id)
    validate_scope(session, actor["workspace"], command.scope_type, command.scope_id)
    candidates = session.scalars(
        select(EconomicsAssignment).where(
            EconomicsAssignment.workspace_id == actor["workspace"],
            EconomicsAssignment.scope_type == command.scope_type,
            EconomicsAssignment.scope_id == command.scope_id,
        )
    ).all()
    for old in candidates:
        # Different explicitly named Offer/GEO groups can coexist, never guessed by names.
        old_profile = profile_row(
            session, actor["workspace"], old.profile_id, deleted=True
        )
        new_profile = profile_row(session, actor["workspace"], command.profile_id)
        if command.scope_type == "profile" and (
            old_profile.payload["offer"],
            old_profile.payload["geo"],
        ) != (new_profile.payload["offer"], new_profile.payload["geo"]):
            continue
        if command.effective_start <= (
            old.effective_end or date.max
        ) and old.effective_start <= (command.effective_end or date.max):
            raise HTTPException(409, "ECONOMICS_ASSIGNMENT_OVERLAP")
    row = EconomicsAssignment(
        id=str(uuid4()),
        workspace_id=actor["workspace"],
        profile_id=command.profile_id,
        scope_type=command.scope_type,
        scope_id=command.scope_id,
        effective_start=command.effective_start,
        effective_end=command.effective_end,
        updated_at=utcnow(),
    )
    session.add(row)
    session.flush()
    out = {"id": row.id, **command.model_dump(mode="json")}
    audit(session, actor, row.id, "ASSIGNMENT_CREATE", None, out)
    return out


def observe(
    session: Session, actor: dict[str, Any], command: ObservationInput
) -> dict[str, Any]:
    profile = profile_row(session, actor["workspace"], command.profile_id)
    validate_scope(session, actor["workspace"], command.scope_type, command.scope_id)
    if command.currency != profile.payload[
        "currency"
    ] or command.lead_source != profile.payload.get("lead_source", "meta"):
        raise HTTPException(422, "ECONOMICS_OBSERVATION_PROFILE_MISMATCH")
    siblings = session.scalars(
        select(ApprovalObservation).where(
            ApprovalObservation.workspace_id == actor["workspace"],
            ApprovalObservation.profile_id == command.profile_id,
            ApprovalObservation.scope_type == command.scope_type,
            ApprovalObservation.scope_id == command.scope_id,
        )
    ).all()
    old = next((x for x in siblings if x.cohort == command.cohort), None)
    if (old.version if old else 0) != command.version:
        raise HTTPException(409, "ECONOMICS_VERSION_CONFLICT")
    for other in siblings:
        if (
            other is not old
            and command.start <= other.end_day
            and other.start_day <= command.end
        ):
            raise HTTPException(409, "ECONOMICS_OBSERVATION_OVERLAP")
    before = {"version": old.version, **old.payload} if old else None
    row = old or ApprovalObservation(
        id=str(uuid4()),
        workspace_id=actor["workspace"],
        profile_id=command.profile_id,
        scope_type=command.scope_type,
        scope_id=command.scope_id,
        cohort=command.cohort,
    )
    row.start_day = command.start
    row.end_day = command.end
    row.version = command.version + 1
    row.payload = {
        k: v for k, v in command.model_dump(mode="json").items() if k != "version"
    }
    row.updated_at = utcnow()
    if old is None:
        session.add(row)
    session.flush()
    out = {
        "id": row.id,
        "version": row.version,
        "quality": "ACTUAL_MANUAL",
        "updated_at": row.updated_at.isoformat(),
        **row.payload,
    }
    audit(
        session,
        actor,
        row.id,
        "OBSERVATION_UPDATE" if old else "OBSERVATION_CREATE",
        before,
        out,
    )
    return out


def grant_edit(
    session: Session, actor: dict[str, Any], user_id: str, can_edit: bool
) -> dict[str, Any]:
    if actor["role"] != "admin":
        raise HTTPException(403, "ADMIN_REQUIRED")
    user = session.get(User, user_id)
    if not user or user.workspace_id != actor["workspace"] or user.role != "operator":
        raise HTTPException(404, "ECONOMICS_OPERATOR_NOT_FOUND")
    row = session.get(EconomicsGrant, (actor["workspace"], user_id))
    before = row.can_edit if row else False
    if row is None:
        row = EconomicsGrant(
            workspace_id=actor["workspace"], user_id=user_id, can_edit=can_edit
        )
        session.add(row)
    else:
        row.can_edit = can_edit
    out = {"user_id": user_id, "can_edit": can_edit}
    audit(session, actor, user_id, "EDIT_GRANT", before, out)
    return out
