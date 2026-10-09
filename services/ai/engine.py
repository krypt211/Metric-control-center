"""Durable inference and approvals, isolated from advertising credentials."""
from datetime import timedelta
import json
import secrets
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from services.actions.engine import ActionEngine, ActionRejected
from services.storage.models import AIAction, AIDecision, User
from services.sync.engine import aware, utc_now
from .policy import permitted, read_policy, reserve
from .schema import CopilotOutput, Proposal
from .snapshot import build_snapshot


def authorize(session, workspace, actor):
    user = session.get(User, actor)
    if not user or user.workspace_id != workspace or user.role not in ("operator", "admin"):
        raise ActionRejected("Operator has no permission")


class CopilotEngine:
    def __init__(self, actions: ActionEngine, *, clock=utc_now):
        self.actions, self.sessions, self.clock = actions, actions.sessions, clock

    def queue(self, workspace, actor, entity_ids, key):
        if not key or len(key) > 128 or not 1 <= len(entity_ids) <= 30 or len(set(entity_ids)) != len(entity_ids):
            raise ActionRejected("Select 1–30 unique entities and an idempotency key")
        identity = str(uuid5(NAMESPACE_URL, "ai:"+json.dumps([workspace, actor, key])))
        now = self.clock()
        try:
            with self.sessions.begin() as session:
                authorize(session, workspace, actor)
                existing = session.get(AIDecision, identity)
                if existing:
                    if existing.payload.get("entity_ids") != sorted(entity_ids):
                        raise ActionRejected("Analysis key was used for different entities")
                    return identity
                policy, revision = read_policy(session, workspace)
                if policy.mode == "OFF":
                    raise ActionRejected("AI Copilot is off")
                try:
                    snapshot = build_snapshot(session, workspace, sorted(entity_ids), now)
                except ValueError as error:
                    raise ActionRejected(str(error)) from None
                reserve(session, workspace, now, "analyses", policy.max_analyses_per_day)
                from services.automation.control import state
                snapshot["autonomy_mode"] = policy.mode
                session.add(AIDecision(id=identity, workspace_id=workspace, owner_id=actor, status="queued",
                    created_at=now, expires_at=now+timedelta(minutes=policy.proposal_ttl_minutes), payload={
                        "snapshot": snapshot, "policy_revision": revision, "mode": policy.mode,
                        "entity_ids": sorted(entity_ids), "callback_token": secrets.token_hex(16),
                        "automation_generation": state(session, workspace)["generation"]}))
        except IntegrityError:
            with self.sessions() as session:
                existing = session.get(AIDecision, identity)
                if existing and existing.payload.get("entity_ids") == sorted(entity_ids):
                    return identity
            raise ActionRejected("Analysis changed concurrently") from None
        return identity

    async def process_next(self, provider):
        now = self.clock()
        with self.sessions.begin() as session:
            # Stalled inference is not retried: a crash cannot duplicate API cost.
            session.execute(update(AIDecision).where(AIDecision.status.in_(("queued", "generating")),
                AIDecision.expires_at <= now).values(status="expired"))
            decision = session.scalar(select(AIDecision).where(AIDecision.status == "queued").order_by(
                AIDecision.created_at).with_for_update(skip_locked=True).limit(1))
            if not decision:
                return None
            identity, workspace, owner, payload = decision.id, decision.workspace_id, decision.owner_id, decision.payload
            try:
                authorize(session, workspace, owner)
            except ActionRejected:
                decision.status = "cancelled"
                return identity
            if not decision.expires_at or "snapshot" not in payload or "policy_revision" not in payload:
                decision.status = "cancelled"
                return identity
            policy, revision = read_policy(session, workspace)
            if policy.mode == "OFF" or revision != payload["policy_revision"]:
                decision.status = "cancelled"
                return identity
            claimed = session.execute(update(AIDecision).where(AIDecision.id == identity,
                AIDecision.status == "queued").values(status="generating"))
            if claimed.rowcount != 1:
                return None
        try:
            output = await provider.analyze(payload["snapshot"])
            output = CopilotOutput.model_validate(output.model_dump() if isinstance(output, CopilotOutput) else output)
            if payload["mode"] == "READ_ONLY":
                output = output.model_copy(update={"proposals": []})
            subjects = {s["entity_id"]: s for s in payload["snapshot"]["entities"]}
            seen = set()
            for proposal in output.proposals:
                if proposal.entity_id not in subjects or proposal.entity_id in seen:
                    raise ValueError("Model selected an unknown or duplicate entity")
                if any(e not in subjects[proposal.entity_id]["evidence_ids"] for e in proposal.evidence):
                    raise ValueError("Model referenced unknown evidence")
                seen.add(proposal.entity_id)
        except Exception as error:
            with self.sessions.begin() as session:
                decision = session.get(AIDecision, identity)
                if decision.status == "generating":
                    decision.status = "failed"
                    decision.payload = {**decision.payload, "error_code": type(error).__name__}
            return identity
        with self.sessions.begin() as session:
            decision = session.get(AIDecision, identity)
            if decision.status != "generating":
                return identity
            policy, revision = read_policy(session, workspace)
            if aware(decision.expires_at) <= self.clock() or revision != payload["policy_revision"]:
                decision.status = "expired" if aware(decision.expires_at) <= self.clock() else "cancelled"
                return identity
            decision.status = "ready" if policy.mode in ("READ_ONLY", "RECOMMEND") else "pending"
            decision.payload = {**decision.payload, "summary": output.summary}
            for proposal in output.proposals:
                status, reason, target = "recommended", None, None
                try:
                    action, value = permitted(proposal, subjects[proposal.entity_id], policy)
                    target = str(value) if value is not None else None
                    if action is None:
                        status = "no_change"
                    elif policy.mode != "RECOMMEND":
                        status = "pending"
                except ActionRejected as error:
                    status, reason = "denied", str(error)
                session.add(AIAction(id=str(uuid4()), workspace_id=workspace, decision_id=identity,
                    status=status, created_at=self.clock(), payload={"proposal": proposal.model_dump(mode="json"),
                        "target_budget": target, "policy_reason": reason}))
        if policy.mode == "AUTOPILOT":
            # Uses exactly the same validation/queue as an operator approval.
            try:
                self.resolve(workspace, owner, identity, "approve", automatic=True)
            except ActionRejected:
                pass  # Approval remains reviewable when global actions are off.
        return identity

    def resolve(self, workspace, actor, identity, operation, *, automatic=False, channel="web"):
        if operation not in ("approve", "reject"):
            raise ActionRejected("Unsupported approval operation")
        now = self.clock()
        with self.sessions.begin() as session:
            authorize(session, workspace, actor)
            decision = session.scalar(select(AIDecision).where(AIDecision.id == identity,
                AIDecision.workspace_id == workspace).with_for_update())
            if not decision:
                raise ActionRejected("AI decision not found")
            if decision.status in ("approved", "rejected"):
                return self.view(session, decision)
            if operation == "reject":
                if decision.status not in ("queued", "generating", "ready", "pending"):
                    raise ActionRejected("Decision is no longer pending")
                changed = session.execute(update(AIDecision).where(AIDecision.id == identity,
                    AIDecision.status == decision.status).values(status="rejected"))
                if changed.rowcount != 1:
                    raise ActionRejected("Decision changed concurrently")
                for action in session.scalars(select(AIAction).where(AIAction.decision_id == identity, AIAction.status == "pending")):
                    action.status = "rejected"
                decision.payload = {**decision.payload, "resolved_by": actor, "resolved_at": now.isoformat(), "approval_channel": channel}
                return self.view(session, decision)
            policy, revision = read_policy(session, workspace)
            if decision.status != "pending" or policy.mode not in ("APPROVAL", "AUTOPILOT") or revision != decision.payload["policy_revision"]:
                raise ActionRejected("AI policy changed or decision is not awaiting approval")
            if not self.actions.policy.enabled:
                raise ActionRejected("Advertising actions are disabled")
            from services.automation.control import guard
            guard(session, workspace, now, decision.payload.get("automation_generation", 0))
            if automatic:
                if decision.payload.get("requires_confirmation"):
                    raise ActionRejected("Chat commands always require explicit confirmation")
                import os
                if policy.mode != "AUTOPILOT" or os.environ.get("AI_AUTOPILOT_ALLOWED", "false").lower() != "true":
                    raise ActionRejected("Autopilot is disabled")
            if not decision.expires_at or aware(decision.expires_at) <= now:
                raise ActionRejected("AI proposal has expired; run a new analysis")
            # UPDATE provides a write fence on SQLite as well as PostgreSQL.
            changed = session.execute(update(AIDecision).where(AIDecision.id == identity,
                AIDecision.status == "pending").values(status="approved"))
            if changed.rowcount != 1:
                raise ActionRejected("Decision changed concurrently")
            decision.payload = {**decision.payload, "resolved_by": actor, "resolved_at": now.isoformat(),
                "approval_source": "autopilot" if automatic else "operator", "approval_channel": channel}
            subjects = {s["entity_id"]: s for s in decision.payload["snapshot"]["entities"]}
            for action in session.scalars(select(AIAction).where(AIAction.decision_id == identity, AIAction.status == "pending")):
                try:
                    with session.begin_nested():
                        proposal = Proposal.model_validate(action.payload["proposal"])
                        current = build_snapshot(session, workspace, [proposal.entity_id], now)
                        subject = current["entities"][0]
                        from .agent_tools import validate_scope
                        validate_scope(session, workspace, decision.payload.get("command_scopes", {}).get(proposal.entity_id), proposal.entity_id, now)
                        if subject["fingerprint"] != subjects[proposal.entity_id]["fingerprint"] or current["detector_revision"] != decision.payload["snapshot"]["detector_revision"]:
                            raise ActionRejected("AI evidence changed; run a new analysis")
                        verb, value = permitted(proposal, subject, policy)
                        reserve(session, workspace, now, "queued", policy.max_actions_per_day)
                        request = self.actions.enqueue_in_session(session, workspace, actor, proposal.entity_id,
                            verb, value, "ai:"+action.id, context={"source": "ai", "decision_id": identity,
                                "mode": policy.mode, "proposal": proposal.model_dump(mode="json"),
                                "automation_generation": decision.payload.get("automation_generation", 0),
                                "reason": proposal.reason, "approval": "autopilot" if automatic else "operator", "approval_channel": channel})
                        action.status, action.request_id = "queued", request
                except (ActionRejected, ValueError, IntegrityError) as error:
                    action.status = "denied"
                    reason = "Another action is pending" if isinstance(error, IntegrityError) else str(error)
                    action.payload = {**action.payload, "policy_reason": reason}
            session.flush()
            return self.view(session, decision)

    @staticmethod
    def view(session, decision):
        from services.storage.models import ActionRequest, Entity
        rows = session.scalars(select(AIAction).where(AIAction.decision_id == decision.id).order_by(AIAction.created_at)).all()
        actions = []
        scope_groups = {}
        for scope in decision.payload.get("command_scopes", {}).values():
            key = (scope["query"]["currency"], scope["timezone"])
            scope_groups.setdefault(key, []).append(scope["metrics"]["spend"])
        from decimal import Decimal
        command_summary = [{"currency": currency, "timezone": zone, "entities": len(values),
            "spend": str(sum(Decimal(str(v)) for v in values)) if all(v is not None for v in values) else None}
            for (currency, zone), values in sorted(scope_groups.items())]
        for row in rows:
            request = session.get(ActionRequest, row.request_id) if row.request_id else None
            entity = session.get(Entity, row.payload.get("proposal", {}).get("entity_id"))
            actions.append({"id": row.id, "status": request.status if request else row.status,
                "request_id": row.request_id, "entity_name": entity.name or entity.external_id if entity else None, **row.payload})
        return {"id": decision.id, "status": decision.status, "mode": decision.payload.get("mode"),
            "requires_confirmation": decision.payload.get("requires_confirmation", False),
            "command_scopes": decision.payload.get("command_scopes", {}),
            "command_summary": command_summary,
            "created_at": aware(decision.created_at).isoformat(), "expires_at": aware(decision.expires_at).isoformat() if decision.expires_at else None,
            "summary": decision.payload.get("summary"), "error_code": decision.payload.get("error_code"),
            "snapshot": decision.payload.get("snapshot"), "actions": actions}
