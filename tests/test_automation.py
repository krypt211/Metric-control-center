from datetime import timedelta
from decimal import Decimal
import threading
import unittest

from pydantic import ValidationError
from sqlalchemy import func, select

from services.actions.engine import ActionEngine, ActionPolicy, ActionRejected
from services.actions.providers import supports
from services.automation.batches import BatchEngine
from services.automation.rules import RuleEngine
from services.automation.schema import BulkCommand, RuleDefinition
from services.storage.models import (
    ActionLog, ActionRequest, Ad, AdAccount, AdSet, BatchAction, BatchItem,
    DailyMetric, Entity, EntityCurrentState, Rule, RuleCooldown, RuleRun, User,
)
from test_sync import DAY, NOW, StorageFixture
from test_actions import FakeWriter


def definition(**changes):
    return RuleDefinition.model_validate({"name": "Scale Winner", "currency": "USD",
        "conditions": [{"metric": "roi", "operator": ">=", "value": "100"},
                       {"metric": "conversions", "operator": ">=", "value": "5"},
                       {"metric": "spend", "operator": ">=", "value": "50"}],
        "operation": {"kind": "budget_change", "value": "20"}, "max_budget": "300", **changes})


class AutomationFixture(StorageFixture):
    def setUp(self):
        super().setUp()
        import os
        from unittest.mock import patch
        allowed = patch.dict(os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"})
        allowed.start()
        self.addCleanup(allowed.stop)
        self.now = NOW
        self.policy = ActionPolicy(enabled=True, budget_contract={"verified": True, "field": "test_budget", "scale": "100", "encoding": "integer"})
        self.actions = ActionEngine(self.sessions, self.policy, clock=lambda: self.now)
        self.rules = RuleEngine(self.actions)
        self.batches = BatchEngine(self.actions)
        with self.sessions.begin() as session:
            session.add(User(id="operator", workspace_id="default", email="test@example.invalid", role="operator"))
            session.add(User(id="viewer", workspace_id="default", email="viewer@example.invalid", role="viewer"))
            session.add(AdAccount(id="account", workspace_id="default", provider="metricflow", external_id="act_100", currency="USD", timezone="Europe/Moscow", observed_at=NOW))
            session.flush()
            session.add(Entity(id="set", account_id="account", kind="adset", external_id="900", name="Winning adset"))
            session.add(Entity(id="second-set", account_id="account", kind="adset", external_id="901", name="Second adset"))
            session.flush()
            session.add(AdSet(entity_id="set"))
            session.add(AdSet(entity_id="second-set"))
            session.add(EntityCurrentState(entity_id="set", status="ACTIVE", budget=Decimal("100"), observed_at=NOW, raw={}))
            session.add(EntityCurrentState(entity_id="second-set", status="PAUSED", budget=Decimal("100"), observed_at=NOW, raw={}))
            for i in range(2):
                entity_id = f"ad-{i}"
                session.add(Entity(id=entity_id, account_id="account", kind="ad", external_id=str(100 + i), name=f"Ad {i}"))
                session.flush()
                session.add(Ad(entity_id=entity_id, adset_id="set"))
                session.add(DailyMetric(entity_id=entity_id, day=DAY, source="metricflow", currency="USD", timezone="Europe/Moscow",
                    spend=Decimal("50"), revenue=Decimal("100"), conversions=5, leads=5, sales=2, impressions=1000, clicks=20, observed_at=NOW, raw={}))

    def rule(self, mode="DRY_RUN", **changes):
        return self.rules.save("default", "operator", definition(**changes), mode)

    def refresh(self):
        with self.sessions.begin() as session:
            for row in session.scalars(select(DailyMetric)):
                row.observed_at = self.now
            for row in session.scalars(select(EntityCurrentState)):
                row.observed_at = self.now

    def count(self, model):
        with self.sessions() as session:
            return session.scalar(select(func.count()).select_from(model))


class RuleTests(AutomationFixture, unittest.TestCase):
    def test_dry_run_aggregates_ad_facts_and_never_queues_even_when_actions_disabled(self):
        engine = RuleEngine(ActionEngine(self.sessions, ActionPolicy(enabled=False), clock=lambda: self.now))
        rule_id = engine.save("default", "operator", definition())
        engine.evaluate(rule_id, "default")
        with self.sessions() as session:
            run = session.scalar(select(RuleRun))
            self.assertEqual(run.status, "would_act")
            self.assertEqual(Decimal(run.payload["value"]), Decimal("120"))
            self.assertEqual(Decimal(run.payload["metrics"]["spend"]), Decimal("100"))
            self.assertEqual(run.payload["metrics"]["conversions"], 10)
            self.assertIsNone(run.request_id)
        self.assertEqual(self.count(ActionRequest), 0)
        self.assertEqual(self.count(RuleCooldown), 0)

    def test_off_does_not_evaluate_or_queue(self):
        self.assertEqual(self.rules.evaluate(self.rule("OFF"), "default")["status"], "off_or_not_due")
        self.assertEqual(self.count(RuleRun), 0)
        self.assertEqual(self.count(ActionRequest), 0)

    def test_active_queue_contains_author_before_after_source_and_evidence(self):
        self.rules.evaluate(self.rule("ACTIVE"), "default")
        with self.sessions() as session:
            request = session.scalar(select(ActionRequest))
            self.assertEqual(request.status, "queued")
            self.assertEqual(request.value, Decimal("120"))
            self.assertEqual(request.provenance["source"], "rule")
            self.assertEqual(request.provenance["actor"], "test@example.invalid")
            self.assertEqual(request.provenance["rule_name"], "Scale Winner")
            self.assertEqual(Decimal(request.provenance["before"]["budget"]), 100)
            self.assertEqual(Decimal(request.provenance["after"]["budget"]), 120)
            self.assertEqual(request.provenance["reason"]["metrics"]["conversions"], 10)
            self.assertEqual(session.scalar(select(ActionLog)).details["source"], "rule")
        self.assertEqual(self.count(RuleCooldown), 1)

    def test_repeated_snapshot_and_competing_workers_do_not_duplicate_requests(self):
        rule_id = self.rule("ACTIVE")
        results, errors = [], []
        barrier = threading.Barrier(2)
        def evaluate():
            try:
                barrier.wait(timeout=5)
                results.append(RuleEngine(self.actions).evaluate(rule_id, "default"))
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=evaluate) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(item["status"] for item in results), ["evaluated", "off_or_not_due"])
        self.now += timedelta(minutes=5)
        self.rules.evaluate(rule_id, "default")
        self.assertEqual(self.count(ActionRequest), 1)
        self.assertEqual(self.count(RuleRun), 1)

    def test_cooldown_survives_restart_and_edit_then_allows_after_expiry(self):
        rule_id = self.rule("ACTIVE")
        self.rules.evaluate(rule_id, "default")
        self.now += timedelta(minutes=5)
        self.refresh()
        restarted = RuleEngine(ActionEngine(self.sessions, self.policy, clock=lambda: self.now))
        restarted.save("default", "operator", definition(name="Renamed"), "ACTIVE", rule_id, 1)
        restarted.evaluate(rule_id, "default")
        self.assertEqual(self.count(ActionRequest), 1)
        with self.sessions() as session:
            self.assertIn("cooldown", session.scalars(select(RuleRun.status)).all())
        self.now += timedelta(hours=8)
        self.refresh()
        with self.sessions.begin() as session:
            session.scalar(select(ActionRequest)).status = "succeeded"
            session.get(EntityCurrentState, "set").budget = Decimal("120")
        restarted.evaluate(rule_id, "default")
        self.assertEqual(self.count(ActionRequest), 2)

    def test_unknown_conversions_do_not_become_zero_in_stop_rule(self):
        with self.sessions.begin() as session:
            session.get(DailyMetric, ("ad-0", DAY, "metricflow")).conversions = None
            session.get(DailyMetric, ("ad-1", DAY, "metricflow")).conversions = 0
        rule_id = self.rule("ACTIVE", conditions=[{"metric": "spend", "operator": ">=", "value": 20}, {"metric": "conversions", "operator": "=", "value": 0}], operation={"kind": "pause"}, max_budget=None)
        self.rules.evaluate(rule_id, "default")
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(RuleRun.status)), "unknown_metrics")
        self.assertEqual(self.count(ActionRequest), 0)

    def test_budget_ceiling_and_global_percentage_limit_apply_to_dry_run_too(self):
        self.rules.evaluate(self.rule(max_budget="110"), "default")
        self.rules.evaluate(self.rule(operation={"kind": "budget_change", "value": 30}), "default")
        with self.sessions() as session:
            self.assertEqual(session.scalars(select(RuleRun.status)).all(), ["rejected", "rejected"])
        self.assertEqual(self.count(ActionRequest), 0)

    def test_stale_facts_block_action_even_if_entity_state_is_fresh(self):
        self.now += timedelta(hours=1)
        with self.sessions.begin() as session:
            session.get(EntityCurrentState, "set").observed_at = self.now
        self.rules.evaluate(self.rule("ACTIVE"), "default")
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(RuleRun.status)), "stale_metrics")
        self.assertEqual(self.count(ActionRequest), 0)

    def test_currency_timezone_account_scope_and_workspace_are_respected(self):
        for changes in ({"currency": "EUR"}, {"timezone": "UTC"}, {"account_ids": ["missing"]}):
            if "account_ids" in changes:
                with self.assertRaises(ActionRejected): self.rule(**changes)
            else:
                self.rules.evaluate(self.rule("ACTIVE", **changes), "default")
        rule_id = self.rule("ACTIVE")
        self.rules.evaluate(rule_id, "other")
        self.assertEqual(self.count(ActionRequest), 0)
        self.assertEqual(self.count(RuleRun), 0)

    def test_schedule_minimum_events_and_no_match(self):
        self.assertEqual(self.rules.evaluate(self.rule(schedule_start="00:00", schedule_end="01:00"), "default")["status"], "outside_schedule")
        self.rules.evaluate(self.rule(minimum_events=11), "default")
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(RuleRun.status)), "no_match")

    def test_rule_edit_revision_and_create_replay_are_checked(self):
        first = self.rules.create_once("default", "operator", definition(), "DRY_RUN", "fixed-id")
        self.assertEqual(first, self.rules.create_once("default", "operator", definition(), "DRY_RUN", "fixed-id"))
        with self.assertRaises(ActionRejected): self.rules.create_once("default", "operator", definition(name="Changed"), "DRY_RUN", "fixed-id")
        self.rules.save("default", "operator", definition(), "OFF", first, 1)
        with self.assertRaises(ActionRejected): self.rules.save("default", "operator", definition(), "ACTIVE", first, 1)
        with self.assertRaises(ActionRejected): self.rules.save("default", "viewer", definition())

    def test_concurrent_rule_edits_do_not_overwrite_a_newer_revision(self):
        rule_id = self.rule()
        results, errors = [], []
        barrier = threading.Barrier(2)
        def edit(name):
            try:
                barrier.wait(timeout=5)
                self.rules.save("default", "operator", definition(name=name), "OFF", rule_id, 1)
                results.append(name)
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=edit, args=(name,)) for name in ("Edit A", "Edit B")]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ActionRejected)
        with self.sessions() as session:
            rule = session.get(Rule, rule_id)
            self.assertEqual(rule.revision, 2)
            self.assertEqual(rule.payload["name"], results[0])

    def test_active_always_obeys_disabled_policy_and_unverified_budget_contract(self):
        for policy in (ActionPolicy(enabled=False), ActionPolicy(enabled=True)):
            engine = RuleEngine(ActionEngine(self.sessions, policy, clock=lambda: self.now))
            rule_id = engine.save("default", "operator", definition(), "ACTIVE")
            engine.evaluate(rule_id, "default")
        self.assertEqual(self.count(ActionRequest), 0)
        with self.sessions() as session:
            self.assertEqual(session.scalars(select(RuleRun.status)).all(), ["rejected", "rejected"])

    def test_exact_roi_does_not_round_up_to_threshold(self):
        with self.sessions.begin() as session:
            session.get(DailyMetric, ("ad-0", DAY, "metricflow")).revenue = Decimal("99.999999")
        self.rules.evaluate(self.rule("ACTIVE"), "default")
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(RuleRun.status)), "no_match")
        self.assertEqual(self.count(ActionRequest), 0)


class BatchTests(AutomationFixture, unittest.TestCase):
    def test_partial_rejection_does_not_abort_other_entities_and_replay_is_identical(self):
        command = BulkCommand(entity_ids=["set", "second-set", "missing"], operation={"kind": "pause"})
        batch_id = self.batches.submit("default", "operator", command, "batch-one")
        self.assertEqual(batch_id, self.batches.submit("default", "operator", command, "batch-one"))
        with self.sessions() as session:
            statuses = {row.entity_id: row.status for row in session.scalars(select(BatchItem))}
            self.assertEqual(statuses, {"set": "queued", "second-set": "rejected", "missing": "rejected"})
            request = session.scalar(select(ActionRequest))
            self.assertEqual(request.provenance["batch_id"], batch_id)
            self.assertEqual(request.provenance["source"], "web")
        self.assertEqual(self.count(ActionRequest), 1)
        self.assertEqual(self.count(BatchAction), 1)
        with self.assertRaises(ActionRejected): self.batches.submit("default", "operator", BulkCommand(entity_ids=["set"], operation={"kind": "enable"}), "batch-one")

    def test_pending_conflict_is_isolated_with_savepoint(self):
        self.actions.enqueue("default", "operator", "set", "pause", None, "manual")
        self.batches.submit("default", "operator", BulkCommand(entity_ids=["set", "second-set"], operation={"kind": "budget_change", "value": "10"}), "batch")
        with self.sessions() as session:
            self.assertEqual({row.entity_id: row.status for row in session.scalars(select(BatchItem))}, {"set": "rejected", "second-set": "queued"})
        self.assertEqual(self.count(ActionRequest), 2)

    def test_percent_uses_individual_budget_and_decimal_rounding(self):
        with self.sessions.begin() as session:
            session.get(EntityCurrentState, "set").budget = Decimal("50")
        self.batches.submit("default", "operator", BulkCommand(entity_ids=["set", "second-set"], operation={"kind": "budget_change", "value": "10"}), "percent")
        with self.sessions() as session:
            self.assertEqual({row.entity_id: row.value for row in session.scalars(select(ActionRequest))}, {"set": Decimal("55"), "second-set": Decimal("110")})

    def test_limits_actor_and_bid_capability(self):
        with self.assertRaises(ActionRejected): self.batches.submit("default", "viewer", BulkCommand(entity_ids=["set"], operation={"kind": "pause"}), "v")
        with self.assertRaises(ValidationError): BulkCommand(entity_ids=["set", "set"], operation={"kind": "pause"})
        with self.assertRaises(ValidationError): BulkCommand(entity_ids=[str(i) for i in range(201)], operation={"kind": "pause"})
        self.assertTrue(supports("metricflow", "pause"))
        self.assertFalse(supports("metricflow", "bid_set"))
        self.assertFalse(supports("meta", "bid_set"))
        with self.assertRaises(ActionRejected): self.actions.enqueue("default", "operator", "set", "bid_set", Decimal("1"), "bid")


class RuleExecutionTests(AutomationFixture, unittest.IsolatedAsyncioTestCase):
    async def test_disabled_rule_cancels_queued_proposal_before_http(self):
        rule_id = self.rule("ACTIVE")
        self.rules.evaluate(rule_id, "default")
        self.rules.save("default", "operator", definition(), "OFF", rule_id, 1)
        writer = FakeWriter()
        await self.actions.execute_next(writer)
        self.assertEqual(writer.calls, [])
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(ActionRequest.status)), "rejected")

    async def test_changed_conditions_cancel_proposal_before_http(self):
        self.rules.evaluate(self.rule("ACTIVE"), "default")
        with self.sessions.begin() as session:
            session.get(DailyMetric, ("ad-0", DAY, "metricflow")).revenue = Decimal("0")
        writer = FakeWriter()
        await self.actions.execute_next(writer)
        self.assertEqual(writer.calls, [])
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(ActionRequest.status)), "rejected")

    async def test_stale_rule_metrics_cancel_even_when_current_state_is_fresh(self):
        self.rules.evaluate(self.rule("ACTIVE"), "default")
        self.now += timedelta(hours=1)
        with self.sessions.begin() as session:
            session.get(EntityCurrentState, "set").observed_at = self.now
        writer = FakeWriter()
        await self.actions.execute_next(writer)
        self.assertEqual(writer.calls, [])

    async def test_active_rule_executes_once_and_then_verifies_via_new_sync(self):
        self.rules.evaluate(self.rule("ACTIVE"), "default")
        writer = FakeWriter()
        await self.actions.execute_next(writer)
        await self.actions.execute_next(writer)
        self.assertEqual(writer.calls, [("budget", "900", {"test_budget": 12000})])
        self.now += timedelta(minutes=10)
        with self.sessions.begin() as session:
            state = session.get(EntityCurrentState, "set")
            state.budget, state.observed_at = Decimal("120"), self.now
        self.assertEqual(self.actions.verify_pending(), 1)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(ActionRequest.status)), "succeeded")
