"""One durable mock-only READ diagnostic after a correlated successful job."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.actions.engine import ActionEngine, ActionRejected, log
from services.actions.job_observation import _binding
from services.actions.safety import ActionSafetyGate
from services.metricflow.errors import RateLimitExceeded
from services.metricflow.readback import MAX_PAGES, collect_reported_status
from services.metricflow.reader import MetricFlowConnector
from services.storage.models import ActionExecution, ActionRequest, AdAccount, ApiQuota
from services.sync.engine import aware


def _finish(session, row, control, evidence, now):
    readback = {**control["readback"], **evidence, "state": "RECORDED"}
    control.update(state="MOCK_READBACK_RECORDED", readback=readback)
    # Even a reported match cannot certify the real command or pause ownership.
    row.status = "unknown"
    row.provenance = {**row.provenance, "controlled": control}
    row.revision += 1
    execution = session.scalar(
        select(ActionExecution).where(ActionExecution.request_id == row.id)
    )
    if execution:
        execution.outcome = "mock_readback_needs_authority"
        execution.completed_at = now
        execution.error_code = evidence.get("error_code")
    log(
        session,
        row.id,
        "controlled_mock_readback_recorded",
        now,
        mode="MOCK_ONLY",
        authoritative=False,
        **evidence,
    )


def recover_readback(session: Session, row: ActionRequest, now: datetime) -> bool:
    """Close interrupted READ after its original deadline without resending it."""
    control = dict(row.provenance.get("controlled") or {})
    readback = control.get("readback") or {}
    if (
        control.get("mode") != "MOCK_ONLY"
        or readback.get("state") != "IN_FLIGHT"
        or now < datetime.fromisoformat(readback["deadline"])
    ):
        return False
    _finish(
        session,
        row,
        control,
        {
            "outcome": "OUTCOME_UNKNOWN",
            "error_code": "READBACK_DEADLINE",
        },
        now,
    )
    return True


async def readback_rehearsal(
    engine: ActionEngine,
    actor: dict,
    request_id: str,
    *,
    read_key: str,
    transport: httpx.AsyncBaseTransport,
) -> str | None:
    """Use an explicit synthetic READ credential and transport in isolated fixtures.

    No vault fallback, production route, worker loop or LIVE permit is provided.
    A claim is single-use across restart, including crashes during pagination.
    """
    if not isinstance(transport, httpx.MockTransport):
        raise ActionRejected("EXPLICIT_MOCK_TRANSPORT_REQUIRED")
    ActionSafetyGate.require_write()
    if not engine.policy.enabled:
        raise ActionRejected("ACTION_POLICY_DISABLED")
    now = engine.clock()
    with engine.sessions.begin() as session:
        row = engine._rehearsal_row(session, actor, request_id)
        control = dict(row.provenance.get("controlled") or {})
        if control.get("mode") != "MOCK_ONLY":
            raise ActionRejected("MOCK_ONLY_READBACK_REQUIRED")
        if control.get("readback"):
            recover_readback(session, row, now)
            return None
        if (
            row.status != "verifying"
            or control.get("state") != "JOB_SUCCESS_NEEDS_READBACK"
            or control.get("observation", {}).get("state")
            != "JOB_SUCCESS_NEEDS_READBACK"
        ):
            raise ActionRejected("SUCCESSFUL_CORRELATED_JOB_REQUIRED")
        _binding(engine, session, row, actor, control)
        account = session.get(AdAccount, control["binding"]["account_id"])
        started = datetime.fromisoformat(control["consumed_at"])
        day = started.astimezone(ZoneInfo(account.timezone)).date()
        deadline = control["observation"]["deadline"]
        claim = str(uuid4())
        control["readback"] = {
            "version": 1,
            "state": "IN_FLIGHT",
            "claim_id": claim,
            "post_claim_id": control["claim_id"],
            "job_id": control["job_id"],
            "deadline": deadline,
            "max_pages": MAX_PAGES,
            "attempts": 0,
            "day": day.isoformat(),
            "timezone": account.timezone,
            "read_credential_revision": control["binding"]["snapshot"][
                "credential_revision"
            ],
            "authoritative": False,
        }
        row.provenance = {**row.provenance, "controlled": control}
        row.revision += 1
        log(
            session,
            row.id,
            "controlled_mock_readback_claimed",
            now,
            mode="MOCK_ONLY",
            claim_id=claim,
        )

    def guard():
        ActionSafetyGate.require_write()
        with engine.sessions.begin() as session:
            row = engine._rehearsal_row(session, actor, request_id)
            current = dict(row.provenance["controlled"])
            diagnostic = dict(current["readback"])
            if (
                row.status != "verifying"
                or current.get("state") != "JOB_SUCCESS_NEEDS_READBACK"
                or diagnostic.get("claim_id") != claim
                or diagnostic.get("state") != "IN_FLIGHT"
                or diagnostic.get("post_claim_id") != control["claim_id"]
                or diagnostic.get("job_id") != control["job_id"]
                or current.get("binding") != control["binding"]
                or diagnostic.get("max_pages") != MAX_PAGES
                or type(diagnostic.get("attempts")) is not int
                or not 0 <= diagnostic["attempts"] < MAX_PAGES
                or diagnostic.get("deadline") != deadline
                or engine.clock() >= datetime.fromisoformat(deadline)
            ):
                raise ActionRejected("READBACK_FINAL_GUARD_HELD")
            _binding(engine, session, row, actor, current)
            account = session.get(AdAccount, current["binding"]["account_id"])
            if account.timezone != control["readback"]["timezone"]:
                raise ActionRejected("READBACK_TIMEZONE_CHANGED")
            diagnostic["attempts"] += 1
            current["readback"] = diagnostic
            row.provenance = {**row.provenance, "controlled": current}
        engine.reserve_api_request(actor["workspace"])

    async def before_http():
        await asyncio.to_thread(guard)
        ActionSafetyGate.require_write()

    evidence, error, retry_after = {}, None, None
    binding = control["binding"]
    try:
        remaining = (datetime.fromisoformat(deadline) - engine.clock()).total_seconds()
        if remaining <= 0:
            raise ActionRejected("READBACK_DEADLINE")
        async with asyncio.timeout(min(30.0, remaining)):
            async with MetricFlowConnector(
                read_key,
                transport=transport,
                read_retries=0,
                before_request=before_http,
            ) as connector:
                result = await collect_reported_status(
                    connector,
                    account_id=binding["snapshot"]["meta_account_id"],
                    ad_id=binding["external_id"],
                    adset_id=binding["snapshot"]["hierarchy"][0],
                    campaign_id=binding["snapshot"]["hierarchy"][1],
                    day=day,
                    operation=binding["action"],
                    command_started_at=started,
                    now=engine.clock(),
                )
                evidence = asdict(result)
                evidence.pop("authoritative")
    except Exception as caught:  # noqa: BLE001 - never store raw provider errors or keys
        error = type(caught).__name__
        if isinstance(caught, RateLimitExceeded):
            retry_after = min(caught.retry_after_seconds or 0, 7 * 86400)

    with engine.sessions.begin() as session:
        row = session.scalar(
            select(ActionRequest)
            .where(ActionRequest.id == request_id)
            .with_for_update()
        )
        current = dict(row.provenance["controlled"])
        diagnostic = current["readback"]
        if diagnostic.get("claim_id") != claim:
            raise ActionRejected("READBACK_CLAIM_CHANGED")
        if diagnostic.get("state") != "IN_FLIGHT":
            return request_id
        if (
            current.get("binding") != binding
            or current.get("claim_id") != control["claim_id"]
            or current.get("job_id") != control["job_id"]
        ):
            error = "READBACK_CORRELATION_CHANGED"
        if engine.clock() >= datetime.fromisoformat(deadline):
            error = "READBACK_DEADLINE"
        if retry_after is not None:
            now = engine.clock()
            until = max(
                now.replace(hour=0, minute=0, second=0, microsecond=0)
                + timedelta(days=1),
                now + timedelta(seconds=retry_after),
            )
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
                quota.blocked_until = (
                    max(until, aware(quota.blocked_until))
                    if quota.blocked_until
                    else until
                )
        if error:
            evidence = {"outcome": "OUTCOME_UNKNOWN", "error_code": error}
        _finish(session, row, current, evidence, engine.clock())
    return request_id
