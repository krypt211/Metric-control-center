"""Durable request attempts and conservative shared app pacing, never provider quotas."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import delete, func, select, text

from services.providers.contracts import ProviderError
from services.providers.integration_models import (
    MetaOperation,
    MetaRateState,
    MetaRequestAttempt,
    MetaRequestQueue,
)
from services.providers.models import ProviderAccountMapping
from services.storage.models import AdAccount
from services.storage.repository import insert_for
from services.sync.engine import aware, utc_now

HEADERS = (
    "x-app-usage",
    "x-ad-account-usage",
    "x-business-use-case-usage",
    "x-fb-ads-insights-throttle",
)
PERCENT_FIELDS = {
    "call_count",
    "total_cputime",
    "total_time",
    "acc_id_util_pct",
    "app_id_util_pct",
}
NUMBER_FIELDS = PERCENT_FIELDS | {
    "estimated_time_to_regain_access",
    "reset_time_duration",
}
RATE_CODES = {4, 17, 32, 613, 80004}
MIN_INTERVAL_SECONDS = 1800
GLOBAL_RATE_KEY = "meta-global"


def usage_headers(headers) -> dict:
    """Keep only documented usage metrics, never opaque identifiers or raw headers."""
    result = {}

    def collect(value, out, depth=0):
        if depth > 6:
            return
        if isinstance(value, list):
            for item in value[:50]:
                collect(item, out, depth + 1)
        if isinstance(value, dict):
            safe = {
                k: v
                for k, v in value.items()
                if k in NUMBER_FIELDS
                and type(v) in (int, float)
                and math.isfinite(v)
                and 0 <= v <= 1000000
            }
            tier = value.get("ads_api_access_tier")
            if tier in {
                "limited_access",
                "full_access",
                "development_access",
                "standard_access",
            }:
                safe["ads_api_access_tier"] = tier
            if safe:
                out.append(safe)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    collect(child, out, depth + 1)

    for name in HEADERS:
        raw = headers.get(name)
        if not raw or len(raw) > 20000:
            continue
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            continue
        items = []
        collect(value, items)
        if items:
            result[name] = items
    return result


def lock(session, key: str) -> None:
    if session.bind.dialect.name == "postgresql":
        number = int.from_bytes(
            hashlib.sha256(key.encode()).digest()[:8], "big", signed=True
        )
        session.execute(text("SET LOCAL lock_timeout = '5s'"))
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": number})


class MetaRequestMeter:
    def __init__(
        self,
        factory,
        workspace,
        app_id,
        *,
        run_id=None,
        operation="read",
        source=None,
        interval=MIN_INTERVAL_SECONDS,
        pilot_id=None,
    ):
        self.pilot_id = pilot_id
        self.factory = factory
        self.workspace = workspace
        self.app_id = app_id
        self.run_id = run_id or str(uuid4())
        self.operation = operation
        self.source = source or ("server:" + str(os.getpid()))
        self.mock_interval = max(0, interval)
        self.interval = max(MIN_INTERVAL_SECONDS, interval)
        self.key = GLOBAL_RATE_KEY
        self.started = False
        self.failed = False

    def start_operation(self):
        if self.started:
            return
        with self.factory.begin() as s:
            s.add(
                MetaOperation(
                    id=self.run_id,
                    workspace_id=self.workspace,
                    app_id=self.app_id,
                    kind=self.operation,
                    source=self.source,
                    started_at=utc_now(),
                    status="STARTED",
                )
            )
        self.started = True

    def end_operation(self):
        if not self.started:
            return
        with self.factory.begin() as s:
            row = s.get(MetaOperation, self.run_id)
            row.finished_at = utc_now()
            row.status = "ERROR" if self.failed else "COMPLETED"

    async def acquire(self, complexity=1):
        ticket = str(uuid4())
        start = time.monotonic()
        now = utc_now()
        with self.factory.begin() as s:
            lock(s, self.key)
            # Carry forward existing per-app pacing/cooldown on upgrade.
            old_next, old_cooldown, old_lease = s.execute(
                select(
                    func.max(MetaRateState.next_start),
                    func.max(MetaRateState.cooldown_until),
                    func.max(MetaRateState.lease_until),
                )
            ).one()
            last_attempt = s.scalar(select(func.max(MetaRequestAttempt.started_at)))
            starts = [aware(v) for v in (old_next,) if v]
            if last_attempt:
                starts.append(aware(last_attempt) + timedelta(seconds=self.interval))
            s.execute(
                insert_for(s, MetaRateState.__table__)
                .values(
                    key=self.key,
                    usage={},
                    next_start=max(starts) if starts else None,
                    cooldown_until=old_cooldown,
                    lease_until=old_lease,
                    owner="legacy-hold"
                    if old_lease and aware(old_lease) > now
                    else None,
                )
                .on_conflict_do_nothing(index_elements=["key"])
            )
            s.add(
                MetaRequestQueue(
                    id=ticket,
                    key=self.key,
                    workspace_id=self.workspace,
                    created_at=now,
                    expires_at=now + timedelta(seconds=120),
                )
            )
        try:
            while time.monotonic() - start < 90:
                delay = 0.05
                with self.factory.begin() as s:
                    lock(s, self.key)
                    now = (
                        aware(s.scalar(select(func.clock_timestamp())))
                        if s.bind.dialect.name == "postgresql"
                        else utc_now()
                    )
                    state = s.get(MetaRateState, self.key)
                    if state.cooldown_until and aware(state.cooldown_until) > now:
                        raise ProviderError(
                            "META_RATE_LIMIT",
                            max(
                                1,
                                int(
                                    (aware(state.cooldown_until) - now).total_seconds()
                                ),
                            ),
                        )
                    s.execute(
                        delete(MetaRequestQueue).where(
                            MetaRequestQueue.key == self.key,
                            MetaRequestQueue.expires_at <= now,
                        )
                    )
                    first = s.scalar(
                        select(MetaRequestQueue.id)
                        .where(MetaRequestQueue.key == self.key)
                        .order_by(MetaRequestQueue.created_at, MetaRequestQueue.id)
                        .limit(1)
                    )
                    available = (
                        not state.owner
                        or not state.lease_until
                        or aware(state.lease_until) <= now
                    )
                    next_start = aware(state.next_start) if state.next_start else now
                    if first == ticket and available and next_start <= now:
                        state.owner = ticket
                        state.lease_until = now + timedelta(seconds=90)
                        state.next_start = now + timedelta(seconds=self.interval)
                        s.delete(s.get(MetaRequestQueue, ticket))
                        return ticket
                    if (
                        first == ticket
                        and available
                        and self.interval >= MIN_INTERVAL_SECONDS
                    ):
                        raise ProviderError(
                            "META_PACING_WAIT",
                            max(1, math.ceil((next_start - now).total_seconds())),
                        )
                    if first == ticket and available:
                        delay = min(0.5, max(0.05, (next_start - now).total_seconds()))
                await asyncio.sleep(delay)
            raise ProviderError("META_REQUEST_QUEUE_TIMEOUT")
        finally:
            with self.factory.begin() as s:
                s.execute(delete(MetaRequestQueue).where(MetaRequestQueue.id == ticket))

    def release(self, ticket):
        with self.factory.begin() as s:
            lock(s, self.key)
            state = s.get(MetaRateState, self.key)
            if state and state.owner == ticket:
                state.owner = None
                state.lease_until = None

    def begin_attempt(self, path, attempt, page, retry_reason, *, ticket=None):
        self.start_operation()
        identifier = str(uuid4())
        category = (
            path.split("/")[-1]
            if "/" in path
            else "auth"
            if path == "debug_token"
            else "entity_state"
        )
        if category == "adcreatives":
            category = "creatives"
        external = path.split("/")[0]
        canonical = None
        with self.factory.begin() as s:
            lock(s, self.key)
            now = (
                aware(s.scalar(select(func.clock_timestamp())))
                if s.bind.dialect.name == "postgresql"
                else utc_now()
            )
            state = s.get(MetaRateState, self.key)
            if not ticket or not state or state.owner != ticket:
                raise ProviderError("META_REQUEST_LEASE_LOST")
            if not state.lease_until or aware(state.lease_until) <= now:
                raise ProviderError("META_REQUEST_LEASE_LOST")
            if state.cooldown_until and aware(state.cooldown_until) > now:
                raise ProviderError("META_RATE_LIMIT")
            # Fence the physical attempt, not only the earlier reservation.
            state.next_start = now + timedelta(seconds=self.interval)
            state.updated_at = now
            if self.pilot_id:
                from services.meta.pilot import reserve_attempt

                reserve_attempt(s, self.workspace, self.pilot_id, path)
            if external.startswith("act_"):
                aid = s.scalar(
                    select(AdAccount.id).where(
                        AdAccount.workspace_id == self.workspace,
                        AdAccount.provider == "meta",
                        AdAccount.external_id == external,
                    )
                )
                mapping = s.get(ProviderAccountMapping, aid) if aid else None
                canonical = mapping.canonical_id if mapping else aid
            s.add(
                MetaRequestAttempt(
                    id=identifier,
                    workspace_id=self.workspace,
                    app_id=self.app_id,
                    account_id=canonical,
                    endpoint=category,
                    operation=self.operation,
                    run_id=self.run_id,
                    started_at=utc_now(),
                    attempt=attempt,
                    page=page,
                    retry_reason=retry_reason,
                    source=self.source,
                    complexity=2 if category == "insights" else 1,
                    usage={},
                    outcome="STARTED",
                )
            )
        return identifier

    def finish_attempt(
        self,
        identifier,
        duration,
        response=None,
        *,
        code=None,
        subcode=None,
        outcome="OK",
        retry_after=0,
    ):
        usage = usage_headers(response.headers) if response is not None else {}
        status = response.status_code if response is not None else None
        rate = (status == 429 or code in RATE_CODES) and outcome not in {
            "TOKEN_INVALID",
            "PERMISSION_DENIED",
        }
        if outcome != "OK":
            self.failed = True
        with self.factory.begin() as s:
            row = s.get(MetaRequestAttempt, identifier)
            row.duration_ms = duration
            row.http_status = status
            row.error_code = code
            row.error_subcode = subcode
            row.outcome = "RATE_LIMIT" if rate else outcome
            row.usage = usage
            lock(s, self.key)
            state = s.get(MetaRateState, self.key)
            if usage:
                state.updated_at = utc_now()
                state.usage = usage
            percent = max(
                [
                    v
                    for items in usage.values()
                    for item in items
                    for k, v in item.items()
                    if k in PERCENT_FIELDS
                ]
                or [0]
            )
            if rate or percent >= 85 or retry_after:
                # Header percentages are utilization, never an absolute quota.
                # Unknown regain-access units do not determine a fabricated resume time.
                seconds = max(retry_after, 900 if rate else 60)
                until = utc_now() + timedelta(seconds=seconds)
                if not state.cooldown_until or aware(state.cooldown_until) < until:
                    state.cooldown_until = until
