from datetime import timedelta
from decimal import Decimal
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx
from sqlalchemy import delete, func, select

from services.actions.engine import ActionEngine, ActionPolicy, ActionRejected
from services.ai.agent import AgentService
from services.ai.agent_tools import AgentTools, definitions, validate_scope
from services.ai.engine import CopilotEngine
from services.ai.policy import permitted, read_policy, save_policy
from services.ai.profiles import MediaProfile, save, snapshot_profiles, reserve_scaling
from services.ai.provider import OpenAIProvider, ProviderFailure
from services.ai.schema import CopilotPolicy, Proposal
from services.ai.snapshot import build_snapshot
from services.automation.control import change, guard, state
from services.storage.models import ActionRequest, Ad, AgentMessage, AIAction, AIDecision, AutomationEvent, Breakdown, Entity, EntityCurrentState
from services.telegram.bot import ApprovalBot, review_text
from test_recommendations import RecommendationFixture
from test_sync import DAY, NOW


QUERY = dict(country="IT", offer="Adenofrin", account_id=None, entity_id=None, currency="USD", window="today", level="ad")
COMMAND = dict(query=QUERY, conditions=[dict(metric="spend", operator=">", value="30"), dict(metric="sales", operator="=", value="0")],
    reason="Spend over threshold with no sales", confidence=87)


class Writer:
    def __init__(self): self.calls = []
    async def pause_entity(self, identity): self.calls.append(identity)
    async def enable_entity(self, identity): self.calls.append(identity)


class AgentFixture(RecommendationFixture):
    def setUp(self):
        super().setUp()
        self.now = NOW
        self.actions = ActionEngine(self.sessions, ActionPolicy(enabled=True, budget_contract={"verified": True,
            "field": "budget", "scale": "100", "encoding": "integer"}), clock=lambda: self.now)
        self.core = CopilotEngine(self.actions, clock=lambda: self.now)
        self.agent = AgentService(self.core)
        with self.sessions.begin() as session:
            session.add(self.metric("ad", DAY))
            session.get(Entity, "ad").labels = {"offer": "Adenofrin"}
            for identity in ("set", "ad"):
                session.add(EntityCurrentState(entity_id=identity, status="ACTIVE", budget=Decimal(100), observed_at=NOW, raw={}))
            session.add(Breakdown(entity_id="ad", day=DAY, source="metricflow", dimension_key="IT", dimensions={"country": "IT"},
                metrics=dict(currency="USD", timezone="Europe/Moscow", spend="31", revenue="0", leads=0, sales=0, conversions=0,
                    clicks=10, impressions=100), observed_at=NOW))

    def configure(self, mode="APPROVAL", **changes):
        with self.sessions() as session: _, revision = read_policy(session, "default")
        policy = CopilotPolicy(mode=mode, daily_budget_verified=True, **changes)
        save_policy(self.sessions, "default", policy, revision, self.now)
        return policy

    def tools(self, mode="APPROVAL"):
        return AgentTools(self.sessions, "default", "operator", CopilotPolicy(mode=mode), self.now)

    def count(self, model):
        with self.sessions() as session: return session.scalar(select(func.count()).select_from(model))

    async def proposed(self, mode="APPROVAL"):
        self.configure(mode)
        identity = self.agent.queue("default", "operator", "Pause Italy spend over 30 without sales", "message1")
        class Provider:
            async def converse(self, question, tools, history):
                tools.call("get_metrics", QUERY)
                tools.call("propose_pause", COMMAND)
                return "Review the filter before confirming."
        await self.agent.process_next(Provider())
        with self.sessions() as session: return self.agent.view(session, session.get(AgentMessage, identity))


class AgentTests(AgentFixture, unittest.IsolatedAsyncioTestCase):
    def test_levels_legacy_and_read_only_tool_gate(self):
        for level, mode in enumerate(("READ_ONLY", "RECOMMEND", "APPROVAL", "AUTOPILOT")):
            self.assertEqual(CopilotPolicy(mode=mode).autonomy_level, level)
        self.assertEqual(CopilotPolicy(mode="COPILOT").mode, "RECOMMEND")
        self.assertFalse(any(d["name"].startswith("propose_") for d in definitions("READ_ONLY")))
        with self.assertRaises(ActionRejected): self.tools("READ_ONLY").call("propose_pause", COMMAND)

    def test_geo_scope_uses_breakdown_not_overall_sales_and_never_queues(self):
        tools = self.tools()
        result = tools.call("propose_pause", COMMAND)
        self.assertEqual(result["count"], 1)
        self.assertEqual(Decimal(result["totals"][0]["spend"]), Decimal(31))
        self.assertEqual(result["entities"][0]["sales"], 0)
        self.assertEqual(self.count(ActionRequest), 0)
        self.assertEqual(tools.call("propose_pause", {**COMMAND, "query": {**QUERY, "country": None}})["count"], 0)

    def test_unknown_sales_or_missing_breakdown_does_not_match(self):
        with self.sessions.begin() as session:
            row = session.get(Breakdown, ("ad", DAY, "metricflow", "IT")); row.metrics = {**row.metrics, "sales": None}
        self.assertEqual(self.tools().call("propose_pause", COMMAND)["count"], 0)
        with self.sessions.begin() as session:
            session.execute(delete(Breakdown)); session.get(Entity, "ad").labels = {"offer": "Adenofrin", "country": "IT"}
        self.assertEqual(self.tools().call("get_metrics", QUERY)["total"], 0)

    def test_strict_threshold_and_unknown_geo_tracker(self):
        with self.sessions.begin() as session:
            row = session.get(Breakdown, ("ad", DAY, "metricflow", "IT")); row.metrics = {**row.metrics, "spend": "30"}
        self.assertEqual(self.tools().call("propose_pause", COMMAND)["count"], 0)
        self.assertEqual(self.tools().call("get_tracker_metrics", QUERY)["status"], "unavailable")

    def test_over_thirty_matches_requires_narrowing_without_partial_plan(self):
        with self.sessions.begin() as session:
            for n in range(31):
                identity = "extra"+str(n)
                session.add(Entity(id=identity, account_id="account", kind="ad", external_id="extra"+str(n)))
                session.flush(); session.add(Ad(entity_id=identity, adset_id="set"))
                session.add(self.metric(identity, DAY))
        tools = self.tools()
        result = tools.call("propose_pause", {**COMMAND, "query": {**QUERY, "country": None, "offer": None}, "conditions": []})
        self.assertEqual(result["status"], "DENIED"); self.assertEqual(tools.staged, {})

    def test_frozen_country_scope_and_unsupported_bid(self):
        tools = self.tools(); tools.call("propose_pause", COMMAND)
        with self.sessions.begin() as session:
            row = session.get(Breakdown, ("ad", DAY, "metricflow", "IT")); row.metrics = {**row.metrics, "spend": "32"}
        with self.sessions() as session:
            with self.assertRaises(ActionRejected): validate_scope(session, "default", tools.staged["ad"]["scope"], "ad", NOW)
        self.assertEqual(tools.call("propose_bid_change", {**COMMAND, "change_percent": 15})["status"], "DENIED")

    async def test_chat_idempotency_and_confirmation_creates_exactly_one_request(self):
        view = await self.proposed()
        decision = view["decision"]
        self.assertEqual(self.agent.queue("default", "operator", view["text"], "message1"), view["id"])
        self.assertTrue(decision["requires_confirmation"])
        self.assertEqual(self.count(ActionRequest), 0)
        result = self.core.resolve("default", "operator", decision["id"], "approve")
        self.assertEqual(result["actions"][0]["status"], "queued")
        self.core.resolve("default", "operator", decision["id"], "approve")
        writer = Writer(); await self.actions.execute_next(writer)
        self.assertEqual(writer.calls, ["1"])
        self.assertEqual(self.count(ActionRequest), 1)
        text = review_text(decision, reasons=False, truncate=False)
        self.assertIn("IT", text); self.assertIn("31", text); self.assertIn("sales = 0", text)

    async def test_chat_requires_manual_confirmation_even_in_autopilot(self):
        with patch.dict(os.environ, {"AI_AUTOPILOT_ALLOWED": "true"}):
            view = await self.proposed("AUTOPILOT")
            self.assertEqual(view["decision"]["status"], "pending")
            with self.assertRaises(ActionRejected): self.core.resolve("default", "operator", view["decision"]["id"], "approve", automatic=True)
        self.assertEqual(self.count(ActionRequest), 0)

    async def test_geo_changed_after_confirmation_prevents_http(self):
        view = await self.proposed()
        self.core.resolve("default", "operator", view["decision"]["id"], "approve")
        with self.sessions.begin() as session:
            row = session.get(Breakdown, ("ad", DAY, "metricflow", "IT")); row.metrics = {**row.metrics, "sales": 1}
        writer = Writer(); await self.actions.execute_next(writer)
        self.assertEqual(writer.calls, [])
        with self.sessions() as session: self.assertEqual(session.scalar(select(ActionRequest.status)), "rejected")

    async def test_read_only_drops_model_proposals_without_publishing_actions(self):
        self.configure("READ_ONLY")
        identity = self.core.queue("default", "operator", ["set"], "readonly")
        from services.ai.schema import CopilotOutput
        class Provider:
            async def analyze(self, snapshot):
                return CopilotOutput(summary="Analysis", proposals=[Proposal(entity_id="set", action="pause", change_percent=None,
                    confidence=87, reason="test", evidence=["today"], priority=1)])
        await self.core.process_next(Provider())
        with self.sessions() as session: self.assertEqual(self.core.view(session, session.get(AIDecision, identity))["actions"], [])
        self.assertEqual(self.count(AIAction), 0)

    async def test_failed_chat_is_not_retried_and_error_does_not_leak_secret(self):
        self.configure()
        identity = self.agent.queue("default", "operator", "question", "failed")
        class Provider:
            async def converse(self, *args): raise RuntimeError("secret")
        await self.agent.process_next(Provider())
        self.assertIsNone(await self.agent.process_next(Provider()))
        with self.sessions() as session:
            row = session.get(AgentMessage, identity)
            self.assertEqual(row.status, "failed"); self.assertNotIn("secret", json.dumps(row.payload))

    def test_enable_denied_unless_explicit_policy_allows_it(self):
        with self.sessions() as session: subject = build_snapshot(session, "default", ["ad"], NOW)["entities"][0]
        p = Proposal(entity_id="ad", action="enable", change_percent=None, confidence=87, reason="test", evidence=["today"], priority=1)
        with self.assertRaises(ActionRejected): permitted(p, subject, CopilotPolicy(mode="APPROVAL"))
        self.assertEqual(permitted(p, subject, CopilotPolicy(mode="APPROVAL", allow_enable=True)), ("enable", None))


class StopTests(AgentFixture, unittest.IsolatedAsyncioTestCase):
    def test_stop_cancels_automation_but_preserves_manual_and_generation(self):
        auto = self.actions.enqueue("default", "operator", "set", "pause", None, "auto", context={"source": "rule"})
        manual = self.actions.enqueue("default", "operator", "ad", "pause", None, "manual")
        stopped = change(self.sessions, "default", "operator", True, clock=lambda: NOW)
        self.assertEqual(stopped, {"stopped": True, "generation": 1})
        self.assertEqual(change(self.sessions, "default", "operator", True, clock=lambda: NOW), stopped)
        with self.sessions() as session:
            self.assertEqual(session.get(ActionRequest, auto).status, "rejected")
            self.assertEqual(session.get(ActionRequest, manual).status, "queued")
        with self.assertRaises(ActionRejected): change(self.sessions, "default", "operator", False, generation=0, clock=lambda: NOW)
        resumed = change(self.sessions, "default", "operator", False, generation=1, clock=lambda: NOW)
        self.assertEqual(resumed["generation"], 2)
        with self.sessions.begin() as session:
            with self.assertRaises(ActionRejected): guard(session, "default", NOW, 0)
        self.assertEqual(self.count(AutomationEvent), 2)

    async def test_stop_between_claim_and_http_prevents_remote_call(self):
        view = await self.proposed()
        self.core.resolve("default", "operator", view["decision"]["id"], "approve")
        reserve = self.actions.reserve_api_request
        def hook(workspace):
            reserve(workspace)
            change(self.sessions, "default", "operator", True, clock=lambda: NOW)
        self.actions.reserve_api_request = hook
        writer = Writer(); await self.actions.execute_next(writer)
        self.assertEqual(writer.calls, [])
        with self.sessions() as session: self.assertEqual(session.scalar(select(ActionRequest.status)), "rejected")

    async def test_stop_resume_does_not_restore_old_proposals(self):
        view = await self.proposed()
        change(self.sessions, "default", "operator", True, clock=lambda: NOW)
        change(self.sessions, "default", "operator", False, generation=1, clock=lambda: NOW)
        with self.assertRaises(ActionRejected): self.core.resolve("default", "operator", view["decision"]["id"], "approve")
        self.assertEqual(self.count(ActionRequest), 0)

    def test_telegram_stop_works_with_ai_disabled_auth_and_dedup(self):
        class API: bot_id = "123"
        bot = ApprovalBot(self.core, API(), "default", [{"telegram_user_id": 10, "chat_id": 10, "user_id": "operator"}])
        update = {"update_id": 1, "message": {"from": {"id": 10}, "chat": {"id": 10, "type": "private"}, "text": "/stop_auto"}}
        with patch.dict(os.environ, {"AI_ENABLED": "false"}):
            first = bot.handle_message(update); self.assertEqual(bot.handle_message(update), first)
        self.assertEqual(self.count(AutomationEvent), 1)
        forged = json.loads(json.dumps(update)); forged["message"]["from"]["id"] = 20
        with self.assertRaises(ActionRejected): bot.handle_message(forged)
        with self.sessions() as session: self.assertTrue(state(session, "default")["stopped"])

    def test_concurrent_stop_and_queue_leave_no_automatic_request_queued(self):
        def queue():
            try: return self.actions.enqueue("default", "operator", "ad", "pause", None, "race", context={"source": "rule"})
            except ActionRejected: return "denied"
        with ThreadPoolExecutor(max_workers=2) as pool:
            queued = pool.submit(queue)
            stopped = pool.submit(change, self.sessions, "default", "operator", True, clock=lambda: NOW)
            queued.result(); self.assertTrue(stopped.result()["stopped"])
        with self.sessions() as session: self.assertEqual(session.scalar(select(func.count()).select_from(ActionRequest).where(ActionRequest.status == "queued")), 0)

    def test_telegram_chat_is_authenticated_durable_and_deduplicated(self):
        self.configure()
        class API: bot_id = "123"
        bot = ApprovalBot(self.core, API(), "default", [{"telegram_user_id": 10, "chat_id": 10, "user_id": "operator"}])
        update = {"update_id": 2, "message": {"from": {"id": 10}, "chat": {"id": 10, "type": "private"}, "text": "Italy stats today"}}
        with patch.dict(os.environ, {"AI_ENABLED": "true"}):
            first = bot.handle_message(update); self.assertEqual(bot.handle_message(update), first)
        self.assertEqual(self.count(AgentMessage), 1)
        with self.sessions() as session: self.assertEqual(session.scalar(select(AgentMessage.payload))["channel"], "telegram")


class ProfileTests(AgentFixture, unittest.TestCase):
    def winning_profile(self):
        config = MediaProfile(country="IT", offer="Adenofrin")
        identity = save(self.sessions, "default", config, 0, NOW)
        with self.sessions.begin() as session:
            row = session.get(Breakdown, ("ad", DAY, "metricflow", "IT"))
            row.metrics = {**row.metrics, "spend": "100", "revenue": "220", "leads": 20, "sales": 13, "conversions": 13}
        return config, identity

    def test_persisted_defaults_revision_and_python_profile_metrics(self):
        config, identity = self.winning_profile()
        with self.assertRaises(ActionRejected): save(self.sessions, "default", config, 0, NOW)
        with self.sessions() as session:
            p = snapshot_profiles(session, "default", session.get(Entity, "set"), NOW)[0]
        self.assertEqual(p["id"], identity); self.assertTrue(p["scale_candidate"])
        self.assertEqual(Decimal(p["metrics"]["cpl"]), Decimal(5))
        self.assertEqual(config.scaling_cooldown_seconds, 28800)
        save(self.sessions, "default", config.model_copy(update={"enabled": False}), 1, NOW)
        with self.sessions() as session: self.assertEqual(snapshot_profiles(session, "default", session.get(Entity, "set"), NOW), [])

    def test_profile_caps_step_and_cooldown_are_enforced(self):
        self.winning_profile()
        with self.sessions() as session: subject = build_snapshot(session, "default", ["set"], NOW)["entities"][0]
        def proposal(change): return Proposal(entity_id="set", action="budget_change", change_percent=change, confidence=87,
            reason="test", evidence=["today"], priority=1)
        policy = CopilotPolicy(mode="APPROVAL", daily_budget_verified=True)
        self.assertEqual(permitted(proposal(15), subject, policy)[1], Decimal("115.00"))
        with self.assertRaises(ActionRejected): permitted(proposal(20), subject, policy)
        expensive = {**subject, "state": {**subject["state"], "budget": "240"}}
        with self.assertRaises(ActionRejected): permitted(proposal(15), expensive, policy)
        with self.sessions.begin() as session: reserve_scaling(session, "default", session.get(Entity, "set"), "budget_set", Decimal(115), Decimal(100), NOW)
        with self.sessions.begin() as session:
            with self.assertRaises(ActionRejected): reserve_scaling(session, "default", session.get(Entity, "set"), "budget_set", Decimal(115), Decimal(100), NOW+timedelta(hours=7))
        with self.sessions.begin() as session: reserve_scaling(session, "default", session.get(Entity, "set"), "budget_set", Decimal(115), Decimal(100), NOW+timedelta(hours=8))

    def test_profile_stop_requires_explicit_zero_and_unknown_never_scales(self):
        save(self.sessions, "default", MediaProfile(country="IT", offer="Adenofrin"), 0, NOW)
        with self.sessions() as session:
            self.assertTrue(snapshot_profiles(session, "default", session.get(Entity, "set"), NOW)[0]["stop_candidate"])
        with self.sessions.begin() as session:
            row = session.get(Breakdown, ("ad", DAY, "metricflow", "IT")); row.metrics = {**row.metrics, "leads": None}
        with self.sessions() as session:
            p = snapshot_profiles(session, "default", session.get(Entity, "set"), NOW)[0]
            self.assertFalse(p["stop_candidate"]); self.assertFalse(p["scale_candidate"])


class FunctionCallingTests(unittest.IsolatedAsyncioTestCase):
    def test_tool_schemas_require_every_property_and_forbid_extras(self):
        def check(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertFalse(node["additionalProperties"])
                    self.assertEqual(set(node.get("required", [])), set(node.get("properties", {})))
                for value in node.values(): check(value)
            elif isinstance(node, list):
                for value in node: check(value)
        for tool in definitions("APPROVAL"): check(tool["parameters"])

    async def test_stateless_tool_result_and_reasoning_are_replayed_with_call_id(self):
        payloads = []
        def handler(request):
            payloads.append(json.loads(request.content))
            if len(payloads) == 1:
                return httpx.Response(200, json={"status": "completed", "output": [
                    {"type": "reasoning", "id": "r", "summary": [], "encrypted_content": "opaque"},
                    {"type": "function_call", "call_id": "call1", "name": "get_accounts", "arguments": "{}"}]})
            return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": '{"answer":"No accounts yet"}'}]}]})
        class Tools:
            policy = CopilotPolicy(mode="READ_ONLY")
            def call(self, name, arguments): return {"accounts": []}
        answer = await OpenAIProvider("test-key", "explicit-model", transport=httpx.MockTransport(handler)).converse("stats", Tools(), [])
        self.assertEqual(answer, "No accounts yet")
        self.assertFalse(payloads[0]["store"])
        self.assertFalse(any(t["name"].startswith("propose_") for t in payloads[0]["tools"]))
        self.assertIn({"type": "reasoning", "id": "r", "summary": [], "encrypted_content": "opaque"}, payloads[1]["input"])
        result = next(i for i in payloads[1]["input"] if i.get("type") == "function_call_output")
        self.assertEqual(result["call_id"], "call1"); self.assertEqual(json.loads(result["output"]), {"accounts": []})

    async def test_http_failure_is_not_retried(self):
        calls = []
        def handler(request): calls.append(request); return httpx.Response(429)
        class Tools: policy = CopilotPolicy(mode="READ_ONLY")
        with self.assertRaises(ProviderFailure):
            await OpenAIProvider("test-key", "explicit-model", transport=httpx.MockTransport(handler)).converse("stats", Tools(), [])
        self.assertEqual(len(calls), 1)


class AgentApiTests(AgentFixture, unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_stop_resume_profile_revision_and_message_gate(self):
        from backend.app import app
        token = Path(self.directory.name)/"token"; token.write_text("test-token", encoding="utf-8")
        env = {"WORKSPACE_ID": "default", "ACTION_OPERATOR_ID": "operator", "ACTION_API_TOKEN_FILE": str(token), "AI_ENABLED": "false"}
        with patch.dict(os.environ, env), patch("backend.app.database_sessions", return_value=self.sessions):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                self.assertEqual((await client.post("/api/ai/automation", json={"stopped": True})).status_code, 401)
                client.headers["Authorization"] = "Bearer test-token"
                self.assertEqual((await client.post("/api/ai/automation", json={"stopped": True})).json()["generation"], 1)
                self.assertEqual((await client.post("/api/ai/automation", json={"stopped": False, "generation": 0})).status_code, 409)
                self.assertEqual((await client.post("/api/ai/automation", json={"stopped": False, "generation": 1})).json()["generation"], 2)
                profile = {"profile": MediaProfile(country="IT", offer="Adenofrin").model_dump(mode="json"), "revision": 0}
                self.assertEqual((await client.put("/api/ai/profiles", json=profile)).json()["profiles"][0]["revision"], 1)
                self.assertEqual((await client.put("/api/ai/profiles", json=profile)).status_code, 409)
                self.assertEqual((await client.post("/api/ai/messages", json={"text": "stats"}, headers={"Idempotency-Key": "chat"})).status_code, 409)
                self.assertEqual((await client.put("/api/ai/profiles", json={**profile, "actor_id": "forged"})).status_code, 422)
                with patch.dict(os.environ, {"WORKSPACE_ID": "other"}):
                    self.assertEqual((await client.get("/api/ai/profiles")).status_code, 403)
        self.assertEqual(self.count(AgentMessage), 0)
