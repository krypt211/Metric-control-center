"""Private credential-management API. GET-only provider verification, no dispatcher."""

from __future__ import annotations

import asyncio
import os
import re
from functools import lru_cache
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, StrictInt

from backend.auth import csrf_check
from services.actions.write_credentials import (
    WriteCredentialError,
    WriteCredentialVault,
)
from services.actions.write_settings import change, metadata
from services.auth.sessions import authenticate, cookie_name
from services.meta.telemetry import lock
from services.metricflow.errors import (
    AuthenticationError,
    MetricFlowError,
    PermissionDenied,
    RateLimitExceeded,
    SubscriptionRequired,
)
from services.metricflow.reader import MetricFlowConnector
from services.providers.contracts import ProviderError
from services.providers.integration_models import (
    WriteCredentialAudit,
    WriteCredentialState,
)
from services.providers.manager import ProviderManager
from services.storage.database import make_engine, sessions
from services.sync.engine import utc_now

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@lru_cache
def factory():
    return sessions(make_engine())


@lru_cache
def vault():
    return WriteCredentialVault.from_environment()


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: StrictInt = Field(ge=0)
    token: SecretStr | None = Field(default=None, min_length=8, max_length=4096)
    confirm: StrictBool = False


@app.exception_handler(RequestValidationError)
async def invalid_input(request, error):
    return JSONResponse({"detail": "INVALID_INPUT"}, status_code=422)


@app.exception_handler(WriteCredentialError)
async def vault_error(request, error):
    return JSONResponse(
        {
            "detail": "WRITE_TOKEN_INVALID"
            if str(error) == "WRITE_VAULT_INVALID_TOKEN"
            else "WRITE_VAULT_UNAVAILABLE"
        },
        status_code=422 if str(error) == "WRITE_VAULT_INVALID_TOKEN" else 503,
    )


def actor(request, mutation=False):
    value = authenticate(factory(), request.cookies.get(cookie_name()))
    if not value:
        raise HTTPException(401, "AUTHENTICATION_REQUIRED")
    if mutation:
        if value["role"] != "admin":
            raise HTTPException(403, "ADMIN_REQUIRED")
        configured = urlsplit(os.environ.get("APP_ORIGIN", ""))
        if configured.scheme != "https" and not (
            configured.scheme == "http"
            and configured.hostname in ("localhost", "127.0.0.1")
        ):
            raise HTTPException(403, "TRUSTED_HTTPS_OR_LOCALHOST_REQUIRED")
        csrf_check(request, value)
    return value


def provider_transport():
    # Isolated browser test service only; impossible on the working workspace.
    if os.environ.get("CREDENTIAL_TEST_MODE") == "true":
        if os.environ.get("APP_ENV") == "production" or not os.environ.get(
            "WORKSPACE_ID", ""
        ).startswith("integration-ui-"):
            raise RuntimeError("ISOLATED_MOCK_WORKSPACE_REQUIRED")

        def respond(request):
            if request.method != "GET" or request.url.path != "/api/v1/me":
                raise RuntimeError("UNEXPECTED_PROVIDER_REQUEST")
            token = request.headers.get("authorization", "")
            if "fixture-invalid" in token:
                return httpx.Response(401, json={})
            if "fixture-unavailable" in token:
                raise httpx.ConnectError("mock unavailable")
            return httpx.Response(
                200,
                json={
                    "access_state": "active_paid",
                    "api_key": {
                        "scopes": ["campaigns:read"]
                        if "fixture-read-only" in token
                        else ["campaigns:write"]
                    },
                },
            )

        return httpx.MockTransport(respond)
    return None


@app.get("/health/live")
def health():
    return {"status": "ok"}


@app.get("/credentials/metricflow")
def state(request: Request):
    a = actor(request)
    with factory()() as s:
        return {**metadata(s, a["workspace"]), "can_manage": a["role"] == "admin"}


def persist_change(a, body, operation):
    with factory().begin() as s:
        return change(
            s,
            a,
            vault(),
            body.revision,
            operation,
            token=body.token.get_secret_value() if body.token else None,
            confirm=body.confirm,
        )


def stored_token(a, revision):
    with factory()() as s:
        row = s.get(WriteCredentialState, a["workspace"])
        if not row or not row.encrypted:
            raise HTTPException(409, "WRITE_NOT_CONFIGURED")
        if row.revision != revision:
            raise HTTPException(409, "WRITE_REVISION_CONFLICT")
        return vault().unseal(row.encrypted.encode(), a["workspace"], revision).token


def persist_check(a, revision, status, scopes, access):
    with factory().begin() as s:
        lock(s, "write-credential:" + a["workspace"])
        row = s.get(WriteCredentialState, a["workspace"])
        if row.revision != revision or not row.encrypted:
            raise HTTPException(409, "WRITE_REVISION_CONFLICT")
        row.status = status
        row.scopes = scopes
        row.access_state = access
        row.checked_at = utc_now()
        s.add(
            WriteCredentialAudit(
                id=str(uuid4()),
                workspace_id=a["workspace"],
                actor_id=a["id"],
                operation="check",
                revision=row.revision,
                created_at=utc_now(),
            )
        )
        return metadata(s, a["workspace"])


@app.post("/credentials/metricflow/{operation}")
async def mutate(operation: str, body: Command, request: Request):
    if operation not in {"save", "replace", "delete", "check"}:
        raise HTTPException(404, "NOT_FOUND")
    a = await asyncio.to_thread(actor, request, True)
    if operation != "check":
        if operation != "delete" and body.token is None:
            raise HTTPException(422, "WRITE_TOKEN_REQUIRED")
        return await asyncio.to_thread(persist_change, a, body, operation)
    if body.token is not None:
        raise HTTPException(422, "CHECK_USES_STORED_CREDENTIAL")
    token = await asyncio.to_thread(stored_token, a, body.revision)
    manager = ProviderManager(factory(), a["workspace"])

    async def reserve():
        await asyncio.to_thread(manager.reserve, "metricflow")

    status = "PERMISSIONS_UNVERIFIED"
    scopes = []
    access = None
    try:
        async with MetricFlowConnector(
            token,
            transport=provider_transport(),
            before_request=reserve,
            read_retries=0,
        ) as client:
            data = await client.get_me()
        # Shapes observed from the documented /me response, no asset permission inference.
        key = data.get("api_key", {}) if isinstance(data, dict) else {}
        values = (
            key.get("scopes", data.get("scopes")) if isinstance(key, dict) else None
        )
        if isinstance(values, list) and all(
            isinstance(v, str)
            and (v == "*" or bool(re.fullmatch(r"[a-z_]{1,32}:(?:read|write)", v)))
            for v in values
        ):
            scopes = values
            status = (
                "SCOPES_VERIFIED"
                if "campaigns:write" in scopes
                else "PERMISSIONS_PARTIAL"
            )
        reported = data.get("access_state") if isinstance(data, dict) else None
        access = (
            reported
            if reported in ("active_paid", "expired", "free", "active_free", "inactive")
            else None
        )
        if access != "active_paid":
            status = "PERMISSIONS_UNVERIFIED"
    except AuthenticationError:
        status = "INVALID_CREDENTIAL"
    except SubscriptionRequired:
        status = "PERMISSIONS_UNVERIFIED"
        access = "expired"
    except PermissionDenied:
        status = "PERMISSIONS_PARTIAL"
    except RateLimitExceeded as error:
        await asyncio.to_thread(manager.failure, "metricflow", error, revision=-1)
        status = "PROVIDER_UNAVAILABLE"
    except (MetricFlowError, ProviderError):
        status = "PROVIDER_UNAVAILABLE"
    return await asyncio.to_thread(
        persist_check, a, body.revision, status, scopes, access
    )
