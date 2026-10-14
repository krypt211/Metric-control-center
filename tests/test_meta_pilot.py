"""Bounded Meta pilot tests. No real Graph transport is constructed."""

import copy
import os
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from test_providers import CREDS, account, graph
from test_sync import StorageFixture

from services.meta import jobs, pilot
from services.meta.pilot_models import MetaPilotSession
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
from services.sync.engine import utc_now
from workers.providers import run_meta_job


class PilotTests(StorageFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        key = Path(self.directory.name) / "cipher"
        key.write_bytes(Fernet.generate_key())
        self.env = patch.dict(
            os.environ,
            {
                "PROVIDER_ENCRYPTION_KEY_FILE": str(key),
                "META_CONTROLLED_READ_PILOT": "true",
                "ACTIONS_ENABLED": "false",
                "LOCAL_READ_ONLY": "true",
                "AI_ENABLED": "false",
                "AI_AUTOPILOT_ALLOWED": "false",
                "META_PILOT_AUTHORIZED_SESSION_ID": "",
                "META_PILOT_CONFIRMED_GRAPH_VERSION": "v26.0",
            },
        )
        self.env.start()
        self.calls = []
        self.behavior = None
        self.after = None
        with self.sessions.begin() as s:
            s.add(
                ProviderConnection(
                    workspace_id="default",
                    provider="meta",
                    enabled=False,
                    credential_source="encrypted",
                    revision=1,
                    status="disconnected",
                    config={"graph_version": "v26.0", "app_id": "123"},
                    permissions={},
                    capabilities={},
                    quota={},
                    updated_at=utc_now(),
                )
            )
            s.add(
                ProviderCredential(
                    workspace_id="default",
                    provider="meta",
                    encrypted=encrypt("default", "meta", CREDS),
                    updated_at=utc_now(),
                )
            )

        def transport(request):
            self.assertEqual(request.method, "GET")
            self.assertNotIn("me/adaccounts", str(request.url.path))
            self.calls.append(request)
            response = self.behavior(request) if self.behavior else None
            if response is None:
                response = (
                    httpx.Response(200, json=account())
                    if request.url.path.endswith("/act_100")
                    else graph(request)
                )
            if self.after:
                self.after()
            return response

        self.manager = ProviderManager(
            self.sessions, transports={"meta": httpx.MockTransport(transport)}
        )

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    def prepare(self, maximum=20):
        with self.sessions.begin() as s:
            row = pilot.prepared(
                s,
                "default",
                "act_100",
                utc_now().date() - timedelta(days=1),
                utc_now().date() - timedelta(days=1),
                maximum,
            )
            return row.id

    def start(self, identifier):
        os.environ["META_PILOT_AUTHORIZED_SESSION_ID"] = identifier
        with self.sessions.begin() as s:
            job_id = pilot.start(s, "default", identifier, "fixture").job_id
            self.assertEqual(len(s.get(ProviderJob, job_id).active_key), 64)
            return job_id

    def execute(self, maximum=20):
        identifier = self.prepare(maximum)
        job = self.start(identifier)
        run_meta_job(self.manager, job)
        with self.sessions() as s:
            row = s.get(MetaPilotSession, identifier)
            attempts = s.scalar(select(func.count()).select_from(MetaRequestAttempt))
            self.assertEqual(row.used_attempts, attempts)
            self.assertEqual(attempts, len(self.calls))
            self.assertFalse(s.get(ProviderConnection, ("default", "meta")).enabled)
            return row.status, row.reason, attempts

    def test_01_preparation_never_authorizes(self):
        identifier = self.prepare()
        with (
            self.sessions.begin() as s,
            self.assertRaisesRegex(ProviderError, "META_PILOT_APPROVAL_REQUIRED"),
        ):
            pilot.start(s, "default", identifier, "fixture")
        self.assertEqual(self.calls, [])

    def test_02_one_account_eight_gets(self):
        self.assertEqual(self.execute(), ("SUCCEEDED", "META_PILOT_COMPLETED", 8))
        self.assertEqual(
            {r.url.path.split("/")[2] for r in self.calls[2:]}, {"act_100"}
        )

    def test_03_pagination_budget_twenty(self):
        def pages(request):
            if request.url.path.endswith("/campaigns"):
                after = request.url.params.get("after", "0")
                body = copy.deepcopy(graph(request).json())
                body["data"][0]["id"] = "10" + after
                body["paging"] = {
                    "next": "https://graph.facebook.com/v26.0/act_100/campaigns",
                    "cursors": {"after": str(int(after) + 1)},
                }
                return httpx.Response(200, json=body)

        self.behavior = pages
        self.assertEqual(self.execute(), ("STOPPED", "META_PILOT_ATTEMPT_LIMIT", 20))

    def test_04_retry_counted_and_bounded(self):
        def retry(request):
            if (
                request.url.path.endswith("/campaigns")
                and sum(r.url.path.endswith("/campaigns") for r in self.calls) == 1
            ):
                return httpx.Response(
                    503, json={"error": {"code": 2, "is_transient": True}}
                )

        self.behavior = retry
        self.assertEqual(self.execute(), ("SUCCEEDED", "META_PILOT_COMPLETED", 9))

    def test_05_429_stop_and_durable_cooldown(self):
        self.behavior = lambda r: httpx.Response(
            429, json={"error": {"code": 4}}, headers={"retry-after": "30"}
        )
        self.assertEqual(self.execute(), ("STOPPED", "META_RATE_LIMIT", 1))
        with self.sessions() as s:
            self.assertIsNotNone(s.get(MetaRateState, "meta-global").cooldown_until)

    def test_06_permission_stop(self):
        self.behavior = lambda r: httpx.Response(403, json={"error": {"code": 200}})
        self.assertEqual(self.execute(), ("STOPPED", "META_PERMISSION_DENIED", 1))

    def test_07_invalid_token_stop(self):
        self.behavior = lambda r: httpx.Response(401, json={"error": {"code": 190}})
        self.assertEqual(self.execute(), ("STOPPED", "META_TOKEN_INVALID", 1))

    def test_08_unknown_response_stops(self):
        self.behavior = lambda r: httpx.Response(200, json=[])
        self.assertEqual(self.execute(), ("STOPPED", "META_INVALID_RESPONSE", 1))

    def test_09_account_binding(self):
        self.behavior = lambda r: (
            httpx.Response(200, json=account("200"))
            if r.url.path.endswith("/act_100")
            else None
        )
        self.assertEqual(self.execute(), ("STOPPED", "META_PILOT_ACCOUNT_BINDING", 3))

    def test_10_stale_jobs_held(self):
        with self.sessions.begin() as s:
            s.add(
                ProviderJob(
                    id="old",
                    workspace_id="default",
                    provider="meta",
                    kind="sync",
                    start_day=date(2020, 1, 1),
                    end_day=date(2020, 1, 1),
                    status="queued",
                    created_at=utc_now(),
                )
            )
        identifier = self.prepare()
        os.environ["META_PILOT_AUTHORIZED_SESSION_ID"] = identifier
        with (
            self.sessions.begin() as s,
            self.assertRaisesRegex(ProviderError, "META_PILOT_EXISTING_JOBS_HELD"),
        ):
            pilot.start(s, "default", identifier, "fixture")
        self.assertEqual(
            run_meta_job(self.manager, "old")["status"], "pilot_existing_job_held"
        )
        self.assertEqual(self.calls, [])

    def test_11_standard_manager_and_enqueue_blocked(self):
        with self.assertRaisesRegex(ProviderError, "META_PILOT_STANDARD_READ_HELD"):
            self.manager.create("meta")
        with self.sessions.begin() as s, self.assertRaises(ProviderError):
            jobs.enqueue(s, "default", "health", utc_now().date(), utc_now().date())
        self.assertEqual(self.calls, [])

    def test_12_other_account_requires_new_session_approval(self):
        identifier = self.prepare()
        self.start(identifier)
        with (
            self.sessions.begin() as s,
            self.assertRaisesRegex(ProviderError, "META_PILOT_ALREADY_RUNNING"),
        ):
            pilot.prepared(s, "default", "act_200", utc_now().date(), utc_now().date())
        self.assertEqual(self.calls, [])

    def test_13_restart_no_budget_reset(self):
        identifier = self.prepare()
        job = self.start(identifier)
        with self.sessions.begin() as s:
            s.get(MetaPilotSession, identifier).used_attempts = 20
        manager = ProviderManager(self.sessions, transports=self.manager.transports)
        run_meta_job(manager, job)
        with self.sessions() as s:
            row = s.get(MetaPilotSession, identifier)
            self.assertEqual(row.used_attempts, 20)
            self.assertEqual(row.status, "STOPPED")
        self.assertEqual(self.calls, [])

    def test_14_cooperative_cancel(self):
        def cancel():
            if len(self.calls) == 1:
                with self.sessions.begin() as s:
                    row = s.scalar(select(MetaPilotSession))
                    pilot.stop(s, "default", row.id)

        self.after = cancel
        status, reason, n = self.execute()
        self.assertEqual(
            (status, reason, n), ("CANCELLED", "META_PILOT_USER_CANCELLED", 1)
        )

    def test_15_expiration_no_http(self):
        identifier = self.prepare()
        job = self.start(identifier)
        with self.sessions.begin() as s:
            row = s.get(MetaPilotSession, identifier)
            row.deadline = utc_now() - timedelta(seconds=1)
        run_meta_job(self.manager, job)
        self.assertEqual(self.calls, [])

    def test_16_wrong_scope_and_window_rejected(self):
        with self.sessions.begin() as s, self.assertRaises(ProviderError):
            pilot.prepared(
                s,
                "default",
                "act_100",
                utc_now().date() - timedelta(days=7),
                utc_now().date(),
            )
        identifier = self.prepare()
        os.environ["META_PILOT_AUTHORIZED_SESSION_ID"] = identifier
        with self.sessions() as s, self.assertRaises(ProviderError):
            pilot.authorization(s, "other", identifier)

    def test_17_headers_and_attempt_journal(self):
        def headers(request):
            response = (
                httpx.Response(200, json=account())
                if request.url.path.endswith("/act_100")
                else graph(request)
            )
            response.headers["x-fb-ads-insights-throttle"] = (
                '{"app_id_util_pct":1,"ads_api_access_tier":"standard_access"}'
            )
            return response

        self.behavior = headers
        self.assertEqual(self.execute()[2], 8)
        with self.sessions() as s:
            report = pilot.metadata(s, "default")
            self.assertEqual(report["access_tier"], "standard_access")
            for r in s.scalars(select(MetaRequestAttempt)):
                self.assertEqual(r.outcome, "OK")
                self.assertTrue(r.source.startswith("pilot:"))

    def test_18_minimum_budget_no_auto_increase(self):
        self.assertEqual(self.execute(7), ("STOPPED", "META_PILOT_ATTEMPT_LIMIT", 7))

    def test_19_unconfirmed_graph_version_blocks(self):
        identifier = self.prepare()
        os.environ["META_PILOT_AUTHORIZED_SESSION_ID"] = identifier
        os.environ["META_PILOT_CONFIRMED_GRAPH_VERSION"] = ""
        with (
            self.sessions.begin() as s,
            self.assertRaisesRegex(
                ProviderError, "META_PILOT_GRAPH_VERSION_UNCONFIRMED"
            ),
        ):
            pilot.start(s, "default", identifier, "fixture")
        self.assertEqual(self.calls, [])

    def test_20_expired_token_stops(self):
        def expired(request):
            if request.url.path.endswith("/debug_token"):
                body = graph(request).json()
                body["data"]["expires_at"] = 1
                return httpx.Response(200, json=body)

        self.behavior = expired
        self.assertEqual(self.execute(), ("STOPPED", "META_TOKEN_EXPIRED", 1))

    def test_21_running_timeout_stops_before_next_attempt(self):
        def expire():
            if len(self.calls) == 1:
                with self.sessions.begin() as s:
                    s.scalar(select(MetaPilotSession)).deadline = utc_now() - timedelta(
                        seconds=1
                    )

        self.after = expire
        self.assertEqual(self.execute(), ("STOPPED", "META_PILOT_TIMEOUT", 1))

    def test_22_restart_owner_lost_does_not_replay(self):
        identifier = self.prepare()
        job = self.start(identifier)
        with self.sessions.begin() as s:
            jobs.claim(s, "default", job)
            s.get(ProviderJob, job).lease_until = utc_now() - timedelta(seconds=1)
        with self.sessions.begin() as s:
            jobs.maintain(s, "default")
        with self.sessions() as s:
            self.assertEqual(
                s.get(ProviderJob, job).error_code, "META_PILOT_OWNER_LOST"
            )
            self.assertEqual(s.get(MetaPilotSession, identifier).status, "STOPPED")
        self.assertEqual(self.calls, [])

    def test_23_revoked_session_gate_stops(self):
        def revoke():
            if len(self.calls) == 1:
                os.environ["META_PILOT_AUTHORIZED_SESSION_ID"] = ""

        self.after = revoke
        self.assertEqual(self.execute(), ("STOPPED", "META_PILOT_APPROVAL_REQUIRED", 1))

    def test_24_partial_diagnostics_survive_catalog_failure(self):
        def denied(request):
            if request.url.path.endswith("/adsets"):
                return httpx.Response(403, json={"error": {"code": 200}})

        self.behavior = denied
        self.assertEqual(self.execute(), ("STOPPED", "META_PERMISSION_DENIED", 5))
        with self.sessions() as s:
            result = s.scalar(select(MetaPilotSession)).result
            self.assertTrue(result["token_verified"])
            self.assertTrue(result["permissions_read"])
            self.assertTrue(result["account_verified"])
            self.assertEqual(result["catalog_rows"], {"campaign": 1})
            self.assertEqual(result["stage"], "CATALOG_ADSET")
            self.assertFalse(result["facts_published"])

    def test_25_account_timezone_change_stops_before_catalog(self):
        with self.sessions.begin() as s:
            s.add(
                AdAccount(
                    id="selected-account",
                    workspace_id="default",
                    provider="meta",
                    external_id="act_100",
                    name="Synthetic",
                    currency="USD",
                    timezone="America/Los_Angeles",
                    observed_at=utc_now(),
                )
            )
        self.assertEqual(
            self.execute(), ("STOPPED", "META_PILOT_ACCOUNT_TIMEZONE_CHANGED", 3)
        )
