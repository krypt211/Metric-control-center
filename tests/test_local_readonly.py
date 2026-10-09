import asyncio
from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from alembic import command
from alembic.config import Config
import httpx
from sqlalchemy import func, select

from backend.app import app
from backend.health import readiness
from services.actions.settings import policy_from_environment
from services.metricflow.errors import PermissionDenied
from services.metricflow.local import ReadBudget, synchronize
from services.metricflow.onboarding import discover, list_mapping
from services.metricflow.probe import check, safe_error, usage_summary
from services.metricflow.reader import MetricFlowConnector
from services.storage.models import AdAccount, DailyMetric, ActionRequest
from services.sync.engine import QuotaExhausted, SyncEngine
from services.sync.schema import InsightSchema, SchemaError
from test_sync import DAY, NOW, ROOT, StorageFixture, row


def catalog():
    return {"items": [{"id": "act_100", "name": "Account", "currency": "USD", "timezone": "Europe/Moscow"}, {"id": "act_200", "name": "Inactive", "currency": "EUR", "timezone": "Europe/Berlin"}], "next_cursor": None}


def sample():
    item = row()
    item.update(campaign_id="10", campaign_name="Campaign", adset_id="20", adset_name="Adset", creative_id="30", creative_name="Creative")
    return {"items": [item], "next_cursor": None}


class OnboardingTests(unittest.TestCase):
    def test_discovers_real_fields_and_catalog_without_values_or_secret(self):
        config = discover(catalog(), sample())
        self.assertEqual(config["fields"]["entity_id"], "entity.id")
        self.assertEqual(config["fields"]["timezone"], "account.timezone")
        self.assertNotIn("Inactive", json.dumps(config))
        self.assertNotIn("Test ad", json.dumps(config))

    def test_ambiguous_fields_and_lists_are_rejected(self):
        payload = sample(); payload["items"][0]["ad_id"] = "2"
        with self.assertRaises(SchemaError): discover(catalog(), payload)
        with self.assertRaises(SchemaError): list_mapping({"items": [], "data": [], "next_cursor": None})

    def test_unknown_pagination_never_becomes_complete_by_guessing(self):
        with self.assertRaises(SchemaError): list_mapping({"items": [row()]})
        with self.assertRaises(SchemaError): list_mapping({"items": [row()], "has_more": True})
        _, _, pagination = list_mapping({"items": [row()], "has_more": False})
        self.assertEqual(pagination["complete_value"], False)

    def test_saved_single_page_mapping_rejects_later_truncation(self):
        source = sample(); source.pop("next_cursor"); source["has_more"] = False
        schema = InsightSchema(discover(catalog(), source))
        source["has_more"] = True
        with self.assertRaises(SchemaError): schema.page(source)

    def test_multi_day_aggregate_is_not_imported_as_one_day(self):
        payload = sample(); payload["items"][0]["date_stop"] = "2026-10-07"
        with self.assertRaises(SchemaError): discover(catalog(), payload)

    def test_empty_insights_do_not_create_synthetic_schema(self):
        with self.assertRaises(SchemaError): discover(catalog(), {"items": [], "next_cursor": None})

    def test_probe_usage_only_exposes_allowlisted_counters(self):
        text = usage_summary({"used": 12, "limit": 1000, "token": "secret", "email": "private", "account_id": 123})
        self.assertEqual(json.loads(text), {"used": 12, "limit": 1000})
        self.assertNotIn("secret", text)


class LocalSyncTests(StorageFixture, unittest.IsolatedAsyncioTestCase):
    async def test_catalog_accounts_without_spend_are_imported_and_replay_is_idempotent(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=catalog() if request.url.path.endswith("ad-accounts") else sample())
        engine = self.sync(handler, schema=discover(catalog(), sample()))
        for _ in range(2):
            result = await engine.run("manual_initial", DAY, DAY)
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual((result["accounts"], result["campaigns"], result["adsets"], result["ads"], result["creatives"], result["rows"]), (2, 1, 1, 1, 1, 1))
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(AdAccount)), 2)
            self.assertEqual(session.scalar(select(func.count()).select_from(DailyMetric)), 1)
        self.assertTrue(all(r.method == "GET" for r in calls))

    async def test_catalog_currency_mismatch_prevents_metric_publication(self):
        bad = sample(); bad["items"][0]["account"]["currency"] = "EUR"; bad["items"][0]["tracker"]["currency"] = "EUR"
        engine = self.sync(lambda r: httpx.Response(200, json=catalog() if r.url.path.endswith("ad-accounts") else bad), schema=discover(catalog(), sample()))
        self.assertEqual((await engine.run("manual_initial", DAY, DAY))["status"], "failed")
        with self.sessions() as session: self.assertEqual(session.scalar(select(func.count()).select_from(DailyMetric)), 0)

    async def test_failed_insights_does_not_publish_even_the_catalog(self):
        bad = sample(); bad["items"][0]["metrics"]["spend"] = -1
        engine = self.sync(lambda r: httpx.Response(200, json=catalog() if r.url.path.endswith("ad-accounts") else bad), schema=discover(catalog(), sample()))
        self.assertEqual((await engine.run("manual_initial", DAY, DAY))["status"], "failed")
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(AdAccount)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(DailyMetric)), 0)

    async def test_duplicate_or_unknown_catalog_id_prevents_publication(self):
        accounts = catalog(); accounts["items"].append(copy.deepcopy(accounts["items"][0]))
        engine = self.sync(lambda r: httpx.Response(200, json=accounts if r.url.path.endswith("ad-accounts") else sample()), schema=discover(catalog(), sample()))
        self.assertEqual((await engine.run("manual_initial", DAY, DAY))["status"], "failed")

    async def test_probe_rejects_reported_write_scope_before_more_requests(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"scopes": ["analytics:read", "campaigns:write"]})
        async with MetricFlowConnector("mfk_test", transport=httpx.MockTransport(handler)) as reader:
            with self.assertRaises(PermissionDenied): await check(reader)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].method, "GET")

    async def test_probe_and_onboarding_reserve_shared_budget(self):
        with patch.dict(os.environ, {"WORKSPACE_ID": "default", "SYNC_DAILY_BUDGET": "2"}):
            budget = ReadBudget(self.sessions)
            await budget.reserve(); await budget.reserve()
            with self.assertRaises(QuotaExhausted): await budget.reserve()

    async def test_full_manual_onboarding_stays_get_only_and_never_creates_actions(self):
        calls = []
        # Use actual local dates, independent of the fixed sync fixtures.
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        payload = sample(); payload["items"][0]["date"] = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Moscow")).date().isoformat()
        def handler(request):
            calls.append(request)
            path = request.url.path
            body = {"scopes": ["analytics:read", "ad_accounts:read", "campaigns:read"]} if path.endswith("/me") else {"used": 0, "limit": 1000} if path.endswith("/usage") else catalog() if path.endswith("/ad-accounts") else payload
            return httpx.Response(200, json=body)
        transport = httpx.MockTransport(handler)
        def reader(key, **kwargs): return MetricFlowConnector(key, transport=transport, **kwargs)
        def sync(*args, **kwargs): return SyncEngine(*args, transport=transport, **kwargs)
        path = Path(self.directory.name) / "schema.json"
        env = {"METRICFLOW_SCHEMA_FILE": str(path), "SYNC_ENABLED": "true", "ACTIONS_ENABLED": "false", "SYNC_DAILY_BUDGET": "800", "WORKSPACE_ID": "default", "SYNC_TIMEZONE": "Europe/Moscow"}
        output = io.StringIO()
        with patch.dict(os.environ, env), patch("services.metricflow.local.read_key_file", return_value="mfk_secret_never_printed"), patch("services.metricflow.local.make_engine", return_value=self.db), patch("services.metricflow.local.MetricFlowConnector", side_effect=reader), patch("services.metricflow.local.SyncEngine", side_effect=sync), redirect_stdout(output):
            self.assertEqual(await synchronize(), 0)
        self.assertTrue(path.is_file())
        self.assertTrue(all(r.method == "GET" for r in calls))
        self.assertNotIn("mfk_secret", output.getvalue())
        self.assertIn("Last sync: SUCCESS", output.getvalue())
        with self.sessions() as session: self.assertEqual(session.scalar(select(func.count()).select_from(ActionRequest)), 0)


class HealthReadOnlyTests(StorageFixture, unittest.IsolatedAsyncioTestCase):
    async def test_ready_requires_migration_head_not_just_existing_models(self):
        with patch.dict(os.environ, {"CELERY_BROKER_URL": ""}):
            status = readiness(self.sessions)
            self.assertEqual(status["database"], "OK")
            self.assertEqual(status["migrations"], "PENDING")
            self.assertEqual(status["status"], "not_ready")

    async def test_read_only_rejects_mutating_api_before_operator_or_action_engine(self):
        with patch.dict(os.environ, {"LOCAL_READ_ONLY": "true", "ACTIONS_ENABLED": "true"}):
            self.assertFalse(policy_from_environment().enabled)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                for path in ("/api/actions", "/api/rules", "/api/ai/analyses", "/api/ai/automation"):
                    response = await client.post(path, json={})
                    self.assertEqual(response.status_code, 403)
                self.assertEqual((await client.get("/health/live")).status_code, 200)

    async def test_ready_passes_actual_migrations_and_safe_system_status(self):
        with tempfile.TemporaryDirectory() as directory:
            url = f"sqlite:///{Path(directory) / 'migrated.db'}"
            env = {"DATABASE_URL": url, "CELERY_BROKER_URL": "", "LOCAL_READ_ONLY": "true", "SYNC_ENABLED": "true", "ACTIONS_ENABLED": "false"}
            with patch.dict(os.environ, env):
                config = Config(str(ROOT / "alembic.ini")); command.upgrade(config, "head")
                from services.storage.database import make_engine, sessions
                engine = make_engine(url)
                try:
                    with patch("backend.app.database_sessions", return_value=sessions(engine)):
                        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                            response = await client.get("/health/ready")
                            self.assertEqual(response.status_code, 200)
                            self.assertEqual(response.json()["schema"], "OK")
                            status = (await client.get("/api/system/status")).json()
                            self.assertEqual(status["mode"], "LOCAL READ ONLY")
                            self.assertFalse(status["actions_enabled"])
                            self.assertIsNone(status["last_sync"])
                finally: engine.dispose()
