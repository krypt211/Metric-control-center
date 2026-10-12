"""Isolated real auth/DB and mock-only external requests."""

import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from test_auth import AuthTests
from test_providers import CREDS
from test_sync import StorageFixture

from services.actions import credential_service as service
from services.actions.write_credentials import WriteCredentialVault
from services.meta.client import MetaClient
from services.meta.diagnostics import estimate, report
from services.meta.telemetry import MetaRequestMeter, usage_headers
from services.providers.contracts import ProviderError
from services.providers.integration_models import (
    MetaRateState,
    MetaRequestAttempt,
    WriteCredentialState,
)
from services.storage.models import ActionExecution


class WriteSettingsTests(AuthTests):
    def setUp(self):
        super().setUp()
        self.mock_vault = WriteCredentialVault(
            Path(self.directory.name) / "write", Fernet.generate_key()
        )
        self.calls = []

        def handler(r):
            self.calls.append(r)
            assert r.method == "GET" and r.url.path == "/api/v1/me"
            return httpx.Response(
                200,
                json={
                    "access_state": "active_paid",
                    "api_key": {"scopes": ["campaigns:write"]},
                },
            )

        self.extra = [
            patch(
                "services.actions.credential_service.factory",
                return_value=self.sessions,
            ),
            patch(
                "services.actions.credential_service.vault",
                return_value=self.mock_vault,
            ),
            patch(
                "services.actions.credential_service.provider_transport",
                return_value=httpx.MockTransport(handler),
            ),
            patch.dict("os.environ", {"APP_ORIGIN": "http://127.0.0.1:3001"}),
        ]
        for p in self.extra:
            p.start()
        self.private = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=service.app), base_url="http://test"
        )

    async def asyncTearDown(self):
        await self.private.aclose()
        await super().asyncTearDown()

    def tearDown(self):
        for p in reversed(self.extra):
            p.stop()
        super().tearDown()

    async def action(self, op, body, csrf=True):
        self.private.cookies.update(self.client.cookies)
        return await self.private.post(
            "/credentials/metricflow/" + op,
            json=body,
            headers=await self.csrf() if csrf else {},
        )

    async def test_write_full_lifecycle_secret_revision_and_zero_ad_write(self):
        await self.login("admin")
        token = "mfk_fixture_write_synthetic_123"
        saved = await self.action("save", {"revision": 0, "token": token})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertNotIn(token, saved.text)
        with self.sessions() as s:
            row = s.get(WriteCredentialState, "default")
            self.assertNotIn(token, row.encrypted)
            self.assertEqual(
                self.mock_vault.unseal(row.encrypted.encode(), "default", 1).token,
                token,
            )
        self.assertEqual(
            (await self.action("save", {"revision": 1, "token": token})).status_code,
            409,
        )
        self.assertEqual(
            (await self.action("replace", {"revision": 1, "token": token})).status_code,
            409,
        )
        checked = await self.action("check", {"revision": 1})
        self.assertTrue(checked.json()["scope_verified"])
        self.assertEqual(checked.json()["permissions"], "PERMISSIONS_UNVERIFIED")
        self.assertEqual(checked.json()["live_actions"], "LIVE_ACTIONS_BLOCKED")
        self.assertEqual(
            (
                await self.action(
                    "replace", {"revision": 1, "confirm": True, "token": token + "-new"}
                )
            ).json()["revision"],
            2,
        )
        self.assertEqual(
            (await self.action("delete", {"revision": 1, "confirm": True})).status_code,
            409,
        )
        deleted = await self.action("delete", {"revision": 2, "confirm": True})
        self.assertFalse(deleted.json()["configured"])
        self.assertEqual(deleted.json()["revision"], 3)
        self.assertEqual(len(self.calls), 1)
        with self.sessions() as s:
            self.assertEqual(
                s.scalar(select(func.count()).select_from(ActionExecution)), 0
            )

    async def test_other_reported_scope_verbs_do_not_hide_exact_write_scope(self):
        await self.login("admin")
        await self.action(
            "save", {"revision": 0, "token": "mfk_fixture_scope_acceptance"}
        )
        for scopes, verified in (
            (["campaigns:read", "entities:write", "ai:use"], False),
            (["campaigns:write", "ai:use", "seeding:*"], True),
        ):

            def handler(request, scopes=scopes):
                self.assertEqual(request.method, "GET")
                self.assertEqual(request.url.path, "/api/v1/me")
                return httpx.Response(
                    200,
                    json={"api_key": {"scopes": scopes}, "access_state": "active_paid"},
                )

            with patch(
                "services.actions.credential_service.provider_transport",
                return_value=httpx.MockTransport(handler),
            ):
                result = await self.action("check", {"revision": 1})
            self.assertEqual(result.json()["scopes"], scopes)
            self.assertEqual(result.json()["scope_verified"], verified)
            self.assertEqual(result.json()["live_actions"], "LIVE_ACTIONS_BLOCKED")

    async def test_write_roles_csrf_workspace_and_no_validation_echo(self):
        for role in ("viewer", "operator"):
            await self.login(role)
            self.assertEqual(
                (
                    await self.action(
                        "save", {"revision": 0, "token": "mfk_fixture_write"}
                    )
                ).status_code,
                403,
            )
        await self.login("admin")
        self.assertEqual(
            (
                await self.action(
                    "save", {"revision": 0, "token": "mfk_fixture_write"}, False
                )
            ).status_code,
            403,
        )
        for token in ("short", "malformed token", ""):
            r = await self.action("save", {"revision": 0, "token": token})
            self.assertEqual(r.status_code, 422)
            self.assertNotIn(token, r.text) if token else None
        self.assertEqual(
            (
                await self.action(
                    "save", {"revision": True, "token": "mfk_fixture_write"}
                )
            ).status_code,
            422,
        )
        self.assertEqual(self.calls, [])

    async def test_scope_missing_unavailable_and_tampering(self):
        await self.login("admin")
        await self.action("save", {"revision": 0, "token": "mfk_fixture_read_only"})
        with patch(
            "services.actions.credential_service.provider_transport",
            return_value=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    json={
                        "access_state": "active_paid",
                        "api_key": {"scopes": ["campaigns:read"]},
                    },
                )
            ),
        ):
            checked = await self.action("check", {"revision": 1})
            self.assertEqual(checked.json()["status"], "PERMISSIONS_PARTIAL")
            self.assertFalse(checked.json()["scope_verified"])
        with patch(
            "services.actions.credential_service.provider_transport",
            return_value=httpx.MockTransport(lambda r: httpx.Response(401, json={})),
        ):
            self.assertEqual(
                (await self.action("check", {"revision": 1})).json()["status"],
                "INVALID_CREDENTIAL",
            )
        with self.sessions.begin() as s:
            s.get(WriteCredentialState, "default").encrypted = "tampered"
        self.assertEqual((await self.action("check", {"revision": 1})).status_code, 503)


class MeterTests(StorageFixture, unittest.IsolatedAsyncioTestCase):
    def meter(self):
        return MetaRequestMeter(self.sessions, "default", CREDS["app_id"], interval=0)

    async def test_physical_attempt_pagination_retry_and_inflight_dedup(self):
        requests = []

        async def handler(r):
            requests.append(r)
            await asyncio.sleep(0.01)
            if len(requests) == 1:
                return httpx.Response(503, json={})
            if "after" not in r.url.params:
                return httpx.Response(
                    200,
                    json={
                        "data": [{"id": "1"}],
                        "paging": {
                            "next": "https://graph.facebook.com/v26.0/me/adaccounts?after=x",
                            "cursors": {"after": "x"},
                        },
                    },
                )
            return httpx.Response(200, json={"data": [{"id": "2"}]})

        client = MetaClient(
            CREDS,
            transport=httpx.MockTransport(handler),
            meter=self.meter(),
            retry_delay=0,
        )
        try:
            result = await asyncio.gather(
                client.edge("me/adaccounts", {"fields": "id"}),
                client.edge("me/adaccounts", {"fields": "id"}),
            )
            self.assertEqual(result[0], result[1])
            self.assertEqual(len(requests), 3)
        finally:
            await client.close()
        with self.sessions() as s:
            rows = s.scalars(select(MetaRequestAttempt)).all()
            self.assertEqual(len(rows), 3)
            self.assertEqual(sum(r.attempt > 1 for r in rows), 1)
            self.assertEqual(sum(r.page > 1 for r in rows), 1)

    async def test_persistent_rate_limit_no_retry_and_headers_percent(self):
        calls = []

        def handler(r):
            calls.append(r)
            return httpx.Response(
                429,
                json={"error": {"code": 80004, "error_subcode": 42}},
                headers={
                    "Retry-After": "30",
                    "X-App-Usage": '{"call_count":99,"total_time":60}',
                },
            )

        first = MetaClient(
            CREDS, transport=httpx.MockTransport(handler), meter=self.meter()
        )
        with self.assertRaises(ProviderError):
            await first.get("me/adaccounts")
        await first.close()
        second = MetaClient(
            CREDS, transport=httpx.MockTransport(handler), meter=self.meter()
        )
        with self.assertRaises(ProviderError):
            await second.get("me/adaccounts")
        await second.close()
        self.assertEqual(len(calls), 1)
        with self.sessions() as s:
            data = report(s, "default")
            self.assertEqual(
                data["usage_percent"], None
            )  # no app identifier on this isolated connection
            row = s.scalar(select(MetaRequestAttempt))
            self.assertEqual(row.error_code, 80004)
            self.assertEqual(row.error_subcode, 42)
            state = s.get(MetaRateState, "meta-app:" + CREDS["app_id"])
            self.assertEqual(state.usage["x-app-usage"][0]["call_count"], 99)

    def test_empty_history_unknown_tier_and_forecast_is_not_network(self):
        with self.sessions() as s:
            data = report(s, "default")
            self.assertIsNone(data["day"])
            self.assertIsNone(data["access_tier"])
            for accounts in (1, 3, 10, 50):
                for days in (1, 7, 30):
                    data = estimate(
                        s,
                        "default",
                        accounts,
                        days,
                        object_counts={
                            "campaign": 100,
                            "adset": 100,
                            "ad": 100,
                            "creative": 100,
                        },
                    )
                    self.assertEqual(data["network_requests"], 0)
                    self.assertEqual(
                        data["total_no_retries"], 3 + accounts * (4 + days)
                    )
        self.assertEqual(usage_headers({"x-app-usage": "malformed"}), {})
        self.assertEqual(usage_headers({}), {})


from datetime import UTC, datetime

from test_providers import ProviderIntegrationTests as _ProviderIntegrationTests
from test_providers import graph

from services.providers.sync import MetaSync


class MetaSyncGuardsTests(_ProviderIntegrationTests):
    async def test_scheduler_overlap_has_one_operation(self):
        today = datetime.now(UTC).date()
        results = await asyncio.gather(
            MetaSync(self.manager).run("today", today, today),
            MetaSync(self.manager).run("today", today, today),
        )
        self.assertEqual(
            sorted(r["status"] for r in results), ["skipped_overlap", "succeeded"]
        )

    async def test_large_roster_stops_before_catalogs(self):
        calls = []

        def handler(r):
            calls.append(r)
            response = graph(r)
            if r.url.path.endswith("/me/adaccounts"):
                import copy

                prototype = response.json()["data"][0]
                response = httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                **copy.deepcopy(prototype),
                                "id": "act_" + str(i),
                                "account_id": str(i),
                            }
                            for i in range(1, 5)
                        ]
                    },
                )
            return response

        self.manager.transports["meta"] = httpx.MockTransport(handler)
        result = await MetaSync(self.manager).run(
            "today", datetime.now(UTC).date(), datetime.now(UTC).date()
        )
        self.assertEqual(result["error_code"], "META_SYNC_ACCOUNT_SELECTION_REQUIRED")
        self.assertEqual(len(calls), 3)
        self.assertTrue(
            all(
                not r.url.path.endswith(("/campaigns", "/adsets", "/ads", "/insights"))
                for r in calls
            )
        )
