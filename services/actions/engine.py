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


CONTROLLED_POST_TIMEOUT_SECONDS = 30.0


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
    def prepare_manual(self, actor, command, key):
        from .manual import prepare

        return prepare(self, actor, command, key)

    def transition_manual(self, actor, request_id, event, revision):
        from .manual import transition

        return transition(self, actor, request_id, event, revision)

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
            if blocked:
                raise ActionRejected("API quota exhausted")
            reserved = session.execute(update(ApiQuota).where(
                ApiQuota.workspace_id == workspace, ApiQuota.provider == "metricflow", ApiQuota.utc_day == now.date(),
                ApiQuota.requests < self.policy.daily_api_budget,
                or_(ApiQuota.blocked_until.is_(None), ApiQuota.blocked_until <= now),
            ).values(requests=ApiQuota.requests + 1))
            if reserved.rowcount != 1:
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
                from .safety import ActionSafetyGate
                from services.providers.contracts import WriteDisabled
                try:
                    ActionSafetyGate.require_write()
                except WriteDisabled as error:
                    raise ActionRejected(error.code) from error
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
            from .safety import ActionSafetyGate
            ActionSafetyGate.require_write()
            if action == "pause":
                await connector.pause_entity(external_id)
            elif action == "enable":
                await connector.enable_entity(external_id)
            else:
                await connector.change_budget(external_id, provider_payload=self.policy.budget_payload(value))
        except Exception as error:
            outcome, error_code = "unknown", type(error).__name__
            from services.providers.contracts import WriteDisabled
            if isinstance(error, WriteDisabled):
                outcome, error_code = "rejected", "WRITE_DISABLED"
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

    def _rehearsal_row(self, session, actor: dict, request_id: str):
        """Use the manual lock order; never admit the working DB/workspace."""
        url = session.bind.url
        isolated = session.bind.dialect.name == "sqlite" or (
            session.bind.dialect.name == "postgresql"
            and (url.database or "").startswith("mcc_integrations_")
        )
        if not isolated or not actor["workspace"].startswith("write-rehearsal-"):
            raise ActionRejected("ISOLATED_REHEARSAL_REQUIRED")
        return self._locked_manual_row(session, actor, request_id)

    def _locked_manual_row(self, session, actor: dict, request_id: str):
        from services.actions.manual import require_permission
        from services.economics.store import lock

        lock(session, actor["workspace"])
        require_permission(session, actor)
        entity_id = session.scalar(
            select(ActionRequest.entity_id).where(
                ActionRequest.id == request_id,
                ActionRequest.workspace_id == actor["workspace"],
            )
        )
        if not entity_id:
            raise ActionRejected("REHEARSAL_REQUEST_NOT_FOUND")
        session.scalar(select(Entity).where(Entity.id == entity_id).with_for_update())
        row = session.scalar(
            select(ActionRequest)
            .where(ActionRequest.id == request_id)
            .with_for_update()
        )
        if row.initiator_id != actor["id"]:
            raise ActionRejected("REHEARSAL_ACTOR_MISMATCH")
        if row.provenance.get("phase") != "4A":
            raise ActionRejected("CONFIRMED_MANUAL_REHEARSAL_REQUIRED")
        return row

    def _controlled_row(self, session, actor: dict, request_id: str, mode: str, contract=None):
        if mode == "MOCK_ONLY":
            if contract is not None:
                raise ActionRejected("CONTROLLED_CONTRACT_MODE_MISMATCH")
            return self._rehearsal_row(session, actor, request_id)
        if mode != "LIVE_SINGLE_OPERATION":
            raise ActionRejected("CONTROLLED_MODE_INVALID")
        from services.actions.pilot import require_ready
        from services.actions.safety import ActionSafetyGate

        ActionSafetyGate.require_write(contract)
        row = self._locked_manual_row(session, actor, request_id)
        require_ready(session, actor, row, self.clock(), contract)
        return row

    def _rehearsal_binding(
        self, session, row, actor: dict, *, asynchronous: bool = True
    ) -> dict:
        from services.actions.manual import preflight, snapshot
        from services.actions.manual_schema import STATUS_OPERATIONS

        entity = session.get(Entity, row.entity_id)
        account = session.get(AdAccount, entity.account_id) if entity else None
        if (
            not entity
            or STATUS_OPERATIONS.get(row.action) != entity.kind
            or (asynchronous and entity.kind != "ad")
            or not account
            or account.provider != "metricflow"
            or account.workspace_id != actor["workspace"]
            or row.value is not None
        ):
            raise ActionRejected("SINGLE_METRICFLOW_AD_REQUIRED")
        if not preflight(self, session, row, actor, self.clock())["local_allowed"]:
            raise ActionRejected("REHEARSAL_PREFLIGHT_HELD")
        if row.provenance.get("confirmation_actor") != actor["id"]:
            raise ActionRejected("LOCAL_CONFIRMATION_REQUIRED")
        binding = {
            "workspace": actor["workspace"],
            "actor_id": actor["id"],
            "request_id": row.id,
            "account_id": account.id,
            "ad_id": entity.id,
            "external_id": entity.external_id,
            "action": row.action,
            "confirmation_at": row.provenance.get("confirmation_at"),
            "snapshot": snapshot(session, entity, account),
        }
        if not asynchronous:
            binding.update(
                entity_id=entity.id, entity_level=entity.kind, response_mode="SYNC_200"
            )
        return binding

    def prepare_rehearsal(
        self,
        actor: dict,
        request_id: str,
        revision: int,
        credential_revision: int,
        expires_at: datetime,
        *,
        asynchronous: bool = True,
    ) -> dict:
        """Prepare a MOCK_ONLY single-object permit in an isolated fixture namespace.

        A local manual confirmation is not LIVE authorization. No public endpoint,
        worker dispatch or working-database permit creation is provided here.
        """
        return self._prepare_controlled(
            actor, request_id, revision, credential_revision, expires_at,
            asynchronous=asynchronous, mode="MOCK_ONLY",
        )

    def _prepare_controlled(
        self, actor, request_id, revision, credential_revision, expires_at,
        *, asynchronous: bool, mode: str, authorization: dict | None = None, contract=None,
    ) -> dict:
        from services.actions.factory import checked_write_state, credential_digest
        from services.actions.job_observation import new_observation

        now = self.clock()
        if (
            type(revision) is not int
            or revision < 1
            or type(asynchronous) is not bool
            or not isinstance(expires_at, datetime)
            or expires_at.tzinfo is None
            or not now < expires_at <= now + timedelta(minutes=10)
        ):
            raise ActionRejected("INVALID_REHEARSAL_WINDOW_OR_REVISION")
        with self.sessions.begin() as session:
            row = self._controlled_row(session, actor, request_id, mode, contract)
            if row.status != "CONFIRMED" or row.revision != revision:
                raise ActionRejected("CONFIRMED_REVISION_REQUIRED")
            if row.provenance.get("controlled"):
                raise ActionRejected("REHEARSAL_ALREADY_PREPARED")
            if mode == "LIVE_SINGLE_OPERATION":
                from services.actions.manual import IN_FLIGHT
                from services.actions.pilot import require_ready

                others = session.scalars(select(ActionRequest).where(
                    ActionRequest.workspace_id == actor["workspace"],
                    ActionRequest.id != row.id,
                    ActionRequest.status.in_(("CONFIRMED", *IN_FLIGHT)),
                )).all()
                for other in others:
                    other_mode = (other.provenance.get("controlled") or {}).get("mode")
                    if other_mode == "MOCK_ONLY":
                        continue  # Isolated synthetic rehearsals cannot dispatch LIVE.
                    if other.status in IN_FLIGHT or other_mode == mode:
                        raise ActionRejected("PILOT_WORKSPACE_CONFLICT")
                evidence_id = require_ready(session, actor, row, now, contract)
            if expires_at > datetime.fromisoformat(row.provenance["expires_at"]):
                raise ActionRejected("REHEARSAL_EXCEEDS_DRAFT_WINDOW")
            state = checked_write_state(
                session, actor["workspace"], credential_revision, now
            )
            control = {
                "mode": mode,
                "observation": new_observation(),
                "state": "PREPARED",
                "attempts": 0,
                "expires_at": expires_at.isoformat(),
                "job_id": None,
                "credential_revision": credential_revision,
                "credential_digest": credential_digest(state),
                "binding": self._rehearsal_binding(
                    session, row, actor, asynchronous=asynchronous
                ),
            }
            if not asynchronous:
                control["response_mode"] = "SYNC_200"
                control["observation"] = {
                    **control["observation"], "state": "NOT_APPLICABLE"
                }
            if mode == "LIVE_SINGLE_OPERATION":
                from services.actions.pilot import bind_authorization

                if asynchronous or not self.policy.enabled:
                    raise ActionRejected("SYNCHRONOUS_ENABLED_PILOT_REQUIRED")
                if contract is not None:
                    control["provider_contract"] = contract.pin()
                control["evidence_id"] = evidence_id
                control["authorization"] = bind_authorization(
                    authorization, control["binding"], actor, now,
                    revision, credential_revision,
                )
            row.provenance = {**row.provenance, "controlled": control}
            row.revision += 1
            log(
                session,
                row.id,
                "controlled_live_authorized" if mode == "LIVE_SINGLE_OPERATION" else "controlled_mock_prepared",
                now,
                actor_id=actor["id"],
                credential_revision=credential_revision,
                expires_at=control["expires_at"],
                max_attempts=1,
                mode=mode,
            )
            return {
                "id": row.id,
                "revision": row.revision,
                "mode": mode,
                "expires_at": control["expires_at"],
                "max_attempts": 1,
            }

    async def execute_rehearsal(
        self, actor: dict, request_id: str, revision: int, *, vault, transport
    ) -> str | None:
        """Spend one durable permit before one MockTransport POST; never resend."""
        return await self._execute_controlled(
            actor, request_id, revision, vault=vault, transport=transport, mode="MOCK_ONLY"
        )

    async def _execute_controlled(
        self, actor, request_id, revision, *, vault, transport, mode: str, contract=None
    ) -> str | None:
        import asyncio

        import httpx
        from fastapi import HTTPException

        from services.actions.factory import (
            checked_write_state,
            create_action_connector,
            credential_digest,
        )
        from services.actions.safety import ActionSafetyGate
        from services.actions.write_credentials import WriteCredentialError
        from services.metricflow.errors import MetricFlowError
        from services.providers.contracts import WriteDisabled

        if mode not in ("MOCK_ONLY", "LIVE_SINGLE_OPERATION"):
            raise ActionRejected("CONTROLLED_MODE_INVALID")
        label = "live" if mode == "LIVE_SINGLE_OPERATION" else "mock"
        if mode == "MOCK_ONLY" and not isinstance(transport, httpx.MockTransport):
            raise ActionRejected("EXPLICIT_MOCK_TRANSPORT_REQUIRED")
        ActionSafetyGate.require_write(contract)
        if not self.policy.enabled:
            raise ActionRejected("ACTION_POLICY_DISABLED")
        if type(revision) is not int or revision < 1:
            raise ActionRejected("INVALID_ACTION_REVISION")
        now = self.clock()
        with self.sessions.begin() as session:
            row = self._controlled_row(session, actor, request_id, mode, contract)
            control = dict(row.provenance.get("controlled") or {})
            if control.get("mode") != mode:
                raise ActionRejected("CONTROLLED_PERMIT_MODE_MISMATCH")
            response_mode = control.get("response_mode", "ASYNC_JOB")
            if response_mode not in ("ASYNC_JOB", "SYNC_200"):
                raise ActionRejected("REHEARSAL_RESPONSE_MODE_INVALID")
            asynchronous = response_mode == "ASYNC_JOB"
            if mode == "LIVE_SINGLE_OPERATION" and asynchronous:
                raise ActionRejected("SYNCHRONOUS_PILOT_REQUIRED")
            if control.get("attempts") or row.status != "CONFIRMED":
                return None
            if row.revision != revision:
                raise ActionRejected("ACTION_REVISION_CONFLICT")
            if now >= datetime.fromisoformat(control["expires_at"]):
                raise ActionRejected("REHEARSAL_PERMIT_EXPIRED")
            if control["binding"] != self._rehearsal_binding(
                session, row, actor, asynchronous=asynchronous
            ):
                raise ActionRejected("REHEARSAL_BINDING_CHANGED")
            if mode == "LIVE_SINGLE_OPERATION":
                from services.actions.pilot import check_authorization

                check_authorization(control, actor)
            state = checked_write_state(
                session, actor["workspace"], control["credential_revision"], now
            )
            if credential_digest(state) != control["credential_digest"]:
                raise ActionRejected("REHEARSAL_CREDENTIAL_CHANGED")
            claim_id = str(uuid4())
            control.update(
                attempts=1,
                state="CLAIMED",
                claim_id=claim_id,
                consumed_at=now.isoformat(),
                http_started=False,
            )
            row.provenance = {**row.provenance, "controlled": control}
            row.status, row.revision = "executing", row.revision + 1
            session.add(
                ActionExecution(
                    id=str(uuid4()),
                    request_id=row.id,
                    started_at=now,
                    outcome=label + "_started",
                )
            )
            log(
                session,
                row.id,
                "controlled_" + label + "_attempt_claimed",
                now,
                claim_id=claim_id,
                mode=mode,
                max_attempts=1,
            )

        # The claim and unique ActionExecution are committed before opening a vault.
        def guard_before_http():
            with self.sessions.begin() as session:
                current = self._controlled_row(session, actor, request_id, mode, contract)
                permit = dict(current.provenance["controlled"])
                if (
                    current.status != "executing"
                    or permit.get("claim_id") != claim_id
                    or permit.get("mode") != mode
                    or permit.get("authorization") != control.get("authorization")
                    or permit.get("http_started")
                    or permit.get("response_mode", "ASYNC_JOB") != response_mode
                    or self.clock() >= datetime.fromisoformat(permit["expires_at"])
                    or permit["binding"]
                    != self._rehearsal_binding(
                        session, current, actor, asynchronous=asynchronous
                    )
                ):
                    raise ActionRejected("REHEARSAL_FINAL_GUARD_HELD")
                permit["http_started"] = True
                current.provenance = {**current.provenance, "controlled": permit}
                log(
                    session,
                    current.id,
                    "controlled_" + label + "_http_reserved",
                    self.clock(),
                    claim_id=claim_id,
                )

        async def before_http():
            await asyncio.to_thread(guard_before_http)

        result, error, unexpected = None, None, False
        post_timeout = None
        try:
            self.reserve_api_request(actor["workspace"])
            remaining = (
                datetime.fromisoformat(control["expires_at"]) - self.clock()
            ).total_seconds()
            if remaining <= 0:
                raise ActionRejected("REHEARSAL_PERMIT_EXPIRED")
            async with asyncio.timeout(
                min(CONTROLLED_POST_TIMEOUT_SECONDS, remaining)
            ) as post_timeout:
                async with create_action_connector(
                    workspace=actor["workspace"],
                    credential_revision=control["credential_revision"],
                    session_factory=self.sessions,
                    vault=vault,
                    transport=transport,
                    before_request=before_http,
                    clock=self.clock,
                    contract=contract,
                ) as connector:
                    operation = (
                        connector.pause_entity
                        if control["binding"]["action"].startswith("PAUSE_")
                        else connector.enable_entity
                    )
                    result = await operation(
                        control["binding"]["external_id"],
                        asynchronous=asynchronous,
                        level=control["binding"].get("entity_level", "ad"),
                    )
        except Exception as caught:  # noqa: BLE001 - sanitize every unknown boundary error
            error = type(
                caught
            ).__name__  # Never store upstream bodies/credential inputs.
            if mode == "LIVE_SINGLE_OPERATION" and isinstance(caught, RateLimitExceeded):
                from services.providers.manager import ProviderManager

                ProviderManager(self.sessions, actor["workspace"]).failure(
                    "metricflow", caught, revision=-1
                )
            if not isinstance(
                caught,
                (
                    ActionRejected,
                    WriteCredentialError,
                    MetricFlowError,
                    WriteDisabled,
                    HTTPException,
                    TimeoutError,
                ),
            ):
                unexpected = True
        # Recording an already-started outcome must survive permission revocation,
        # credential rotation and expiry. They cannot recall an in-flight command.
        with self.sessions.begin() as session:
            row = session.scalar(
                select(ActionRequest)
                .where(ActionRequest.id == request_id)
                .with_for_update()
            )
            saved = dict(row.provenance["controlled"])
            if saved.get("claim_id") != claim_id:
                raise ActionRejected("REHEARSAL_CLAIM_CHANGED")
            # A late ACK is correlation evidence, never permission to reopen a
            # closed attempt or start observation after the original deadline.
            closed = row.status != "executing" or saved.get("state") != "CLAIMED"
            if result and not error:
                if (
                    self.clock() >= datetime.fromisoformat(saved["expires_at"])
                    or (post_timeout is not None and post_timeout.expired())
                ):
                    error = "POST_DEADLINE"
                elif closed:
                    error = "POST_OUTCOME_ALREADY_CLOSED"
            acknowledged = bool(result and not error and not closed)
            saved.update(
                state=(
                    (
                        "ACKNOWLEDGED_NEEDS_READBACK"
                        if asynchronous
                        else "SYNC_ACKNOWLEDGED_NEEDS_MANUAL_READBACK"
                    )
                    if acknowledged else "OUTCOME_UNKNOWN"
                ),
                job_id=result["job_id"] if result else saved.get("job_id"),
            )
            if acknowledged and asynchronous:
                from services.actions.job_observation import arm_observation

                arm_observation(saved, self.clock())
            row.provenance = {**row.provenance, "controlled": saved}
            row.status, row.revision = (
                ("verifying" if acknowledged else "unknown"),
                row.revision + 1,
            )
            execution = session.scalar(
                select(ActionExecution).where(ActionExecution.request_id == request_id)
            )
            execution.completed_at = self.clock()
            execution.outcome, execution.error_code = (
                (label + "_acknowledged" if acknowledged else label + "_unknown"),
                error,
            )
            log(
                session,
                row.id,
                "controlled_" + label + ("_acknowledged" if acknowledged else "_unknown"),
                self.clock(),
                claim_id=claim_id,
                job_id=saved["job_id"],
                error_code=error,
                mode=mode,
            )
        if unexpected:
            raise ActionRejected("REHEARSAL_INTERNAL_ERROR_RECONCILE") from None
        return request_id

    async def observe_rehearsal_job(
        self, actor: dict, request_id: str, *, vault: Any, transport: Any
    ) -> str | None:
        """One durable mock GET step; no route, scheduler, or LIVE authorization."""
        from services.actions.job_observation import observe_rehearsal_job

        return await observe_rehearsal_job(
            self, actor, request_id, vault=vault, transport=transport
        )

    async def readback_rehearsal(
        self, actor: dict, request_id: str, *, read_key: str, transport: Any
    ) -> str | None:
        """Bounded mock READ diagnostic; never certifies LIVE ownership."""
        from services.actions.readback import readback_rehearsal

        return await readback_rehearsal(
            self, actor, request_id, read_key=read_key, transport=transport
        )

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
                controlled = dict(request.provenance.get("controlled") or {})
                if controlled:
                    label = "live" if controlled.get("mode") == "LIVE_SINGLE_OPERATION" else "mock"
                    from services.actions.job_observation import recover_observation
                    from services.actions.readback import recover_readback

                    # Synchronous ACK is not authoritative state evidence. No job
                    # observer or legacy status match may certify it as succeeded.
                    if (
                        controlled.get("response_mode") == "SYNC_200"
                        and controlled.get("state") == "SYNC_ACKNOWLEDGED_NEEDS_MANUAL_READBACK"
                        and now >= datetime.fromisoformat(controlled["expires_at"])
                    ):
                        controlled["state"] = "OUTCOME_UNKNOWN"
                        request.provenance = {**request.provenance, "controlled": controlled}
                        request.status, request.revision = "unknown", request.revision + 1
                        execution.outcome, execution.error_code = (
                            label + "_unknown", "MANUAL_READBACK_DEADLINE"
                        )
                        log(
                            session, request.id, "controlled_" + label + "_manual_readback_expired",
                            now, claim_id=controlled.get("claim_id"), mode=controlled.get("mode")
                        )
                        continue

                    if recover_readback(session, request, now):
                        continue

                    if recover_observation(session, request, execution, now):
                        continue
                    # Rehearsal acknowledgements cannot become LIVE ownership
                    # evidence through the legacy effective-status reconciler.
                    if request.status == "executing" and (now - started).total_seconds() >= 120:
                        controlled["state"] = "OUTCOME_UNKNOWN"
                        request.provenance = {**request.provenance, "controlled": controlled}
                        request.status, execution.outcome = "unknown", label + "_unknown"
                        execution.completed_at, execution.error_code = now, "PROCESS_INTERRUPTED"
                        log(session, request.id, "controlled_" + label + "_recovery_no_resend", now,
                            claim_id=controlled.get("claim_id"), mode=controlled.get("mode"))
                    continue
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
