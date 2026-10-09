"""Durable chat agent. Tools stage intent; every chat action requires confirmation."""
from datetime import timedelta
import hashlib
import json
import secrets
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from services.actions.engine import ActionRejected
from services.automation.control import state
from services.storage.models import AgentMessage, AIDecision, AIAction
from services.sync.engine import aware
from .agent_tools import AgentTools
from .engine import authorize
from .policy import permitted, read_policy, reserve
from .schema import Proposal
from .snapshot import build_snapshot


class AgentService:
    def __init__(self, core):
        self.core, self.sessions, self.clock = core, core.sessions, core.clock

    def queue(self, workspace, actor, text, key, *, conversation="web", channel="web", chat_id=None):
        text = text.strip()
        if not 1 <= len(text) <= 4000 or not 1 <= len(key) <= 128:
            raise ActionRejected("Message or idempotency key is invalid")
        conversation_id = hashlib.sha256(json.dumps([workspace, actor, conversation]).encode()).hexdigest()
        identity = str(uuid5(NAMESPACE_URL, json.dumps(["agent", workspace, actor, key])))
        now = self.clock()
        try:
            with self.sessions.begin() as session:
                authorize(session, workspace, actor)
                existing = session.get(AgentMessage, identity)
                if existing:
                    if existing.text != text or existing.conversation_id != conversation_id:
                        raise ActionRejected("Message key was used for another request")
                    return identity
                policy, revision = read_policy(session, workspace)
                if policy.mode == "OFF":
                    raise ActionRejected("AI is off; select an autonomy level first")
                reserve(session, workspace, now, "analyses", policy.max_analyses_per_day)
                session.add(AgentMessage(id=identity, workspace_id=workspace, actor_id=actor,
                    conversation_id=conversation_id, status="queued", created_at=now,
                    expires_at=now+timedelta(minutes=policy.proposal_ttl_minutes), text=text, payload={
                        "policy_revision": revision, "mode": policy.mode, "channel": channel, "chat_id": chat_id,
                        "automation_generation": state(session, workspace)["generation"]}))
        except IntegrityError:
            with self.sessions() as session:
                existing = session.get(AgentMessage, identity)
                if existing and existing.text == text and existing.conversation_id == conversation_id:
                    return identity
            raise ActionRejected("Message was changed concurrently") from None
        return identity

    async def process_next(self, provider):
        now = self.clock()
        with self.sessions.begin() as session:
            session.execute(update(AgentMessage).where(AgentMessage.status.in_(("queued", "generating")),
                AgentMessage.expires_at <= now).values(status="expired"))
            message = session.scalar(select(AgentMessage).where(AgentMessage.status == "queued").order_by(
                AgentMessage.created_at).with_for_update(skip_locked=True).limit(1))
            if not message:
                return None
            identity, workspace, actor, text, payload = message.id, message.workspace_id, message.actor_id, message.text, message.payload
            policy, revision = read_policy(session, workspace)
            try: authorize(session, workspace, actor)
            except ActionRejected:
                message.status = "cancelled"
                return identity
            if policy.mode == "OFF" or revision != payload["policy_revision"]:
                message.status = "cancelled"
                return identity
            claimed = session.execute(update(AgentMessage).where(AgentMessage.id == identity,
                AgentMessage.status == "queued").values(status="generating"))
            if claimed.rowcount != 1:
                return None
            history = session.scalars(select(AgentMessage).where(AgentMessage.workspace_id == workspace,
                AgentMessage.actor_id == actor, AgentMessage.conversation_id == message.conversation_id,
                AgentMessage.status == "completed", AgentMessage.created_at < message.created_at).order_by(
                    AgentMessage.created_at.desc()).limit(6)).all()
            history = [{"question": r.text, "answer": r.payload.get("answer", "")} for r in reversed(history)]
        tools = AgentTools(self.sessions, workspace, actor, policy, now)
        try:
            answer = await provider.converse(text, tools, history)
            if not isinstance(answer, str) or not 1 <= len(answer) <= 4000:
                raise ValueError("Invalid agent answer")
        except Exception as error:
            with self.sessions.begin() as session:
                current = session.get(AgentMessage, identity)
                if current.status == "generating":
                    current.status = "failed"
                    current.payload = {**current.payload, "error_code": type(error).__name__}
            return identity
        with self.sessions.begin() as session:
            current = session.get(AgentMessage, identity)
            if current.status != "generating":
                return identity
            policy, revision = read_policy(session, workspace)
            if revision != payload["policy_revision"] or aware(current.expires_at) <= self.clock():
                current.status = "cancelled" if revision != payload["policy_revision"] else "expired"
                return identity
            current.payload = {**current.payload, "answer": answer, "trace": tools.trace}
            staged = tools.staged if policy.mode != "READ_ONLY" else {}
            if staged:
                try:
                    snapshot = build_snapshot(session, workspace, sorted(staged), self.clock())
                except ValueError:
                    current.status = "failed"
                    current.payload = {**current.payload, "error_code": "SnapshotUnavailable"}
                    return identity
                decision_id = str(uuid5(NAMESPACE_URL, "agent-decision:"+identity))
                snapshot["autonomy_mode"] = policy.mode
                decision = AIDecision(id=decision_id, workspace_id=workspace, owner_id=actor,
                    created_at=self.clock(), expires_at=current.expires_at,
                    status="ready" if policy.mode == "RECOMMEND" else "pending", payload={
                        "snapshot": snapshot, "mode": policy.mode, "policy_revision": revision,
                        "summary": answer[:2000], "entity_ids": sorted(staged), "requires_confirmation": True,
                        "automation_generation": payload["automation_generation"], "callback_token": secrets.token_hex(16),
                        "command_scopes": {key: data["scope"] for key, data in staged.items()}, "agent_message_id": identity})
                session.add(decision); session.flush()
                for subject in snapshot["entities"]:
                    p = Proposal.model_validate(staged[subject["entity_id"]]["proposal"])
                    status, reason, target = "recommended" if policy.mode == "RECOMMEND" else "pending", None, None
                    try:
                        _, value = permitted(p, subject, policy)
                        target = str(value) if value is not None else None
                    except ActionRejected as error:
                        status, reason = "denied", str(error)
                    session.add(AIAction(id=str(uuid5(NAMESPACE_URL, decision_id+":"+p.entity_id)), workspace_id=workspace,
                        decision_id=decision_id, created_at=self.clock(), status=status,
                        payload={"proposal": p.model_dump(mode="json"), "target_budget": target, "policy_reason": reason,
                            "scope": staged[p.entity_id]["scope"]}))
                current.decision_id = decision_id
            current.status = "completed"
        return identity

    def view(self, session, message):
        decision = session.get(AIDecision, message.decision_id) if message.decision_id else None
        return {"id": message.id, "text": message.text, "status": message.status,
            "created_at": aware(message.created_at).isoformat(), "answer": message.payload.get("answer"),
            "error_code": message.payload.get("error_code"), "trace": message.payload.get("trace", []),
            "decision": self.core.view(session, decision) if decision else None}
