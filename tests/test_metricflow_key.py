import unittest

import httpx

from services.metricflow.errors import ConfigurationError
from services.metricflow.reader import MetricFlowConnector
from services.metricflow.secrets import validate_key


class MetricFlowKeyTests(unittest.IsolatedAsyncioTestCase):
    def test_supported_formats_are_preserved_with_outer_whitespace_trimmed(self):
        for key in ("mfk_fixture_legacy", "mf_live_fixture-url_safe_123"):
            with self.subTest(prefix=key.split("_fixture")[0]):
                self.assertEqual(validate_key("  " + key + "\n"), key)

    def test_invalid_masked_and_header_injection_values_are_rejected_without_echo(self):
        for value in ("", "mfk_", "mf_live_", "other_fixture", "MF_LIVE_fixture", "mf_live_fixture**", "mf_live_fixture with_space", "mf_live_fixture\r\nInjected: true", "mf_live_кириллица"):
            with self.subTest(case=value):
                with self.assertRaises(ConfigurationError) as caught:
                    validate_key(value)
                if len(value) > 12:
                    self.assertNotIn(value, str(caught.exception))

    async def test_live_format_is_passed_unchanged_to_get_only_connector(self):
        key = "mf_live_fixture_url-safe_123"
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={})
        async with MetricFlowConnector(key, transport=httpx.MockTransport(handler)) as reader:
            await reader.get_me()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].method, "GET")
        self.assertEqual(calls[0].headers["Authorization"], "Bearer " + key)
