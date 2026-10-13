"""Durable Meta READ lifecycle in the existing ProviderJob queue."""

import hashlib
import json
import os
from collections import Counter
from datetime import timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

from services.meta.telemetry import lock
from services.providers.contracts import ProviderError
from services.providers.job_models import ProviderJobAudit
from services.providers.models import ProviderConnection, ProviderJob
from services.storage.models import AdAccount, SyncLease
from services.sync.engine import aware, utc_now

ACTIVE = ("queued", "running")
TTL = {"today": 540, "yesterday": 3300, "last7": 82800, "manual": 1800, "health": 300}


def option(name, default, low, high):
    value = int(os.environ.get(name, default))
    if not low <= value <= high:
        raise ValueError("INVALID_META_JOB_SETTING")
    return value


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def configuration(connection):
    from services.meta.provider import MetaMarketingProvider

    return digest(
        {
            "revision": connection.revision,
            "config": connection.config,
            "fields": MetaMarketingProvider.FIELDS,
            "insights_version": 1,
        }
    )


def audit(session, job, event, reason, actor=None):
    session.add(
        ProviderJobAudit(
            id=str(uuid4()),
            job_id=job.id,
            workspace_id=job.workspace_id,
            at=utc_now(),
            event=event,
            reason=reason,
            actor_id=actor,
        )
    )


def finish(session, job, status, reason, actor=None):
    job.status = status
    job.error_code = reason
    job.finished_at = utc_now()
    job.owner = None
    job.lease_until = None
    audit(session, job, status.upper(), reason or "READ_COMPLETED", actor)
    if job.purpose == "pilot":
        from services.meta.pilot_models import MetaPilotSession

        row = session.get(
            MetaPilotSession, (job.request_params or {}).get("pilot_session_id")
        )
        if row and row.status in ("QUEUED", "RUNNING"):
            row.status = "CANCELLED" if status == "cancelled" else "STOPPED"
            row.reason = reason or "META_PILOT_STOPPED"
            row.finished_at = utc_now()


def scope(session, connection, accounts=None):
    chosen = (
        accounts if accounts is not None else connection.config.get("sync_account_ids")
    )
    if chosen is None:
        raise ProviderError("META_SYNC_ACCOUNT_SELECTION_REQUIRED")
    if len(chosen) > 3:
        raise ProviderError("META_SYNC_ACCOUNT_SELECTION_REQUIRED")
    for identifier in chosen:
        a = session.get(AdAccount, identifier)
        if not a or a.workspace_id != connection.workspace_id or a.provider != "meta":
            raise ProviderError("INVALID_META_ACCOUNTS")
    return sorted(set(chosen))


def enqueue(
    session,
    workspace,
    purpose,
    start,
    end,
    *,
    actor=None,
    accounts=None,
    refresh=None,
    published_at=None,
    message_deadline=None,
):
    from services.meta.pilot import enabled as pilot_mode

    if pilot_mode():
        raise ProviderError("META_PILOT_STANDARD_READ_HELD")
    if purpose not in TTL or start > end:
        raise ProviderError("INVALID_META_JOB")
    lock(session, "meta-jobs:" + workspace)
    c = session.get(ProviderConnection, (workspace, "meta"))
    if not c or not c.enabled:
        raise ProviderError("PROVIDER_DISABLED")
    now = utc_now()
    origin = aware(published_at) if published_at else now
    timezone = os.environ.get("SYNC_TIMEZONE", "Europe/Moscow")
    ZoneInfo(timezone)
    selected = scope(session, c, [] if purpose == "health" else accounts)
    if purpose != "health" and not selected:
        raise ProviderError("META_SYNC_ACCOUNT_SELECTION_REQUIRED")
    # Empty unknown roster is explicit discovery, capped by MetaSync, never another workspace.
    params = {"level": "ad", "fields_version": 1, "discovery": not selected}
    base = digest(
        {
            "workspace": workspace,
            "provider": "meta",
            "accounts": selected,
            "purpose": purpose,
            "start": str(start),
            "end": str(end),
            "timezone": timezone,
            "params": params,
            "config": configuration(c),
        }
    )
    interval = {
        "today": 600,
        "yesterday": 3600,
        "manual": option("META_MANUAL_DEDUP_SECONDS", 60, 10, 3600),
        "health": 60,
    }.get(purpose)
    slot = (
        str(int(origin.timestamp()) // interval)
        if interval
        else origin.astimezone(ZoneInfo(timezone)).date().isoformat()
    )
    if refresh is not None:
        slot = refresh
    key = digest([base, slot])
    previous = session.scalar(select(ProviderJob).where(ProviderJob.dedup_key == key))
    if previous:
        return previous, False
    ttl = option(
        "META_JOB_TTL_" + purpose.upper() + "_SECONDS", TTL[purpose], 30, 172800
    )
    deadline = origin + timedelta(seconds=ttl)
    if message_deadline is not None:
        deadline = min(deadline, aware(message_deadline))
    if deadline <= now:
        j = ProviderJob(
            id=str(uuid4()),
            workspace_id=workspace,
            provider="meta",
            kind="sync",
            purpose=purpose,
            start_day=start,
            end_day=end,
            status="expired",
            created_at=origin,
            expires_at=deadline,
            dedup_key=key,
            account_scope=selected,
            request_params=params,
            config_revision=c.revision,
            config_hash=configuration(c),
            timezone=timezone,
            slot=slot,
            finished_at=now,
            error_code="JOB_TTL_EXPIRED",
        )
        session.add(j)
        session.flush()
        audit(session, j, "EXPIRED", "JOB_TTL_EXPIRED", actor)
        return j, True
    candidates = session.scalars(
        select(ProviderJob).where(
            ProviderJob.workspace_id == workspace,
            ProviderJob.provider == "meta",
            ProviderJob.status.in_(ACTIVE),
            ProviderJob.expires_at.is_not(None),
            *([ProviderJob.purpose == "pilot"] if pilot_mode() else []),
        )
    ).all()
    for old in candidates:
        if old.status == "queued" and aware(old.expires_at) <= now:
            finish(session, old, "expired", "JOB_TTL_EXPIRED")
        elif old.status == "queued" and (
            old.config_hash != configuration(c)
            or (
                purpose in ("today", "yesterday", "last7")
                and old.purpose == purpose
                and old.account_scope == selected
                and older_slot(old.slot, slot)
            )
        ):
            finish(session, old, "cancelled", "JOB_SUPERSEDED")
    session.flush()
    existing = session.scalar(
        select(ProviderJob).where(
            ProviderJob.active_key == base, ProviderJob.status.in_(ACTIVE)
        )
    )
    if existing:
        return existing, False
    count = sum(j.status in ACTIVE for j in candidates)
    if count >= option("META_JOB_QUEUE_LIMIT", 20, 1, 1000):
        raise ProviderError("META_JOB_QUEUE_FULL")
    ttl = option(
        "META_JOB_TTL_" + purpose.upper() + "_SECONDS", TTL[purpose], 30, 172800
    )
    j = ProviderJob(
        id=str(uuid4()),
        workspace_id=workspace,
        provider="meta",
        kind="health" if purpose == "health" else "sync",
        purpose=purpose,
        start_day=start,
        end_day=end,
        status="queued",
        created_at=origin,
        expires_at=deadline,
        dedup_key=key,
        active_key=base,
        account_scope=selected,
        request_params=params,
        config_revision=c.revision,
        config_hash=configuration(c),
        timezone=timezone,
        slot=slot,
        cancel_requested=False,
        recoveries=0,
    )
    session.add(j)
    session.flush()
    audit(session, j, "QUEUED", "READ_ENQUEUED", actor)
    return j, True


def stop_reason(job, connection, now):
    if job.cancel_requested:
        return job.error_code or "JOB_CANCEL_REQUESTED"
    if aware(job.expires_at) <= now:
        return "JOB_TTL_EXPIRED"
    if not connection or (not connection.enabled and job.purpose != "pilot"):
        return "PROVIDER_DISABLED"
    if (
        connection.revision != job.config_revision
        or configuration(connection) != job.config_hash
    ):
        return "JOB_CONFIG_SUPERSEDED"
    return None


def stopped(session, job, reason):
    finish(
        session, job, "expired" if reason == "JOB_TTL_EXPIRED" else "cancelled", reason
    )


def maintain(session, workspace):
    from services.meta.pilot import enabled as pilot_mode

    lock(session, "meta-jobs:" + workspace)
    now = utc_now()
    c = session.get(ProviderConnection, (workspace, "meta"))
    rows = session.scalars(
        select(ProviderJob).where(
            ProviderJob.workspace_id == workspace,
            ProviderJob.provider == "meta",
            ProviderJob.status.in_(ACTIVE),
            ProviderJob.expires_at.is_not(None),
            *([ProviderJob.purpose == "pilot"] if pilot_mode() else []),
        )
    ).all()
    for j in rows:
        reason = stop_reason(j, c, now)
        if j.status == "queued":
            if reason:
                stopped(session, j, reason)
        elif not j.lease_until or aware(j.lease_until) <= now:
            # Worker lease outlives renewable sync lease and HTTP timeout.
            if reason:
                stopped(session, j, reason)
            elif j.purpose == "pilot":
                finish(session, j, "failed", "META_PILOT_OWNER_LOST")
            elif (j.recoveries or 0) >= 2:
                finish(session, j, "failed", "JOB_RECOVERY_LIMIT")
            else:
                j.status = "queued"
                j.owner = None
                j.lease_until = None
                j.recoveries = (j.recoveries or 0) + 1
                audit(session, j, "RECOVERED", "JOB_OWNER_LEASE_EXPIRED")
    session.execute(
        delete(SyncLease).where(
            SyncLease.key == workspace + ":meta:insights", SyncLease.expires_at <= now
        )
    )
    session.flush()


def claim(session, workspace, identifier):
    maintain(session, workspace)
    j = session.scalar(
        select(ProviderJob)
        .where(
            ProviderJob.id == identifier,
            ProviderJob.workspace_id == workspace,
            ProviderJob.provider == "meta",
        )
        .with_for_update()
    )
    if not j:
        return None
    if not j.expires_at:
        return None  # Legacy records are held for explicit reviewed policy.
    if j.status != "queued":
        return None
    if session.scalar(
        select(ProviderJob.id)
        .where(
            ProviderJob.workspace_id == workspace,
            ProviderJob.provider == "meta",
            ProviderJob.status == "running",
        )
        .limit(1)
    ):
        return None
    owner = str(uuid4())
    j.owner = owner
    j.status = "running"
    j.started_at = utc_now()
    j.lease_until = utc_now() + timedelta(
        seconds=option("META_JOB_LEASE_SECONDS", 240, 240, 600)
    )
    audit(session, j, "RUNNING", "READ_CLAIMED")
    return owner


def checkpoint(factory, workspace, identifier, owner):
    reason = None
    with factory.begin() as s:
        lock(s, "meta-jobs:" + workspace)
        j = s.get(ProviderJob, identifier)
        if (
            not j
            or j.workspace_id != workspace
            or j.status != "running"
            or j.owner != owner
        ):
            reason = "JOB_CLAIM_LOST"
        else:
            reason = stop_reason(
                j, s.get(ProviderConnection, (workspace, "meta")), utc_now()
            )
            if reason:
                stopped(s, j, reason)
            else:
                j.lease_until = utc_now() + timedelta(
                    seconds=option("META_JOB_LEASE_SECONDS", 240, 240, 600)
                )
    if reason:
        raise ProviderError(reason)


def cancel(session, workspace, identifier, actor=None, reason="JOB_USER_CANCELLED"):
    lock(session, "meta-jobs:" + workspace)
    j = session.scalar(
        select(ProviderJob)
        .where(
            ProviderJob.workspace_id == workspace,
            ProviderJob.provider == "meta",
            ProviderJob.id == identifier,
        )
        .with_for_update()
    )
    if not j:
        raise ProviderError("META_JOB_NOT_FOUND")
    if j.status == "queued":
        finish(session, j, "cancelled", reason, actor)
    elif j.status == "running":
        j.cancel_requested = True
        j.error_code = reason
        audit(session, j, "CANCEL_REQUESTED", reason, actor)
    return j


def complete(session, workspace, identifier, owner, status, reason=None):
    lock(session, "meta-jobs:" + workspace)
    j = session.get(ProviderJob, identifier)
    if (
        not j
        or j.workspace_id != workspace
        or j.status != "running"
        or j.owner != owner
    ):
        return
    stop = stop_reason(
        j, session.get(ProviderConnection, (workspace, "meta")), utc_now()
    )
    if stop:
        stopped(session, j, stop)
    elif status == "queued":
        j.status = "queued"
        j.owner = None
        j.lease_until = None
        audit(session, j, "DEFERRED", "SYNC_OVERLAP")
    else:
        finish(session, j, status, reason)


def monitoring(session, workspace):
    now = utc_now()
    query = select(ProviderJob).where(
        ProviderJob.workspace_id == workspace, ProviderJob.provider == "meta"
    )
    rows = session.scalars(
        query.order_by(ProviderJob.created_at.desc()).limit(40)
    ).all()
    counts = dict(
        session.execute(
            select(ProviderJob.status, func.count())
            .where(
                ProviderJob.workspace_id == workspace, ProviderJob.provider == "meta"
            )
            .group_by(ProviderJob.status)
        ).all()
    )
    counts = Counter(counts)
    pending = session.scalars(
        query.where(ProviderJob.status == "queued", ProviderJob.expires_at.is_not(None))
    ).all()
    history = session.scalars(
        query.where(
            ProviderJob.started_at.is_not(None), ProviderJob.expires_at.is_not(None)
        )
        .order_by(ProviderJob.started_at.desc())
        .limit(1000)
    ).all()
    waits = [
        max(0, (aware(j.started_at) - aware(j.created_at)).total_seconds())
        for j in history
    ]
    legacy_held = session.scalar(
        select(func.count())
        .select_from(ProviderJob)
        .where(
            ProviderJob.workspace_id == workspace,
            ProviderJob.provider == "meta",
            ProviderJob.status.in_(ACTIVE),
            ProviderJob.expires_at.is_(None),
        )
    )
    ages = [max(0, (now - aware(j.created_at)).total_seconds()) for j in pending]
    capacity = option("META_JOB_QUEUE_LIMIT", 20, 1, 1000)
    latest = sorted(rows, key=lambda j: aware(j.created_at), reverse=True)[:40]
    from services.meta.diagnostics import estimate

    c = session.get(ProviderConnection, (workspace, "meta"))
    interval = max(10, float(c.config.get("request_interval_seconds", 10))) if c else 10
    drain = 0
    for j in pending:
        forecast = estimate(
            session,
            workspace,
            min(3, len(j.account_scope or []) or 1),
            (j.end_day - j.start_day).days + 1,
        )
        drain += (
            interval
            * (
                forecast["auth_and_accounts"]
                + sum(forecast["catalog_pages"].values())
                + 2 * forecast["insights_pages"]
            )
            if j.purpose != "health"
            else interval * forecast["auth_and_accounts"]
        )

    return {
        "pending": counts["queued"],
        "running": counts["running"],
        "expired": counts["expired"],
        "cancelled": counts["cancelled"],
        "failed": counts["failed"],
        "legacy_held": legacy_held,
        "wait_sample": "LATEST_1000_STARTED_JOBS",
        "oldest_pending_seconds": max(ages, default=0),
        "average_wait_seconds": sum(waits) / len(waits) if waits else None,
        "max_wait_seconds": max(waits, default=None),
        "backlog": len(pending) > 0,
        "queue_limit": capacity,
        "saturation_warning": len(pending) >= max(1, int(capacity * 0.8)),
        "estimated_drain_seconds": drain,
        "drain_basis": "ESTIMATED_FROM_LOCAL_CATALOG_EXCLUDES_RUNNING_LATENCY_COOLDOWN",
        "jobs": [
            {
                "id": j.id,
                "status": j.status.upper(),
                "purpose": j.purpose or "LEGACY",
                "expires_at": j.expires_at.isoformat() if j.expires_at else None,
                "reason": j.error_code,
                "cancel_requested": bool(j.cancel_requested),
            }
            for j in latest
        ],
    }


def fence(session, workspace, identifier, owner):
    lock(session, "meta-jobs:" + workspace)
    j = session.get(ProviderJob, identifier)
    if (
        not j
        or j.workspace_id != workspace
        or j.status != "running"
        or j.owner != owner
    ):
        raise ProviderError("JOB_CLAIM_LOST")
    reason = stop_reason(
        j, session.get(ProviderConnection, (workspace, "meta")), utc_now()
    )
    if reason:
        raise ProviderError(reason)


def in_cooldown(session, workspace):
    from services.providers.integration_models import MetaRateState

    c = session.get(ProviderConnection, (workspace, "meta"))
    state = (
        session.get(MetaRateState, "meta-app:" + str(c.config.get("app_id", "")))
        if c
        else None
    )
    return bool(
        state and state.cooldown_until and aware(state.cooldown_until) > utc_now()
    )


def review_legacy(session, workspace, *, apply_digest=None):
    """Inventory first; expire only unstarted 90-day-old pending rows after review."""
    lock(session, "meta-jobs:" + workspace)
    now = utc_now()
    cutoff = now - timedelta(days=90)
    lease = session.get(SyncLease, workspace + ":meta:insights")
    idle = not lease or aware(lease.expires_at) <= now
    rows = session.scalars(
        select(ProviderJob)
        .where(
            ProviderJob.workspace_id == workspace,
            ProviderJob.provider == "meta",
            ProviderJob.status.in_(ACTIVE),
            ProviderJob.expires_at.is_(None),
        )
        .order_by(ProviderJob.id)
    ).all()
    inventory = [
        {
            "id": j.id,
            "status": j.status,
            "age_days": (now - aware(j.created_at)).days,
            "eligible": bool(
                idle
                and j.status == "queued"
                and j.started_at is None
                and aware(j.created_at) < cutoff
                and j.end_day < cutoff.date()
            ),
        }
        for j in rows
    ]
    proof = digest(inventory)
    if apply_digest is not None:
        if proof != apply_digest:
            raise ProviderError("LEGACY_INVENTORY_CHANGED")
        for j, item in zip(rows, inventory, strict=True):
            if item["eligible"]:
                finish(session, j, "expired", "LEGACY_REVIEWED_STALE_90D")
    return {
        "inventory": inventory,
        "digest": proof,
        "policy": "UNSTARTED_PENDING_CREATED_AND_PERIOD_OVER_90D_NO_ACTIVE_SYNC_LEASE",
        "applied": apply_digest is not None,
    }


def older_slot(previous, current):
    if previous is None:
        return False
    if previous.isdecimal() and current.isdecimal():
        return int(previous) < int(current)
    return previous < current
