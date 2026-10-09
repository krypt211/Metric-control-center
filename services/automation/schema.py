from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Operation(Strict):
    kind: Literal["pause", "enable", "budget_set", "budget_change"]
    value: Decimal | None = Field(default=None, allow_inf_nan=False, max_digits=24, decimal_places=8)

    @model_validator(mode="after")
    def validate_value(self):
        if self.kind in ("pause", "enable"):
            if self.value is not None:
                raise ValueError("Status operations do not accept a value")
        elif self.value is None:
            raise ValueError("Budget operation needs a value")
        elif self.kind == "budget_set" and self.value <= 0:
            raise ValueError("Budget must be positive")
        elif self.kind == "budget_change" and (self.value == 0 or not -100 < self.value <= 100):
            raise ValueError("Percentage must be nonzero and between -100 and 100")
        return self

    def command(self, budget):
        if self.kind == "budget_change":
            if budget is None or budget <= 0:
                raise ValueError("Current budget is unknown")
            return "budget_set", (Decimal(budget) * (1 + self.value / 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return self.kind, self.value


class BulkCommand(Strict):
    # Internal UUIDs disambiguate equal provider IDs in different accounts.
    entity_ids: list[str] = Field(min_length=1, max_length=200)
    operation: Operation

    @model_validator(mode="after")
    def unique_entities(self):
        if len(set(self.entity_ids)) != len(self.entity_ids) or any(not value or len(value) > 36 for value in self.entity_ids):
            raise ValueError("Select unique entity IDs")
        return self


class Condition(Strict):
    metric: Literal["spend", "impressions", "clicks", "ctr", "cpc", "cpm", "leads", "sales", "conversions", "revenue", "profit", "roi", "cpl", "cpa", "cr", "epc"]
    operator: Literal[">=", ">", "<=", "<", "=", "!="]
    value: Decimal = Field(allow_inf_nan=False, max_digits=24, decimal_places=8)


class RuleDefinition(Strict):
    name: str = Field(min_length=1, max_length=128)
    level: Literal["campaign", "adset", "ad"] = "adset"
    window: Literal["today", "yesterday", "last3", "last7", "last14", "last30"] = "today"
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    timezone: str = "Europe/Moscow"
    account_ids: list[str] = Field(default_factory=list, max_length=200)
    conditions: list[Condition] = Field(min_length=1, max_length=20)
    operation: Operation
    max_budget: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False, max_digits=24, decimal_places=8)
    cooldown_seconds: int = Field(default=28800, ge=60, le=604800)
    interval_seconds: int = Field(default=300, ge=60, le=86400)
    minimum_events: int = Field(default=0, ge=0, le=2**63-1)
    schedule_start: str = Field(default="00:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    schedule_end: str = Field(default="00:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def check(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown timezone") from None
        if self.operation.kind.startswith("budget") and (self.level == "ad" or self.max_budget is None):
            raise ValueError("Budget rules require campaign/adset level and a ceiling")
        if any(not value or len(value) > 36 for value in self.account_ids):
            raise ValueError("Invalid account ID")
        return self
