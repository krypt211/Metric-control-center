"""Durable action queue. A recorded attempt is never automatically sent again."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from services.metricflow.errors import APIError, RateLimitExceeded
from services.storage.models import (
    ActionExecution, ActionLog, ActionRequest, AdAccount, ApiQuota, Entity,
    EntityCurrentState, User,
)
from services.storage.repository import insert_for
from services.sync.engine import aware, utc_now
from .providers import supports


class ActionRejected(ValueError):
    pass


@dataclass(frozen=True)
class ActionPolicy:
    enabled: bool = False
    max_budget: Decimal = Decimal("10000")
    max_change_percent: Decimal = Decimal("20")
    max_state_age_seconds: int = 900
    verification_timeout_seconds: int = 1800
    daily_api_budget: int = 800
    budget_contract: dict[str, Any] | None = None

    def __post_init__(self):
        if not self.max_budget.is_finite() or self.max_budget <= 0 or not self.max_change_percent.is_finite() or not 0 < self.max_change_percent <= 100:
            raise ValueError("Invalid action budget limits")
        if self.daily_api_budget <= 0 or self.max_state_age_seconds <= 0 or self.verification_timeout_seconds <= 0:
            raise ValueError("Invalid action timing/quota limits")
        contract = self.budget_contract
        if contract and contract.get("verified") is True:
            scale = Decimal(str(contract.get("scale", "0")))
            if not scale.is_finite() or scale <= 0 or not isinstance(contract.get("field"), str) or not contract["field"]:
                raise ValueError("Invalid verified budget contract")
            if contract.get("encoding") not in ("integer", "decimal_string") or not isinstance(contract.get("fixed_fields", {}), dict):
                raise ValueError("Invalid verified budget encoding")

    def budget_payload(self, value: Decimal) -> dict[str, Any]:
        contract = self.budget_contract
        if not contract or contract.get("verified") is not True:
            raise ActionRejected("Budget API contract has not been verified")
        scaled = value * Decimal(str(contract["scale"]))
        if contract["encoding"] == "integer":
            if scaled != scaled.to_integral_value():
                raise ActionRejected("Budget cannot be represented in provider units")
            encoded = int(scaled)
        elif contract["encoding"] == "decimal_string":
            encoded = format(scaled, "f")
        else:
            raise ActionRejected("Unsupported budget encoding")
        return {**contract.get("fixed_fields", {}), contract["field"]: encoded}


def log(session, request_id: str, event: str, now: datetime, **details):
    session.add(ActionLog(id=str(uuid4()), request_id=request_id, created_at=now, event=event, details=details))


class ActionEngine:
    def __init__(self, sessions, policy: ActionPolicy, *, clock=utc_now):
        self.sessions, self.policy, self.clock = sessions, policy, clock

    def validate(self, session, workspace: str, actor_id: str, entity_id: str, action: str, value: Decimal | None, *, dry_run=False):
        if not self.policy.enabled and not dry_run:
            raise ActionRejected("Actions are not enabled")
        actor = session.get(User, actor_id)
        if not actor or actor.workspace_id != workspace or actor.role not in ("admin", "operator"):
            raise ActionRejected("Operator has no permission")
        entity = session.get(Entity, entity_id)
        account = session.get(AdAccount, entity.account_id) if entity else None
        if not entity or not account or account.workspace_id != workspace:
            raise ActionRejected("Entity does not exist in this workspace")
        if not supports(account.provider, action):
            raise ActionRejected("Provider has no verified capability for this operation")
        if entity.kind not in ("campaign", "adset", "ad") or action not in ("pause", "enable", "budget_set"):
            raise ActionRejected("Unsupported operation")
        state = session.get(EntityCurrentState, entity_id)
        if not state or not -60 <= (self.clock() - aware(state.observed_at)).total_seconds() <= self.policy.max_state_age_seconds:
            raise ActionRejected("Refresh current entity state before acting")
        if state.status not in ("ACTIVE", "PAUSED"):
            raise ActionRejected("Current status is unavailable or unsupported")
        if action == "pause" and state.status == "PAUSED" or action == "enable" and state.status == "ACTIVE":
            raise ActionRejected("Entity is already in the requested state")
        if action == "budget_set":
            if entity.kind == "ad" or value is None or not value.is_finite() or not 0 < value <= self.policy.max_budget:
                raise ActionRejected("Invalid budget or entity level")
            if value.as_tuple().exponent < -8:
                raise ActionRejected("Budget precision exceeds the database precision")
            if state.budget is None or state.budget <= 0:
                raise ActionRejected("Current budget is unknown")
            if value == state.budget:
                raise ActionRejected("Budget is already at the requested value")
            if abs(value - state.budget) / state.budget * 100 > self.policy.max_change_percent:
                raise ActionRejected("Budget change exceeds the configured percentage limit")
            if not dry_run:
                self.policy.budget_payload(value)
        elif value is not None:
            raise ActionRejected("This operation does not accept a value")
        return entity, state

    def enqueue_in_session(self, session, workspace: str, actor_id: str, entity_id: str,
                           action: str, value: Decimal | None, key: str, *, context=None) -> str:
        """Caller can atomically record a rule result/cooldown with the command."""
        if not key or len(key) > 128:
            raise ActionRejected("A valid idempotency key is required")
        existing = session.scalar(select(ActionRequest).where(
            ActionRequest.workspace_id == workspace, ActionRequest.initiator_id == actor_id,
            ActionRequest.idempotency_key == key,
        ))
        if existing:
            if (existing.entity_id, existing.action, existing.value) != (entity_id, action, value):
                raise ActionRejected("Idempotency key was already used for another command")
            return existing.id
        entity, state = self.validate(session, workspace, actor_id, entity_id, action, value)
        context = dict(context or {"source": "web"})
        from services.automation.control import SOURCES, guard
        if context.get("source") in SOURCES:
            context["automation_generation"] = guard(session, workspace, self.clock(), context.get("automation_generation"))
        if context.get("source") in ("ai", "agent"):
            from services.ai.profiles import reserve_scaling
            reserve_scaling(session, workspace, entity, action, value, state.budget, self.clock())
        actor = session.get(User, actor_id)
        account = session.get(AdAccount, entity.account_id)
        provenance = {
            **context, "actor": actor.email,
            "entity_name": entity.name or entity.external_id, "external_id": entity.external_id,
            "provider": account.provider, "currency": account.currency,
            "before": {"status": state.status, "budget": str(state.budget) if state.budget is not None else None},
            "after": {"status": "PAUSED" if action == "pause" else "ACTIVE" if action == "enable" else state.status,
                      "budget": str(value) if action == "budget_set" else str(state.budget) if state.budget is not None else None},
        }
        request_id = str(uuid4())
        session.add(ActionRequest(
            id=request_id, workspace_id=workspace, entity_id=entity.id, initiator_id=actor_id,
            idempotency_key=key, action=action, value=value, baseline_status=state.status,
            baseline_budget=state.budget, provenance=provenance, status="queued", created_at=self.clock(),
        ))
        session.flush()
        log(session, request_id, "queued", self.clock(), initiator_id=actor_id, action=action,
            value=str(value) if value is not None else None, **provenance)
        return request_id

    def enqueue(self, workspace: str, actor_id: str, entity_id: str, action: str, value: Decimal | None,
                key: str, *, context=None) -> str:
        try:
            with self.sessions.begin() as session:
                return self.enqueue_in_session(session, workspace, actor_id, entity_id, action, value, key, context=context)
        except IntegrityError:
            # Concurrent submissions may be the same idempotent request.
            with self.sessions() as session:
                existing = session.scalar(select(ActionRequest).where(
                    ActionRequest.workspace_id == workspace, ActionRequest.initiator_id == actor_id,
                    ActionRequest.idempotency_key == key,
                ))
                if existing and (existing.entity_id, existing.action, existing.value) == (entity_id, action, value):
                    return existing.id
            raise ActionRejected("Another action for this entity is still pending") from None

    def reserve_api_request(self, workspace: str):
        now = self.clock()
        with self.sessions.begin() as session:
            session.execute(insert_for(session, ApiQuota.__table__).values(
                workspace_id=workspace, provider="metricflow", utc_day=now.date(), requests=0
            ).on_conflict_do_nothing(index_elements=["workspace_id", "provider", "utc_day"]))
            blocked = session.scalar(select(ApiQuota).where(
                ApiQuota.workspace_id == workspace, ApiQuota.provider == "metricflow", ApiQuota.blocked_until > now,
            ).limit(1))
            reserved = session.execute(update(ApiQuota).where(
                ApiQuota.workspace_id == workspace, ApiQuota.provider == "metricflow", ApiQuota.utc_day == now.date(),
                ApiQuota.requests < self.policy.daily_api_budget,
                or_(ApiQuota.blocked_until.is_(None), ApiQuota.blocked_until <= now),
            ).values(requests=ApiQuota.requests + 1))
            if blocked or reserved.rowcount != 1:
                raise ActionRejected("API quota exhausted")

    async def execute_next(self, connector) -> str | None:
        now = self.clock()
        with self.sessions.begin() as session:
            candidate = session.execute(select(ActionRequest.id, ActionRequest.workspace_id, ActionRequest.provenance).where(ActionRequest.status == "queued").order_by(
                ActionRequest.created_at
            ).limit(1)).first()
            if candidate is None:
                return None
            # Every automation transaction locks control before the request.
            # Emergency Stop uses the same order, avoiding a PostgreSQL deadlock.
            from services.automation.control import SOURCES, guard, lock_control
            if candidate.provenance.get("source") in SOURCES:
                lock_control(session, candidate.workspace_id, now)
            request = session.scalar(select(ActionRequest).where(ActionRequest.id == candidate.id,
                ActionRequest.status == "queued").with_for_update(skip_locked=True))
            if request is None:
                return None
            request_id = request.id
            try:
                entity, state = self.validate(session, request.workspace_id, request.initiator_id, request.entity_id, request.action, request.value)
                if request.provenance.get("source") in SOURCES:
                    guard(session, request.workspace_id, now, request.provenance.get("automation_generation", 0))
                from services.automation.rules import validate_queued_rule
                validate_queued_rule(session, request, now, self.policy.max_state_age_seconds)
                from services.ai.policy import validate_queued_ai
                validate_queued_ai(session, request, now)
                if state.status != request.baseline_status or state.budget != request.baseline_budget:
                    raise ActionRejected("Entity state changed since the command was submitted")
                external_id, workspace, action, value = entity.external_id, request.workspace_id, request.action, request.value
            except ActionRejected as error:
                request.status = "rejected"
                log(session, request_id, "rejected", now, reason=str(error))
                return request_id
            request.status = "executing"
            session.add(ActionExecution(id=str(uuid4()), request_id=request_id, started_at=now, outcome="started"))
            log(session, request_id, "attempt_started", now)
        try:
            self.reserve_api_request(workspace)
        except ActionRejected:
            with self.sessions.begin() as session:
                session.get(ActionRequest, request_id).status = "rejected"
                execution = session.scalar(select(ActionExecution).where(ActionExecution.request_id == request_id))
                execution.completed_at, execution.outcome = self.clock(), "not_sent"
                log(session, request_id, "quota_rejected", self.clock())
            return request_id
        outcome, error_code = "acknowledged", None
        # Emergency Stop may have committed after the queue claim/quota step.
        # Recheck immediately before beginning the remote request. Requests
        # already sent cannot be revoked by a local switch.
        with self.sessions.begin() as session:
            current = session.get(ActionRequest, request_id)
            if current.provenance.get("source") in SOURCES:
                try:
                    guard(session, workspace, self.clock(), current.provenance.get("automation_generation", 0))
                except ActionRejected as error:
                    current.status = "rejected"
                    execution = session.scalar(select(ActionExecution).where(ActionExecution.request_id == request_id))
                    execution.completed_at, execution.outcome = self.clock(), "not_sent"
                    log(session, request_id, "automation_blocked_before_http", self.clock(), reason=str(error))
                    return request_id
        try:
            if action == "pause":
                await connector.pause_entity(external_id)
            elif action == "enable":
                await connector.enable_entity(external_id)
            else:
                await connector.change_budget(external_id, provider_payload=self.policy.budget_payload(value))
        except Exception as error:
            outcome, error_code = "unknown", type(error).__name__
            if isinstance(error, APIError) and error.status_code in (400, 401, 402, 403, 404, 422, 429):
                outcome = "rejected"
            if isinstance(error, RateLimitExceeded):
                reset = datetime.combine(self.clock().date() + timedelta(days=1), datetime.min.time(), self.clock().tzinfo)
                with self.sessions.begin() as session:
                    quota = session.get(ApiQuota, (workspace, "metricflow", self.clock().date()))
                    quota.blocked_until = reset
        with self.sessions.begin() as session:
            request = session.get(ActionRequest, request_id)
            request.status = "rejected" if outcome == "rejected" else "verifying"
            execution = session.scalar(select(ActionExecution).where(ActionExecution.request_id == request_id))
            execution.completed_at, execution.outcome, execution.error_code = self.clock(), outcome, error_code
            log(session, request_id, "provider_" + outcome, self.clock(), error_code=error_code)
        return request_id

    def verify_pending(self) -> int:
        """Verify against a newer current-state observation fetched by the read worker."""
        now, count = self.clock(), 0
        with self.sessions.begin() as session:
            requests = session.scalars(select(ActionRequest).where(
                ActionRequest.status.in_(("executing", "verifying", "unknown"))
            ).with_for_update(skip_locked=True)).all()
            for request in requests:
                execution = session.scalar(select(ActionExecution).where(ActionExecution.request_id == request.id))
                if not execution:
                    continue
                started = aware(execution.started_at)
                if request.status == "executing":
                    if (now - started).total_seconds() < 120:
                        continue
                    request.status, execution.outcome = "verifying", "unknown"
                    execution.completed_at = execution.started_at
                    log(session, request.id, "worker_recovery_no_resend", now)
                observed_after = aware(execution.completed_at or execution.started_at)
                state = session.get(EntityCurrentState, request.entity_id)
                verified = state is not None and aware(state.observed_at) > observed_after and (
                    (request.action == "pause" and state.status == "PAUSED") or
                    (request.action == "enable" and state.status == "ACTIVE") or
                    (request.action == "budget_set" and state.budget == request.value)
                )
                if verified:
                    request.status = "succeeded"
                    log(session, request.id, "verified", now, observed_status=state.status,
                        observed_budget=str(state.budget) if state.budget is not None else None)
                    count += 1
                elif (now - started).total_seconds() >= self.policy.verification_timeout_seconds and request.status != "unknown":
                    request.status = "unknown"
                    log(session, request.id, "verification_timeout", now)
        return count
