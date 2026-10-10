"""The only HTTP implementation used by MetricFlow connectors."""

import asyncio
import json
from typing import Any, Awaitable, Callable, Mapping

import httpx

from services.contracts import JSONPayload, Query

from .errors import (
    ActionOutcomeUnknown,
    APIError,
    AuthenticationError,
    InvalidResponse,
    PermissionDenied,
    RateLimitExceeded,
    SubscriptionRequired,
    TransportUnavailable,
)
from .secrets import validate_key

BASE_URL = "https://metricflowit.click/api/v1/"


class MetricFlowTransport:
    def __init__(
        self,
        key: str,
        *,
        write: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        read_retries: int = 2,
        retry_delay: float = 0.5,
        before_request: Callable[[], Awaitable[None]] | None = None,
    ):
        if read_retries < 0 or retry_delay < 0:
            raise ValueError("Retry settings must be nonnegative")
        self._write = write
        self._read_retries = read_retries
        self._retry_delay = retry_delay
        self._before_request = before_request
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {validate_key(key)}", "Accept": "application/json"},
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Query | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> JSONPayload:
        expected = "POST" if self._write else "GET"
        if method != expected:
            raise PermissionDenied(403, "Operation not allowed by this connector")
        # Paths are built by connector methods, never accepted from HTTP callers.
        if not path or path.startswith("/") or any(c in path for c in (":", "?", "#", "\\", "%")):
            raise ValueError("Invalid API path")
        if any(part in (".", "..", "") for part in path.split("/")):
            raise ValueError("Invalid API path")

        # Validate JSON locally before a command can possibly leave the process.
        if payload is not None:
            json.dumps(dict(payload), allow_nan=False)
        attempts = 1 if self._write else self._read_retries + 1
        for attempt in range(attempts):
            if self._write:
                from services.actions.safety import ActionSafetyGate

                ActionSafetyGate.require_write()
            if self._before_request is not None:
                await self._before_request()
            if self._write:
                from services.actions.safety import ActionSafetyGate

                ActionSafetyGate.require_write()
            try:
                response = await self._client.request(
                    method, path, params=params, json=dict(payload) if payload is not None else None
                )
            except httpx.TransportError:
                if self._write:
                    raise ActionOutcomeUnknown("Command outcome unknown; reconcile before retrying") from None
                if attempt + 1 < attempts:
                    await asyncio.sleep(self._retry_delay * (2**attempt))
                    continue
                raise TransportUnavailable("MetricFlow is unreachable") from None

            status = response.status_code
            if status == 429:
                retry_after = response.headers.get("Retry-After", "")
                seconds = int(retry_after) if retry_after.isascii() and retry_after.isdigit() else None
                # Limits can be daily. Let the scheduler choose when to resume.
                raise RateLimitExceeded(seconds)
            if status == 401:
                raise AuthenticationError(status)
            if status == 403:
                raise PermissionDenied(status)
            if status == 402:
                raise SubscriptionRequired(status)
            if status >= 500 or status == 408:
                if self._write:
                    raise ActionOutcomeUnknown("Command outcome unknown; reconcile before retrying")
                if attempt + 1 < attempts:
                    await asyncio.sleep(self._retry_delay * (2**attempt))
                    continue
            if not 200 <= status < 300:
                raise APIError(status)
            if status == 204:
                return {}
            try:
                result = response.json()
                if not isinstance(result, (dict, list)):
                    raise ValueError("Expected an object or array")
            except (ValueError, UnicodeError):
                if self._write:
                    raise ActionOutcomeUnknown("Command returned an unreadable result; reconcile before retrying") from None
                raise InvalidResponse("MetricFlow returned an invalid JSON response") from None
            return result
        raise AssertionError("Unreachable")
