from decimal import Decimal
import hmac
import os
from pathlib import Path
from typing import Literal

from fastapi import Request, APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from services.actions.engine import ActionEngine, ActionRejected
from services.actions.settings import policy_from_environment
from services.storage.models import ActionLog, ActionRequest, AdAccount, Entity, User

router = APIRouter(prefix="/api/actions")


def operator(request: Request, authorization: str | None = Header(default=None)) -> str:
    from services.auth.sessions import auth_enabled
    if auth_enabled():
        from backend.auth import identity
        return identity(request)["id"]
    path = os.environ.get("ACTION_API_TOKEN_FILE")
    if not path or not Path(path).is_file():
        raise HTTPException(503, "Operator access is not configured")
    expected = Path(path).read_text(encoding="utf-8-sig").strip()
    if not expected or not authorization or not hmac.compare_digest(authorization.encode(), f"Bearer {expected}".encode()):
        raise HTTPException(401, "Operator authentication required")
    # Identity comes from server configuration, never from a request body.
    return os.environ.get("ACTION_OPERATOR_ID", "local-operator")


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str
    entity_type: Literal["campaign", "adset", "ad"]
    action: Literal["pause", "enable", "budget_set"]
    value: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)


@router.post("", status_code=202)
def enqueue(command: Command, actor_id=Depends(operator), idempotency_key: str = Header(alias="Idempotency-Key")):
    from backend.app import database_sessions
    factory = database_sessions()
    workspace = os.environ.get("WORKSPACE_ID", "default")
    with factory() as session:
        # The public API accepts a provider ID. Resolve it within this workspace.
        entities = session.scalars(select(Entity).join(AdAccount).where(
            AdAccount.workspace_id == workspace, AdAccount.provider == "metricflow",
            Entity.external_id == command.entity_id, Entity.kind == command.entity_type,
        )).all()
        if len(entities) != 1:
            raise HTTPException(422, "Entity is missing or ambiguous")
        entity_id = entities[0].id
    try:
        request_id = ActionEngine(factory, policy_from_environment()).enqueue(
            workspace, actor_id, entity_id, command.action, command.value, idempotency_key
        )
    except ActionRejected as error:
        raise HTTPException(409, str(error)) from None
    return {"request_id": request_id}


@router.get("/{request_id}")
def status(request_id: str, actor_id=Depends(operator)):
    from backend.app import database_sessions
    workspace = os.environ.get("WORKSPACE_ID", "default")
    with database_sessions()() as session:
        actor = session.get(User, actor_id)
        request = session.get(ActionRequest, request_id)
        if not actor or actor.workspace_id != workspace or actor.role not in ("admin", "operator"):
            raise HTTPException(403, "Operator has no permission")
        if not request or request.workspace_id != workspace:
            raise HTTPException(404, "Request not found")
        events = session.scalars(select(ActionLog).where(ActionLog.request_id == request_id).order_by(ActionLog.created_at)).all()
        return {"request_id": request_id, "status": request.status, "provenance": request.provenance, "events": [
            {"event": event.event, "at": event.created_at.isoformat(), "details": event.details} for event in events
        ]}


@router.get("/capabilities/info")
def capabilities(actor_id=Depends(operator)):
    from backend.app import database_sessions
    policy = policy_from_environment()
    with database_sessions()() as session:
        actor = session.get(User, actor_id)
        permitted = bool(actor and actor.workspace_id == os.environ.get("WORKSPACE_ID", "default") and actor.role in ("admin", "operator"))
    from services.actions.providers import PROVIDERS
    return {"operator_enabled": permitted, "actions_enabled": policy.enabled and permitted, "budget_enabled": policy.enabled and permitted and bool(policy.budget_contract and policy.budget_contract.get("verified") is True),
        "providers": {name: sorted(provider.actions) for name, provider in PROVIDERS.items()}, "bid_enabled": False}


@router.get("/lookup/by-key")
def lookup(key: str = Query(min_length=1, max_length=128), actor_id=Depends(operator)):
    from backend.app import database_sessions
    workspace = os.environ.get("WORKSPACE_ID", "default")
    with database_sessions()() as session:
        request = session.scalar(select(ActionRequest).where(
            ActionRequest.workspace_id == workspace, ActionRequest.initiator_id == actor_id,
            ActionRequest.idempotency_key == key,
        ))
        if not request:
            raise HTTPException(404, "Request not registered yet")
        request_id = request.id
    return status(request_id, actor_id)
