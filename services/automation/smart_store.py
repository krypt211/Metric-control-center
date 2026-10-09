"""CAS, grants and immutable history for the simulation family of existing rules."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.automation.smart_models import RuleAuditLog, RuleGrant, RuleVersion
from services.automation.smart_schema import SmartRuleInput
from services.economics.store import lock, profile_row, utcnow
from services.providers.matching import identity_maps
from services.storage.models import AdAccount, Entity, Rule, User

STATES = ("SMART_DRY_RUN", "SMART_ARCHIVED")


def editor(s: Session, actor: dict[str, Any]) -> bool:
    grant = s.get(RuleGrant, (actor["workspace"], actor["id"]))
    return actor["role"] == "admin" or bool(
        actor["role"] == "operator" and grant and grant.can_edit
    )


def require_editor(s: Session, actor: dict[str, Any]) -> None:
    if not editor(s, actor):
        raise HTTPException(403, "RULE_EDIT_REQUIRED")


def get_rule(s: Session, workspace: str, key: str) -> Rule:
    row = s.get(Rule, key)
    if not row or row.workspace_id != workspace or row.status not in STATES:
        raise HTTPException(404, "RULE_NOT_FOUND")
    return row


def rule_json(row: Rule) -> dict[str, Any]:
    return {
        "id": row.id,
        "revision": row.revision,
        "deleted": row.status == "SMART_ARCHIVED",
        "created_at": row.created_at.isoformat(),
        "updated_by": row.owner_id,
        "definition": row.payload,
    }


def audit(
    s: Session, actor: dict[str, Any], key: str, event: str, payload: dict[str, Any]
) -> None:
    s.add(
        RuleAuditLog(
            id=str(uuid4()),
            workspace_id=actor["workspace"],
            actor_id=actor["id"],
            resource_id=key,
            event=event,
            payload=payload,
            created_at=utcnow(),
        )
    )


def validate_scope(s: Session, actor: dict[str, Any], rule: SmartRuleInput) -> None:
    if rule.profile_id:
        profile_row(s, actor["workspace"], rule.profile_id)
    accounts, entities = identity_maps(s, actor["workspace"])
    allowed = {
        accounts.get(a.id, a.id)
        for a in s.scalars(
            select(AdAccount).where(AdAccount.workspace_id == actor["workspace"])
        )
    }
    if not set(rule.selection.account_ids) <= allowed:
        raise HTTPException(422, "ACCOUNT_NOT_MAPPED")
    for kind in ("campaign", "adset", "ad"):
        key = getattr(rule.selection, kind)
        if key and key not in {
            entities.get(e.id, e.id)
            for e in s.scalars(
                select(Entity)
                .join(AdAccount)
                .where(
                    AdAccount.workspace_id == actor["workspace"], Entity.kind == kind
                )
            )
        }:
            raise HTTPException(422, "INVALID_ENTITY_SCOPE")


def save(
    s: Session,
    actor: dict[str, Any],
    config: SmartRuleInput | None,
    key: str | None = None,
    revision: int | None = None,
    *,
    deleted: bool = False,
    restore_revision: int | None = None,
) -> dict[str, Any]:
    lock(s, actor["workspace"])
    require_editor(s, actor)
    before = None
    if key:
        row = get_rule(s, actor["workspace"], key)
        if revision != row.revision:
            raise HTTPException(409, "RULE_VERSION_CONFLICT")
        before = rule_json(row)
        if restore_revision:
            version = s.scalar(
                select(RuleVersion).where(
                    RuleVersion.workspace_id == actor["workspace"],
                    RuleVersion.rule_id == key,
                    RuleVersion.revision == restore_revision,
                )
            )
            if not version:
                raise HTTPException(404, "RULE_VERSION_NOT_FOUND")
            config = SmartRuleInput.model_validate(version.payload["definition"])
        if config is None:
            config = SmartRuleInput.model_validate(row.payload)
        row.revision += 1
    else:
        assert config is not None
        row = Rule(
            id=str(uuid4()),
            workspace_id=actor["workspace"],
            status="SMART_DRY_RUN",
            owner_id=actor["id"],
            revision=1,
            created_at=utcnow(),
            payload={},
        )
        s.add(row)
    validate_scope(s, actor, config)
    row.payload = config.model_dump(mode="json")
    row.owner_id = actor["id"]
    row.status = "SMART_ARCHIVED" if deleted else "SMART_DRY_RUN"
    row.next_evaluation_at = None
    s.flush()
    result = {**rule_json(row), "updated_at": utcnow().isoformat()}
    s.add(
        RuleVersion(
            id=str(uuid4()),
            workspace_id=actor["workspace"],
            rule_id=row.id,
            revision=row.revision,
            actor_id=actor["id"],
            created_at=utcnow(),
            payload=result,
        )
    )
    audit(
        s,
        actor,
        row.id,
        "ARCHIVE"
        if deleted
        else "RESTORE"
        if restore_revision
        else "UPDATE"
        if before
        else "CREATE",
        {"before": before, "after": result},
    )
    return result


def grant(s: Session, actor: dict[str, Any], user_id: str, can_edit: bool) -> None:
    lock(s, actor["workspace"])
    if actor["role"] != "admin":
        raise HTTPException(403, "ADMIN_REQUIRED")
    user = s.get(User, user_id)
    if (
        not user
        or user.workspace_id != actor["workspace"]
        or user.role != "operator"
        or not user.is_active
    ):
        raise HTTPException(422, "INVALID_OPERATOR")
    row = s.get(RuleGrant, (actor["workspace"], user_id))
    before = row.can_edit if row else False
    if row:
        row.can_edit = can_edit
    else:
        s.add(
            RuleGrant(
                workspace_id=actor["workspace"], user_id=user_id, can_edit=can_edit
            )
        )
    audit(s, actor, user_id, "GRANT", {"before": before, "after": can_edit})
