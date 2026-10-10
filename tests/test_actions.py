from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
import unittest
import os
from unittest.mock import patch

from sqlalchemy import select

from services.actions.engine import ActionEngine, ActionPolicy, ActionRejected
from services.metricflow.errors import ActionOutcomeUnknown
from services.storage.models import ActionExecution, ActionLog, ActionRequest, AdAccount, Entity, EntityCurrentState, User
from test_sync import NOW, StorageFixture


class FakeWriter:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def pause_entity(self, external):
        self.calls.append(("pause", external))
        if self.fail:
            raise ActionOutcomeUnknown("timeout")

    async def enable_entity(self, external):
        self.calls.append(("enable", external))

    async def change_budget(self, external, *, provider_payload):
        self.calls.append(("budget", external, provider_payload))


class ActionTests(StorageFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        # Only fake writers in these legacy execution contract tests.
        allowed = patch.dict(os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"})
        allowed.start()
        self.addCleanup(allowed.stop)
        self.now = NOW
        self.policy = ActionPolicy(enabled=True, budget_contract={"verified": True, "field": "synthetic", "scale": "100", "encoding": "integer"})
        self.engine = ActionEngine(self.sessions, self.policy, clock=lambda: self.now)
        with self.sessions.begin() as session:
            session.add(User(id="operator", workspace_id="default", email="operator@example.invalid", role="operator"))
            session.add(User(id="viewer", workspace_id="default", email="viewer@example.invalid", role="viewer"))
            session.add(AdAccount(id="account", workspace_id="default", provider="metricflow", external_id="act_900", name="Account", currency="USD", timezone="Europe/Moscow", observed_at=NOW))
            session.flush()
            session.add(Entity(id="entity", account_id="account", kind="adset", external_id="999", name="Adset"))
            session.flush()
            session.add(EntityCurrentState(entity_id="entity", status="ACTIVE", budget=Decimal(100), bid=None, observed_at=NOW, raw={}))

    def enqueue(self, action="pause", value=None, key="one"):
        return self.engine.enqueue("default", "operator", "entity", action, value, key)

    async def test_environment_gate_blocks_legacy_queue_before_attempt(self):
        request_id = self.enqueue()
        writer = FakeWriter()
        with patch.dict(os.environ, {"ACTIONS_ENABLED": "false", "LOCAL_READ_ONLY": "true"}):
            await self.engine.execute_next(writer)
        with self.sessions() as s:
            self.assertEqual(s.get(ActionRequest, request_id).status, "rejected")
            self.assertIsNone(s.scalar(select(ActionExecution).where(ActionExecution.request_id == request_id)))
            self.assertIn("WRITE_DISABLED", str(s.scalar(select(ActionLog.details).where(ActionLog.event == "rejected"))))
        self.assertEqual(writer.calls, [])

    async def test_duplicate_request_never_calls_provider_twice(self):
        first = self.enqueue()
        self.assertEqual(first, self.enqueue())
        writer = FakeWriter()
        await self.engine.execute_next(writer)
        await self.engine.execute_next(writer)
        self.assertEqual(writer.calls, [("pause", "999")])
        with self.sessions() as session:
            self.assertEqual(session.get(ActionRequest, first).status, "verifying")

    async def test_changed_payload_and_concurrent_entity_request_are_rejected(self):
        self.enqueue()
        with self.assertRaises(ActionRejected):
            self.enqueue("budget_set", Decimal(80))
        with self.assertRaises(ActionRejected):
            self.enqueue(key="two")

    async def test_viewer_stale_state_and_budget_limits_are_rejected(self):
        with self.assertRaises(ActionRejected):
            self.engine.enqueue("default", "viewer", "entity", "pause", None, "v")
        with self.assertRaises(ActionRejected):
            self.enqueue("budget_set", Decimal(70))
        with self.assertRaises(ActionRejected):
            self.engine.enqueue("other", "operator", "entity", "pause", None, "x")
        self.now += timedelta(hours=1)
        with self.assertRaises(ActionRejected):
            self.enqueue()

    async def test_budget_contract_is_required_and_verified_encoding_is_used(self):
        unconfigured = ActionEngine(self.sessions, ActionPolicy(enabled=True), clock=lambda: self.now)
        with self.assertRaises(ActionRejected):
            unconfigured.enqueue("default", "operator", "entity", "budget_set", Decimal(80), "b")
        self.enqueue("budget_set", Decimal(80))
        writer = FakeWriter()
        await self.engine.execute_next(writer)
        self.assertEqual(writer.calls, [("budget", "999", {"synthetic": 8000})])

    async def test_state_drift_before_execution_prevents_api_call(self):
        request_id = self.enqueue()
        with self.sessions.begin() as session:
            session.get(EntityCurrentState, "entity").budget = Decimal(120)
        writer = FakeWriter()
        await self.engine.execute_next(writer)
        self.assertEqual(writer.calls, [])
        with self.sessions() as session:
            self.assertEqual(session.get(ActionRequest, request_id).status, "rejected")

    async def test_timeout_is_verified_from_new_sync_without_resending(self):
        request_id = self.enqueue()
        writer = FakeWriter(fail=True)
        await self.engine.execute_next(writer)
        self.engine.verify_pending()
        with self.sessions() as session:
            self.assertEqual(session.get(ActionRequest, request_id).status, "verifying")
        self.now += timedelta(minutes=10)
        with self.sessions.begin() as session:
            state = session.get(EntityCurrentState, "entity")
            state.status, state.observed_at = "PAUSED", self.now
        self.assertEqual(self.engine.verify_pending(), 1)
        self.assertEqual(len(writer.calls), 1)
        with self.sessions() as session:
            self.assertEqual(session.get(ActionRequest, request_id).status, "succeeded")
            self.assertIn("verified", [r.event for r in session.scalars(select(ActionLog).where(ActionLog.request_id == request_id))])

    async def test_worker_crash_recovers_to_verification_never_requeues(self):
        request_id = self.enqueue()
        with self.sessions.begin() as session:
            session.get(ActionRequest, request_id).status = "executing"
            session.add(ActionExecution(id=str(uuid4()), request_id=request_id, started_at=self.now, outcome="started"))
        self.now += timedelta(minutes=3)
        self.engine.verify_pending()
        writer = FakeWriter()
        await self.engine.execute_next(writer)
        self.assertEqual(writer.calls, [])
        with self.sessions() as session:
            self.assertEqual(session.get(ActionRequest, request_id).status, "verifying")

    async def test_unverified_timeout_blocks_followup_commands(self):
        request_id = self.enqueue()
        await self.engine.execute_next(FakeWriter())
        self.now += timedelta(minutes=31)
        with self.sessions.begin() as session:
            session.get(EntityCurrentState, "entity").observed_at = self.now
        self.engine.verify_pending()
        with self.sessions() as session:
            self.assertEqual(session.get(ActionRequest, request_id).status, "unknown")
        with self.assertRaises(ActionRejected):
            self.enqueue(key="new-command")
