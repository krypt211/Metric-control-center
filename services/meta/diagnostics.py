"""Local-only measured telemetry and explicitly hypothetical sync estimates."""

from __future__ import annotations

import math
from datetime import timedelta

from sqlalchemy import func, select

from services.meta.telemetry import PERCENT_FIELDS
from services.providers.integration_models import (
    MetaOperation,
    MetaRateState,
    MetaRequestAttempt,
)
from services.providers.models import ProviderConnection
from services.storage.models import AdAccount, Entity
from services.sync.engine import aware, utc_now


def report(session, workspace):
    now = utc_now()
    rows = session.scalars(
        select(MetaRequestAttempt).where(
            MetaRequestAttempt.workspace_id == workspace,
            MetaRequestAttempt.started_at >= now - timedelta(days=1),
        )
    ).all()
    first = session.scalar(
        select(func.min(MetaRequestAttempt.started_at)).where(
            MetaRequestAttempt.workspace_id == workspace
        )
    )
    connection = session.get(ProviderConnection, (workspace, "meta"))
    app = str(connection.config.get("app_id", "")) if connection else ""
    state = session.get(MetaRateState, "meta-app:" + app) if app else None
    logical_day = session.scalar(
        select(func.count())
        .select_from(MetaOperation)
        .where(
            MetaOperation.workspace_id == workspace,
            MetaOperation.started_at >= now - timedelta(days=1),
        )
    )
    latest = session.scalar(
        select(MetaOperation)
        .where(MetaOperation.workspace_id == workspace)
        .order_by(MetaOperation.started_at.desc())
        .limit(1)
    )
    usage = state.usage if state else {}
    tiers = [
        item["ads_api_access_tier"]
        for items in usage.values()
        for item in items
        if "ads_api_access_tier" in item
    ]
    percentages = [
        v
        for items in usage.values()
        for item in items
        for k, v in item.items()
        if k in PERCENT_FIELDS
    ]

    def count(seconds):
        return (
            sum((now - aware(r.started_at)).total_seconds() <= seconds for r in rows)
            if first
            else None
        )

    per_account = {}
    for row in rows:
        key = row.account_id or "UNKNOWN_ACCOUNT"
        per_account[key] = per_account.get(key, 0) + 1
    incidents = [r for r in rows if r.outcome == "RATE_LIMIT"]
    last = max(incidents, key=lambda r: r.started_at) if incidents else None
    return {
        "logical_operations_day": logical_day,
        "enabled": bool(connection and connection.enabled),
        "access_tier": tiers[-1] if tiers else None,
        "coverage_since": first.isoformat() if first else None,
        "coverage": "MEASURED_SINCE_FIRST_ATTEMPT" if first else "NOT_MEASURED",
        "minute": count(60),
        "hour": count(3600),
        "day": count(86400),
        "per_account": per_account,
        "success": sum(r.outcome == "OK" for r in rows) if first else None,
        "errors": sum(r.outcome not in ("OK", "STARTED") for r in rows)
        if first
        else None,
        "pending": sum(r.outcome == "STARTED" for r in rows) if first else None,
        "retries": sum(r.attempt > 1 for r in rows) if first else None,
        "pagination": sum(r.page > 1 for r in rows) if first else None,
        "incidents": len(incidents) if first else None,
        "usage_percent": max(percentages) if percentages else None,
        "usage": usage,
        "usage_checked_at": state.updated_at.isoformat()
        if state and state.updated_at
        else None,
        "cooldown_until": state.cooldown_until.isoformat()
        if state and state.cooldown_until
        else None,
        "last_incident": {
            "at": last.started_at.isoformat(),
            "http_status": last.http_status,
            "code": last.error_code,
            "subcode": last.error_subcode,
            "endpoint": last.endpoint,
            "account_id": last.account_id,
            "run_id": last.run_id,
        }
        if last
        else None,
        "last_operation": {
            "id": latest.id,
            "kind": latest.kind,
            "status": latest.status,
            "requests": session.scalar(
                select(func.count())
                .select_from(MetaRequestAttempt)
                .where(
                    MetaRequestAttempt.workspace_id == workspace,
                    MetaRequestAttempt.run_id == latest.id,
                )
            ),
        }
        if latest
        else None,
        "settings": {
            "request_interval_seconds": connection.config.get(
                "request_interval_seconds", 10
            )
            if connection
            else 10,
            "app_concurrency": 1,
            "account_concurrency": 1,
            "retry_cap": 2,
            "page_size": 100,
            "scheduler_minutes": 10,
        },
        "legacy_history": "NO_PER_ATTEMPT_TELEMETRY_BEFORE_0013",
        "sync_account_ids": connection.config.get("sync_account_ids", [])
        if connection
        else [],
        "available_accounts": [
            {"id": a.id, "name": a.name or a.external_id}
            for a in session.scalars(
                select(AdAccount).where(
                    AdAccount.workspace_id == workspace, AdAccount.provider == "meta"
                )
            )
        ],
    }


def estimate(session, workspace, accounts, days, *, object_counts=None):
    counts = object_counts or {}
    local = {
        kind: session.scalar(
            select(func.count())
            .select_from(Entity)
            .join(AdAccount)
            .where(
                AdAccount.workspace_id == workspace,
                AdAccount.provider == "meta",
                Entity.kind == kind,
            )
        )
        or 0
        for kind in ("campaign", "adset", "ad", "creative")
    }
    existing = (
        session.scalar(
            select(func.count())
            .select_from(AdAccount)
            .where(AdAccount.workspace_id == workspace, AdAccount.provider == "meta")
        )
        or 0
    )
    known = object_counts is not None
    if not known:
        counts = {k: math.ceil(v / max(existing, 1)) for k, v in local.items()}

    def pages(n):
        return max(1, math.ceil(n / 100))

    catalogs = {k: pages(counts.get(k, 0)) * accounts for k in local}
    insights = pages(counts.get("ad", 0) * days) * accounts
    auth = 1 + 1 + pages(accounts)
    total = auth + sum(catalogs.values()) + insights
    return {
        "mode": "DRY_RUN",
        "network_requests": 0,
        "classification": "CALCULATED_UNDER_EXPLICIT_ROW_ASSUMPTIONS"
        if known
        else "ESTIMATED_FROM_LOCAL_CATALOG"
        if existing
        else "ESTIMATED_UNKNOWN_OBJECT_COUNTS",
        "accounts": accounts,
        "days": days,
        "objects_per_account": counts,
        "local_reference_accounts": existing,
        "auth_and_accounts": auth,
        "catalog_pages": catalogs,
        "insights_pages": insights,
        "daily_rows_assumed": counts.get("ad", 0) * days * accounts,
        "total_no_retries": total,
        "maximum_with_two_retries": total * 3,
        "minimum_one_page_per_edge": 3 + 5 * accounts,
        "scheduled_today_per_day": total * 144,
        "assumptions": [
            "100 rows/page; one Insights row per AD/day assumed, actual pages unknown",
            "four catalogs and one AD-level Insights query per account; no per-AD Insights calls",
            "fields, attribution and timezone unchanged; no breakdowns/batch/async jobs",
            "Insights local pacing weight 2 is not a provider complexity score",
            "auth reads the full account roster; account selection does not constrain that roster",
            "today every 10 minutes, yesterday hourly, seven-day reconciliation daily",
        ],
    }
