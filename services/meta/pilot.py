"""One approved READ session on the existing job queue. Saving never authorizes LIVE."""

from __future__ import annotations

import os
from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.meta.pilot_models import MetaPilotSession
from services.meta.provider import account_id
from services.meta.telemetry import lock
from services.providers.contracts import ProviderError
from services.providers.models import (
    ProviderConnection,
    ProviderCredential,
    ProviderJob,
)
from services.storage.models import AdAccount
from services.sync.engine import aware, utc_now

ACTIVE = ("QUEUED", "RUNNING")


def enabled() -> bool:
    return os.environ.get("META_CONTROLLED_READ_PILOT", "false").lower() == "true"


def safe_flags() -> bool:
    return all(
        os.environ.get(k, default).lower() == expected
        for k, default, expected in (
            ("ACTIONS_ENABLED", "false", "false"),
            ("LOCAL_READ_ONLY", "false", "true"),
            ("AI_ENABLED", "false", "false"),
            ("AI_AUTOPILOT_ALLOWED", "false", "false"),
        )
    )


def prepared(
    session: Session,
    workspace: str,
    account: str,
    start: date,
    end: date,
    maximum: int = 20,
    timeout: int = 600,
) -> MetaPilotSession:
    if not enabled() or not safe_flags():
        raise ProviderError("META_PILOT_MODE_REQUIRED")
    if start > end or (end - start).days > 2 or end > utc_now().date():
        raise ProviderError("META_PILOT_WINDOW_1_TO_3_DAYS")
    if not 1 <= maximum <= 20 or not 30 <= timeout <= 900:
        raise ProviderError("META_PILOT_INVALID_LIMIT")
    identifier = account_id(account)
    lock(session, "meta-jobs:" + workspace)
    if session.scalar(
        select(MetaPilotSession.id).where(
            MetaPilotSession.workspace_id == workspace,
            MetaPilotSession.status.in_(ACTIVE),
        )
    ):
        raise ProviderError("META_PILOT_ALREADY_RUNNING")
    c = session.get(ProviderConnection, (workspace, "meta"))
    if not c:
        raise ProviderError("META_NOT_CONNECTED")
    row = MetaPilotSession(
        id=str(uuid4()),
        workspace_id=workspace,
        account_id=identifier,
        start_day=start,
        end_day=end,
        max_attempts=maximum,
        used_attempts=0,
        timeout_seconds=timeout,
        status="PREPARED",
        created_at=utc_now(),
        credential_revision=c.revision,
        result={},
    )
    session.add(row)
    session.flush()
    return row


def authorization(
    session: Session, workspace: str, identifier: str
) -> MetaPilotSession:
    row = session.get(MetaPilotSession, identifier)
    if not enabled() or not safe_flags() or not row or row.workspace_id != workspace:
        raise ProviderError("META_PILOT_NOT_AUTHORIZED")
    # Deployment-owned, session-specific gate; no API can change it.
    if os.environ.get("META_PILOT_AUTHORIZED_SESSION_ID", "") != identifier:
        raise ProviderError("META_PILOT_APPROVAL_REQUIRED")
    c = session.get(ProviderConnection, (workspace, "meta"))
    if not c or c.revision != row.credential_revision:
        raise ProviderError("META_PILOT_CREDENTIAL_CHANGED")
    version = c.config.get("graph_version")
    if (
        not version
        or os.environ.get("META_PILOT_CONFIRMED_GRAPH_VERSION", "") != version
    ):
        raise ProviderError("META_PILOT_GRAPH_VERSION_UNCONFIRMED")
    if not session.get(ProviderCredential, (workspace, "meta")):
        raise ProviderError("META_NOT_CONNECTED")
    return row


def start(
    session: Session, workspace: str, identifier: str, actor: str
) -> MetaPilotSession:
    from services.meta.jobs import audit, configuration, digest, option

    lock(session, "meta-jobs:" + workspace)
    row = authorization(session, workspace, identifier)
    if row.status != "PREPARED":
        raise ProviderError("META_PILOT_NOT_PREPARED")
    if session.scalar(
        select(ProviderJob.id).where(
            ProviderJob.workspace_id == workspace,
            ProviderJob.provider == "meta",
            ProviderJob.status.in_(("queued", "running")),
        )
    ):
        raise ProviderError("META_PILOT_EXISTING_JOBS_HELD")
    c = session.get(ProviderConnection, (workspace, "meta"))
    row.deadline = utc_now() + timedelta(seconds=row.timeout_seconds)
    job = ProviderJob(
        id=str(uuid4()),
        workspace_id=workspace,
        provider="meta",
        kind="sync",
        purpose="pilot",
        start_day=row.start_day,
        end_day=row.end_day,
        status="queued",
        created_at=utc_now(),
        expires_at=row.deadline,
        dedup_key="pilot:" + row.id,
        active_key=digest(["pilot", workspace]),
        account_scope=[row.account_id],
        request_params={"pilot_session_id": row.id},
        config_revision=c.revision,
        config_hash=configuration(c),
        timezone=os.environ.get("SYNC_TIMEZONE", "Europe/Moscow"),
        slot=row.id,
        cancel_requested=False,
        recoveries=0,
    )
    if session.scalar(
        select(func.count())
        .select_from(ProviderJob)
        .where(
            ProviderJob.workspace_id == workspace,
            ProviderJob.provider == "meta",
            ProviderJob.status.in_(("queued", "running")),
        )
    ) >= option("META_JOB_QUEUE_LIMIT", 20, 1, 1000):
        raise ProviderError("META_JOB_QUEUE_FULL")
    session.add(job)
    session.flush()
    row.job_id = job.id
    row.status = "QUEUED"
    audit(session, job, "QUEUED", "PILOT_EXPLICIT_SESSION_APPROVAL", actor)
    return row


def guard(session: Session, workspace: str, identifier: str) -> MetaPilotSession:
    row = authorization(session, workspace, identifier)
    if row.status not in ACTIVE:
        raise ProviderError("META_PILOT_STOPPED")
    if not row.deadline or aware(row.deadline) <= utc_now():
        raise ProviderError("META_PILOT_TIMEOUT")
    job = session.get(ProviderJob, row.job_id)
    if not job or job.status != "running" or job.cancel_requested:
        raise ProviderError("META_PILOT_CANCELLED")
    if row.used_attempts >= row.max_attempts:
        raise ProviderError("META_PILOT_ATTEMPT_LIMIT")
    return row


def reserve_attempt(
    session: Session, workspace: str, identifier: str, path: str
) -> None:
    lock(session, "meta-jobs:" + workspace)
    row = guard(session, workspace, identifier)
    allowed = {"debug_token", "me/permissions", row.account_id}
    allowed.update(
        row.account_id + "/" + edge
        for edge in ("campaigns", "adsets", "ads", "adcreatives", "insights")
    )
    if path not in allowed:
        raise ProviderError("META_PILOT_ACCOUNT_BINDING")
    row.used_attempts += 1  # Same transaction as HTTP-attempt journal insertion.


def stop(session: Session, workspace: str, identifier: str) -> MetaPilotSession:
    from services.meta.jobs import cancel

    lock(session, "meta-jobs:" + workspace)
    row = session.get(MetaPilotSession, identifier)
    if not row or row.workspace_id != workspace:
        raise ProviderError("META_PILOT_NOT_FOUND")
    if row.status in ACTIVE and row.job_id:
        cancel(session, workspace, row.job_id, reason="JOB_PILOT_USER_CANCELLED")
    if row.status in ACTIVE or row.status == "PREPARED":
        row.status = "CANCELLED"
        row.reason = "META_PILOT_USER_CANCELLED"
        row.finished_at = utc_now()
    return row


def metadata(session: Session, workspace: str) -> dict:
    from services.meta.diagnostics import report

    row = session.scalar(
        select(MetaPilotSession)
        .where(MetaPilotSession.workspace_id == workspace)
        .order_by(MetaPilotSession.created_at.desc())
        .limit(1)
    )
    c = session.get(ProviderConnection, (workspace, "meta"))
    usage = report(session, workspace)
    return {
        "mode": enabled(),
        "scheduler": "HELD" if enabled() else "STANDARD",
        "credentials_present": bool(
            session.get(ProviderCredential, (workspace, "meta"))
        ),
        "graph_version": c.config.get("graph_version") if c else None,
        "access_tier": usage.get("access_tier"),
        "cooldown_until": usage.get("cooldown_until"),
        "minimum_attempts": 8,
        "live_approval_required": True,
        "session": None
        if not row
        else {
            "id": row.id,
            "account_id": row.account_id,
            "start": str(row.start_day),
            "end": str(row.end_day),
            "max_attempts": row.max_attempts,
            "used_attempts": row.used_attempts,
            "timeout_seconds": row.timeout_seconds,
            "status": row.status,
            "reason": row.reason,
            "result": row.result,
            "deadline": row.deadline.isoformat() if row.deadline else None,
        },
    }


async def run(manager, identifier: str) -> dict:
    """Execute only a separately approved session. Never enable standard Meta."""
    client = None
    reason = None
    result = {}
    with manager.factory.begin() as s:
        row = guard(s, manager.workspace, identifier)
        row.status = "RUNNING"
        account, start_day, end_day = row.account_id, row.start_day, row.end_day
        selected = s.scalar(
            select(AdAccount).where(
                AdAccount.workspace_id == manager.workspace,
                AdAccount.provider == "meta",
                AdAccount.external_id == account,
            )
        )
        expected_timezone = selected.timezone if selected else None

    def progress(stage: str) -> None:
        # Safe booleans/counts only; never raw token, account payload or URLs.
        result["stage"] = stage
        result["facts_published"] = False
        with manager.factory.begin() as session:
            current = session.get(MetaPilotSession, identifier)
            if current and current.status in ACTIVE:
                current.result = dict(result)

    try:
        manager.pilot_id = identifier
        client = manager.create(
            "meta", operation="controlled_read_pilot", source="pilot:" + identifier
        )
        # Bounded edge materialization; session-wide 20-attempt budget is stronger.
        client.client.max_pages = 20
        client.client.max_rows = 2000
        progress("TOKEN_AND_PERMISSIONS")
        permissions = await client.client.verify_token()
        result.update(
            token_verified=permissions["token_verified"],
            permissions_read=permissions["read"],
        )
        progress("ACCOUNT")
        raw = await client.client.get(
            account,
            {"fields": "id,account_id,name,account_status,currency,timezone_name"},
        )
        if (
            account_id(raw.get("id")) != account
            or account_id(raw.get("account_id")) != account
        ):
            raise ProviderError("META_PILOT_ACCOUNT_BINDING")
        if raw.get("account_status") != 1:
            raise ProviderError("META_PILOT_ACCOUNT_NOT_ACTIVE")
        if expected_timezone and raw.get("timezone_name") != expected_timezone:
            raise ProviderError("META_PILOT_ACCOUNT_TIMEZONE_CHANGED")
        result["account_verified"] = True
        catalogs = {}
        result["catalog_rows"] = {}
        for kind in ("campaign", "adset", "ad", "creative"):
            progress("CATALOG_" + kind.upper())
            catalogs[kind] = await client._catalog(account, kind)
            result["catalog_rows"] = {k: len(v) for k, v in catalogs.items()}
            progress("CATALOG_" + kind.upper() + "_COMPLETE")
        progress("INSIGHTS")
        insights = await client.get_insights(account, start_day, end_day)
        result["insights_response_rows"] = len(insights["data"])
        progress("VALIDATE_INSIGHTS")
        # Validate fully; pilot is evidence-only, never replaces production facts.
        from services.meta.mapper import map_rows

        mapped = map_rows(
            insights["data"], raw, catalogs, start_day, end_day, insights["attribution"]
        )
        result = {
            "token_verified": permissions["token_verified"],
            "stage": "COMPLETE",
            "permissions_read": permissions["read"],
            "account_verified": True,
            "catalog_rows": {k: len(v) for k, v in catalogs.items()},
            "insights_rows": len(mapped),
            "facts_published": False,
        }
    except Exception as error:  # noqa: BLE001 - close and persist sanitized stop reason
        reason = (
            error.code
            if isinstance(error, ProviderError)
            else "META_PILOT_INTERNAL_ERROR"
        )
    finally:
        if client:
            client.client.meter.failed = bool(reason)
            await client.close()
        with manager.factory.begin() as s:
            lock(s, "meta-jobs:" + manager.workspace)
            row = s.get(MetaPilotSession, identifier)
            if not reason:
                try:
                    authorization(s, manager.workspace, identifier)
                    job = s.get(ProviderJob, row.job_id)
                    if not job or job.cancel_requested or job.status != "running":
                        reason = "META_PILOT_CANCELLED"
                except ProviderError as error:
                    reason = error.code
            if row.status != "CANCELLED":
                if not reason and (
                    not row.deadline or aware(row.deadline) <= utc_now()
                ):
                    reason = "META_PILOT_TIMEOUT"
                row.status = "STOPPED" if reason else "SUCCEEDED"
                row.reason = reason or "META_PILOT_COMPLETED"
                row.result = result
                row.finished_at = utc_now()
    return {"status": "failed" if reason else "succeeded", "error_code": reason}
