"""ADMIN/CSRF preparation and independent credentials, without provider traffic."""

import os
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from test_auth import MemoryLimits
from test_providers import CREDS
from test_sync import StorageFixture

from backend.app import app
from services.auth.sessions import new_user
from services.meta.pilot_models import MetaPilotSession
from services.providers.models import ProviderConnection, ProviderJob
from services.sync.engine import utc_now


class PilotApiTests(StorageFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        secret = Path(self.directory.name) / "session"
        secret.write_text("s" * 48)
        key = Path(self.directory.name) / "cipher"
        key.write_bytes(Fernet.generate_key())
        self.env = patch.dict(
            os.environ,
            {
                "AUTH_ENABLED": "true",
                "APP_ENV": "development",
                "SESSION_SECRET_FILE": str(secret),
                "PROVIDER_ENCRYPTION_KEY_FILE": str(key),
                "APP_ORIGIN": "http://test",
                "WORKSPACE_ID": "default",
                "LOCAL_READ_ONLY": "true",
                "ACTIONS_ENABLED": "false",
                "AI_ENABLED": "false",
                "AI_AUTOPILOT_ALLOWED": "false",
                "META_CONTROLLED_READ_PILOT": "true",
                "META_PILOT_AUTHORIZED_SESSION_ID": "",
            },
        )
        self.env.start()
        self.patches = [
            patch("backend.app.database_sessions", return_value=self.sessions),
            patch("backend.auth.limiter", return_value=MemoryLimits()),
        ]
        for p in self.patches:
            p.start()
        with self.sessions.begin() as s:
            for role in ("admin", "viewer", "operator"):
                new_user(s, "default", role, "Strong-password-12345", role)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.env.stop()
        super().tearDown()

    async def csrf(self):
        r = await self.client.get("/api/auth/csrf")
        return {"Origin": "http://test", "X-CSRF-Token": r.json()["csrf_token"]}

    async def login(self, role="admin"):
        r = await self.client.post(
            "/api/auth/login",
            headers=await self.csrf(),
            json={"login": role, "password": "Strong-password-12345"},
        )
        self.assertEqual(r.status_code, 200)

    async def test_credentials_saved_without_enabling_or_health_job(self):
        await self.login()
        r = await self.client.post(
            "/api/admin/providers/meta/credentials",
            headers=await self.csrf(),
            json=CREDS,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "stored_for_pilot")
        with self.sessions() as s:
            self.assertFalse(s.get(ProviderConnection, ("default", "meta")).enabled)
            self.assertEqual(s.scalar(select(func.count()).select_from(ProviderJob)), 0)
        for operation in ("check", "sync"):
            r = await self.client.post(
                "/api/admin/providers/meta/" + operation,
                headers=await self.csrf(),
                json={"start": "2026-10-01", "end": "2026-10-01"},
            )
            self.assertEqual(r.status_code, 409)

    async def test_prepare_cannot_authorize_start(self):
        await self.login()
        await self.client.get("/api/admin/providers")
        day = str(utc_now().date() - timedelta(days=1))
        body = {"account_id": "act_100", "start": day, "end": day}
        r = await self.client.post(
            "/api/admin/providers/meta/pilot", headers=await self.csrf(), json=body
        )
        self.assertEqual(r.status_code, 200, r.text)
        identifier = r.json()["id"]
        r = await self.client.post(
            "/api/admin/providers/meta/pilot/" + identifier + "/start",
            headers=await self.csrf(),
            json={},
        )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"], "META_PILOT_APPROVAL_REQUIRED")
        self.assertEqual(
            (
                await self.client.post(
                    "/api/admin/providers/meta/pilot/" + identifier + "/cancel",
                    headers=await self.csrf(),
                    json={},
                )
            ).status_code,
            200,
        )
        with self.sessions() as s:
            self.assertEqual(s.get(MetaPilotSession, identifier).status, "CANCELLED")

    async def test_roles_csrf_extra_fields_and_multiple_accounts_rejected(self):
        day = str(utc_now().date())
        for role in ("viewer", "operator"):
            await self.login(role)
            self.assertEqual(
                (await self.client.get("/api/admin/providers/meta/pilot")).status_code,
                403,
            )
        await self.login()
        self.assertEqual(
            (
                await self.client.post("/api/admin/providers/meta/pilot", json={})
            ).status_code,
            403,
        )
        for body in (
            {"account_id": ["act_100", "act_200"], "start": day, "end": day},
            {"account_id": "act_100", "start": day, "end": day, "max_attempts": 21},
            {"account_id": "act_100", "start": day, "end": day, "live_approved": True},
        ):
            self.assertEqual(
                (
                    await self.client.post(
                        "/api/admin/providers/meta/pilot",
                        headers=await self.csrf(),
                        json=body,
                    )
                ).status_code,
                422,
            )
