"""Durable single-step job observation for isolated MOCK_ONLY rehearsals."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.actions.engine import ActionEngine, ActionRejected, log
from services.actions.factory import (
    checked_write_state,
    create_action_connector,
    credential_digest,
)
from services.actions.manual import snapshot
from services.actions.safety import ActionSafetyGate
from services.actions.write_credentials import WriteCredentialVault
from services.metricflow.errors import RateLimitExceeded
from services.metricflow.writer import ActionJob
from services.storage.models import (
    ActionExecution,
    ActionRequest,
    AdAccount,
    ApiQuota,
    Entity,
)

MAX_ATTEMPTS = 6
INTERVAL_SECONDS = 10
TIMEOUT_SECONDS = 600
TERMINAL = {"JOB_SUCCESS_NEEDS_READBACK", "OUTCOME_UNKNOWN"}


def new_observation() -> dict:
    """Local conservative bounds, not provider quota or polling guarantees."""
    return {
        "version": 1,
        "max_attempts": MAX_ATTEMPTS,
        "interval_seconds": INTERVAL_SECONDS,
        "timeout_seconds": TIMEOUT_SECONDS,
        "attempts": 0,
        "state": "UNARMED",
        "deadline": None,
        "next_poll_at": None,
    }


def arm_observation(control: dict, now: datetime) -> None:
    """Bind observation to the accepted job and the original permit deadline."""
    observation = dict(control["observation"])
    deadline = min(
        datetime.fromisoformat(control["expires_at"]),
        datetime.fromisoformat(control["consumed_at"])
        + timedelta(seconds=TIMEOUT_SECONDS),
    )
    observation.update(
        job_id=control["job_id"],
        post_claim_id=control["claim_id"],
        state="READY",
        deadline=deadline.isoformat(),
        next_poll_at=(now + timedelta(seconds=INTERVAL_SECONDS)).isoformat(),
    )
    control["observation"] = observation


def _validate(observation: dict) -> None:
    expected = new_observation()
    if (
        any(
            type(observation.get(k)) is not int or observation[k] != expected[k]
            for k in ("version", "max_attempts", "interval_seconds", "timeout_seconds")
        )
        or type(observation.get("attempts")) is not int
        or not 0 <= observation["attempts"] <= MAX_ATTEMPTS
    ):
        raise ActionRejected("OBSERVATION_BOUNDS_INVALID")


def _binding(
    engine: ActionEngine,
    session: Session,
    row: ActionRequest,
    actor: dict,
    control: dict,
) -> None:
    entity = session.get(Entity, row.entity_id)
    account = session.get(AdAccount, entity.account_id) if entity else None
    binding = control.get("binding") or {}
    if (
        not entity
        or entity.kind != "ad"
        or not account
        or account.provider != "metricflow"
        or account.workspace_id != actor["workspace"]
        or row.value is not None
        or row.action not in ("PAUSE_AD", "ENABLE_AD")
        or control.get("attempts") != 1
        or not control.get("http_started")
        or not control.get("claim_id")
        or control["observation"].get("job_id") != control.get("job_id")
        or control["observation"].get("post_claim_id") != control.get("claim_id")
        or binding.get("workspace") != actor["workspace"]
        or binding.get("actor_id") != actor["id"]
        or binding.get("request_id") != row.id
        or binding.get("ad_id") != entity.id
        or binding.get("account_id") != account.id
        or binding.get("external_id") != entity.external_id
        or binding.get("action") != row.action
        or binding.get("confirmation_at") != row.provenance.get("confirmation_at")
        or row.provenance.get("confirmation_actor") != actor["id"]
    ):
        raise ActionRejected("OBSERVATION_BINDING_CHANGED")
    current = snapshot(session, entity, account)
    captured = binding.get("snapshot") or {}
    # A post-command status/timestamp can change legitimately. Identity/routing cannot.
    stable = (
        "entity_id",
        "meta_ad_id",
        "account_id",
        "meta_account_id",
        "canonical_account_id",
        "hierarchy",
        "provider",
        "credential_revision",
        "routing",
    )
    if (
        any(current[k] != captured.get(k) for k in stable)
        or not current["account_confirmed"]
        or not current["hierarchy_confirmed"]
    ):
        raise ActionRejected("OBSERVATION_BINDING_CHANGED")
    state = checked_write_state(
        session, actor["workspace"], control["credential_revision"], engine.clock()
    )
    if credential_digest(state) != control.get("credential_digest"):
        raise ActionRejected("OBSERVATION_CREDENTIAL_CHANGED")


def _save(
    session: Session,
    row: ActionRequest,
    control: dict,
    observation: dict,
    now: datetime,
    *,
    error: str | None = None,
    job: ActionJob | None = None,
) -> None:
    control["observation"] = observation
    if observation["state"] in TERMINAL:
        control["state"] = observation["state"]
        row.status = (
            "verifying"
            if observation["state"] == "JOB_SUCCESS_NEEDS_READBACK"
            else "unknown"
        )
    row.provenance = {**row.provenance, "controlled": control}
    row.revision += 1
    execution = session.scalar(
        select(ActionExecution).where(ActionExecution.request_id == row.id)
    )
    if execution and observation["state"] in TERMINAL:
        execution.outcome = (
            "mock_job_success_needs_readback"
            if row.status == "verifying"
            else "mock_job_unknown"
        )
        execution.completed_at, execution.error_code = now, error
    log(
        session,
        row.id,
        "controlled_mock_job_observation",
        now,
        mode="MOCK_ONLY",
        state=observation["state"],
        attempts=observation["attempts"],
        job_id=observation.get("job_id"),
        job_status=job.status if job else None,
        error_code=error,
    )


def recover_observation(
    session: Session,
    row: ActionRequest,
    _execution: ActionExecution | None,
    now: datetime,
) -> bool:
    """Existing recovery can close an expired observer without another HTTP call."""
    control = dict(row.provenance.get("controlled") or {})
    observation = dict(control.get("observation") or {})
    if (
        control.get("mode") != "MOCK_ONLY"
        or observation.get("state") not in ("READY", "IN_FLIGHT")
        or not observation.get("deadline")
        or now < datetime.fromisoformat(observation["deadline"])
    ):
        return False
    observation.update(state="OUTCOME_UNKNOWN", error_code="OBSERVATION_DEADLINE")
    _save(session, row, control, observation, now, error="OBSERVATION_DEADLINE")
    return True


async def observe_rehearsal_job(
    engine: ActionEngine,
    actor: dict,
    request_id: str,
    *,
    vault: WriteCredentialVault,
    transport: httpx.AsyncBaseTransport,
) -> str | None:
    """Consume at most one GET slot; never resend an action or certify readback."""
    if not isinstance(transport, httpx.MockTransport):
        raise ActionRejected("EXPLICIT_MOCK_TRANSPORT_REQUIRED")
    ActionSafetyGate.require_write()
    if not engine.policy.enabled:
        raise ActionRejected("ACTION_POLICY_DISABLED")
    now = engine.clock()
    with engine.sessions.begin() as session:
        row = engine._rehearsal_row(session, actor, request_id)
        control = dict(row.provenance.get("controlled") or {})
        observation = dict(control.get("observation") or {})
        if control.get("mode") != "MOCK_ONLY" or not observation:
            raise ActionRejected("MOCK_ONLY_OBSERVATION_REQUIRED")
        _validate(observation)
        if observation["state"] in TERMINAL or row.status != "verifying":
            return None
        if recover_observation(session, row, None, now):
            return request_id
        if observation["state"] == "IN_FLIGHT":
            return None  # Interrupted GET keeps its slot until deadline/recovery.
        if (
            observation["state"] != "READY"
            or type(control.get("job_id")) is not int
            or control["job_id"] < 1
        ):
            raise ActionRejected("ACKNOWLEDGED_JOB_REQUIRED")
        if now < datetime.fromisoformat(observation["next_poll_at"]):
            return None
        if observation["attempts"] >= MAX_ATTEMPTS:
            observation.update(
                state="OUTCOME_UNKNOWN", error_code="OBSERVATION_ATTEMPTS_EXHAUSTED"
            )
            _save(
                session, row, control, observation, now, error=observation["error_code"]
            )
            return request_id
        _binding(engine, session, row, actor, control)
        claim = str(uuid4())
        observation.update(
            attempts=observation["attempts"] + 1,
            state="IN_FLIGHT",
            claim_id=claim,
            http_started=False,
        )
        control["observation"] = observation
        row.provenance = {**row.provenance, "controlled": control}
        row.revision += 1
        log(
            session,
            row.id,
            "controlled_mock_job_slot_claimed",
            now,
            mode="MOCK_ONLY",
            attempts=observation["attempts"],
            claim_id=claim,
        )

    def final_guard():
        with engine.sessions.begin() as session:
            row = engine._rehearsal_row(session, actor, request_id)
            saved = dict(row.provenance["controlled"])
            observed = dict(saved["observation"])
            if (
                row.status != "verifying"
                or saved.get("job_id") != control["job_id"]
                or observed.get("claim_id") != claim
                or observed["state"] != "IN_FLIGHT"
                or observed.get("http_started")
                or engine.clock() >= datetime.fromisoformat(observed["deadline"])
            ):
                raise ActionRejected("OBSERVATION_FINAL_GUARD_HELD")
            _validate(observed)
            _binding(engine, session, row, actor, saved)
            observed["http_started"] = True
            saved["observation"] = observed
            row.provenance = {**row.provenance, "controlled": saved}

    async def before_http():
        await asyncio.to_thread(final_guard)

    job, error, retry_after = None, None, None
    try:
        engine.reserve_api_request(actor["workspace"])
        remaining = (
            datetime.fromisoformat(observation["deadline"]) - engine.clock()
        ).total_seconds()
        if remaining <= 0:
            raise ActionRejected("OBSERVATION_DEADLINE")
        async with asyncio.timeout(min(30.0, remaining)):
            async with create_action_connector(
                workspace=actor["workspace"],
                credential_revision=control["credential_revision"],
                session_factory=engine.sessions,
                vault=vault,
                transport=transport,
                before_request=before_http,
                clock=engine.clock,
            ) as connector:
                job = await connector.get_action_job(
                    control["job_id"], entity_id=control["binding"]["external_id"]
                )
    except Exception as caught:  # noqa: BLE001 - store only a sanitized class at this boundary
        error = type(caught).__name__
        if isinstance(caught, RateLimitExceeded):
            retry_after = min(caught.retry_after_seconds or 0, 7 * 86400)

    # Save an already-started GET even if permissions/credentials change mid-flight.
    with engine.sessions.begin() as session:
        row = session.scalar(
            select(ActionRequest)
            .where(ActionRequest.id == request_id)
            .with_for_update()
        )
        saved = dict(row.provenance["controlled"])
        observed = dict(saved["observation"])
        if retry_after is not None:
            now = engine.clock()
            next_day = now.replace(
                hour=0, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
            until = max(next_day, now + timedelta(seconds=retry_after))
            quota = session.scalar(
                select(ApiQuota)
                .where(
                    ApiQuota.workspace_id == actor["workspace"],
                    ApiQuota.provider == "metricflow",
                    ApiQuota.utc_day == now.date(),
                )
                .with_for_update()
            )
            if quota:
                from services.sync.engine import aware

                quota.blocked_until = (
                    max(until, aware(quota.blocked_until))
                    if quota.blocked_until
                    else until
                )
        if observed.get("claim_id") != claim:
            raise ActionRejected("OBSERVATION_CLAIM_CHANGED")
        # Recovery may have closed this attempt while its GET was in flight.
        if observed["state"] != "IN_FLIGHT":
            return request_id
        if (
            saved.get("job_id") != control["job_id"]
            or saved.get("claim_id") != control["claim_id"]
            or saved.get("binding") != control["binding"]
        ):
            job, error = None, "OBSERVATION_CORRELATION_CHANGED"
        observed.update(job_status=job.status if job else None, error_code=error)
        if (
            error
            or not job
            or engine.clock() >= datetime.fromisoformat(observed["deadline"])
        ):
            observed["state"] = "OUTCOME_UNKNOWN"
            error = error or "OBSERVATION_DEADLINE"
        elif job.status == "success":
            observed["state"] = "JOB_SUCCESS_NEEDS_READBACK"
        elif job.status in ("partial", "failed", "expired"):
            observed["state"] = "OUTCOME_UNKNOWN"
            error = "JOB_" + job.status.upper()
        elif observed["attempts"] >= MAX_ATTEMPTS:
            observed["state"] = "OUTCOME_UNKNOWN"
            error = "OBSERVATION_ATTEMPTS_EXHAUSTED"
        else:
            observed.update(
                state="READY",
                next_poll_at=(
                    engine.clock() + timedelta(seconds=INTERVAL_SECONDS)
                ).isoformat(),
            )
        observed["error_code"] = error
        _save(session, row, saved, observed, engine.clock(), error=error, job=job)
    return request_id
