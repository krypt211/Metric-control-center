from datetime import date, datetime
import os
import re
from typing import Awaitable, Callable, Self

import httpx

from services.contracts import JSONPayload, Query

from .secrets import read_key_file
from .transport import MetricFlowTransport


def _period(start: date, end: date, params: Query | None) -> dict[str, str | int | bool]:
    if not isinstance(start, date) or isinstance(start, datetime) or not isinstance(end, date) or isinstance(end, datetime):
        raise ValueError("Dates must be datetime.date values")
    if start > end:
        raise ValueError("Start date must not exceed end date")
    extra = dict(params or {})
    if "from" in extra or "to" in extra:
        raise ValueError("Use start/end arguments for the date range")
    return {**extra, "from": start.isoformat(), "to": end.isoformat()}


class MetricFlowConnector:
    """GET-only connector. Preserve raw JSON until live schemas are verified."""

    def __init__(
        self, read_key: str, *, transport: httpx.AsyncBaseTransport | None = None,
        read_retries: int = 2, retry_delay: float = 0.5,
        before_request: Callable[[], Awaitable[None]] | None = None,
    ):
        self._http = MetricFlowTransport(
            read_key, transport=transport, read_retries=read_retries, retry_delay=retry_delay,
            before_request=before_request,
        )

    @classmethod
    def from_environment(cls) -> Self:
        # Deliberately never reads METRICFLOW_WRITE_KEY_FILE.
        return cls(read_key_file(os.environ.get("METRICFLOW_READ_KEY_FILE")))

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.close()

    async def get_me(self) -> JSONPayload:
        return await self._http.request("GET", "me")

    async def get_usage(self) -> JSONPayload:
        return await self._http.request("GET", "usage")

    async def get_accounts(self, *, params: Query | None = None) -> JSONPayload:
        return await self._http.request("GET", "ad-accounts", params=params)

    async def get_summary(self, start: date, end: date, *, params: Query | None = None) -> JSONPayload:
        return await self._http.request("GET", "summary", params=_period(start, end, params))

    async def get_insights(self, start: date, end: date, *, params: Query | None = None) -> JSONPayload:
        return await self._http.request("GET", "insights", params=_period(start, end, params))

    async def _account_data(
        self, endpoint: str, account_id: str, start: date, end: date, params: Query | None
    ) -> JSONPayload:
        if not re.fullmatch(r"act_[0-9]+", account_id):
            raise ValueError("Use the act_<numeric_id> value returned by get_accounts")
        return await self._http.request(
            "GET", f"ad-accounts/{account_id}/{endpoint}", params=_period(start, end, params)
        )

    async def get_campaigns(self, account_id: str, start: date, end: date, *, params: Query | None = None) -> JSONPayload:
        return await self._account_data("campaigns", account_id, start, end, params)

    async def get_adsets(self, account_id: str, start: date, end: date, *, params: Query | None = None) -> JSONPayload:
        return await self._account_data("adsets", account_id, start, end, params)

    async def get_ads(self, account_id: str, start: date, end: date, *, params: Query | None = None) -> JSONPayload:
        return await self._account_data("ads", account_id, start, end, params)

    async def get_daily(self, account_id: str, start: date, end: date, *, params: Query | None = None) -> JSONPayload:
        return await self._account_data("daily", account_id, start, end, params)

    async def get_creatives(self, account_id: str, start: date, end: date, *, params: Query | None = None) -> JSONPayload:
        return await self._account_data("creatives", account_id, start, end, params)

    async def get_tracker_stats(self, account_id: str, start: date, end: date, *, params: Query | None = None) -> JSONPayload:
        return await self._account_data("tracker", account_id, start, end, params)

    async def get_breakdowns(self, account_id: str, start: date, end: date, *, params: Query | None = None) -> JSONPayload:
        return await self._account_data("breakdowns", account_id, start, end, params)

    async def get_rules(self, *, params: Query | None = None) -> JSONPayload:
        return await self._http.request("GET", "rules", params=params)

    async def get_bundles(self, *, params: Query | None = None) -> JSONPayload:
        return await self._http.request("GET", "bundles", params=params)
