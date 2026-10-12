"""Mock-only pacing, expiration and cancellation acceptance."""

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from unittest.mock import patch
from uuid import uuid4

import httpx
from sqlalchemy import func, select
from test_providers import CREDS
from test_sync import StorageFixture

from services.meta.client import MetaClient
from services.meta.telemetry import MetaRequestMeter
from services.providers.integration_models import (
    MetaRateState,
    MetaRequestAttempt,
    MetaRequestQueue,
)


class VirtualClock:
    def __init__(self):
        self.elapsed = 0.0
        self.origin = datetime(2026, 10, 13, tzinfo=UTC)

    def now(self):
        return self.origin + timedelta(seconds=self.elapsed)

    def monotonic(self):
        return self.elapsed

    async def sleep(self, delay):
        self.elapsed += delay


class MetaPacingAcceptanceTests(StorageFixture, unittest.IsolatedAsyncioTestCase):
    async def test_one_three_and_max_three_accounts_use_ten_second_intervals(self):
        for label, accounts in (("one", 1), ("three", 3), ("maximum", 3)):
            clock = VirtualClock()
            times = []

            def handler(request, times=times, clock=clock):
                self.assertEqual(request.method, "GET")
                times.append((clock.elapsed, request.url.path.endswith("/insights")))
                return httpx.Response(200, json={"data": []})

            meter = MetaRequestMeter(self.sessions, "fixture", label, interval=10)
            client = MetaClient(
                CREDS, transport=httpx.MockTransport(handler), meter=meter
            )
            with (
                patch("services.meta.telemetry.utc_now", clock.now),
                patch("services.meta.telemetry.time.monotonic", clock.monotonic),
                patch("services.meta.telemetry.asyncio.sleep", clock.sleep),
            ):
                try:
                    for path in ("debug_token", "me/permissions", "me/adaccounts"):
                        await client.get(path)
                    for i in range(accounts):
                        for edge in (
                            "campaigns",
                            "adsets",
                            "ads",
                            "adcreatives",
                            "insights",
                        ):
                            await client.get(f"act_{100 + i}/{edge}")
                finally:
                    await client.close()
            self.assertEqual(len(times), 3 + 5 * accounts)
            for previous, current in pairwise(times):
                self.assertGreaterEqual(
                    current[0] - previous[0], 20 if previous[1] else 10
                )
            with self.sessions() as s:
                self.assertEqual(
                    s.scalar(select(func.count()).select_from(MetaRequestQueue)), 0
                )
                self.assertIsNone(s.get(MetaRateState, "meta-app:" + label).owner)

    async def test_expired_http_ticket_removed_without_attempt(self):
        meter = MetaRequestMeter(self.sessions, "fixture", "expiry", interval=10)
        now = datetime.now(UTC)
        with self.sessions.begin() as s:
            s.add(
                MetaRequestQueue(
                    id=str(uuid4()),
                    key=meter.key,
                    workspace_id="fixture",
                    created_at=now - timedelta(minutes=3),
                    expires_at=now - timedelta(minutes=1),
                )
            )
        ticket = await meter.acquire()
        meter.release(ticket)
        with self.sessions() as s:
            self.assertEqual(
                s.scalar(select(func.count()).select_from(MetaRequestQueue)), 0
            )
            self.assertEqual(
                s.scalar(select(func.count()).select_from(MetaRequestAttempt)), 0
            )

    async def test_cancelled_waiter_cleans_ticket_and_does_not_send_http(self):
        meter = MetaRequestMeter(self.sessions, "fixture", "cancel", interval=10)
        owner = await meter.acquire()
        waiter = asyncio.create_task(meter.acquire())
        await asyncio.sleep(0.02)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        meter.release(owner)
        with self.sessions() as s:
            self.assertEqual(
                s.scalar(select(func.count()).select_from(MetaRequestQueue)), 0
            )
            self.assertEqual(
                s.scalar(select(func.count()).select_from(MetaRequestAttempt)), 0
            )
