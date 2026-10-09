import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from sqlalchemy import func, select

from backend.app import app
from services.storage.models import AIDecision, AISettings
from test_recommendations import RecommendationFixture


class CopilotApiTests(RecommendationFixture, unittest.IsolatedAsyncioTestCase):
    async def test_operator_auth_revision_and_disabled_provider(self):
        token = Path(self.directory.name) / "operator-token"
        token.write_text("test-operator", encoding="utf-8")
        env = {"ACTION_API_TOKEN_FILE": str(token), "ACTION_OPERATOR_ID": "operator", "WORKSPACE_ID": "default",
            "AI_ENABLED": "false", "AI_AUTOPILOT_ALLOWED": "false", "ACTIONS_ENABLED": "false", "OPENAI_MODEL": "explicit-model"}
        headers = {"Authorization": "Bearer test-operator"}
        with patch.dict(os.environ, env), patch("backend.app.database_sessions", return_value=self.sessions):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                self.assertEqual((await client.get("/api/ai/settings")).status_code, 401)
                initial = await client.get("/api/ai/settings", headers=headers)
                self.assertEqual(initial.json()["settings"]["mode"], "OFF")
                with self.sessions() as session: self.assertEqual(session.scalar(select(func.count()).select_from(AISettings)), 0)
                command = {"settings": {"mode": "COPILOT"}, "revision": 0}
                self.assertEqual((await client.put("/api/ai/settings", json=command, headers=headers)).status_code, 200)
                self.assertEqual((await client.put("/api/ai/settings", json=command, headers=headers)).status_code, 409)
                auto = {"settings": {"mode": "AUTOPILOT"}, "revision": 1}
                self.assertEqual((await client.put("/api/ai/settings", json=auto, headers=headers)).status_code, 409)
                enqueue = {"entity_ids": ["set"]}
                action_headers = {**headers, "Idempotency-Key": "one-analysis"}
                self.assertEqual((await client.post("/api/ai/analyses", json=enqueue, headers=action_headers)).status_code, 409)
                with patch.dict(os.environ, {"AI_ENABLED": "true"}):
                    response = await client.post("/api/ai/analyses", json=enqueue, headers=action_headers)
                    self.assertEqual(response.status_code, 202)
                    again = await client.post("/api/ai/analyses", json=enqueue, headers=action_headers)
                    self.assertEqual(response.json()["id"], again.json()["id"])
                    self.assertNotIn("callback_token", response.text)
                    self.assertEqual(len((await client.get("/api/ai/decisions", headers=headers)).json()["decisions"]), 1)
                    spoof = await client.post("/api/ai/analyses", json={**enqueue, "source": "ai", "actor": "admin"}, headers=action_headers)
                    self.assertEqual(spoof.status_code, 422)
                with self.sessions() as session: self.assertEqual(session.scalar(select(func.count()).select_from(AIDecision)), 1)
