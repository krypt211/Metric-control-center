import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx

from backend.app import app
from test_automation import AutomationFixture, definition


class AutomationApiTests(AutomationFixture, unittest.IsolatedAsyncioTestCase):
    async def test_rule_lifecycle_replay_provenance_and_workspace_auth(self):
        token = Path(self.directory.name) / "token"
        token.write_text("test-token", encoding="utf-8")
        env = {"ACTION_API_TOKEN_FILE": str(token), "ACTION_OPERATOR_ID": "operator", "WORKSPACE_ID": "default", "ACTIONS_ENABLED": "true"}
        # HTTP evaluation uses the current wall clock; test fixture's date is
        # deterministic by patching only the policy engine's clock factory.
        from services.actions.engine import ActionEngine
        create_engine = lambda factory, policy: ActionEngine(factory, self.policy, clock=lambda: self.now)
        headers = {"Authorization": "Bearer test-token", "Idempotency-Key": "create-rule"}
        with patch.dict(os.environ, env), patch("backend.app.database_sessions", return_value=self.sessions), patch("backend.automation_api.ActionEngine", side_effect=create_engine):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                payload = {"definition": definition().model_dump(mode="json")}
                self.assertEqual((await client.get("/api/rules")).status_code, 401)
                response = await client.post("/api/rules", json=payload, headers=headers)
                self.assertEqual(response.status_code, 201)
                rule = response.json()
                self.assertEqual(rule["mode"], "DRY_RUN")
                self.assertEqual((await client.post("/api/rules", json=payload, headers=headers)).json()["id"], rule["id"])
                self.assertEqual((await client.post(f"/api/rules/{rule['id']}/evaluate", headers=headers)).json()["decisions"], 1)
                run = (await client.get(f"/api/rules/{rule['id']}/runs", headers=headers)).json()["runs"][0]
                self.assertEqual(run["status"], "would_act")
                self.assertEqual((await client.get("/api/audit", headers=headers)).json()["actions"], [])
                response = await client.put(f"/api/rules/{rule['id']}", json={**payload, "mode": "ACTIVE", "revision": 1}, headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual((await client.put(f"/api/rules/{rule['id']}", json={**payload, "mode": "OFF", "revision": 1}, headers=headers)).status_code, 409)
                await client.post(f"/api/rules/{rule['id']}/evaluate", headers=headers)
                audit = (await client.get("/api/audit", headers=headers)).json()["actions"]
                self.assertEqual(len(audit), 1)
                self.assertEqual(audit[0]["provenance"]["source"], "rule")
                self.assertEqual((await client.post("/api/rules", json={**payload, "source": "AI"}, headers={**headers, "Idempotency-Key": "spoof"})).status_code, 422)
                with patch.dict(os.environ, {"WORKSPACE_ID": "other"}):
                    self.assertEqual((await client.get("/api/audit", headers=headers)).status_code, 403)

    async def test_batch_api_is_authenticated_idempotent_and_has_individual_results(self):
        token = Path(self.directory.name) / "token"
        token.write_text("test-token", encoding="utf-8")
        env = {"ACTION_API_TOKEN_FILE": str(token), "ACTION_OPERATOR_ID": "operator", "WORKSPACE_ID": "default"}
        from services.actions.engine import ActionEngine
        create_engine = lambda factory, policy: ActionEngine(factory, self.policy, clock=lambda: self.now)
        headers = {"Authorization": "Bearer test-token", "Idempotency-Key": "batch"}
        with patch.dict(os.environ, env), patch("backend.app.database_sessions", return_value=self.sessions), patch("backend.automation_api.ActionEngine", side_effect=create_engine):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                command = {"entity_ids": ["set", "second-set", "missing"], "operation": {"kind": "pause"}}
                self.assertEqual((await client.post("/api/batches", json=command, headers={"Idempotency-Key": "unauth"})).status_code, 401)
                response = await client.post("/api/batches", json=command, headers=headers)
                self.assertEqual(response.status_code, 202)
                result = response.json()
                self.assertEqual([item["status"] for item in result["items"]].count("queued"), 1)
                self.assertEqual([item["status"] for item in result["items"]].count("rejected"), 2)
                self.assertEqual((await client.post("/api/batches", json=command, headers=headers)).json()["batch_id"], result["batch_id"])
                self.assertEqual((await client.get("/api/batches/lookup?key=batch", headers=headers)).json()["batch_id"], result["batch_id"])
                self.assertEqual((await client.get(f"/api/batches/{result['batch_id']}", headers=headers)).status_code, 200)
                self.assertEqual((await client.post("/api/batches", json={**command, "source": "AI"}, headers=headers)).status_code, 422)
