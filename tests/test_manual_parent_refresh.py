"""Demand-bound parent READ refresh through the existing sync and quota gates."""

from __future__ import annotations

import copy
from datetime import date, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import select
from test_live_contract import ParentStateTests

from services.storage.models import (
    ActionExecution,
    ActionRequest,
    AdAccount,
    ApiQuota,
    Entity,
    EntityCurrentState,
    User,
)
from services.sync.engine import SyncEngine, aware
from services.sync.schema import InsightSchema


class ManualParentRefreshTests(ParentStateTests):
    def block(self, kind, *, status="BLOCKED", changes=None, index=0):
        with self.factory.begin() as session:
            if not session.get(User, "manual-admin"):
                session.add(
                    User(
                        id="manual-admin",
                        workspace_id="default",
                        email="fixture",
                        role="admin",
                    )
                )
                session.flush()
            entities = session.execute(
                select(Entity, AdAccount.external_id)
                .join(AdAccount)
                .where(Entity.kind == kind)
                .order_by(AdAccount.external_id, Entity.external_id)
            ).all()
            entity, account_id = entities[index]
            metadata = {
                "phase": "4A",
                "source": "manual",
                "provider": "metricflow",
                "entity_level": kind,
                "entity_id": entity.id,
                "expires_at": (self.now + timedelta(minutes=15)).isoformat(),
                "preflight": {"blocking_reasons": ["STATUS_STALE"]},
            }
            metadata.update(changes or {})
            request = ActionRequest(
                id=str(uuid4()),
                workspace_id="default",
                entity_id=entity.id,
                initiator_id="manual-admin",
                idempotency_key=str(uuid4()),
                action="PAUSE_" + kind.upper(),
                baseline_status="ACTIVE",
                provenance=metadata,
                status=status,
                created_at=self.now,
            )
            session.add(request)
            return request.id, entity.id, account_id

    async def stale_cache(self):
        self.assertEqual((await self.run_sync())["status"], "succeeded")
        self.now += timedelta(minutes=30)
        self.calls.clear()

    def observations(self):
        with self.factory() as session:
            return {
                state.entity_id: aware(state.observed_at)
                for state in session.scalars(select(EntityCurrentState))
            }

    async def test_two_blocked_levels_refresh_once_and_leave_commands_untouched(self):
        await self.stale_cache()
        campaign = self.block("campaign")
        adset = self.block("adset")
        with self.factory() as session:
            before = {
                rid: copy.deepcopy(session.get(ActionRequest, rid).provenance)
                for rid in (campaign[0], adset[0])
            }
        self.now += timedelta(seconds=1)
        self.assertEqual((await self.run_sync())["status"], "succeeded")
        self.assertEqual(len(self.calls), 4)  # accounts, insights, two catalogs
        self.assertEqual(sum(p.endswith("/campaigns") for p in self.calls), 1)
        self.assertEqual(sum(p.endswith("/adsets") for p in self.calls), 1)
        with self.factory() as session:
            for rid, eid, _ in (campaign, adset):
                state = session.get(EntityCurrentState, eid)
                self.assertEqual(aware(state.observed_at), self.now)
                self.assertEqual(state.status, "ACTIVE")
                request = session.get(ActionRequest, rid)
                self.assertEqual(request.provenance, before[rid])
                self.assertEqual(request.status, "BLOCKED")
            self.assertIsNone(session.scalar(select(ActionExecution)))
        self.calls.clear()
        self.now += timedelta(minutes=10)
        self.assertEqual((await self.run_sync())["status"], "succeeded")
        self.assertEqual(len(self.calls), 2)  # Old blocking reason cannot refetch.

    async def test_multiple_objects_share_one_account_kind_catalog(self):
        # The recorded fixture has one adset per account. Add a second synthetic
        # adset in the same account before ingestion to exercise coalescing.
        extra = copy.deepcopy(
            min(self.insights["data"], key=lambda r: r["ad_account_id"])
        )
        extra.update(ad_id="999700000000001", adset_id="999700000000002")
        self.insights["data"].append(extra)
        self.insights["meta"]["total"] = len(self.insights["data"])
        await self.stale_cache()
        first = self.block("adset")
        second = self.block("adset", index=1)
        self.assertEqual(first[2], second[2])
        self.now += timedelta(seconds=1)
        self.assertEqual((await self.run_sync())["status"], "succeeded")
        self.assertEqual(len(self.calls), 3)

    async def test_cancelled_expired_and_unrelated_requests_do_not_bypass_cache(self):
        changes = [
            {"phase": "other"},
            {"source": "rule"},
            {"provider": "meta"},
            {"entity_level": "ad"},
            {"entity_id": "different"},
            {"preflight": {"blocking_reasons": ["PROVIDER_UNAVAILABLE"]}},
            {"expires_at": "malformed"},
            {"expires_at": None},
            {"expires_at": "2026-10-07T17:30:00"},
            {"expires_at": self.now.isoformat()},
        ]
        await self.stale_cache()
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                rid, _, _ = self.block("campaign", changes=change)
                self.calls.clear()
                self.assertEqual((await self.run_sync())["status"], "succeeded")
                self.assertEqual(len(self.calls), 2)
                with self.factory.begin() as session:
                    session.delete(session.get(ActionRequest, rid))
        for status in ("CANCELLED", "SIMULATED", "EXPIRED", "DRAFT"):
            with self.subTest(status=status):
                rid, _, _ = self.block("campaign", status=status)
                self.calls.clear()
                self.assertEqual((await self.run_sync())["status"], "succeeded")
                self.assertEqual(len(self.calls), 2)
                with self.factory.begin() as session:
                    session.delete(session.get(ActionRequest, rid))

    async def test_expired_and_future_created_blocked_requests_are_ignored(self):
        await self.stale_cache()
        rid, _, _ = self.block("campaign")
        self.now += timedelta(minutes=15)
        self.assertEqual((await self.run_sync())["status"], "succeeded")
        self.assertEqual(len(self.calls), 2)
        with self.factory.begin() as session:
            request = session.get(ActionRequest, rid)
            request.created_at = self.now + timedelta(minutes=5)
            request.provenance = {
                **request.provenance,
                "expires_at": (self.now + timedelta(minutes=20)).isoformat(),
            }
        self.calls.clear()
        self.assertEqual((await self.run_sync())["status"], "succeeded")
        self.assertEqual(len(self.calls), 2)

    async def test_quota_exhaustion_never_publishes_a_fresh_timestamp(self):
        await self.stale_cache()
        self.block("campaign")
        before = self.observations()
        sync = SyncEngine(
            self.factory,
            InsightSchema(self.config),
            "mfk_fixture",
            transport=httpx.MockTransport(self.handler),
            clock=lambda: self.now,
            daily_budget=10,
        )
        result = await sync.run("test", date(2026, 10, 6), date(2026, 10, 7))
        self.assertEqual(result["status"], "skipped_quota")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.observations(), before)
        with self.factory() as session:
            self.assertEqual(session.scalar(select(ApiQuota.requests)), 10)

    async def test_parent_429_sets_cooldown_and_stops_subsequent_sync(self):
        await self.stale_cache()
        self.block("campaign")
        before = self.observations()

        def limited(request):
            if request.url.path.endswith("/campaigns"):
                self.calls.append(request.url.path)
                return httpx.Response(429, headers={"Retry-After": "30"})
            return self.handler(request)

        sync = SyncEngine(
            self.factory,
            InsightSchema(self.config),
            "mfk_fixture",
            transport=httpx.MockTransport(limited),
            clock=lambda: self.now,
        )
        result = await sync.run("test", date(2026, 10, 6), date(2026, 10, 7))
        self.assertEqual(result["error_code"], "RateLimitExceeded")
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.observations(), before)
        self.calls.clear()
        result = await sync.run("test", date(2026, 10, 6), date(2026, 10, 7))
        self.assertEqual(result["status"], "skipped_quota")
        self.assertEqual(self.calls, [])

    async def test_failed_catalog_keeps_previous_timestamps(self):
        await self.stale_cache()
        self.block("adset")
        before = self.observations()
        self.corrupt = True
        self.assertEqual((await self.run_sync())["error_code"], "SchemaError")
        self.assertEqual(self.observations(), before)
        self.assertEqual(len(self.calls), 3)

    async def test_refresh_respects_shared_page_cap(self):
        await self.stale_cache()
        self.block("campaign")
        before = self.observations()
        sync = SyncEngine(
            self.factory,
            InsightSchema(self.config),
            "mfk_fixture",
            transport=httpx.MockTransport(self.handler),
            clock=lambda: self.now,
            max_pages=2,
        )
        result = await sync.run("test", date(2026, 10, 6), date(2026, 10, 7))
        self.assertEqual(result["error_code"], "SchemaError")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.observations(), before)

    async def test_unreferenced_target_does_not_refresh_unrelated_parents(self):
        await self.stale_cache()
        _, entity_id, _ = self.block("campaign")
        with self.factory() as session:
            external_id = session.get(Entity, entity_id).external_id
        self.insights["data"] = [
            item for item in self.insights["data"] if item["campaign_id"] != external_id
        ]
        self.insights["meta"]["total"] = len(self.insights["data"])
        self.assertEqual((await self.run_sync())["status"], "succeeded")
        self.assertEqual(len(self.calls), 2)
