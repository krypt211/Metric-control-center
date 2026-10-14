"""Global physical-attempt policy; no external network."""

import unittest
from datetime import timedelta
from unittest.mock import patch

import httpx
from sqlalchemy import func, select
from test_meta_pacing_acceptance import VirtualClock
from test_providers import CREDS
from test_sync import StorageFixture

from services.meta.client import MetaClient
from services.meta.telemetry import GLOBAL_RATE_KEY, MetaRequestMeter
from services.providers.contracts import ProviderError
from services.providers.integration_models import (
    MetaRateState,
    MetaRequestAttempt,
    MetaRequestQueue,
)


class GlobalLimitTests(StorageFixture, unittest.IsolatedAsyncioTestCase):
    async def test_global_across_apps_workspaces_and_restart(self):
        clock = VirtualClock()
        first = MetaRequestMeter(self.sessions, "one", "app1", interval=1)
        second = MetaRequestMeter(self.sessions, "two", "app2", interval=0)
        self.assertEqual(first.interval, 1800)
        self.assertEqual(first.key, second.key)
        with patch("services.meta.telemetry.utc_now", clock.now):
            ticket = await first.acquire()
            first.begin_attempt("debug_token", 1, 1, None, ticket=ticket)
            first.release(ticket)
            with self.assertRaises(ProviderError) as error:
                await second.acquire()
            self.assertEqual(error.exception.code, "META_PACING_WAIT")
            self.assertEqual(error.exception.retry_after, 1800)
            clock.elapsed = 1799
            restarted = MetaRequestMeter(self.sessions, "third", "app3")
            with self.assertRaises(ProviderError):
                await restarted.acquire()
            clock.elapsed = 1800
            ticket = await restarted.acquire()
            restarted.begin_attempt("me/permissions", 1, 1, None, ticket=ticket)
            restarted.release(ticket)
        with self.sessions() as s:
            self.assertEqual(
                s.scalar(select(func.count()).select_from(MetaRequestAttempt)), 2
            )
            self.assertEqual(
                s.scalar(select(func.count()).select_from(MetaRequestQueue)), 0
            )

    async def test_expired_reservation_cannot_send_delayed_attempt(self):
        clock = VirtualClock()
        meter = MetaRequestMeter(self.sessions, "one", "app")
        with patch("services.meta.telemetry.utc_now", clock.now):
            ticket = await meter.acquire()
            clock.elapsed = 91
            with self.assertRaises(ProviderError) as error:
                meter.begin_attempt("debug_token", 1, 1, None, ticket=ticket)
            self.assertEqual(error.exception.code, "META_REQUEST_LEASE_LOST")
            meter.release(ticket)
        with self.sessions() as s:
            self.assertEqual(
                s.scalar(select(func.count()).select_from(MetaRequestAttempt)), 0
            )

    async def test_only_mock_transport_can_reduce_interval(self):
        meter = MetaRequestMeter(self.sessions, "one", "app", interval=0)
        mock = MetaClient(
            CREDS,
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
            meter=meter,
        )
        self.assertEqual(meter.interval, 0)
        await mock.close()
        meter = MetaRequestMeter(self.sessions, "one", "app", interval=0)
        real = MetaClient(CREDS, meter=meter)
        self.assertEqual(meter.interval, 1800)
        await real.close()  # Never call get().

    async def test_cooldown_persists_for_other_app(self):
        meter = MetaRequestMeter(self.sessions, "one", "app")
        ticket = await meter.acquire()
        meter.release(ticket)
        with self.sessions.begin() as s:
            from services.sync.engine import utc_now

            s.get(MetaRateState, GLOBAL_RATE_KEY).cooldown_until = (
                utc_now() + timedelta(hours=2)
            )
        other = MetaRequestMeter(self.sessions, "two", "different")
        with self.assertRaises(ProviderError) as error:
            await other.acquire()
        self.assertEqual(error.exception.code, "META_RATE_LIMIT")

    async def test_legacy_cooldown_is_preserved_on_global_upgrade(self):
        from services.sync.engine import utc_now

        with self.sessions.begin() as s:
            s.add(
                MetaRateState(
                    key="meta-app:old",
                    cooldown_until=utc_now() + timedelta(hours=2),
                    usage={},
                )
            )
        new = MetaRequestMeter(self.sessions, "new", "new-app")
        with self.assertRaises(ProviderError) as error:
            await new.acquire()
        self.assertEqual(error.exception.code, "META_RATE_LIMIT")
