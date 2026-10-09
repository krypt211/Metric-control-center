"""Atomic insight reconciliation, leases and a persistent per-HTTP-attempt quota."""

from datetime import date, datetime, timedelta, timezone
import json
from typing import Callable
from uuid import uuid4

import httpx
from sqlalchemy import delete, or_, select, update

from services.metricflow import MetricFlowConnector
from services.metricflow.errors import RateLimitExceeded
from services.storage.models import AdAccount, ApiQuota, RawSnapshot, SyncLease, SyncRun
from services.storage.repository import identity, insert_for, save_row, upsert

from .schema import InsightSchema, SchemaError, field, page_items


class QuotaExhausted(Exception):
    pass


class LeaseLost(Exception):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class SyncEngine:
    def __init__(
        self, sessions, schema: InsightSchema, read_key: str, *, workspace: str = "default",
        daily_budget: int = 800, max_pages: int = 100, max_rows: int = 100000,
        lease_seconds: int = 180, clock: Callable[[], datetime] = utc_now,
        transport: httpx.AsyncBaseTransport | None = None, retry_delay: float = 0.5,
        publish_guard=None,
    ):
        if daily_budget <= 0 or max_pages <= 0 or max_rows <= 0 or lease_seconds < 60:
            raise ValueError("Invalid sync limits")
        self.publish_guard = publish_guard
        self.sessions, self.schema, self._read_key = sessions, schema, read_key
        self.workspace, self.daily_budget = workspace, daily_budget
        self.max_pages, self.max_rows, self.lease_seconds = max_pages, max_rows, lease_seconds
        self.clock, self.transport, self.retry_delay = clock, transport, retry_delay
        self.lease_key = f"{workspace}:metricflow:insights"

    def claim(self, owner: str) -> bool:
        now = self.clock()
        with self.sessions.begin() as session:
            session.execute(insert_for(session, SyncLease.__table__).values(
                key=self.lease_key, owner=owner, expires_at=now + timedelta(seconds=self.lease_seconds)
            ).on_conflict_do_nothing(index_elements=["key"]))
            changed = session.execute(update(SyncLease).where(
                SyncLease.key == self.lease_key,
                or_(SyncLease.owner == owner, SyncLease.expires_at <= now),
            ).values(owner=owner, expires_at=now + timedelta(seconds=self.lease_seconds)))
            return changed.rowcount == 1

    def reserve_request(self, owner: str, run_id: str) -> None:
        now = self.clock()
        with self.sessions.begin() as session:
            renewed = session.execute(update(SyncLease).where(
                SyncLease.key == self.lease_key, SyncLease.owner == owner, SyncLease.expires_at > now,
            ).values(expires_at=now + timedelta(seconds=self.lease_seconds)))
            if renewed.rowcount != 1:
                raise LeaseLost()
            if session.scalar(select(ApiQuota).where(
                ApiQuota.workspace_id == self.workspace, ApiQuota.provider == "metricflow",
                ApiQuota.blocked_until > now,
            ).limit(1)) is not None:
                raise QuotaExhausted()
            session.execute(insert_for(session, ApiQuota.__table__).values(
                workspace_id=self.workspace, provider="metricflow", utc_day=now.date(), requests=0
            ).on_conflict_do_nothing(index_elements=["workspace_id", "provider", "utc_day"]))
            reserved = session.execute(update(ApiQuota).where(
                ApiQuota.workspace_id == self.workspace, ApiQuota.provider == "metricflow",
                ApiQuota.utc_day == now.date(), ApiQuota.requests < self.daily_budget,
                or_(ApiQuota.blocked_until.is_(None), ApiQuota.blocked_until <= now),
            ).values(requests=ApiQuota.requests + 1))
            if reserved.rowcount != 1:
                raise QuotaExhausted()
            session.execute(update(SyncRun).where(SyncRun.id == run_id).values(requests=SyncRun.requests + 1))

    def block_quota(self, retry_after: int | None) -> None:
        now = self.clock()
        next_reset = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), timezone.utc)
        # Conservative for a potentially daily upstream limit, even if Retry-After is short.
        blocked = max(next_reset, now + timedelta(seconds=min(retry_after or 0, 7 * 86400)))
        with self.sessions.begin() as session:
            session.execute(update(ApiQuota).where(
                ApiQuota.workspace_id == self.workspace, ApiQuota.provider == "metricflow",
                ApiQuota.utc_day == now.date(),
            ).values(blocked_until=blocked))

    async def parent_states(self, rows, connector, now, page_number, run_id):
        """Refresh referenced parents; reuse known statuses for up to one hour."""
        from dataclasses import replace
        from services.storage.models import Entity, EntityCurrentState
        config = self.schema.config.get("state_catalog")
        if not config:
            return rows, page_number
        ttl = config.get("cache_seconds")
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 60 <= ttl <= 3600:
            raise SchemaError("Parent state cache interval must be 60..3600 seconds")
        kinds = config.get("entities")
        if not isinstance(kinds, dict) or set(kinds) != {"campaign", "adset"}:
            raise SchemaError("Parent state catalog requires campaign and adset mappings")
        with self.sessions() as session:
            observations = session.execute(select(
                AdAccount.external_id, Entity.kind, Entity.external_id, EntityCurrentState.observed_at,
            ).join(Entity, Entity.account_id == AdAccount.id).join(
                EntityCurrentState, EntityCurrentState.entity_id == Entity.id,
            ).where(AdAccount.workspace_id == self.workspace, AdAccount.provider == "metricflow",
                    Entity.kind.in_(kinds), EntityCurrentState.status.is_not(None))).all()
        cached = {(aid, kind, eid): at for aid, kind, eid, at in observations}
        refresh = {(row.account_id, parent.kind) for row in rows for parent in row.parents
                   if (row.account_id, parent.kind, parent.external_id) not in cached or
                   (now - aware(cached[(row.account_id, parent.kind, parent.external_id)])).total_seconds() >= ttl}
        found = {}
        for aid, kind in sorted(refresh):
            mapping = kinds[kind]
            page_number += 1
            if page_number > self.max_pages:
                raise SchemaError("Parent catalog exceeded the shared page cap")
            fetch = connector.get_campaigns if kind == "campaign" else connector.get_adsets
            # Metadata is current; use exactly the insight window, without a backfill.
            days = [r.day for r in rows if r.account_id == aid]
            payload = await fetch(aid, min(days), max(days))
            with self.sessions.begin() as session:
                session.add(RawSnapshot(run_id=run_id, page=page_number,
                    payload={"endpoint": kind + "s", "account_id": aid, "response": payload}))
                session.execute(update(SyncRun).where(SyncRun.id == run_id).values(pages=page_number))
            items, cursor = page_items(payload, mapping["items_path"], mapping["pagination"])
            if cursor is not None or len(items) > self.max_rows:
                raise SchemaError("Parent catalog is not a verified complete response")
            for item in items:
                eid = field(item, mapping["fields"]["entity_id"])
                if not isinstance(eid, str) or not eid.isascii() or not eid.isdigit():
                    raise SchemaError("Invalid parent catalog provider ID")
                key = (aid, kind, eid)
                if key in found:
                    raise SchemaError("Duplicate parent catalog entry")
                status = field(item, mapping["fields"]["status"])
                name = field(item, mapping["fields"]["name"])
                if status is not None and (not isinstance(status, str) or not status):
                    raise SchemaError("Invalid parent status")
                if name is not None and not isinstance(name, str):
                    raise SchemaError("Invalid parent name")
                campaign = field(item, mapping["fields"]["campaign_id"]) if kind == "adset" else None
                found[key] = (status, name, campaign)
        enriched = []
        for row in rows:
            parents = []
            expected_campaign = next((p.external_id for p in row.parents if p.kind == "campaign"), None)
            for parent in row.parents:
                if (row.account_id, parent.kind) in refresh:
                    value = found.get((row.account_id, parent.kind, parent.external_id))
                    if value is None or value[0] is None:
                        raise SchemaError("Referenced parent or current status is absent from the complete catalog")
                    if parent.kind == "adset" and value[2] != expected_campaign:
                        raise SchemaError("Parent catalog hierarchy differs from insights")
                    parent = replace(parent, name=value[1] or parent.name, state={"status": value[0]})
                parents.append(parent)
            enriched.append(replace(row, parents=parents))
        return enriched, page_number

    async def run(self, job: str, start: date, end: date) -> dict[str, str | int]:
        if start > end:
            raise ValueError("Invalid sync window")
        owner, run_id = str(uuid4()), str(uuid4())
        if not self.claim(owner):
            return {"status": "skipped_overlap"}
        now = self.clock()
        with self.sessions.begin() as session:
            session.add(SyncRun(
                id=run_id, workspace_id=self.workspace, provider="metricflow", job=job,
                status="running", start_day=start, end_day=end, started_at=now,
                requests=0, pages=0, rows=0,
            ))
        result = {"run_id": run_id, "status": "failed"}
        try:
            async def reserve():
                self.reserve_request(owner, run_id)

            normalized = []
            row_keys, cursors = set(), set()
            query = dict(self.schema.config.get("query", {}))
            contexts = [None]
            if self.schema.config.get("endpoint") == "breakdowns":
                with self.sessions() as session:
                    contexts = session.scalars(select(AdAccount).where(
                        AdAccount.workspace_id == self.workspace, AdAccount.provider == "metricflow",
                    ).order_by(AdAccount.external_id)).all()
                if not contexts:
                    raise SchemaError("Synchronize accounts before breakdowns")
            page_number = 0
            catalog = {}
            async with MetricFlowConnector(
                self._read_key, transport=self.transport, before_request=reserve, retry_delay=self.retry_delay,
            ) as connector:
                catalog_config = self.schema.config.get("account_catalog")
                if catalog_config and self.schema.config.get("endpoint", "insights") == "insights":
                    from services.metricflow.onboarding import account_values
                    account_query, account_cursors = {}, set()
                    while True:
                        page_number += 1
                        if page_number > self.max_pages:
                            raise SchemaError("Account pagination exceeded the page cap")
                        payload = await connector.get_accounts(params=account_query)
                        with self.sessions.begin() as session:
                            session.add(RawSnapshot(run_id=run_id, page=page_number, payload={"endpoint": "ad-accounts", "response": payload}))
                            session.execute(update(SyncRun).where(SyncRun.id == run_id).values(pages=page_number))
                        account_rows, cursor = page_items(payload, catalog_config["items_path"], catalog_config["pagination"])
                        if len(catalog)+len(account_rows) > self.max_rows:
                            raise SchemaError("Account row cap exceeded")
                        for item in account_rows:
                            values = account_values(item, catalog_config)
                            aid = str(values["account_id"])
                            if aid in catalog:
                                raise SchemaError("Duplicate account catalog entry")
                            catalog[aid] = values
                        paging = catalog_config["pagination"]
                        if cursor is None:
                            break
                        if not isinstance(cursor, str) or not cursor or cursor in account_cursors:
                            raise SchemaError("Invalid account pagination cursor")
                        account_cursors.add(cursor)
                        account_query[paging["cursor_parameter"]] = cursor
                for account in contexts:
                    query = dict(self.schema.config.get("query", {}))
                    cursors = set()
                    snapshot_version = None
                    while True:
                        page_number += 1
                        if page_number > self.max_pages:
                            raise SchemaError("Pagination did not complete before the page cap")
                        payload = await connector.get_breakdowns(account.external_id, start, end, params=query) if account else await connector.get_insights(start, end, params=query)
                        with self.sessions.begin() as session:
                            snapshot = {"account_id": account.external_id, "response": payload} if account else payload
                            session.add(RawSnapshot(run_id=run_id, page=page_number, payload=snapshot))
                            session.execute(update(SyncRun).where(SyncRun.id == run_id).values(pages=page_number))
                        items, next_cursor = self.schema.page(payload)
                        range_paths = self.schema.config.get("range_paths", {})
                        if range_paths and (field(payload, range_paths["start"]) != start.isoformat() or field(payload, range_paths["end"]) != end.isoformat()):
                            raise SchemaError("Response date range differs from the requested window")
                        version_path = self.schema.config.get("snapshot_version_path")
                        if version_path:
                            version = field(payload, version_path)
                            if not isinstance(version, str) or not version:
                                raise SchemaError("Snapshot version is missing")
                            if snapshot_version is not None and version != snapshot_version:
                                raise SchemaError("Provider data changed between cursor pages; retry the window")
                            snapshot_version = version
                        if len(normalized) + len(items) > self.max_rows:
                            raise SchemaError("Sync row cap exceeded")
                        for item in items:
                            if account:
                                item = {**item, "_context": {"account_id": account.external_id, "currency": account.currency, "timezone": account.timezone}}
                            if not account and catalog_config:
                                aid = str(self.schema.value(item, "account_id"))
                                if aid not in catalog:
                                    raise SchemaError("Insight account is absent from catalog")
                                item = {**item, "_context": catalog[aid]}
                            row = self.schema.row(item)
                            if not account and catalog_config and (row.currency != catalog[aid]["currency"] or row.timezone != catalog[aid]["timezone"]):
                                raise SchemaError("Insight currency/timezone differs from account catalog")
                            if not start <= row.day <= end or account and row.account_id != account.external_id:
                                raise SchemaError("API returned a date/account outside the requested scope")
                            key = (row.account_id, row.kind, row.entity_id, row.day, json.dumps(row.dimensions, sort_keys=True))
                            if key in row_keys:
                                raise SchemaError("Duplicate entity/date: verify level and breakdown parameters")
                            row_keys.add(key)
                            normalized.append(row)
                        if next_cursor is None:
                            break
                        if next_cursor in cursors:
                            raise SchemaError("Pagination cursor loop")
                        cursors.add(next_cursor)
                        query[self.schema.pagination["cursor_parameter"]] = next_cursor
                normalized, page_number = await self.parent_states(normalized, connector, now, page_number, run_id)
            with self.sessions.begin() as session:
                lease = session.scalar(select(SyncLease).where(SyncLease.key == self.lease_key).with_for_update())
                if not lease or lease.owner != owner or aware(lease.expires_at) <= self.clock():
                    raise LeaseLost()
                if self.publish_guard is not None:
                    self.publish_guard(session)
                for aid, values in catalog.items():
                    account_values = {"id": identity(self.workspace, "metricflow", aid), "workspace_id": self.workspace, "provider": "metricflow", "external_id": aid, "name": values.get("account_name"), "currency": values["currency"], "timezone": values["timezone"], "observed_at": now}
                    if "account_status" in values:
                        previous = session.get(AdAccount, account_values["id"])
                        account_values["labels"] = {**(previous.labels if previous else {}), "status": values["account_status"]}
                    upsert(session, AdAccount, account_values)
                for row in normalized:
                    save_row(session, self.workspace, "metricflow", row, now)
                session.execute(update(SyncRun).where(SyncRun.id == run_id).values(
                    status="succeeded", finished_at=self.clock(), rows=len(normalized)
                ))
            result.update(status="succeeded", rows=len(normalized))
            result["accounts"] = len(set(catalog) | {r.account_id for r in normalized})
            result["campaigns"] = len({(r.account_id, p.external_id) for r in normalized for p in r.parents if p.kind == "campaign"} | {(r.account_id, r.entity_id) for r in normalized if r.kind == "campaign"})
            result["adsets"] = len({(r.account_id, p.external_id) for r in normalized for p in r.parents if p.kind == "adset"} | {(r.account_id, r.entity_id) for r in normalized if r.kind == "adset"})
            result["ads"] = len({(r.account_id, r.entity_id) for r in normalized if r.kind == "ad"})
            result["creatives"] = len({(r.account_id, r.creative_id) for r in normalized if r.creative_id})
        except Exception as error:
            if isinstance(error, RateLimitExceeded):
                self.block_quota(error.retry_after_seconds)
            status = "skipped_quota" if isinstance(error, QuotaExhausted) else "failed"
            # Never persist a raw exception string: driver/upstream messages may contain secrets.
            with self.sessions.begin() as session:
                session.execute(update(SyncRun).where(SyncRun.id == run_id).values(
                    status=status, finished_at=self.clock(), error_code=type(error).__name__,
                ))
            result.update(status=status, error_code=type(error).__name__)
        finally:
            with self.sessions.begin() as session:
                session.execute(delete(SyncLease).where(SyncLease.key == self.lease_key, SyncLease.owner == owner))
        return result
