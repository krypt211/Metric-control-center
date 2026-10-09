from datetime import timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from pydantic import ValidationError
from sqlalchemy import delete, func, select

from backend.app import app
from services.analytics.recommendations import DetectorConfig, SettingsConflict, loser, recommendations, save_settings, winner
from services.analytics.table import Filters, table_data
from services.storage.models import ActionRequest, Ad, AdAccount, AdSet, Creative, DailyMetric, Entity, TrackerMetric, User
from test_sync import DAY, NOW, StorageFixture, config, row


class DetectorMathTests(unittest.TestCase):
    def test_winner_requires_all_four_conditions_and_keeps_boundary_precision(self):
        settings = DetectorConfig()
        data = {"spend": "50", "conversions": 5, "roi": "100", "cpl": "10"}
        self.assertTrue(winner(data, settings)["matched"])
        for key, value in (("spend", "49.99999999"), ("conversions", 4), ("roi", "99.99999999"), ("cpl", "10.00000001"), ("cpl", None)):
            self.assertFalse(winner({**data, key: value}, settings)["matched"])

    def test_loser_requires_explicit_zero_leads_at_two_target_cpl(self):
        settings = DetectorConfig(target_cpl="10")
        self.assertTrue(loser({"spend": "20", "leads": 0}, settings)["matched"])
        self.assertFalse(loser({"spend": "19.99999999", "leads": 0}, settings)["matched"])
        self.assertFalse(loser({"spend": "100", "leads": None}, settings)["matched"])
        self.assertFalse(loser({"spend": "100", "leads": 1}, settings)["matched"])

    def test_settings_reject_invalid_currency_zero_cpl_nan_and_insufficient_history_window(self):
        for changes in ({"currency": "usd"}, {"target_cpl": "0"}, {"target_roi": "NaN"}, {"fatigue_days": 2}, {"minimum_conversions": 0}):
            with self.assertRaises(ValidationError): DetectorConfig(**changes)


class RecommendationFixture(StorageFixture):
    def setUp(self):
        super().setUp()
        with self.sessions.begin() as session:
            session.add(User(id="operator", workspace_id="default", email="preview@example.invalid", role="operator"))
            session.add(AdAccount(id="account", workspace_id="default", provider="metricflow", external_id="act_100", currency="USD", timezone="Europe/Moscow", observed_at=NOW))
            session.flush()
            session.add(Entity(id="set", account_id="account", kind="adset", external_id="20", name="Adset"))
            session.add(Entity(id="creative", account_id="account", kind="creative", external_id="30", name="Creative"))
            session.add(Entity(id="ad", account_id="account", kind="ad", external_id="1", name="Ad"))
            session.flush()
            session.add(AdSet(entity_id="set"))
            session.add(Creative(entity_id="creative"))
            session.flush()
            session.add(Ad(entity_id="ad", adset_id="set", creative_id="creative"))
            for n, (clicks, spend, leads) in enumerate(zip((51, 48, 40, 33, 27), (50, 60, 70, 80, 90), (10, 9, 8, 7, 6))):
                session.add(self.metric("ad", DAY - timedelta(days=5-n), clicks=clicks, spend=spend, leads=leads,
                    frequency=Decimal("1") + Decimal(n)/10))

    def metric(self, entity, day, *, clicks=50, spend=100, leads=20, conversions=10, revenue=220, frequency=None, impressions=1000):
        return DailyMetric(entity_id=entity, day=day, source="metricflow", currency="USD", timezone="Europe/Moscow", impressions=impressions,
            clicks=clicks, spend=Decimal(spend), leads=leads, conversions=conversions, sales=2, revenue=Decimal(revenue),
            frequency=frequency, observed_at=NOW, raw={})

    def report(self, **kwargs):
        with self.sessions() as session:
            return recommendations(session, "default", now=NOW, **kwargs)


class RecommendationTests(RecommendationFixture, unittest.TestCase):
    def test_fatigue_uses_five_closed_days_with_simultaneous_four_trends_and_no_actions(self):
        report = self.report()
        self.assertEqual(report["counts"], {"stop": 0, "fatigue": 1, "scale": 0, "watch": 0})
        tired = report["rows"][0]["signals"]["fatigue"]
        self.assertTrue(tired["matched"])
        self.assertEqual([Decimal(day["ctr"]) for day in tired["series"]], list(map(Decimal, ("5.1", "4.8", "4.0", "3.3", "2.7"))))
        self.assertEqual(tired["window"], [(DAY-timedelta(days=5)).isoformat(), (DAY-timedelta(days=1)).isoformat()])
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ActionRequest)), 0)

    def test_winner_with_fatigue_gets_fatigue_priority_and_stop_has_priority_over_both(self):
        with self.sessions.begin() as session:
            session.add(self.metric("ad", DAY))
        result = self.report()["rows"][0]
        self.assertTrue(result["signals"]["winner"]["matched"])
        self.assertEqual(result["category"], "fatigue")
        with self.sessions.begin() as session:
            today = session.get(DailyMetric, ("ad", DAY, "metricflow"))
            today.leads, today.conversions, today.revenue = 0, 0, Decimal(0)
        result = self.report()["rows"][0]
        self.assertEqual(result["category"], "stop")
        self.assertTrue(result["signals"]["loser"]["matched"])

    def test_missing_frequency_displays_watch_rather_than_fabricated_fatigue(self):
        with self.sessions.begin() as session:
            for metric in session.scalars(select(DailyMetric)): metric.frequency = None
        result = self.report()["rows"][0]
        self.assertEqual(result["category"], "watch")
        self.assertEqual(result["signals"]["fatigue"]["reason"], "frequency_unavailable")

    def test_frequency_can_be_derived_from_single_ad_reach(self):
        with self.sessions.begin() as session:
            for n, metric in enumerate(session.scalars(select(DailyMetric).order_by(DailyMetric.day))):
                metric.frequency, metric.reach = None, 1000-n*100
        self.assertEqual(self.report()["rows"][0]["category"], "fatigue")

    def test_multiple_ad_reaches_are_not_summed_or_frequencies_averaged_for_shared_creative(self):
        with self.sessions.begin() as session:
            session.add(Entity(id="ad-2", account_id="account", kind="ad", external_id="2", name="Ad 2"))
            session.flush()
            session.add(Ad(entity_id="ad-2", adset_id="set", creative_id="creative"))
            for n in range(5):
                session.add(self.metric("ad-2", DAY-timedelta(days=5-n), frequency=Decimal("2")+n, clicks=51-n*5, spend=50+n*10, leads=10-n))
        save_settings(self.sessions, "default", DetectorConfig(level="creative"), 0, now=NOW)
        result = self.report()["rows"][0]
        self.assertEqual(result["category"], "watch")
        self.assertEqual(result["signals"]["fatigue"]["reason"], "frequency_unavailable")

    def test_parent_frequency_requires_matching_impression_population_and_does_not_double_spend(self):
        with self.sessions.begin() as session:
            for n in range(5):
                session.add(self.metric("set", DAY-timedelta(days=5-n), spend=10000, frequency=Decimal("1")+Decimal(n)/10))
        result = self.report()["rows"][0]
        self.assertEqual(result["category"], "fatigue")
        self.assertEqual(Decimal(result["signals"]["fatigue"]["series"][0]["cpc"]), Decimal(50)/51)
        with self.sessions.begin() as session:
            for row in session.scalars(select(DailyMetric).where(DailyMetric.entity_id == "set")): row.impressions = 2000
        self.assertEqual(self.report()["rows"][0]["signals"]["fatigue"]["reason"], "frequency_unavailable")

    def test_non_monotonic_ctr_or_flat_cpc_does_not_confirm_fatigue(self):
        with self.sessions.begin() as session:
            session.get(DailyMetric, ("ad", DAY-timedelta(days=3), "metricflow")).clicks = 55
        result = self.report()["rows"][0]
        self.assertFalse(result["signals"]["fatigue"]["matched"])
        self.assertEqual(result["signals"]["fatigue"]["reason"], "trend_not_confirmed")

    def test_missing_day_zero_leads_low_volume_and_stale_history_do_not_signal_fatigue(self):
        mutations = ("missing", "zero_leads", "low_volume", "stale")
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.sessions.begin() as session:
                    metric = session.get(DailyMetric, ("ad", DAY-timedelta(days=3), "metricflow"))
                    if mutation == "missing":
                        session.delete(metric)
                    elif mutation == "zero_leads": metric.leads = 0
                    elif mutation == "low_volume": metric.impressions, metric.clicks = 10, 1
                    else: metric.observed_at = NOW-timedelta(hours=40)
                self.assertFalse(self.report()["rows"][0]["signals"]["fatigue"]["matched"])
                with self.sessions.begin() as session:
                    session.execute(delete(DailyMetric).where(DailyMetric.entity_id == "ad", DailyMetric.day == DAY-timedelta(days=3)))
                    session.add(self.metric("ad", DAY-timedelta(days=3), clicks=40, spend=70, leads=8, frequency=Decimal("1.2")))

    def test_mixed_tracker_sources_are_not_compared_as_one_fatigue_series(self):
        with self.sessions.begin() as session:
            session.add(TrackerMetric(entity_id="ad", day=DAY-timedelta(days=3), source="metricflow", currency="USD", timezone="Europe/Moscow",
                clicks=40, leads=8, conversions=10, sales=2, revenue=Decimal(220), observed_at=NOW, raw={}))
        result = self.report()["rows"][0]
        self.assertFalse(result["signals"]["fatigue"]["matched"])
        self.assertEqual(result["signals"]["fatigue"]["reason"], "conversion_source_changed")

    def test_winner_period_uses_weighted_totals_and_never_averages_day_roi_cpl(self):
        save_settings(self.sessions, "default", DetectorConfig(window="last3"), 0, now=NOW)
        with self.sessions.begin() as session:
            session.add(self.metric("ad", DAY, spend=1000, revenue=0, leads=20, conversions=10))
        result = self.report()["rows"][0]
        self.assertEqual(Decimal(result["metrics"]["spend"]), Decimal(1170))
        self.assertEqual(Decimal(result["metrics"]["revenue"]), Decimal(440))
        self.assertFalse(result["signals"]["winner"]["matched"])
        self.assertLess(Decimal(result["metrics"]["roi"]), 0)

    def test_closed_days_use_daily_reconciliation_age_while_today_requires_recent_sync(self):
        save_settings(self.sessions, "default", DetectorConfig(window="last3"), 0, now=NOW)
        with self.sessions.begin() as session:
            session.add(self.metric("ad", DAY))
            for row in session.scalars(select(DailyMetric).where(DailyMetric.day < DAY)):
                row.observed_at = NOW-timedelta(hours=8)
        self.assertTrue(self.report()["rows"][0]["current_fresh"])
        with self.sessions.begin() as session:
            session.get(DailyMetric, ("ad", DAY, "metricflow")).observed_at = NOW-timedelta(hours=1)
        row = self.report()["rows"][0]
        self.assertFalse(row["current_fresh"])
        self.assertFalse(row["signals"]["winner"]["matched"])

    def test_settings_are_persistent_and_conflicting_edits_do_not_overwrite(self):
        self.assertEqual(save_settings(self.sessions, "default", DetectorConfig(target_cpl="7"), 0, now=NOW), 1)
        with self.assertRaises(SettingsConflict): save_settings(self.sessions, "default", DetectorConfig(target_cpl="8"), 0)
        self.assertEqual(self.report()["settings"]["target_cpl"], "7")
        save_settings(self.sessions, "default", DetectorConfig(target_cpl="9"), 1)
        with self.assertRaises(SettingsConflict): save_settings(self.sessions, "default", DetectorConfig(target_cpl="10"), 1)

    def test_currency_workspace_categories_and_pagination_remain_separate(self):
        report = self.report(category="scale", limit=1)
        self.assertEqual(report["rows"], [])
        self.assertEqual(report["counts"]["fatigue"], 1)
        with self.sessions() as session:
            self.assertEqual(recommendations(session, "other", now=NOW)["rows"], [])
        save_settings(self.sessions, "default", DetectorConfig(currency="EUR"), 0)
        self.assertEqual(self.report()["counts"], {"stop": 0, "fatigue": 0, "scale": 0, "watch": 0})

    def test_future_partial_today_cannot_confirm_closed_day_trend(self):
        with self.sessions.begin() as session:
            session.add(self.metric("ad", DAY, clicks=1000, frequency=Decimal("100")))
        result = self.report()["rows"][0]
        self.assertEqual(result["signals"]["fatigue"]["series"][-1]["date"], (DAY-timedelta(days=1)).isoformat())
        self.assertEqual(result["category"], "fatigue")


class RecommendationApiTests(RecommendationFixture, unittest.IsolatedAsyncioTestCase):
    async def test_read_only_report_and_authenticated_revisioned_settings(self):
        token = Path(self.directory.name) / "token"
        token.write_text("test-token", encoding="utf-8")
        environment = {"WORKSPACE_ID": "default", "ACTION_API_TOKEN_FILE": str(token), "ACTION_OPERATOR_ID": "operator"}
        def report(session, workspace, **kwargs): return recommendations(session, workspace, now=NOW, **kwargs)
        with patch.dict(os.environ, environment), patch("backend.app.database_sessions", return_value=self.sessions), patch("backend.recommendation_api.recommendations", side_effect=report):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/api/recommendations")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["counts"]["fatigue"], 1)
                payload = {"settings": DetectorConfig().model_dump(mode="json"), "revision": 0}
                self.assertEqual((await client.put("/api/recommendations/settings", json=payload)).status_code, 401)
                headers = {"Authorization": "Bearer test-token"}
                self.assertEqual((await client.put("/api/recommendations/settings", json=payload, headers=headers)).json()["revision"], 1)
                self.assertEqual((await client.put("/api/recommendations/settings", json=payload, headers=headers)).status_code, 409)
                self.assertEqual((await client.put("/api/recommendations/settings", json={**payload, "source": "AI"}, headers=headers)).status_code, 422)
                with patch.dict(os.environ, {"WORKSPACE_ID": "other"}):
                    self.assertEqual((await client.put("/api/recommendations/settings", json=payload, headers=headers)).status_code, 403)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ActionRequest)), 0)

    async def test_frequency_reach_sync_mapping_is_optional_validated_and_upserted(self):
        schema = config()
        schema["fields"].update(frequency="metrics.frequency", reach="metrics.reach")
        item = row()
        item["account"]["id"] = "act_200"
        item["metrics"].update(frequency="2.5", reach=400)
        result = await self.sync(lambda request: httpx.Response(200, json={"items": [item], "next_cursor": None}), schema=schema).run("today", DAY, DAY)
        self.assertEqual(result["status"], "succeeded")
        with self.sessions() as session:
            metric = session.scalar(select(DailyMetric).where(DailyMetric.reach == 400))
            self.assertEqual(metric.frequency, Decimal("2.5"))
        item["metrics"]["frequency"] = "-1"
        result = await self.sync(lambda request: httpx.Response(200, json={"items": [item], "next_cursor": None}), schema=schema).run("today", DAY, DAY)
        self.assertEqual(result["status"], "failed")


class ParentFrequencySyncTests(StorageFixture, unittest.IsolatedAsyncioTestCase):
    async def test_separate_parent_sync_supplies_frequency_without_doubling_ad_totals(self):
        ad_schema = config()
        ad_schema["fields"].update(adset_id="parents.adset", adset_name="parents.name", conversions="metrics.conversions")
        items = []
        for n, clicks in enumerate((51, 48, 40, 33, 27)):
            for entity in ("1", "2"):
                item = row(entity, spend=str(50+n*10), day=(DAY-timedelta(days=5-n)).isoformat())
                item["parents"] = {"adset": "20", "name": "Parent"}
                item["has_tracker"] = False
                item["metrics"].update(clicks=clicks, leads=10-n, conversions=10)
                items.append(item)
        result = await self.sync(lambda request: httpx.Response(200, json={"items": items, "next_cursor": None}), schema=ad_schema).run("last7", DAY-timedelta(days=5), DAY-timedelta(days=1))
        self.assertEqual(result["status"], "succeeded")
        with self.sessions() as session:
            self.assertEqual(recommendations(session, "default", now=NOW)["rows"][0]["signals"]["fatigue"]["reason"], "frequency_unavailable")
        from test_sync import ROOT
        parent_schema = json.loads((ROOT / "config/metricflow-frequency-schema.example.json").read_text(encoding="utf-8"))
        parents = []
        for n in range(5):
            item = row("20", spend="5000", day=(DAY-timedelta(days=5-n)).isoformat())
            item["metrics"].update(impressions=2000, frequency=str(Decimal(1)+Decimal(n)/10), reach=None, conversions=10)
            parents.append(item)
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"items": parents, "next_cursor": None})
        result = await self.sync(handler, schema=parent_schema).run("frequency", DAY-timedelta(days=5), DAY-timedelta(days=1))
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(requests[0].url.params["level"], "adset")
        with self.sessions() as session:
            report = recommendations(session, "default", now=NOW)
            self.assertEqual(report["counts"]["fatigue"], 1)
            table = table_data(session, "default", Filters(DAY-timedelta(days=5), DAY-timedelta(days=1)), level="adset")
            self.assertEqual(Decimal(table["rows"][0]["spend"]), Decimal("700"))
