"""Local diagnostics and fixed private Docker credential provisioning boundary."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from backend.auth import admin, csrf_check, factory, identity
from services.actions.write_settings import metadata
from services.meta.diagnostics import estimate, report
from services.providers.integration_models import MetaRequestAttempt
from services.providers.models import ProviderConnection
from services.storage.models import AdAccount

router = APIRouter()
BASE = "/api/admin/providers"
# Fixed Compose service, no host port. Cannot be overridden by input/env/redirect.
CREDENTIAL_SERVICE = "http://credential-manager:8002"


@router.get(BASE + "/metricflow/write-credentials")
def write_state(request: Request):
    a = identity(request)
    with factory()() as s:
        return {
            **metadata(s, a["workspace"]),
            "can_manage": a["role"] == "admin",
            "management_available": os.environ.get("CREDENTIAL_MANAGEMENT_ENABLED")
            == "true",
        }


@router.post(BASE + "/metricflow/write-credentials/{operation}")
async def write_change(operation: str, request: Request):
    a = admin(request)
    csrf_check(request, a)
    if operation not in {"save", "replace", "check", "delete"}:
        raise HTTPException(404, "NOT_FOUND")
    if os.environ.get("CREDENTIAL_MANAGEMENT_ENABLED") != "true":
        raise HTTPException(503, "CREDENTIAL_MANAGER_UNAVAILABLE")
    body = await request.body()
    if len(body) > 8192:
        raise HTTPException(413, "CREDENTIAL_INPUT_TOO_LARGE")
    headers = {
        k: v
        for k, v in request.headers.items()
        if k in {"cookie", "origin", "x-csrf-token"}
    }
    headers["content-type"] = "application/json"
    try:
        async with httpx.AsyncClient(
            timeout=40, follow_redirects=False, trust_env=False
        ) as client:
            result = await client.post(
                CREDENTIAL_SERVICE + "/credentials/metricflow/" + operation,
                headers=headers,
                content=body,
            )
        return JSONResponse(
            result.json()
            if result.status_code < 500
            else {"detail": "CREDENTIAL_MANAGER_UNAVAILABLE"},
            status_code=result.status_code,
        )
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "CREDENTIAL_MANAGER_UNAVAILABLE") from None


@router.get(BASE + "/meta/usage")
def meta_usage(request: Request):
    a = identity(request)
    with factory()() as s:
        result = report(s, a["workspace"])
    from redis.exceptions import RedisError

    from backend.auth import limiter

    try:
        result["scheduler_status"] = (
            "RUNNING" if limiter().get("mcc:heartbeat:scheduler") else "NO_HEARTBEAT"
        )
    except RedisError:
        result["scheduler_status"] = "UNKNOWN"
    return result


@router.get(BASE + "/meta/requests")
def meta_requests(
    request: Request,
    account: str | None = Query(default=None, max_length=36),
    endpoint: str | None = Query(default=None, max_length=32),
    error_code: int | None = None,
    run_id: str | None = Query(default=None, max_length=36),
    start: datetime | None = None,
    end: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
):
    a = identity(request)
    query = select(MetaRequestAttempt).where(
        MetaRequestAttempt.workspace_id == a["workspace"]
    )
    for column, value in (
        (MetaRequestAttempt.account_id, account),
        (MetaRequestAttempt.endpoint, endpoint),
        (MetaRequestAttempt.error_code, error_code),
        (MetaRequestAttempt.run_id, run_id),
    ):
        if value is not None:
            query = query.where(column == value)
    if start:
        query = query.where(MetaRequestAttempt.started_at >= start)
    if end:
        query = query.where(MetaRequestAttempt.started_at <= end)
    with factory()() as s:
        total = s.scalar(select(func.count()).select_from(query.subquery()))
        rows = s.scalars(
            query.order_by(MetaRequestAttempt.started_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        names = (
            "id",
            "app_id",
            "account_id",
            "endpoint",
            "method",
            "operation",
            "run_id",
            "attempt",
            "page",
            "http_status",
            "duration_ms",
            "retry_reason",
            "error_code",
            "error_subcode",
            "outcome",
            "usage",
            "complexity",
            "source",
        )
        return {
            "total": total,
            "rows": [
                {
                    **{k: getattr(r, k) for k in names},
                    "timestamp": r.started_at.isoformat(),
                    "provider": "META",
                    "complexity_basis": "LOCAL_ESTIMATE",
                }
                for r in rows
            ],
        }


class EstimateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accounts: int = Field(default=1, ge=1, le=50)
    days: Literal[1, 7, 30] = 1
    object_counts: dict[Literal["campaign", "adset", "ad", "creative"], int] | None = (
        None
    )


@router.post(BASE + "/meta/estimate")
def meta_estimate(body: EstimateInput, request: Request):
    a = identity(request)
    csrf_check(request, a)
    if body.object_counts and any(
        v < 0 or v > 100000 for v in body.object_counts.values()
    ):
        raise HTTPException(422, "INVALID_OBJECT_COUNTS")
    with factory()() as s:
        return estimate(
            s,
            a["workspace"],
            body.accounts,
            body.days,
            object_counts=body.object_counts,
        )


class PacingInput(BaseModel):
    request_interval_seconds: int = Field(ge=1, le=600)
    account_ids: list[str] | None = Field(default=None, max_length=3)


@router.put(BASE + "/meta/pacing")
def meta_pacing(body: PacingInput, request: Request):
    a = admin(request)
    csrf_check(request, a)
    with factory().begin() as s:
        row = s.get(ProviderConnection, (a["workspace"], "meta"))
        if not row:
            raise HTTPException(404, "PROVIDER_NOT_FOUND")
        settings = {
            **row.config,
            "request_interval_seconds": body.request_interval_seconds,
        }
        if body.account_ids is not None:
            for key in body.account_ids:
                account = s.get(AdAccount, key)
                if (
                    not account
                    or account.workspace_id != a["workspace"]
                    or account.provider != "meta"
                ):
                    raise HTTPException(422, "INVALID_META_ACCOUNTS")
            settings["sync_account_ids"] = list(dict.fromkeys(body.account_ids))
        row.config = settings
    return {
        "local_limit": True,
        "request_interval_seconds": body.request_interval_seconds,
        "app_concurrency": 1,
        "account_concurrency": 1,
    }
