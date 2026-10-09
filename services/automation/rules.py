"""Database-only evaluation. Active decisions use the same Action Engine as Web."""
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import operator
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from services.actions.engine import ActionEngine, ActionRejected
from services.analytics.table import Filters, table_data
from services.storage.models import AdAccount, EntityCurrentState, Rule, RuleCooldown, RuleRun, User
from services.sync.engine import aware
from .schema import RuleDefinition

COMPARE = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt, "=": operator.eq, "!=": operator.ne}
MODES = {"OFF", "DRY_RUN", "ACTIVE"}


def rule_window(definition, now):
    today = now.astimezone(ZoneInfo(definition.timezone)).date()
    if definition.window == "yesterday":
        return today - timedelta(days=1), today - timedelta(days=1)
    days = 1 if definition.window == "today" else int(definition.window[4:])
    return today - timedelta(days=days - 1), today


def validate_queued_rule(session, request, now, max_age):
    """A queued proposal is rechecked before its single provider attempt."""
    context = request.provenance
    if context.get("source") != "rule":
        return
    rule = session.get(Rule, context.get("rule_id"))
    evidence = context.get("reason", {})
    if not rule or rule.workspace_id != request.workspace_id or rule.status != "ACTIVE" or rule.revision != evidence.get("revision"):
        raise ActionRejected("Rule was disabled or changed after the decision")
    definition = RuleDefinition.model_validate(rule.payload)
    first, last = rule_window(definition, now)
    if evidence.get("window") != [first.isoformat(), last.isoformat()]:
        raise ActionRejected("Rule decision window has expired")
    local_time = now.astimezone(ZoneInfo(definition.timezone)).strftime("%H:%M")
    start, end = definition.schedule_start, definition.schedule_end
    if start != end and not (start <= local_time < end if start < end else local_time >= start or local_time < end):
        raise ActionRejected("Rule is outside its schedule")
    rows = table_data(session, request.workspace_id, Filters(first, last), level=definition.level, limit=1_000_000, exact_ratios=True)["rows"]
    row = next((r for r in rows if r["id"] == request.entity_id and r["currency"] == definition.currency and r["timezone"] == definition.timezone), None)
    if not row or not -60 <= (now - aware(datetime.fromisoformat(row["oldest_observation"]))).total_seconds() <= max_age:
        raise ActionRejected("Rule metrics require refresh")
    if any(row[c.metric] is None or not COMPARE[c.operator](Decimal(str(row[c.metric])), c.value) for c in definition.conditions):
        raise ActionRejected("Rule conditions no longer match")
    if definition.minimum_events and (row["conversions"] is None or row["conversions"] < definition.minimum_events):
        raise ActionRejected("Rule minimum events no longer match")


class RuleEngine:
    def __init__(self, actions: ActionEngine):
        self.actions, self.sessions = actions, actions.sessions

    def create_once(self, workspace, actor_id, definition, mode, creation_id):
        def existing():
            with self.sessions() as session:
                rule = session.get(Rule, creation_id)
                if rule:
                    if (rule.workspace_id, rule.owner_id, rule.payload, rule.status) != (
                        workspace, actor_id, definition.model_dump(mode="json"), mode):
                        raise ActionRejected("Rule creation key was already used")
                    return rule.id
        result = existing()
        if result:
            return result
        try:
            return self.save(workspace, actor_id, definition, mode, _new_id=creation_id)
        except IntegrityError:
            result = existing()
            if result:
                return result
            raise ActionRejected("Rule creation conflict") from None

    def save(self, workspace, actor_id, definition: RuleDefinition, mode="DRY_RUN", rule_id=None, revision=None, *, _new_id=None):
        if mode not in MODES:
            raise ActionRejected("Unknown rule mode")
        with self.sessions.begin() as session:
            actor = session.get(User, actor_id)
            if not actor or actor.workspace_id != workspace or actor.role not in ("admin", "operator"):
                raise ActionRejected("Operator has no permission")
            for account_id in definition.account_ids:
                account = session.get(AdAccount, account_id)
                if not account or account.workspace_id != workspace:
                    raise ActionRejected("Account does not belong to this workspace")
            if rule_id:
                rule = session.scalar(select(Rule).where(Rule.id == rule_id, Rule.workspace_id == workspace).with_for_update())
                if not rule:
                    raise ActionRejected("Rule not found")
                if rule.revision != revision:
                    raise ActionRejected("Rule was changed; reload before editing")
                changed = session.execute(update(Rule).where(Rule.id == rule_id,
                    Rule.workspace_id == workspace, Rule.revision == revision).values(
                        revision=revision + 1, owner_id=actor_id, payload=definition.model_dump(mode="json"),
                        status=mode, next_evaluation_at=None))
                if changed.rowcount != 1:
                    raise ActionRejected("Rule was changed; reload before editing")
                return rule.id
            else:
                rule = Rule(id=_new_id or str(uuid4()), workspace_id=workspace, created_at=self.actions.clock(), revision=1)
                session.add(rule)
            rule.owner_id, rule.payload, rule.status = actor_id, definition.model_dump(mode="json"), mode
            rule.next_evaluation_at = None
            return rule.id

    def evaluate(self, rule_id, workspace):
        now = self.actions.clock()
        with self.sessions.begin() as session:
            # This write obtains a row lock on PostgreSQL, and serializes SQLite
            # evaluations before reading facts. Competing workers cannot claim
            # the same due rule. Everything is committed with commands/cooldown.
            claimed = session.execute(update(Rule).where(Rule.id == rule_id, Rule.workspace_id == workspace,
                Rule.status.in_(("DRY_RUN", "ACTIVE")),
                or_(Rule.next_evaluation_at.is_(None), Rule.next_evaluation_at <= now)
            ).values(next_evaluation_at=now + timedelta(days=1)))
            if claimed.rowcount != 1:
                return {"status": "off_or_not_due", "decisions": 0}
            rule = session.get(Rule, rule_id)
            definition = RuleDefinition.model_validate(rule.payload)
            rule.next_evaluation_at = now + timedelta(seconds=definition.interval_seconds)
            local = now.astimezone(ZoneInfo(definition.timezone))
            time = local.strftime("%H:%M")
            start, end = definition.schedule_start, definition.schedule_end
            scheduled = start == end or (start <= time < end if start < end else time >= start or time < end)
            if not scheduled:
                return {"status": "outside_schedule", "decisions": 0}
            first, last = rule_window(definition, now)
            rows = table_data(session, workspace, Filters(first, last), level=definition.level, limit=1_000_000, exact_ratios=True)["rows"]
            decisions = 0
            for row in rows:
                if row["currency"] != definition.currency or row["timezone"] != definition.timezone:
                    continue
                if definition.account_ids and row["account_id"] not in definition.account_ids:
                    continue
                state = session.get(EntityCurrentState, row["id"])
                evidence = {"rule_name": definition.name, "entity_name": row["name"], "entity_id": row["id"],
                    "currency": row["currency"], "timezone": row["timezone"], "window": [first.isoformat(), last.isoformat()],
                    "metrics": {metric: row[metric] for metric in {"conversions", *(condition.metric for condition in definition.conditions)}},
                    "conditions": [condition.model_dump(mode="json") for condition in definition.conditions],
                    "observed_at": row["oldest_observation"], "mode": rule.status, "revision": rule.revision}
                fingerprint = {**evidence, "state_observed_at": aware(state.observed_at).isoformat() if state else None,
                    "budget": str(state.budget) if state and state.budget is not None else None,
                    "status": state.status if state else None}
                evaluation_key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
                if session.scalar(select(RuleRun.id).where(RuleRun.rule_id == rule.id, RuleRun.evaluation_key == evaluation_key)):
                    continue
                result, request_id = "no_match", None
                freshness = (now - aware(datetime.fromisoformat(row["oldest_observation"]))).total_seconds()
                account = session.get(AdAccount, row["account_id"])
                if freshness < -60 or freshness > self.actions.policy.max_state_age_seconds:
                    result = "stale_metrics"
                elif account.currency != row["currency"] or account.timezone != row["timezone"]:
                    result = "account_units_mismatch"
                elif any(row[c.metric] is None for c in definition.conditions) or (
                    definition.minimum_events and row["conversions"] is None):
                    result = "unknown_metrics"
                elif all(COMPARE[c.operator](Decimal(str(row[c.metric])), c.value) for c in definition.conditions) and (
                    not definition.minimum_events or row["conversions"] >= definition.minimum_events):
                    cooldown = session.get(RuleCooldown, (rule.id, row["id"]))
                    if cooldown and (now - aware(cooldown.last_queued_at)).total_seconds() < definition.cooldown_seconds:
                        result = "cooldown"
                    else:
                        try:
                            action, value = definition.operation.command(state.budget if state else None)
                            evidence["before"] = {"budget": str(state.budget) if state and state.budget is not None else None,
                                                  "status": state.status if state else None}
                            evidence["action"], evidence["value"] = action, str(value) if value is not None else None
                            if value is not None and definition.max_budget is not None and value > definition.max_budget:
                                raise ActionRejected("Rule budget ceiling exceeded")
                            if not state or (now - aware(state.observed_at)).total_seconds() > self.actions.policy.max_state_age_seconds:
                                raise ActionRejected("Refresh current entity state before acting")
                            # DRY_RUN calculates even while live actions/contracts
                            # are disabled. ACTIVE always passes full policy.
                            if rule.status == "DRY_RUN":
                                self.actions.validate(session, workspace, rule.owner_id, row["id"], action, value, dry_run=True)
                                result = "would_act"
                            else:
                                with session.begin_nested():
                                    request_id = self.actions.enqueue_in_session(session, workspace, rule.owner_id, row["id"],
                                        action, value, f"rule:{rule.id}:{evaluation_key}",
                                        context={"source": "rule", "rule_id": rule.id, "rule_name": definition.name, "reason": evidence})
                                result = "queued"
                                if cooldown:
                                    cooldown.last_queued_at = now
                                else:
                                    session.add(RuleCooldown(rule_id=rule.id, entity_id=row["id"], last_queued_at=now))
                        except (ActionRejected, ValueError, IntegrityError) as error:
                            result = "rejected"
                            evidence["reason"] = "Another action for this entity is pending" if isinstance(error, IntegrityError) else str(error)
                session.add(RuleRun(id=str(uuid4()), workspace_id=workspace, rule_id=rule.id,
                    request_id=request_id, evaluation_key=evaluation_key, created_at=now, status=result, payload=evidence))
                decisions += 1
            return {"status": "evaluated", "decisions": decisions}

    def evaluate_due(self, workspace):
        with self.sessions() as session:
            ids = session.scalars(select(Rule.id).where(Rule.workspace_id == workspace,
                Rule.status.in_(("DRY_RUN", "ACTIVE")), or_(Rule.next_evaluation_at.is_(None), Rule.next_evaluation_at <= self.actions.clock()))).all()
        return [self.evaluate(rule_id, workspace) for rule_id in ids]
