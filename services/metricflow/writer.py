"""Documented AD wire format; LIVE execution remains behind ActionSafetyGate."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from services.contracts import JSONPayload

from .errors import ActionOutcomeUnknown, InvalidResponse
from .transport import MetricFlowTransport

ENTITY_WRITE_SCOPE = "entities:write"


class ActionAcknowledgement(BaseModel):
    """Provider acknowledgement, never proof of configured/effective AD state."""

    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    success: bool
    entity_id: str
    message: str = Field(repr=False)
    job_id: int | None = Field(default=None, gt=0)


class ActionJobItem(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    entity_id: str
    success: bool
    error: str | None = Field(default=None, repr=False)


class ActionJob(BaseModel):
    """Documented job status. Even success needs separate fresh READ verification."""

    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    job_id: int = Field(gt=0)
    action_type: Literal["status"]
    status: Literal["pending", "running", "success", "partial", "failed", "expired"]
    total: int = Field(ge=0)
    done: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    results: list[ActionJobItem] | None = None
    error_message: str | None = Field(default=None, repr=False)
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    meta: dict[str, Any]


def decode_action_job(
    payload: JSONPayload, *, job_id: int, entity_id: str
) -> ActionJob:
    """Decode one AD job without polling, retrying, or marking an action verified."""
    if type(job_id) is not int or job_id < 1:
        raise ValueError("A positive job ID is required")
    try:
        job = ActionJob.model_validate(payload)
    except ValidationError:
        raise InvalidResponse("Invalid action job response") from None
    items = job.results or []
    if (
        job.job_id != job_id
        or job.total != 1
        or job.done > job.total
        or job.succeeded + job.failed != job.done
        or len(items) > 1
        or any(item.entity_id != entity_id for item in items)
        or (items and len(items) != job.done)
        or (items and sum(item.success for item in items) != job.succeeded)
        or (
            job.status == "success"
            and (job.done != 1 or job.succeeded != 1 or len(items) != 1)
        )
    ):
        raise InvalidResponse("Action job correlation or counts are inconsistent")
    return job


class MetricFlowActionConnector:
    """AD-only POST adapter, tested with mocks. Never retries commands.

    IDs are safe opaque path segments here, not verified provider IDs. Binding to
    the account/AD namespace is still a LIVE prerequisite. No job poller or budget
    contract is enabled by this adapter.
    """

    def __init__(
        self,
        write_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        before_request: Callable[[], Awaitable[None]] | None = None,
    ):
        self._http = MetricFlowTransport(
            write_key, write=True, transport=transport, before_request=before_request
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.close()

    @staticmethod
    def _path(entity_id: str, operation: str) -> str:
        # Local path-injection policy; not a claim about the provider ID namespace.
        if not isinstance(entity_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,128}", entity_id, flags=re.ASCII
        ):
            raise ValueError("Entity ID must be a safe opaque path segment")
        return f"entities/{entity_id}/{operation}"

    async def _status(
        self, entity_id: str, operation: str, *, asynchronous: bool
    ) -> ActionAcknowledgement:
        if type(asynchronous) is not bool:
            raise ValueError("Asynchronous must be a boolean")
        data = await self._http.request(
            "POST",
            self._path(entity_id, operation),
            params={"async": "true"} if asynchronous else None,
            payload={"level": "ad"},
            accepted_statuses=frozenset({200, 202} if asynchronous else {200}),
        )
        try:
            result = ActionAcknowledgement.model_validate(data)
        except ValidationError:
            raise ActionOutcomeUnknown(
                "Invalid action acknowledgement; reconcile"
            ) from None
        if (
            not result.success
            or result.entity_id != entity_id
            or (asynchronous and result.job_id is None)
            or (not asynchronous and result.job_id is not None)
        ):
            raise ActionOutcomeUnknown("Unconfirmed action acknowledgement; reconcile")
        return result

    async def pause_entity(
        self, entity_id: str, *, asynchronous: bool = False
    ) -> JSONPayload:
        result = await self._status(entity_id, "pause", asynchronous=asynchronous)
        return result.model_dump()

    async def enable_entity(
        self, entity_id: str, *, asynchronous: bool = False
    ) -> JSONPayload:
        result = await self._status(entity_id, "enable", asynchronous=asynchronous)
        return result.model_dump()

    async def change_budget(
        self, entity_id: str, *, provider_payload: Mapping[str, Any]
    ) -> JSONPayload:
        # Legacy synthetic transport coverage only; LIVE gate stays closed.
        if not provider_payload:
            raise ValueError("Provide a verified MetricFlow budget request payload")
        return await self._http.request(
            "POST", self._path(entity_id, "budget"), payload=provider_payload
        )
