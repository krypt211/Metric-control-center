from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import os
import unittest
from unittest.mock import patch

import httpx
from pydantic import ValidationError
from sqlalchemy import func, select

from services.actions.engine import ActionEngine, ActionPolicy, ActionRejected
from services.ai.engine import CopilotEngine
from services.ai.policy import read_policy, save_policy, reserve
from services.ai.provider import OpenAIProvider, ProviderFailure
from services.ai.schema import CopilotOutput, CopilotPolicy, Proposal
from services.ai.snapshot import build_snapshot
from services.storage.models import ActionRequest, AIAction, AIDecision, AIQuota, DailyMetric, EntityCurrentState, TelegramCursor, User
from services.telegram.bot import ApprovalBot, Binding, TelegramFailure
from test_recommendations import RecommendationFixture
from test_sync import DAY, NOW


def proposal(action="budget_change", **changes):
    return Proposal(entity_id="set", action=action, change_percent=15 if action == "budget_change" else None,
        confidence=87, reason="ROI выше цели; CPL ниже среднего", evidence=["today", "account_baseline"], priority=1, **changes)


class Provider:
    def __init__(self, proposals): self.proposals, self.calls = proposals, []
    async def analyze(self, snapshot):
        self.calls.append(snapshot)
        return CopilotOutput(summary="Предложения для проверки", proposals=self.proposals)


class Writer:
    def __init__(self): self.calls = []
    async def change_budget(self, identity, *, provider_payload): self.calls.append((identity, provider_payload))
    async def pause_entity(self, identity): self.calls.append((identity, "pause"))


class CopilotTests(RecommendationFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.now = NOW
        self.actions = ActionEngine(self.sessions, ActionPolicy(enabled=True, budget_contract={"verified": True,
            "field": "budget", "scale": "100", "encoding": "integer"}), clock=lambda: self.now)
        self.core = CopilotEngine(self.actions, clock=lambda: self.now)
        with self.sessions.begin() as session:
            session.add(self.metric("ad", DAY, spend=100, revenue=220, leads=20, conversions=13))
            session.add(EntityCurrentState(entity_id="set", status="ACTIVE", budget=Decimal(100), observed_at=NOW, raw={}))

    def configure(self, mode="APPROVAL", **changes):
        with self.sessions() as session: _, revision = read_policy(session, "default")
        return save_policy(self.sessions, "default", CopilotPolicy(mode=mode, daily_budget_verified=True, **changes), revision, self.now)

    async def analyzed(self, proposals=None, mode="APPROVAL", **settings):
        self.configure(mode, **settings)
        identity = self.core.queue("default", "operator", ["set"], "test")
        self.provider = Provider(proposals if proposals is not None else [proposal()])
        self.assertEqual(await self.core.process_next(self.provider), identity)
        with self.sessions() as session: return self.core.view(session, session.get(AIDecision, identity))

    async def test_copilot_never_creates_action_even_with_valid_proposal(self):
        view = await self.analyzed(mode="COPILOT")
        self.assertEqual(view["status"], "ready")
        self.assertEqual(view["actions"][0]["target_budget"], "115.00")
        with self.sessions() as session: self.assertEqual(session.scalar(select(func.count()).select_from(ActionRequest)), 0)
        with self.assertRaises(ActionRejected): self.core.resolve("default", "operator", view["id"], "approve")

    async def test_approval_is_idempotent_and_writes_once_through_existing_engine(self):
        view = await self.analyzed()
        first = self.core.resolve("default", "operator", view["id"], "approve")
        second = self.core.resolve("default", "operator", view["id"], "approve")
        self.assertEqual(first["actions"][0]["request_id"], second["actions"][0]["request_id"])
        writer = Writer()
        await self.actions.execute_next(writer); await self.actions.execute_next(writer)
        self.assertEqual(writer.calls, [("20", {"budget": 11500})])
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(AIQuota.queued)), 1)
            self.assertEqual(session.scalar(select(AIQuota.attempted)), 1)
            request = session.scalar(select(ActionRequest))
            self.assertEqual(request.provenance["source"], "ai")
            self.assertEqual(request.provenance["approval_channel"], "web")

    async def test_seventy_percent_is_denied_even_if_model_is_confident(self):
        view = await self.analyzed([proposal().model_copy(update={"change_percent": 70, "confidence": 100})])
        self.assertEqual(view["actions"][0]["status"], "denied")
        self.assertIn("20%", view["actions"][0]["policy_reason"])
        self.core.resolve("default", "operator", view["id"], "approve")
        with self.sessions() as session: self.assertEqual(session.scalar(select(func.count()).select_from(ActionRequest)), 0)

    async def test_daily_budget_interpretation_and_ceiling_are_enforced(self):
        self.configure()
        for settings in (CopilotPolicy(mode="APPROVAL"), CopilotPolicy(mode="APPROVAL", daily_budget_verified=True, max_daily_budget="110")):
            with self.sessions() as session:
                subject = build_snapshot(session, "default", ["set"], NOW)["entities"][0]
                from services.ai.policy import permitted
                with self.assertRaises(ActionRejected): permitted(proposal(), subject, settings)

    async def test_reject_then_approve_does_not_enqueue(self):
        view = await self.analyzed()
        self.assertEqual(self.core.resolve("default", "operator", view["id"], "reject")["status"], "rejected")
        self.assertEqual(self.core.resolve("default", "operator", view["id"], "approve")["status"], "rejected")
        with self.sessions() as session: self.assertEqual(session.scalar(select(func.count()).select_from(ActionRequest)), 0)

    async def test_changed_state_denies_at_approval(self):
        view = await self.analyzed()
        with self.sessions.begin() as session: session.get(EntityCurrentState, "set").budget = Decimal(120)
        result = self.core.resolve("default", "operator", view["id"], "approve")
        self.assertEqual(result["actions"][0]["status"], "denied")
        with self.sessions() as session: self.assertEqual(session.scalar(select(func.count()).select_from(ActionRequest)), 0)

    async def test_changed_metrics_after_approval_prevent_the_post(self):
        view = await self.analyzed()
        self.core.resolve("default", "operator", view["id"], "approve")
        with self.sessions.begin() as session:
            session.get(DailyMetric, ("ad", DAY, "metricflow")).revenue = Decimal(50)
        writer = Writer(); await self.actions.execute_next(writer)
        self.assertEqual(writer.calls, [])
        with self.sessions() as session: self.assertEqual(session.scalar(select(ActionRequest.status)), "rejected")

    async def test_expiry_and_policy_change_cancel_execution(self):
        view = await self.analyzed()
        self.core.resolve("default", "operator", view["id"], "approve")
        self.now = NOW+timedelta(minutes=16)
        writer = Writer(); await self.actions.execute_next(writer)
        self.assertEqual(writer.calls, [])

    async def test_mode_change_revokes_unsent_approved_actions(self):
        view = await self.analyzed()
        self.core.resolve("default", "operator", view["id"], "approve")
        self.configure("OFF")
        writer = Writer(); await self.actions.execute_next(writer)
        self.assertEqual(writer.calls, [])

    async def test_unknown_metrics_and_stale_today_cannot_act(self):
        with self.sessions.begin() as session:
            session.get(DailyMetric, ("ad", DAY, "metricflow")).leads = None
        view = await self.analyzed()
        self.assertEqual(view["actions"][0]["status"], "denied")

    async def test_unknown_entities_or_evidence_fail_the_whole_model_output(self):
        view = await self.analyzed([proposal().model_copy(update={"evidence": ["invented"]})])
        self.assertEqual(view["status"], "failed")
        self.assertEqual(view["actions"], [])

    async def test_analysis_is_idempotent_and_names_never_enter_model_context(self):
        view = await self.analyzed()
        self.assertEqual(self.core.queue("default", "operator", ["set"], "test"), view["id"])
        self.assertIsNone(await self.core.process_next(self.provider))
        serialized = json.dumps(self.provider.calls[0])
        self.assertNotIn('"name"', serialized)
        self.assertNotIn('"raw"', serialized)
        self.assertEqual(self.provider.calls[0]["entities"][0]["windows"]["today"]["metrics"]["conversions"], 13)

    async def test_global_actions_off_preserves_pending_proposal(self):
        view = await self.analyzed()
        off = CopilotEngine(ActionEngine(self.sessions, ActionPolicy(), clock=lambda: NOW), clock=lambda: NOW)
        with self.assertRaises(ActionRejected): off.resolve("default", "operator", view["id"], "approve")
        with self.sessions() as session: self.assertEqual(session.get(AIDecision, view["id"]).status, "pending")

    async def test_autopilot_requires_deployment_gate_and_obeys_policy(self):
        with patch.dict(os.environ, {"AI_AUTOPILOT_ALLOWED": "false"}):
            with self.assertRaises(ActionRejected): self.configure("AUTOPILOT")
        with patch.dict(os.environ, {"AI_AUTOPILOT_ALLOWED": "true"}):
            view = await self.analyzed(mode="AUTOPILOT")
            self.assertEqual(view["status"], "approved")
            self.assertEqual(view["actions"][0]["status"], "queued")
        with patch.dict(os.environ, {"AI_AUTOPILOT_ALLOWED": "false"}):
            writer = Writer(); await self.actions.execute_next(writer)
            self.assertEqual(writer.calls, [])

    async def test_daily_queue_and_execution_limits_and_rollback_on_denied(self):
        view = await self.analyzed(max_actions_per_day=1)
        self.core.resolve("default", "operator", view["id"], "approve")
        with self.assertRaises(ActionRejected):
            with self.sessions.begin() as session: reserve(session, "default", NOW, "queued", 1)
        # Executions are limited again on the day actually sent, across midnight.
        with self.sessions.begin() as session: reserve(session, "default", NOW, "attempted", 1)
        writer = Writer(); await self.actions.execute_next(writer)
        self.assertEqual(writer.calls, [])
        with self.sessions() as session: self.assertEqual(session.scalar(select(AIQuota.attempted)), 1)

    async def test_foreign_workspace_and_viewer_cannot_approve(self):
        view = await self.analyzed()
        with self.sessions.begin() as session:
            session.add(User(id="viewer", workspace_id="default", role="viewer", email="viewer@example.invalid"))
            session.add(User(id="foreign", workspace_id="other", role="operator", email="foreign@example.invalid"))
        for workspace, actor in (("default", "viewer"), ("other", "foreign")):
            with self.assertRaises(ActionRejected): self.core.resolve(workspace, actor, view["id"], "approve")

    async def test_trends_use_closed_comparable_days_and_missing_days_are_unknown(self):
        with self.sessions() as session:
            s = build_snapshot(session, "default", ["set"], NOW)["entities"][0]
        self.assertEqual(s["trends"]["1d"]["window"], [(DAY-timedelta(days=1)).isoformat()]*2)
        self.assertFalse(s["windows"]["last7"]["complete"])
        self.assertIsNone(s["windows"]["last7"]["metrics"]["spend"])
        self.assertIsNone(s["trends"]["7d"]["change_percent"]["cpl"])

    async def test_concurrent_approvals_create_one_queue_entry_and_quota_reservation(self):
        view = await self.analyzed()
        def approve():
            try: return self.core.resolve("default", "operator", view["id"], "approve")["status"]
            except ActionRejected: return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: approve(), range(2)))
        self.assertIn("approved", results)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ActionRequest)), 1)
            self.assertEqual(session.scalar(select(AIQuota.queued)), 1)

    async def test_missing_durable_approval_blocks_worker_even_when_metrics_match(self):
        view = await self.analyzed()
        self.core.resolve("default", "operator", view["id"], "approve")
        with self.sessions.begin() as session: session.get(AIDecision, view["id"]).status = "rejected"
        writer = Writer(); await self.actions.execute_next(writer)
        self.assertEqual(writer.calls, [])

    async def test_stale_observations_require_leave_unchanged(self):
        with self.sessions.begin() as session:
            session.get(DailyMetric, ("ad", DAY, "metricflow")).observed_at = NOW-timedelta(hours=1)
        view = await self.analyzed()
        self.assertEqual(view["actions"][0]["status"], "denied")

    async def test_telegram_uncertain_delivery_is_not_sent_again(self):
        await self.analyzed()
        class API:
            bot_id = "123"
            calls = 0
            async def call(self, method, payload):
                self.calls += 1
                raise TelegramFailure("network")
        api = API()
        bot = ApprovalBot(self.core, api, "default", [{"telegram_user_id": 10, "chat_id": 10, "user_id": "operator"}])
        await bot.notify_next(); await bot.notify_next()
        self.assertEqual(api.calls, 1)

    async def test_telegram_expired_acknowledgement_does_not_block_inbox(self):
        class API:
            bot_id = "123"
            async def call(self, method, payload):
                if method == "getUpdates":
                    return [{"update_id": 5, "callback_query": {"id": "old", "from": {"id": 99},
                        "message": {"chat": {"id": 99, "type": "private"}}, "data": "invalid"}}]
                raise TelegramFailure("Callback expired")
        bot = ApprovalBot(self.core, API(), "default", [])
        await bot.poll_once()
        with self.sessions() as session: self.assertEqual(session.get(TelegramCursor, bot.scope).next_update, 6)

    async def test_telegram_checks_sender_message_and_replays_without_duplicate_action(self):
        view = await self.analyzed()
        class API:
            bot_id = "123"
            async def call(self, method, payload): return {"message_id": 50}
        bot = ApprovalBot(self.core, API(), "default", [{"telegram_user_id": 10, "chat_id": 10, "user_id": "operator"}])
        await bot.notify_next()
        with self.sessions() as session: token = session.get(AIDecision, view["id"]).payload["callback_token"]
        update = {"update_id": 1, "callback_query": {"id": "callback1", "from": {"id": 10}, "message": {"message_id": 50,
            "chat": {"id": 10, "type": "private"}}, "data": "approve:"+token}}
        forbidden = json.loads(json.dumps(update)); forbidden["callback_query"]["from"]["id"] = 20
        with self.assertRaises(ActionRejected): bot.handle(forbidden)
        forged = json.loads(json.dumps(update)); forged["callback_query"]["message"]["message_id"] = 60
        with self.assertRaises(ActionRejected): bot.handle(forged)
        first = bot.handle(update); self.assertEqual(bot.handle(update), first)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ActionRequest)), 1)
            self.assertEqual(session.scalar(select(ActionRequest.provenance))["approval_channel"], "telegram")
        self.assertNotIn("callback_token", json.dumps(view))


class OutputContractTests(unittest.TestCase):
    def test_forbidden_operations_source_spoofing_and_nonfinite_values_are_rejected(self):
        base = proposal().model_dump()
        for changes in ({"action": "delete"}, {"source": "web"}, {"change_percent": float("nan")}, {"confidence": 101}):
            with self.assertRaises(ValidationError): Proposal.model_validate({**base, **changes})
        with self.assertRaises(ValidationError): Binding(telegram_user_id=10, chat_id=20, user_id="operator")


class OpenAIContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_responses_request_is_strict_stateless_and_has_no_tools(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": CopilotOutput(summary="Оставить", proposals=[proposal("leave_unchanged")]).model_dump_json()}]}]})
        provider = OpenAIProvider("test-key", "explicit-model", transport=httpx.MockTransport(handler))
        result = await provider.analyze({"entities": []})
        self.assertEqual(result.proposals[0].action, "leave_unchanged")
        payload = json.loads(requests[0].content)
        self.assertFalse(payload["store"])
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertNotIn("tools", payload)
        self.assertEqual(str(requests[0].url), "https://api.openai.com/v1/responses")

    async def test_rate_limit_refusal_incomplete_response_are_not_retried(self):
        for response in (httpx.Response(429, json={"error": "secret"}), httpx.Response(200, json={"status": "incomplete"}),
            httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]})):
            calls = []
            def handler(request): calls.append(request); return response
            with self.assertRaises(ProviderFailure): await OpenAIProvider("test-key", "explicit-model", transport=httpx.MockTransport(handler)).analyze({})
            self.assertEqual(len(calls), 1)
