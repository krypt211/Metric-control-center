import asyncio
from datetime import date
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from services.actions.factory import create_action_connector
from services.metricflow import MetricFlowConnector
from services.metricflow.errors import (
    ActionOutcomeUnknown, APIError, AuthenticationError, ConfigurationError,
    InvalidResponse, PermissionDenied, RateLimitExceeded, SubscriptionRequired,
    TransportUnavailable,
)
from services.metricflow.transport import MetricFlowTransport
from services.metricflow.writer import MetricFlowActionConnector

START, END = date(2026, 10, 1), date(2026, 10, 6)
READ, WRITE = "mfk_test_read", "mfk_test_write"


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_account_endpoints_keep_dates_extra_fields_and_read_key(self):
        requests = []
        data = {"items": [{"spend": "12.50", "unknown_metric": 7}], "next_cursor": "opaque"}

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=data)

        async with MetricFlowConnector(READ, transport=httpx.MockTransport(handler)) as reader:
            endpoints = {
                "get_campaigns": "campaigns", "get_adsets": "adsets", "get_ads": "ads",
                "get_daily": "daily", "get_creatives": "creatives",
                "get_tracker_stats": "tracker", "get_breakdowns": "breakdowns",
            }
            for method, endpoint in endpoints.items():
                with self.subTest(method=method):
                    result = await getattr(reader, method)("act_123", START, END, params={"cursor": "opaque"})
                    self.assertEqual(result, data)
                    req = requests[-1]
                    self.assertEqual(req.method, "GET")
                    self.assertEqual(req.url.path, f"/api/v1/ad-accounts/act_123/{endpoint}")
                    self.assertEqual(req.headers["Authorization"], f"Bearer {READ}")
                    self.assertEqual(dict(req.url.params), {"from": "2026-10-01", "to": "2026-10-06", "cursor": "opaque"})

    async def test_flat_endpoints_and_no_write_methods(self):
        paths = []

        def handler(request):
            paths.append(request.url.path)
            return httpx.Response(200, json=[])

        async with MetricFlowConnector(READ, transport=httpx.MockTransport(handler)) as reader:
            for method in (reader.get_me, reader.get_usage, reader.get_accounts, reader.get_rules, reader.get_bundles):
                await method()
            await reader.get_summary(START, END)
            await reader.get_insights(START, END)
            self.assertFalse(hasattr(reader, "pause_entity"))
            self.assertFalse(hasattr(reader, "enable_entity"))
            self.assertFalse(hasattr(reader, "change_budget"))
        self.assertEqual(paths, [f"/api/v1/{p}" for p in ("me", "usage", "ad-accounts", "rules", "bundles", "summary", "insights")])

    async def test_invalid_dates_ids_and_date_override_do_not_send(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={})

        async with MetricFlowConnector(READ, transport=httpx.MockTransport(handler)) as reader:
            for account_id in ("123", "act_123/../../entities", "act_%31", "https://evil.invalid"):
                with self.subTest(account_id=account_id), self.assertRaises(ValueError):
                    await reader.get_ads(account_id, START, END)
            with self.assertRaises(ValueError):
                await reader.get_insights(END, START)
            with self.assertRaises(ValueError):
                await reader.get_insights(START, END, params={"from": "2020-01-01"})
            with self.assertRaises(ValueError):
                await reader.get_insights("2026-10-01", END)
        self.assertEqual(calls, [])

    async def test_read_retries_are_bounded(self):
        responses = [503, 502, 200]
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(responses.pop(0), json={"data": []})

        async with MetricFlowConnector(READ, transport=httpx.MockTransport(handler), retry_delay=0) as reader:
            self.assertEqual(await reader.get_accounts(), {"data": []})
        self.assertEqual(len(requests), 3)

    async def test_network_failure_stops_after_three_read_attempts(self):
        calls = []

        def handler(request):
            calls.append(request)
            raise httpx.ConnectError(f"sensitive {READ}", request=request)

        async with MetricFlowConnector(READ, transport=httpx.MockTransport(handler), retry_delay=0) as reader:
            with self.assertRaises(TransportUnavailable) as caught:
                await reader.get_accounts()
        self.assertEqual(len(calls), 3)
        self.assertNotIn(READ, str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    async def test_auth_subscription_and_rate_errors_never_retry_or_leak_body(self):
        for status, error_class in ((401, AuthenticationError), (402, SubscriptionRequired), (403, PermissionDenied), (429, RateLimitExceeded)):
            calls = []

            def handler(request):
                calls.append(request)
                return httpx.Response(status, json={"secret": READ}, headers={"Retry-After": "60"})

            with self.subTest(status=status):
                async with MetricFlowConnector(READ, transport=httpx.MockTransport(handler), retry_delay=0) as reader:
                    with self.assertRaises(error_class) as caught:
                        await reader.get_accounts()
                self.assertEqual(len(calls), 1)
                self.assertNotIn(READ, str(caught.exception))
                if status == 429:
                    self.assertEqual(caught.exception.retry_after_seconds, 60)

    async def test_redirect_not_followed(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(302, headers={"Location": "https://evil.invalid/steal"})

        async with MetricFlowConnector(READ, transport=httpx.MockTransport(handler)) as reader:
            with self.assertRaises(APIError):
                await reader.get_accounts()
        self.assertEqual(len(calls), 1)

    async def test_read_invalid_json_is_not_retried(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, text="not JSON")

        async with MetricFlowConnector(READ, transport=httpx.MockTransport(handler)) as reader:
            with self.assertRaises(InvalidResponse):
                await reader.get_accounts()
        self.assertEqual(len(calls), 1)

    async def test_writes_use_write_key_and_explicit_budget_payload(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"provider_response": "preserved"})

        # Synthetic payload verifies passthrough, not the live budget schema.
        payload = {"contract_test_only": "do-not-use-in-production"}
        async with MetricFlowActionConnector(WRITE, transport=httpx.MockTransport(handler)) as writer:
            await writer.pause_entity("123")
            await writer.enable_entity("123")
            await writer.change_budget("123", provider_payload=payload)
            self.assertFalse(hasattr(writer, "get_accounts"))
        self.assertEqual([r.url.path for r in requests], [f"/api/v1/entities/123/{p}" for p in ("pause", "enable", "budget")])
        self.assertTrue(all(r.method == "POST" and r.headers["Authorization"] == f"Bearer {WRITE}" for r in requests))
        self.assertEqual(json.loads(requests[-1].content), payload)

    async def test_write_timeout_server_error_and_bad_success_never_retry(self):
        for failure in ("timeout", "server", "invalid"):
            calls = []

            def handler(request):
                calls.append(request)
                if failure == "timeout":
                    raise httpx.ReadTimeout(WRITE, request=request)
                if failure == "server":
                    return httpx.Response(503, json={"secret": WRITE})
                return httpx.Response(200, text=WRITE)

            with self.subTest(failure=failure):
                async with MetricFlowActionConnector(WRITE, transport=httpx.MockTransport(handler)) as writer:
                    with self.assertRaises(ActionOutcomeUnknown) as caught:
                        await writer.pause_entity("123")
                self.assertEqual(len(calls), 1)
                self.assertNotIn(WRITE, str(caught.exception))

    async def test_invalid_write_inputs_do_not_send(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={})

        async with MetricFlowActionConnector(WRITE, transport=httpx.MockTransport(handler)) as writer:
            with self.assertRaises(ValueError):
                await writer.pause_entity("123/enable")
            with self.assertRaises(ValueError):
                await writer.change_budget("123", provider_payload={})
            with self.assertRaises(ValueError):
                await writer.change_budget("123", provider_payload={"value": float("nan")})
        self.assertEqual(calls, [])

    async def test_transport_rejects_wrong_capability_and_path_escape(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={})

        reader = MetricFlowTransport(READ, transport=httpx.MockTransport(handler))
        writer = MetricFlowTransport(WRITE, write=True, transport=httpx.MockTransport(handler))
        try:
            with self.assertRaises(PermissionDenied):
                await reader.request("POST", "entities/123/pause")
            with self.assertRaises(PermissionDenied):
                await writer.request("GET", "ad-accounts")
            for path in ("https://evil.invalid", "../me", "/me", "ad-accounts/%2e%2e", "me?extra=1"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    await reader.request("GET", path)
        finally:
            await reader.close()
            await writer.close()
        self.assertEqual(calls, [])

    async def test_secret_files_and_factories_never_fall_back_to_other_key(self):
        with tempfile.TemporaryDirectory() as directory:
            read_path, write_path = Path(directory) / "read", Path(directory) / "write"
            read_path.write_text(READ + "\n", encoding="utf-8")
            write_path.write_text(WRITE, encoding="utf-8")
            with patch.dict(os.environ, {"METRICFLOW_READ_KEY_FILE": str(read_path), "METRICFLOW_WRITE_KEY_FILE": str(write_path)}, clear=True):
                reader = MetricFlowConnector.from_environment()
                writer = create_action_connector()
                self.assertEqual(reader._http._client.headers["Authorization"], f"Bearer {READ}")
                self.assertEqual(writer._http._client.headers["Authorization"], f"Bearer {WRITE}")
                await reader.close()
                await writer.close()
            with patch.dict(os.environ, {"METRICFLOW_WRITE_KEY_FILE": str(write_path)}, clear=True):
                with self.assertRaises(ConfigurationError):
                    MetricFlowConnector.from_environment()
            with patch.dict(os.environ, {"METRICFLOW_READ_KEY_FILE": str(read_path)}, clear=True):
                with self.assertRaises(ConfigurationError):
                    create_action_connector()

    async def test_no_content_response(self):
        async with MetricFlowActionConnector(WRITE, transport=httpx.MockTransport(lambda r: httpx.Response(204))) as writer:
            self.assertEqual(await writer.pause_entity("123"), {})


if __name__ == "__main__":
    unittest.main()
