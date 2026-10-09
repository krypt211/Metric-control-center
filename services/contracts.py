"""Provider-independent boundaries. MetricFlow response schemas are not assumed."""

from datetime import date
from typing import Any, Mapping, Protocol

JSONPayload = dict[str, Any] | list[Any]
Query = Mapping[str, str | int | bool]


class StatisticsSource(Protocol):
    async def get_accounts(self, *, params: Query | None = None) -> JSONPayload: ...

    async def get_insights(
        self, start: date, end: date, *, params: Query | None = None
    ) -> JSONPayload: ...


class ActionSource(Protocol):
    async def pause_entity(self, entity_id: str) -> JSONPayload: ...

    async def enable_entity(self, entity_id: str) -> JSONPayload: ...

    async def change_budget(
        self, entity_id: str, *, provider_payload: Mapping[str, Any]
    ) -> JSONPayload: ...
