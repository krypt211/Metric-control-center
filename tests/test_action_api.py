from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from sqlalchemy import func, select

from backend.app import app
from services.storage.models import ActionRequest, AdAccount, Entity, EntityCurrentState, User
from test_sync import StorageFixture


class ActionApiTests(StorageFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            session.add(User(id="operator", workspace_id="default", email="operator@example.invalid", role="operator"))
            session.add(AdAccount(id="account", workspace_id="default", provider="metricflow", external_id="act_900", name="A", currency="USD", timezone="Europe/Moscow", observed_at=now))
            session.flush()
            session.add(Entity(id="entity", account_id="account", kind="adset", external_id="999", name="Adset"))
            session.flush()
            session.add(EntityCurrentState(entity_id="entity", status="ACTIVE", observed_at=now, raw={}))
        self.token_path = Path(self.directory.name) / "token"
        self.token_path.write_text("test-operator-token", encoding="utf-8")

    async def test_authenticated_idempotent_request_lookup_and_audit(self):
        environment = {"ACTION_API_TOKEN_FILE": str(self.token_path), "ACTION_OPERATOR_ID": "operator", "ACTIONS_ENABLED": "true", "WORKSPACE_ID": "default"}
        with patch.dict(os.environ, environment), patch("backend.app.database_sessions", return_value=self.sessions):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                command = {"entity_type": "adset", "entity_id": "999", "action": "pause"}
                headers = {"Authorization": "Bearer test-operator-token", "Idempotency-Key": "api-key-one"}
                response = await client.post("/api/actions", json=command, headers=headers)
                self.assertEqual(response.status_code, 202)
                request_id = response.json()["request_id"]
                self.assertEqual((await client.post("/api/actions", json=command, headers=headers)).json()["request_id"], request_id)
                lookup = await client.get("/api/actions/lookup/by-key?key=api-key-one", headers=headers)
                self.assertEqual(lookup.status_code, 200)
                self.assertEqual(lookup.json()["status"], "queued")
                self.assertEqual(lookup.json()["events"][0]["details"]["initiator_id"], "operator")
                self.assertEqual((await client.post("/api/actions", json={**command, "initiator_id": "admin"}, headers=headers)).status_code, 422)
                self.assertEqual((await client.post("/api/actions", json=command, headers={"Idempotency-Key": "unauth"})).status_code, 401)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ActionRequest)), 1)
