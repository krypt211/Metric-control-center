"""ADMIN/CSRF preparation endpoints; deployment owns session authorization."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.auth import admin, csrf_check, factory
from services.meta import pilot
from services.providers.contracts import ProviderError

router = APIRouter()
BASE = "/api/admin/providers/meta/pilot"


class Prepare(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(pattern=r"^act_[0-9]{1,64}$")
    start: date
    end: date
    max_attempts: int = Field(default=20, ge=1, le=20)
    timeout_seconds: int = Field(default=600, ge=30, le=900)


@router.get(BASE)
def state(request: Request) -> dict:
    actor = admin(request)
    with factory()() as s:
        return pilot.metadata(s, actor["workspace"])


@router.post(BASE)
def prepare(body: Prepare, request: Request) -> dict:
    actor = admin(request)
    csrf_check(request, actor)
    try:
        with factory().begin() as s:
            row = pilot.prepared(
                s,
                actor["workspace"],
                body.account_id,
                body.start,
                body.end,
                body.max_attempts,
                body.timeout_seconds,
            )
            return {"id": row.id, "status": row.status, "live_enabled": False}
    except ProviderError as error:
        raise HTTPException(409, error.code) from None


@router.post(BASE + "/{identifier}/{operation}")
def change(identifier: str, operation: str, request: Request) -> dict:
    actor = admin(request)
    csrf_check(request, actor)
    if operation not in ("start", "cancel"):
        raise HTTPException(404, "NOT_FOUND")
    try:
        with factory().begin() as s:
            row = (
                pilot.start(s, actor["workspace"], identifier, actor["id"])
                if operation == "start"
                else pilot.stop(s, actor["workspace"], identifier)
            )
            return {"id": row.id, "status": row.status}
    except ProviderError as error:
        raise HTTPException(409, error.code) from None
