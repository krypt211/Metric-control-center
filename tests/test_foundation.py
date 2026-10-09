import asyncio
from pathlib import Path
import unittest

import httpx
import yaml

from backend.app import app

ROOT = Path(__file__).resolve().parents[1]


class FoundationTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_exposes_no_credentials_and_statistics_routes(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health/live")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"status": "ok", "stage": "foundation"})
            spec = (await client.get("/openapi.json")).json()
            self.assertTrue({"/health/live", "/api/dashboard/today", "/api/stats/summary"} <= set(spec["paths"]))

    def test_compose_limits_write_secret_to_opt_in_action_worker(self):
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        for name, config in compose["services"].items():
            with self.subTest(service=name):
                secrets = config.get("secrets", [])
                environment = config.get("environment", {})
                if name == "action-worker":
                    self.assertIn("metricflow_write_key", secrets)
                    self.assertNotIn("metricflow_read_key", secrets)
                    self.assertEqual(config["profiles"], ["actions"])
                    self.assertNotIn("METRICFLOW_READ_KEY_FILE", environment)
                else:
                    self.assertNotIn("metricflow_write_key", secrets)
                    self.assertNotIn("METRICFLOW_WRITE_KEY_FILE", environment)
        for name in ("postgres", "redis"):
            self.assertNotIn("ports", compose["services"][name])
        self.assertTrue(compose["services"]["backend"]["ports"][0].startswith("127.0.0.1:"))

    def test_inference_and_telegram_credentials_are_isolated(self):
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        for name, config in compose["services"].items():
            for secret, owner in (("openai_api_key", "ai-worker"), ("telegram_bot_token", "telegram-bot")):
                self.assertEqual(secret in config.get("secrets", []), name == owner)
        self.assertEqual(compose["services"]["ai-worker"]["profiles"], ["ai"])
        self.assertEqual(compose["services"]["telegram-bot"]["profiles"], ["telegram"])


if __name__ == "__main__":
    unittest.main()
