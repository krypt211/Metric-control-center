"""Bounded reported-status evidence; never proof of authoritative AD state."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict, ValidationError

from services.metricflow.errors import InvalidResponse
from services.metricflow.reader import MetricFlowConnector

MAX_PAGES = 3
KNOWN_STATUSES = frozenset(
    {
        "ACTIVE",
        "PAUSED",
        "DELETED",
        "ARCHIVED",
        "PENDING_REVIEW",
        "DISAPPROVED",
        "PREAPPROVED",
        "PENDING_BILLING_INFO",
        "CAMPAIGN_PAUSED",
        "ADSET_PAUSED",
        "IN_PROCESS",
        "WITH_ISSUES",
    }
)


class _Row(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)
    ad_account_id: str
    date: str
    ad_id: str | None = None
    adset_id: str | None = None
    campaign_id: str | None = None
    status: str | None = None
    effective_status: str | None = None


class _Pagination(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)
    # Explicit presence is a local completeness requirement, not a new API field.
    has_more: bool
    cursor: str | None = None


class _Meta(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)
    data_updated_at: str | None = None


class _Page(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)
    data: list[_Row]
    meta: _Meta
    pagination: _Pagination


@dataclass(frozen=True)
class ReportedStatusEvidence:
    """Sanitized diagnostic evidence, without permissions or ownership claims."""

    outcome: str
    status: str | None
    effective_status: str | None
    source_synced_at: str | None
    pages: int
    authoritative: bool = False


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        raise InvalidResponse("Invalid sync timestamp") from None


async def collect_reported_status(
    connector: MetricFlowConnector,
    *,
    account_id: str,
    ad_id: str,
    adset_id: str,
    campaign_id: str,
    day: date,
    operation: str,
    command_started_at: datetime,
    now: datetime,
) -> ReportedStatusEvidence:
    """Scan at most three account-filtered pages; never infer configured status.

    The caller must use read_retries=0 and charge/guard each physical GET.
    The public contract has no AD-ID filter or authoritative cache bypass.
    """
    if operation not in ("PAUSE_AD", "ENABLE_AD"):
        raise ValueError("Unsupported readback operation")
    if command_started_at.utcoffset() is None or now.utcoffset() is None:
        raise ValueError("Aware readback timestamps required")
    if not re.fullmatch(r"act_[0-9]+", account_id) or any(
        not re.fullmatch(r"[0-9]+", value) for value in (ad_id, adset_id, campaign_id)
    ):
        raise ValueError("Exact READ identity required")
    cursor, seen, selected, version = None, set(), None, None
    for pages in range(1, MAX_PAGES + 1):
        params = {
            "level": "ad",
            "ad_account_ids": account_id,
            "fields": "spend",
            "currency": "native",
            "limit": 100,
        }
        if cursor:
            params["cursor"] = cursor
        raw = await connector.get_insights(day, day, params=params)
        try:
            page = _Page.model_validate(raw)
        except ValidationError:
            raise InvalidResponse("Invalid readback page") from None
        if len(page.data) > 100:
            raise InvalidResponse("Readback page exceeds requested limit")
        stamp = _timestamp(page.meta.data_updated_at)
        if pages > 1 and stamp != version:
            raise InvalidResponse("Readback snapshot changed")
        version = stamp
        for row in page.data:
            if row.ad_account_id != account_id or row.date != day.isoformat():
                raise InvalidResponse("Readback account or date mismatch")
            if row.ad_id != ad_id:
                continue
            if (row.adset_id, row.campaign_id) != (adset_id, campaign_id):
                raise InvalidResponse("Readback hierarchy mismatch")
            if selected is not None:
                raise InvalidResponse("Duplicate readback AD")
            selected = row
        if not page.pagination.has_more:
            break
        cursor = page.pagination.cursor
        if not cursor or len(cursor) > 2048 or cursor in seen:
            raise InvalidResponse("Invalid readback pagination")
        seen.add(cursor)
    else:
        return ReportedStatusEvidence("PAGE_BUDGET_EXHAUSTED", None, None, None, pages)
    synced = version.isoformat() if version else None
    if selected is None:
        return ReportedStatusEvidence("NOT_FOUND", None, None, synced, pages)
    status = selected.status if selected.status in KNOWN_STATUSES else None
    effective = (
        selected.effective_status
        if selected.effective_status in KNOWN_STATUSES
        else None
    )
    if not version:
        outcome = "FRESHNESS_UNKNOWN"
    elif version < command_started_at:
        outcome = "STALE_SYNC"
    elif (version - now).total_seconds() > 60:
        outcome = "FUTURE_SYNC"
    elif not status or not effective:
        outcome = "STATUS_UNKNOWN"
    else:
        expected = "PAUSED" if operation == "PAUSE_AD" else "ACTIVE"
        outcome = (
            "REPORTED_STATUS_MATCH_NEEDS_AUTHORITY"
            if status == effective == expected
            else "REPORTED_STATUS_MISMATCH"
        )
    return ReportedStatusEvidence(outcome, status, effective, synced, pages)
