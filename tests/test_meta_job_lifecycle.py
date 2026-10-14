"""Meta durable lifecycle acceptance; every provider transport is a mock."""

import copy
import json
import os
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from test_providers import CREDS, account, graph
from test_sync import StorageFixture

from services.meta import jobs
from services.providers.contracts import ProviderError
from services.providers.credentials import encrypt
from services.providers.integration_models import MetaRateState, MetaRequestAttempt
from services.providers.manager import ProviderManager
from services.providers.models import (
    ProviderConnection,
    ProviderCredential,
    ProviderJob,
)
from services.storage.models import AdAccount
from services.storage.repository import identity
from workers.providers import run_meta_job

EVIDENCE = {}


class LifecycleTests(StorageFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.now = datetime(2026, 10, 13, 12, tzinfo=UTC)
        self.clock = patch("services.meta.jobs.utc_now", side_effect=lambda: self.now)
        self.clock.start()
        key = Path(self.directory.name) / "cipher"
        key.write_bytes(Fernet.generate_key())
        self.env = patch.dict(
            os.environ,
            {
                "PROVIDER_ENCRYPTION_KEY_FILE": str(key),
                "META_JOB_QUEUE_LIMIT": "20",
                "ACTIONS_ENABLED": "false",
                "LOCAL_READ_ONLY": "true",
                "SYNC_DAILY_BUDGET": "800",
                "META_DAILY_BUDGET": "5000",
            },
        )
        self.env.start()
        self.calls = []
        self.count = 1
        self.after_http = None

        def transport(request):
            self.calls.append(request)
            self.assertEqual(request.method, "GET")
            response = graph(request)
            data = copy.deepcopy(response.json())
            if request.url.path.endswith("/me/adaccounts"):
                data["data"] = [account(str(100 + i)) for i in range(self.count)]
            else:
                part = request.url.path.split("/")[-2]
                if part.startswith("act_"):
                    number = part[4:]

                    def fix(value):
                        if isinstance(value, dict):
                            for k, v in list(value.items()):
                                if k == "account_id":
                                    value[k] = number
                                elif k in (
                                    "id",
                                    "campaign_id",
                                    "adset_id",
                                    "ad_id",
                                ) and isinstance(v, str):
                                    value[k] = v + number
                                else:
                                    fix(v)
                        elif isinstance(value, list):
                            for v in value:
                                fix(v)

                    fix(data)
            if self.after_http:
                self.after_http(len(self.calls))
            return httpx.Response(
                response.status_code, json=data, headers=response.headers
            )

        self.manager = ProviderManager(
            self.sessions, transports={"meta": httpx.MockTransport(transport)}
        )
        with self.sessions.begin() as s:
            s.add(
                ProviderConnection(
                    workspace_id="default",
                    provider="meta",
                    enabled=True,
                    revision=1,
                    credential_source="encrypted",
                    status="healthy",
                    config={"app_id": CREDS["app_id"]},
                    permissions={},
                    capabilities={},
                    quota={},
                    updated_at=self.now,
                )
            )
            s.add(
                ProviderCredential(
                    workspace_id="default",
                    provider="meta",
                    encrypted=encrypt("default", "meta", CREDS),
                    updated_at=self.now,
                )
            )
        self.accounts(1)

    def tearDown(self):
        EVIDENCE[self._testMethodName] = len(self.calls)
        self.clock.stop()
        self.env.stop()
        super().tearDown()
        output = os.getenv("META_LIFECYCLE_TEST_EVIDENCE")
        if output:
            Path(output).write_text(json.dumps(EVIDENCE, indent=2))

    def accounts(self, n):
        self.count = n
        ids = []
        with self.sessions.begin() as s:
            for i in range(n):
                identifier = identity("default", "meta", "act_" + str(100 + i))
                if not s.get(AdAccount, identifier):
                    s.add(
                        AdAccount(
                            id=identifier,
                            workspace_id="default",
                            provider="meta",
                            external_id="act_" + str(100 + i),
                            name="Fixture",
                            currency="USD",
                            timezone="UTC",
                            observed_at=self.now,
                        )
                    )
                ids.append(identifier)
            c = s.get(ProviderConnection, ("default", "meta"))
            c.config = {**c.config, "sync_account_ids": ids}
        self.ids = ids
        return ids

    def queue(self, purpose="today", start=None, end=None, **kwargs):
        with self.sessions.begin() as s:
            j, created = jobs.enqueue(
                s,
                "default",
                purpose,
                start or date(2026, 10, 13),
                end or date(2026, 10, 13),
                **kwargs,
            )
            return j.id, created

    def row(self, identifier):
        with self.sessions() as s:
            return s.get(ProviderJob, identifier)

    def test_01_one_account(self):
        j, _ = self.queue()
        self.assertEqual(run_meta_job(self.manager, j)["status"], "succeeded")
        self.assertEqual(len(self.calls), 8)

    def test_02_three_accounts(self):
        self.accounts(3)
        j, _ = self.queue()
        self.assertEqual(run_meta_job(self.manager, j)["status"], "succeeded")
        self.assertEqual(len(self.calls), 18)

    def test_03_169_tasks_full_day(self):
        events = sorted(
            [(i * 600, "today") for i in range(144)]
            + [(i * 3600 + 300, "yesterday") for i in range(24)]
            + [(4 * 3600 + 540, "last7")]
        )
        origin = self.now
        for seconds, purpose in events:
            self.now = origin + timedelta(seconds=seconds)
            j, created = self.queue(purpose)
            self.assertTrue(created)
            self.assertEqual(run_meta_job(self.manager, j)["status"], "succeeded")
        self.assertEqual(len(self.calls), 169 * 8)

    def test_04_duplicate_tick_terminal_and_next_interval(self):
        j, _ = self.queue()
        self.assertEqual(self.queue()[0], j)
        run_meta_job(self.manager, j)
        self.assertEqual(self.queue()[0], j)
        self.now += timedelta(minutes=10)
        self.assertNotEqual(self.queue()[0], j)
        self.assertEqual(len(self.calls), 8)

    def test_05_duplicate_manual(self):
        j, _ = self.queue("manual")
        self.assertEqual(self.queue("manual"), (j, False))
        run_meta_job(self.manager, j)
        self.assertEqual(self.queue("manual"), (j, False))
        self.now += timedelta(minutes=1)
        self.assertNotEqual(self.queue("manual")[0], j)
        self.assertEqual(len(self.calls), 8)

    def test_06_180_day_legacy_held(self):
        with self.sessions.begin() as s:
            s.add(
                ProviderJob(
                    id="legacy",
                    workspace_id="default",
                    provider="meta",
                    kind="sync",
                    start_day=date(2026, 1, 1),
                    end_day=date(2026, 1, 1),
                    status="queued",
                    created_at=self.now - timedelta(days=180),
                )
            )
        self.assertEqual(
            run_meta_job(self.manager, "legacy")["status"], "not_claimable"
        )
        self.assertEqual(self.row("legacy").status, "queued")
        with self.sessions.begin() as s:
            review = jobs.review_legacy(s, "default")
        self.assertTrue(review["inventory"][0]["eligible"])
        with self.sessions.begin() as s:
            jobs.review_legacy(s, "default", apply_digest=review["digest"])
        self.assertEqual(self.row("legacy").status, "expired")
        self.assertEqual(self.row("legacy").error_code, "LEGACY_REVIEWED_STALE_90D")

    def test_07_expired_periodic(self):
        j, _ = self.queue()
        self.now += timedelta(seconds=541)
        self.assertEqual(run_meta_job(self.manager, j)["status"], "not_claimable")
        self.assertEqual(self.row(j).status, "expired")

    def test_08_expired_manual(self):
        j, _ = self.queue("manual")
        self.now += timedelta(seconds=1801)
        run_meta_job(self.manager, j)
        self.assertEqual(self.row(j).error_code, "JOB_TTL_EXPIRED")

    def test_09_running_cancel_cooperative(self):
        j, _ = self.queue()

        def stop(n):
            if n == 1:
                with self.sessions.begin() as s:
                    jobs.cancel(s, "default", j)

        self.after_http = stop
        self.assertEqual(run_meta_job(self.manager, j)["status"], "cancelled")
        self.assertEqual(len(self.calls), 1)

    def test_10_worker_restart_reclaims_owner(self):
        j, _ = self.queue("manual")
        with self.sessions.begin() as s:
            old = jobs.claim(s, "default", j)
        self.now += timedelta(seconds=241)
        with self.sessions.begin() as s:
            new = jobs.claim(s, "default", j)
        self.assertNotEqual(old, new)
        with self.assertRaises(ProviderError):
            jobs.checkpoint(self.sessions, "default", j, old)
        self.assertEqual(self.row(j).recoveries, 1)

    def test_11_broker_loss_fresh_job_still_dispatchable(self):
        j, _ = self.queue("manual")
        self.db.dispose()
        with self.sessions.begin() as s:
            owner = jobs.claim(s, "default", j)
        self.assertIsNotNone(owner)

    def test_12_stale_owner_recovery_limit(self):
        j, _ = self.queue("manual")
        for _ in range(3):
            with self.sessions.begin() as s:
                jobs.claim(s, "default", j)
            self.now += timedelta(seconds=241)
        with self.sessions.begin() as s:
            jobs.maintain(s, "default")
        self.assertEqual(self.row(j).status, "failed")
        self.assertEqual(self.row(j).error_code, "JOB_RECOVERY_LIMIT")

    def test_13_429_no_retry(self):
        def rate(request):
            self.calls.append(request)
            return httpx.Response(
                429, json={"error": {"code": 80004}}, headers={"Retry-After": "30"}
            )

        self.manager.transports["meta"] = httpx.MockTransport(rate)
        j, _ = self.queue()
        run_meta_job(self.manager, j)
        self.assertEqual(len(self.calls), 1)
        with self.sessions() as s:
            self.assertIsNotNone(
                s.get(MetaRateState, "meta-global").cooldown_until
            )

    def test_14_cooldown_survives_new_engine_connection(self):
        with self.sessions.begin() as s:
            s.add(
                MetaRateState(
                    key="meta-global",
                    cooldown_until=self.now + timedelta(hours=2),
                    usage={},
                )
            )
        self.db.dispose()
        with self.sessions() as s:
            self.assertTrue(jobs.in_cooldown(s, "default"))

    def test_15_pending_cancel_no_claim(self):
        j, _ = self.queue()
        with self.sessions.begin() as s:
            jobs.cancel(s, "default", j)
        run_meta_job(self.manager, j)
        self.assertEqual(self.row(j).status, "cancelled")

    def test_16_expire_running_before_next_attempt(self):
        j, _ = self.queue()

        def stop(n):
            if n == 1:
                self.now += timedelta(seconds=541)

        self.after_http = stop
        self.assertEqual(run_meta_job(self.manager, j)["status"], "expired")
        self.assertEqual(len(self.calls), 1)

    def test_17_queue_saturation(self):
        with patch.dict(os.environ, {"META_JOB_QUEUE_LIMIT": "2"}):
            self.queue("manual", end=date(2026, 10, 14))
            self.queue("manual", end=date(2026, 10, 15))
            with self.assertRaises(ProviderError):
                self.queue("manual", end=date(2026, 10, 16))
        with (
            patch.dict(os.environ, {"META_JOB_QUEUE_LIMIT": "2"}),
            self.sessions() as s,
        ):
            self.assertTrue(jobs.monitoring(s, "default")["saturation_warning"])

    def test_18_account_isolation(self):
        self.accounts(3)
        a, _ = self.queue("manual", accounts=[self.ids[0]])
        b, _ = self.queue("manual", accounts=[self.ids[1]])
        self.assertNotEqual(a, b)
        with self.assertRaises(ProviderError):
            self.queue(accounts=["unknown"])

    def test_19_workspace_isolation(self):
        j, _ = self.queue()
        with self.sessions.begin() as s:
            self.assertIsNone(jobs.claim(s, "another", j))
            with self.assertRaises(ProviderError):
                jobs.cancel(s, "another", j)

    def test_20_superseded_pending_and_configuration(self):
        os.environ["META_JOB_TTL_TODAY_SECONDS"] = "1200"
        j, _ = self.queue()
        self.now += timedelta(minutes=10)
        new, _ = self.queue()
        self.assertNotEqual(j, new)
        self.assertEqual(self.row(j).error_code, "JOB_SUPERSEDED")
        with self.sessions.begin() as s:
            c = s.get(ProviderConnection, ("default", "meta"))
            c.revision += 1
            jobs.maintain(s, "default")
        self.assertEqual(self.row(new).error_code, "JOB_CONFIG_SUPERSEDED")

    def test_21_pagination_actual_attempts(self):
        original = self.manager.transports["meta"].handler

        def pages(request):
            result = original(request)
            if request.url.path.endswith("/adcreatives"):
                body = result.json()
                if "after" not in request.url.params:
                    body["paging"] = {
                        "next": "https://graph.facebook.com/v26.0/act_100/adcreatives?after=x",
                        "cursors": {"after": "x"},
                    }
                else:
                    body["data"][0]["id"] = "31" + "100"
                return httpx.Response(200, json=body)
            return result

        self.manager.transports["meta"] = httpx.MockTransport(pages)
        j, _ = self.queue()
        self.assertEqual(run_meta_job(self.manager, j)["status"], "succeeded")
        self.assertEqual(len(self.calls), 9)
        with self.sessions() as s:
            self.assertEqual(
                s.scalar(
                    select(func.count())
                    .select_from(MetaRequestAttempt)
                    .where(MetaRequestAttempt.page > 1)
                ),
                1,
            )

    def test_22_retry_actual_attempts(self):
        original = self.manager.transports["meta"].handler

        def retry(request):
            if not self.calls:
                self.calls.append(request)
                return httpx.Response(503, json={})
            return original(request)

        self.manager.transports["meta"] = httpx.MockTransport(retry)
        j, _ = self.queue()
        self.assertEqual(run_meta_job(self.manager, j)["status"], "succeeded")
        self.assertEqual(len(self.calls), 9)
        with self.sessions() as s:
            self.assertEqual(
                s.scalar(
                    select(func.count())
                    .select_from(MetaRequestAttempt)
                    .where(MetaRequestAttempt.attempt > 1)
                ),
                1,
            )

    def test_23_original_periodic_deadline_not_extended(self):
        j, _ = self.queue(
            published_at=self.now - timedelta(minutes=10),
            message_deadline=self.now - timedelta(seconds=1),
        )
        self.assertEqual(self.row(j).status, "expired")
        self.assertEqual(run_meta_job(self.manager, j)["status"], "not_claimable")

    def test_24_out_of_order_tick_cannot_supersede_newer(self):
        with patch.dict(os.environ, {"META_JOB_TTL_TODAY_SECONDS": "1200"}):
            current, _ = self.queue()
            delayed, created = self.queue(published_at=self.now - timedelta(minutes=10))
        self.assertEqual(delayed, current)
        self.assertFalse(created)
        self.assertEqual(self.row(current).status, "queued")

    def test_25_health_cancellation_does_not_poison_connection(self):
        j, _ = self.queue("health")

        def stop(n):
            if n == 1:
                with self.sessions.begin() as s:
                    jobs.cancel(s, "default", j)

        self.after_http = stop
        self.assertEqual(run_meta_job(self.manager, j)["status"], "cancelled")
        self.assertEqual(len(self.calls), 1)
        with self.sessions() as s:
            self.assertEqual(
                s.get(ProviderConnection, ("default", "meta")).status, "healthy"
            )
