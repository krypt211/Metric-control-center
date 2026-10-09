from datetime import date
from decimal import Decimal
import unittest

import httpx
from sqlalchemy import select

from services.analytics.table import Filters, filter_options, table_data
from services.storage.models import DailyMetric
from test_sync import DAY, StorageFixture, config, row


class StatisticsTests(StorageFixture, unittest.IsolatedAsyncioTestCase):
    async def prepare(self):
        schema = config()
        schema["fields"].update(campaign_id="parents.campaign", campaign_name="parents.campaign_name", adset_id="parents.adset", adset_name="parents.adset_name", creative_id="creative.id", creative_name="creative.name", buyer="labels.buyer", offer="labels.offer", tracker_campaign="labels.tracker_campaign")
        items = [row("1", spend="100"), row("2", spend="200")]
        for item in items:
            item["parents"] = {"campaign": "10", "campaign_name": "Campaign", "adset": "20", "adset_name": "Adset"}
            item["creative"] = {"id": "30", "name": "Creative"}
            item["labels"] = {"buyer": "Buyer 1", "offer": "Offer 1", "tracker_campaign": "Tracker 1"}
        result = await self.sync(lambda request: httpx.Response(200, json={"items": items, "next_cursor": None}), schema=schema).run("today", DAY, DAY)
        self.assertEqual(result["status"], "succeeded")

    async def test_tree_and_shared_creative_use_ad_facts_once(self):
        await self.prepare()
        with self.sessions() as session:
            for level in ("account", "campaign", "adset", "creative"):
                with self.subTest(level=level):
                    result = table_data(session, "default", Filters(DAY, DAY), level=level)
                    self.assertEqual(len(result["rows"]), 1)
                    self.assertEqual(Decimal(result["rows"][0]["spend"]), Decimal(300))
            self.assertEqual(table_data(session, "default", Filters(DAY, DAY), level="ad")["total"], 2)

    async def test_filters_pagination_and_workspace_boundaries(self):
        await self.prepare()
        with self.sessions() as session:
            options = filter_options(session, "default")["options"]
            selected = Filters(DAY, DAY, account=options["account"][0]["id"], campaign=options["campaign"][0]["id"], buyer="Buyer 1", offer="Offer 1", tracker_campaign="Tracker 1")
            result = table_data(session, "default", selected, level="ad", limit=1)
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["next_offset"], 1)
            self.assertEqual(table_data(session, "other", selected)["rows"], [])
            self.assertEqual(table_data(session, "default", Filters(DAY, DAY, buyer="other"))["rows"], [])

    async def test_geo_uses_country_slices_not_total_or_unsliced_tracker(self):
        await self.prepare()
        schema = config()
        schema.update(endpoint="breakdowns", dimension_fields={"country": "country"})
        country_row = row("1", spend="25", revenue=None)
        country_row["country"] = "IT"
        country_row["has_tracker"] = False
        result = await self.sync(lambda request: httpx.Response(200, json={"items": [country_row], "next_cursor": None}), schema=schema).run("breakdowns", DAY, DAY)
        self.assertEqual(result["status"], "succeeded")
        with self.sessions() as session:
            result = table_data(session, "default", Filters(DAY, DAY, geo="IT"), level="ad")
            self.assertEqual(result["rows"][0]["spend"], "25")
            self.assertIsNone(result["rows"][0]["revenue"])
            self.assertEqual(len(session.scalars(select(DailyMetric)).all()), 2)
            self.assertEqual(filter_options(session, "default")["options"]["geo"], [{"id": "IT", "name": "IT"}])

    async def test_numeric_sort_applies_to_all_rows_before_pagination(self):
        await self.prepare()
        with self.sessions() as session:
            filters=Filters(DAY, DAY)
            first=table_data(session, "default", filters, level="ad", limit=1, sort_key="spend", sort_direction="desc")
            second=table_data(session, "default", filters, level="ad", offset=1, limit=1, sort_key="spend", sort_direction="desc")
            self.assertEqual(Decimal(first["rows"][0]["spend"]), Decimal(200))
            self.assertEqual(Decimal(second["rows"][0]["spend"]), Decimal(100))
            self.assertEqual(first["total"], 2)
            self.assertEqual(first["next_offset"], 1)
            self.assertIsNone(second["next_offset"])

    async def test_unknown_sort_is_rejected_even_when_workspace_is_empty(self):
        with self.sessions() as session:
            with self.assertRaises(ValueError):
                table_data(session, "empty", Filters(DAY, DAY), sort_key="invented_metric")
