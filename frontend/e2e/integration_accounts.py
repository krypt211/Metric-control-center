import asyncio
import json
import os
import sys
from uuid import uuid4

import httpx
from sqlalchemy import func, select

from services.auth.sessions import cookie_name, create_session, new_user, utcnow
from services.meta.client import MetaClient
from services.meta.telemetry import MetaRequestMeter
from services.providers.contracts import ProviderError
from services.providers.credentials import encrypt
from services.providers.integration_models import WriteCredentialState
from services.providers.models import (
    ProviderAccountMapping,
    ProviderConnection,
    ProviderCredential,
)
from services.storage.database import make_engine, sessions
from services.storage.models import ActionExecution, AdAccount

factory = sessions(make_engine())
workspace = os.environ["WORKSPACE_ID"]
assert workspace.startswith("integration-ui-")
if len(sys.argv) > 1 and sys.argv[1] == "inspect":
    with factory() as s:
        row = s.get(WriteCredentialState, workspace)
        read = s.get(ProviderCredential, (workspace, "metricflow"))
        print(
            json.dumps(
                {
                    "encrypted": bool(
                        row and row.encrypted and "mfk_" not in row.encrypted
                    ),
                    "read_encrypted": read.encrypted,
                    "read_revision": s.get(
                        ProviderConnection, (workspace, "metricflow")
                    ).revision,
                    "action_executions": s.scalar(
                        select(func.count()).select_from(ActionExecution)
                    ),
                }
            )
        )
    raise SystemExit()
users = []
with factory.begin() as s:
    for role in ("admin", "viewer", "operator"):
        user = new_user(
            s,
            workspace,
            role + "@fixture.local",
            "Synthetic-fixture-password-12345",
            role,
        )
        s.flush()
        token, csrf, ttl = create_session(s, user)
        users.append(
            {
                "role": role,
                "cookie": {
                    "name": cookie_name(),
                    "value": token,
                    "httpOnly": True,
                    "sameSite": "Strict",
                    "url": "http://127.0.0.1:3001",
                },
                "csrf": csrf,
            }
        )
    for provider in ("metricflow", "meta"):
        s.add(
            ProviderConnection(
                workspace_id=workspace,
                provider=provider,
                enabled=provider == "metricflow",
                credential_source="encrypted",
                revision=7,
                config={"app_id": "101"} if provider == "meta" else {},
                status="healthy" if provider == "metricflow" else "disconnected",
                permissions={
                    "read": provider == "metricflow",
                    "scopes": ["analytics:read", "campaigns:read"],
                }
                if provider == "metricflow"
                else {},
                capabilities={},
                quota={},
                updated_at=utcnow(),
            )
        )
    s.add(
        ProviderCredential(
            workspace_id=workspace,
            provider="metricflow",
            encrypted=encrypt(
                workspace, "metricflow", {"token": "mfk_fixture_existing_read_key"}
            ),
            updated_at=utcnow(),
        )
    )
    aid = str(uuid4())
    s.add(
        AdAccount(
            id=aid,
            workspace_id=workspace,
            provider="meta",
            external_id="act_101",
            name="Synthetic fixture account",
            currency="USD",
            timezone="UTC",
            observed_at=utcnow(),
        )
    )
    s.flush()
    s.add(
        ProviderAccountMapping(
            account_id=aid,
            workspace_id=workspace,
            canonical_id=aid,
            meta_account_id="act_101",
            proof="fixture",
            updated_at=utcnow(),
        )
    )


async def meter():
    calls = []

    def mock(r):
        calls.append(r)
        return (
            httpx.Response(
                200, json={"data": []}, headers={"X-App-Usage": '{"call_count":10}'}
            )
            if len(calls) == 1
            else httpx.Response(
                429,
                json={"error": {"code": 80004, "error_subcode": 42}},
                headers={
                    "Retry-After": "30",
                    "X-App-Usage": '{"call_count":99}',
                    "X-FB-Ads-Insights-Throttle": '{"ads_api_access_tier":"full_access","acc_id_util_pct":99}',
                },
            )
        )

    client = MetaClient(
        {
            "app_id": "101",
            "app_secret": "fixture-meta-app-secret-12345",
            "token": "fixture-meta-token-12345",
            "graph_version": "v26.0",
        },
        transport=httpx.MockTransport(mock),
        meter=MetaRequestMeter(
            factory, workspace, "101", source="acceptance_mock", interval=0
        ),
    )
    try:
        await client.get("act_101/campaigns")
        try:
            await client.get("act_101/insights")
        except ProviderError as error:
            assert getattr(error, "code", None) == "META_RATE_LIMIT"
    finally:
        await client.close()
    assert len(calls) == 2


asyncio.run(meter())
print(json.dumps({"users": users, "workspace": workspace}))
