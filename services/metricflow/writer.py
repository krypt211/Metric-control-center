import re
from typing import Any, Mapping, Self

import httpx

from services.contracts import JSONPayload

from .transport import MetricFlowTransport


class MetricFlowActionConnector:
    """POST-only transport for the action process. Never retries commands."""

    def __init__(self, write_key: str, *, transport: httpx.AsyncBaseTransport | None = None):
        self._http = MetricFlowTransport(write_key, write=True, transport=transport)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.close()

    @staticmethod
    def _path(entity_id: str, operation: str) -> str:
        if not re.fullmatch(r"[0-9]+", entity_id):
            raise ValueError("Entity ID must be a numeric provider ID")
        return f"entities/{entity_id}/{operation}"

    async def pause_entity(self, entity_id: str) -> JSONPayload:
        return await self._http.request("POST", self._path(entity_id, "pause"))

    async def enable_entity(self, entity_id: str) -> JSONPayload:
        return await self._http.request("POST", self._path(entity_id, "enable"))

    async def change_budget(self, entity_id: str, *, provider_payload: Mapping[str, Any]) -> JSONPayload:
        # Units, keys and campaign/adset budget semantics need live verification.
        # Do not invent a {budget: value} contract from the endpoint name.
        if not provider_payload:
            raise ValueError("Provide a verified MetricFlow budget request payload")
        return await self._http.request(
            "POST", self._path(entity_id, "budget"), payload=provider_payload
        )
