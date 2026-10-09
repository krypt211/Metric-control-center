"""Operator endpoints submit commands; no provider credential enters this API."""
import os
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from backend.action_api import operator
from services.actions.engine import ActionEngine, ActionRejected
from services.actions.settings import policy_from_environment
from services.automation.batches import BatchEngine
from services.automation.rules import RuleEngine
from services.automation.schema import BulkCommand, RuleDefinition
from services.storage.models import ActionRequest, BatchAction, BatchItem, Rule, RuleRun, User

router = APIRouter(prefix="/api")


def context(actor_id):
    from backend.app import database_sessions
    factory = database_sessions()
    workspace = os.environ.get("WORKSPACE_ID", "default")
    with factory() as session:
        actor = session.get(User, actor_id)
        if not actor or actor.workspace_id != workspace or actor.role not in ("admin", "operator"):
            raise HTTPException(403, "Operator has no permission")
    return factory, workspace


def conflict(call):
    try:
        return call()
    except ActionRejected as error:
        raise HTTPException(409, str(error)) from None


@router.post("/batches", status_code=202)
def batch_submit(command: BulkCommand, actor_id=Depends(operator), key: str = Header(alias="Idempotency-Key")):
    factory, workspace = context(actor_id)
    engine = BatchEngine(ActionEngine(factory, policy_from_environment()))
    batch_id = conflict(lambda: engine.submit(workspace, actor_id, command, key))
    return batch_status(batch_id, actor_id)


@router.get("/batches/lookup")
def batch_lookup(key: str = Query(min_length=1, max_length=128), actor_id=Depends(operator)):
    factory, workspace = context(actor_id)
    with factory() as session:
        batch = session.scalar(select(BatchAction).where(BatchAction.workspace_id == workspace,
            BatchAction.initiator_id == actor_id, BatchAction.idempotency_key == key))
        if not batch:
            raise HTTPException(404, "Batch not registered yet")
        return batch_status(batch.id, actor_id)


@router.get("/batches/{batch_id}")
def batch_status(batch_id: str, actor_id=Depends(operator)):
    factory, workspace = context(actor_id)
    with factory() as session:
        batch = session.get(BatchAction, batch_id)
        if not batch or batch.workspace_id != workspace:
            raise HTTPException(404, "Batch not found")
        items = session.execute(select(BatchItem, ActionRequest).outerjoin(ActionRequest,
            BatchItem.request_id == ActionRequest.id).where(BatchItem.batch_id == batch_id)).all()
        return {"batch_id": batch_id, "created_at": batch.created_at.isoformat(), "operation": batch.payload["operation"],
            "items": [{"entity_id": item.entity_id, "request_id": item.request_id,
                "status": request.status if request else item.status, "reason": item.reason,
                "provenance": request.provenance if request else {}} for item, request in items]}


class RuleCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definition: RuleDefinition
    mode: Literal["OFF", "DRY_RUN", "ACTIVE"] = "DRY_RUN"
    revision: int | None = Field(default=None, ge=1)


def rule_json(rule):
    return {"id": rule.id, "mode": rule.status, "revision": rule.revision, "definition": rule.payload,
        "next_evaluation_at": rule.next_evaluation_at.isoformat() if rule.next_evaluation_at else None}


@router.get("/rules")
def rules_list(actor_id=Depends(operator)):
    factory, workspace = context(actor_id)
    with factory() as session:
        return {"rules": [rule_json(rule) for rule in session.scalars(select(Rule).where(
            Rule.workspace_id == workspace).order_by(Rule.created_at.desc()))]}


@router.post("/rules", status_code=201)
def rule_create(command: RuleCommand, actor_id=Depends(operator), key: str = Header(alias="Idempotency-Key")):
    # Stable UUID for create retries, scoped to workspace + server identity.
    from uuid import uuid5, NAMESPACE_URL
    if not key or len(key) > 128:
        raise HTTPException(422, "A valid idempotency key is required")
    factory, workspace = context(actor_id)
    rule_id = str(uuid5(NAMESPACE_URL, repr((workspace, actor_id, key))))
    engine = RuleEngine(ActionEngine(factory, policy_from_environment()))
    conflict(lambda: engine.create_once(workspace, actor_id, command.definition, command.mode, rule_id))
    with factory() as session:
        return rule_json(session.get(Rule, rule_id))


@router.put("/rules/{rule_id}")
def rule_update(rule_id: str, command: RuleCommand, actor_id=Depends(operator)):
    factory, workspace = context(actor_id)
    engine = RuleEngine(ActionEngine(factory, policy_from_environment()))
    conflict(lambda: engine.save(workspace, actor_id, command.definition, command.mode, rule_id, command.revision))
    with factory() as session:
        return rule_json(session.get(Rule, rule_id))


@router.post("/rules/{rule_id}/evaluate")
def rule_evaluate(rule_id: str, actor_id=Depends(operator)):
    factory, workspace = context(actor_id)
    return RuleEngine(ActionEngine(factory, policy_from_environment())).evaluate(rule_id, workspace)


@router.get("/rules/{rule_id}/runs")
def rule_runs(rule_id: str, actor_id=Depends(operator), limit: int = Query(default=100, ge=1, le=500)):
    factory, workspace = context(actor_id)
    with factory() as session:
        records = session.execute(select(RuleRun, ActionRequest).outerjoin(ActionRequest, RuleRun.request_id == ActionRequest.id).where(
            RuleRun.workspace_id == workspace, RuleRun.rule_id == rule_id).order_by(RuleRun.created_at.desc()).limit(limit)).all()
        return {"runs": [{"id": run.id, "at": run.created_at.isoformat(), "status": run.status,
            "request_id": run.request_id, "action_status": request.status if request else None, "details": run.payload} for run, request in records]}


@router.get("/audit")
def audit(actor_id=Depends(operator), limit: int = Query(default=100, ge=1, le=500)):
    factory, workspace = context(actor_id)
    with factory() as session:
        return {"actions": [{"id": request.id, "at": request.created_at.isoformat(), "action": request.action,
            "status": request.status, "provenance": request.provenance} for request in session.scalars(select(ActionRequest).where(
            ActionRequest.workspace_id == workspace).order_by(ActionRequest.created_at.desc()).limit(limit))]}
