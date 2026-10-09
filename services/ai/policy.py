"""Deterministic restrictions for approved and autonomous AI actions."""
from decimal import Decimal
import os
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from services.actions.engine import ActionRejected
from services.storage.models import AIAction, AIDecision, AISettings, AIQuota
from services.storage.repository import insert_for
from services.sync.engine import aware
from .schema import CopilotPolicy


def read_policy(session, workspace):
    row = session.get(AISettings, workspace)
    return (CopilotPolicy.model_validate(row.payload), row.revision) if row else (CopilotPolicy(), 0)


def save_policy(sessions, workspace, policy, revision, now):
    if policy.mode == "AUTOPILOT" and os.environ.get("AI_AUTOPILOT_ALLOWED", "false").lower() != "true":
        raise ActionRejected("Autopilot is disabled by deployment configuration")
    from sqlalchemy.exc import IntegrityError
    try:
        with sessions.begin() as session:
            if revision == 0:
                session.add(AISettings(workspace_id=workspace, revision=1, payload=policy.model_dump(mode="json"), updated_at=now))
            else:
                result = session.execute(update(AISettings).where(AISettings.workspace_id == workspace,
                    AISettings.revision == revision).values(revision=revision+1, payload=policy.model_dump(mode="json"), updated_at=now))
                if result.rowcount != 1:
                    raise ActionRejected("AI policy changed; reload before saving")
    except IntegrityError:
        raise ActionRejected("AI policy changed; reload before saving") from None
    return revision+1


def reserve(session, workspace, now, field, ceiling):
    # Stable workspace timezone; account zones cannot split the action quota.
    day = now.astimezone(ZoneInfo("Europe/Moscow")).date()
    session.execute(insert_for(session, AIQuota.__table__).values(workspace_id=workspace,
        day=day, queued=0, attempted=0, analyses=0).on_conflict_do_nothing(index_elements=["workspace_id", "day"]))
    column = getattr(AIQuota, field)
    changed = session.execute(update(AIQuota).where(AIQuota.workspace_id == workspace,
        AIQuota.day == day, column < ceiling).values({field: column+1}))
    if changed.rowcount != 1:
        raise ActionRejected(f"AI daily {field} limit reached")


def permitted(proposal, subject, policy):
    if proposal.action == "leave_unchanged":
        return None, None
    if subject["currency"] != policy.currency:
        raise ActionRejected("AI policy currency does not match the account")
    if not subject["state"]["fresh"] or not subject["windows"]["today"]["fresh"]:
        raise ActionRejected("AI evidence is incomplete or stale")
    metrics = subject["windows"]["today"]["metrics"]
    if metrics.get("spend") is None or metrics.get("leads") is None and metrics.get("sales") is None:
        raise ActionRejected("AI action requires known spend and lead or sale counts")
    if proposal.action == "enable":
        if not policy.allow_enable or subject["level"] not in ("ad", "adset"):
            raise ActionRejected("Enable is not permitted by AI policy")
        return "enable", None
    if proposal.action == "pause":
        if subject["level"] not in ("ad", "adset"):
            raise ActionRejected("AI may pause only ads and adsets")
        return "pause", None
    if subject["level"] not in ("adset", "campaign"):
        raise ActionRejected("AI budget changes require a campaign or adset")
    if not policy.daily_budget_verified:
        raise ActionRejected("Daily budget interpretation is not verified")
    change = Decimal(str(proposal.change_percent))
    if abs(change) > policy.max_change_percent:
        raise ActionRejected(f"Maximum AI budget change is {policy.max_change_percent}%")
    budget = subject["state"]["budget"]
    if budget is None or Decimal(budget) <= 0:
        raise ActionRejected("Current budget is unknown")
    if any(metrics.get(k) is None for k in ("conversions", "roi", "cpl")):
        raise ActionRejected("Budget change requires known conversions, ROI and CPL")
    target = (Decimal(budget) * (1+change/100)).quantize(Decimal("0.01"))
    if abs(target-Decimal(budget))/Decimal(budget)*100 > policy.max_change_percent:
        raise ActionRejected("Rounded budget exceeds the AI change limit")
    if target <= 0 or target > policy.max_daily_budget:
        raise ActionRejected(f"Maximum AI daily budget is {policy.max_daily_budget} {policy.currency}")
    from .profiles import check_budget
    check_budget(subject, change, target)
    return "budget_set", target


def validate_queued_ai(session, request, now):
    context = request.provenance
    if context.get("source") != "ai":
        return
    from services.automation.control import guard
    guard(session, request.workspace_id, now, context.get("automation_generation", 0))
    decision = session.get(AIDecision, context.get("decision_id"))
    if not decision or decision.workspace_id != request.workspace_id or not decision.expires_at or aware(decision.expires_at) <= now:
        raise ActionRejected("AI proposal has expired")
    approved = session.scalar(select(AIAction).where(AIAction.decision_id == decision.id,
        AIAction.request_id == request.id, AIAction.workspace_id == request.workspace_id))
    if decision.status != "approved" or not approved or approved.status != "queued" or approved.payload["proposal"] != context.get("proposal"):
        raise ActionRejected("AI command has no durable approval")
    policy, revision = read_policy(session, request.workspace_id)
    if revision != decision.payload["policy_revision"] or policy.mode not in ("APPROVAL", "AUTOPILOT"):
        raise ActionRejected("AI policy or mode changed")
    if context.get("mode") != policy.mode or decision.payload["mode"] != policy.mode:
        raise ActionRejected("AI action mode differs from its approval")
    if context.get("mode") == "AUTOPILOT" and os.environ.get("AI_AUTOPILOT_ALLOWED", "false").lower() != "true":
        raise ActionRejected("Autopilot is disabled")
    from .schema import Proposal
    from .snapshot import build_snapshot
    try:
        fresh = build_snapshot(session, request.workspace_id, [request.entity_id], now)
    except ValueError:
        raise ActionRejected("AI evidence is no longer available") from None
    original = next(s for s in decision.payload["snapshot"]["entities"] if s["entity_id"] == request.entity_id)
    subject = fresh["entities"][0]
    if subject["fingerprint"] != original["fingerprint"] or fresh["detector_revision"] != decision.payload["snapshot"]["detector_revision"]:
        raise ActionRejected("AI evidence changed; run a new analysis")
    from .agent_tools import validate_scope
    validate_scope(session, request.workspace_id, decision.payload.get("command_scopes", {}).get(request.entity_id), request.entity_id, now)
    action, value = permitted(Proposal.model_validate(context["proposal"]), subject, policy)
    if (request.action, request.value) != (action, value):
        raise ActionRejected("AI action differs from the approved proposal")
    reserve(session, request.workspace_id, now, "attempted", policy.max_actions_per_day)
