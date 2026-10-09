import copy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

import httpx
from sqlalchemy import func, select

from services.analytics.dashboard import dashboard_today, summary
from services.storage.database import make_engine, sessions
from services.storage.models import ApiQuota, Base, DailyMetric, EntityCurrentState, RawSnapshot, SyncRun
from services.sync.engine import SyncEngine
from services.sync.schema import InsightSchema

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 10, 6)
NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)


def config():
    return json.loads((ROOT / "config/metricflow-schema.example.json").read_text(encoding="utf-8"))


def row(entity="1", *, spend="100", revenue="180", currency="USD", day="2026-10-06"):
    return {
        "account": {"id": "act_100", "name": "Test account", "currency": currency, "timezone": "Europe/Moscow"},
        "entity": {"id": entity, "name": "Test ad"}, "date": day,
        "metrics": {"spend": spend, "impressions": 1000, "clicks": 20, "leads": 5, "sales": 2, "revenue": revenue},
        "has_tracker": True,
        "tracker": {"currency": currency, "clicks": 18, "leads": 5, "sales": 2, "revenue": revenue},
    }


class StorageFixture:
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = make_engine(f"sqlite:///{Path(self.directory.name) / 'test.db'}")
        Base.metadata.create_all(self.db)
        self.sessions = sessions(self.db)

    def tearDown(self):
        self.db.dispose()
        self.directory.cleanup()

    def sync(self, handler, *, schema=None, budget=800, max_pages=100, clock=lambda: NOW):
        return SyncEngine(self.sessions, InsightSchema(schema or config()), "mfk_test", daily_budget=budget,
                          transport=httpx.MockTransport(handler), retry_delay=0, max_pages=max_pages, clock=clock)


class SyncTests(StorageFixture, unittest.IsolatedAsyncioTestCase):
    async def test_full_pagination_and_idempotent_late_conversion_update(self):
        requests = []
        late = False

        def handler(request):
            requests.append(request)
            if "cursor" not in request.url.params:
                return httpx.Response(200, json={"items": [row()], "next_cursor": "page2"})
            return httpx.Response(200, json={"items": [row("2", revenue="300" if late else "180")], "next_cursor": None})

        sync = self.sync(handler)
        self.assertEqual((await sync.run("today", DAY, DAY))["status"], "succeeded")
        late = True
        self.assertEqual((await sync.run("yesterday", DAY, DAY))["status"], "succeeded")
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(DailyMetric)), 2)
            self.assertEqual(session.scalar(select(func.count()).select_from(RawSnapshot)), 4)
            result = summary(session, "default", DAY, DAY)[0]
            self.assertEqual(Decimal(result["spend"]), Decimal(200))
            self.assertEqual(Decimal(result["revenue"]), Decimal(480))
            self.assertEqual(Decimal(result["roi"]), Decimal(140))
            self.assertEqual(session.scalar(select(ApiQuota.requests)), 4)
        self.assertEqual(len(requests), 4)

    async def test_second_page_error_does_not_publish_partial_metrics(self):
        def handler(request):
            if "cursor" not in request.url.params:
                return httpx.Response(200, json={"items": [row()], "next_cursor": "page2"})
            return httpx.Response(200, json={"items": [{"invalid": True}], "next_cursor": None})
        result = await self.sync(handler).run("today", DAY, DAY)
        self.assertEqual(result["status"], "failed")
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(DailyMetric)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(RawSnapshot)), 2)

    async def test_page_cap_and_cursor_loop_cannot_publish_partial_data(self):
        for cap in (1, 3):
            with self.subTest(cap=cap):
                handler = lambda request: httpx.Response(200, json={"items": [], "next_cursor": "same"})
                self.assertEqual((await self.sync(handler, max_pages=cap).run("today", DAY, DAY))["status"], "failed")
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(DailyMetric)), 0)

    async def test_quota_counts_every_retry_and_stops_before_extra_request(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(503, json={})
        result = await self.sync(handler, budget=2).run("today", DAY, DAY)
        self.assertEqual(result["status"], "skipped_quota")
        self.assertEqual(len(requests), 2)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(ApiQuota.requests)), 2)
            self.assertEqual(session.scalar(select(SyncRun.requests)), 2)

    async def test_429_blocks_later_runs_until_utc_reset(self):
        calls = []
        now = NOW
        def handler(request):
            calls.append(request)
            return httpx.Response(429)
        engine = self.sync(handler, clock=lambda: now)
        await engine.run("today", DAY, DAY)
        self.assertEqual((await engine.run("today", DAY, DAY))["status"], "skipped_quota")
        self.assertEqual(len(calls), 1)
        now += timedelta(days=1)
        await engine.run("today", DAY, DAY)
        self.assertEqual(len(calls), 2)

    async def test_lease_blocks_overlap_and_fences_expired_commit(self):
        now = NOW
        engine = self.sync(lambda request: httpx.Response(200, json={"items": [], "next_cursor": None}), clock=lambda: now)
        self.assertTrue(engine.claim("another-worker"))
        self.assertEqual((await engine.run("today", DAY, DAY))["status"], "skipped_overlap")
        now += timedelta(minutes=4)
        self.assertEqual((await engine.run("today", DAY, DAY))["status"], "succeeded")

    async def test_expired_lease_prevents_publishing_a_late_response(self):
        now = NOW
        def handler(request):
            nonlocal now
            now += timedelta(minutes=4)
            return httpx.Response(200, json={"items": [row()], "next_cursor": None})
        result = await self.sync(handler, clock=lambda: now).run("today", DAY, DAY)
        self.assertEqual(result["error_code"], "LeaseLost")
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(DailyMetric)), 0)

    async def test_current_state_is_separate_from_historical_days(self):
        schema = config()
        schema["fields"].update(status="state.status", budget="state.budget")
        first, second = row(day="2026-10-05"), row(day="2026-10-06")
        first["state"] = second["state"] = {"status": "ACTIVE", "budget": "80"}
        engine = self.sync(lambda request: httpx.Response(200, json={"items": [first, second], "next_cursor": None}), schema=schema)
        self.assertEqual((await engine.run("last7", date(2026, 10, 5), DAY))["status"], "succeeded")
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(DailyMetric)), 2)
            self.assertEqual(session.scalar(select(func.count()).select_from(EntityCurrentState)), 1)

    async def test_missing_revenue_is_not_zero_and_zero_denominators_are_null(self):
        item = row(spend="0", revenue=None)
        item["tracker"].update(leads=0, sales=0)
        await self.sync(lambda r: httpx.Response(200, json={"items": [item], "next_cursor": None})).run("today", DAY, DAY)
        with self.sessions() as session:
            result = summary(session, "default", DAY, DAY)[0]
            self.assertIsNone(result["revenue"])
            self.assertIsNone(result["profit"])
            self.assertIsNone(result["roi"])
            self.assertIsNone(result["cpl"])

    async def test_currencies_and_workspaces_are_not_mixed(self):
        usd, eur = row(), row("2", currency="EUR")
        eur["account"]["id"] = "act_200"
        await self.sync(lambda r: httpx.Response(200, json={"items": [usd, eur], "next_cursor": None})).run("today", DAY, DAY)
        with self.sessions() as session:
            self.assertEqual({group["currency"] for group in summary(session, "default", DAY, DAY)}, {"USD", "EUR"})
            self.assertEqual(summary(session, "other", DAY, DAY), [])

    async def test_today_is_account_local_day_and_old_data_is_stale(self):
        item = row(day="2026-10-07")
        await self.sync(lambda r: httpx.Response(200, json={"items": [item], "next_cursor": None})).run("today", date(2026, 10, 7), date(2026, 10, 7))
        with self.sessions() as session:
            dashboard = dashboard_today(session, "default", now=datetime(2026, 10, 6, 22, tzinfo=timezone.utc))
            self.assertEqual(dashboard["groups"][0]["start"], "2026-10-07")
            self.assertTrue(dashboard["groups"][0]["stale"])


if __name__ == "__main__":
    unittest.main()
