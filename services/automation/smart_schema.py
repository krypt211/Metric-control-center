"""Bounded, declarative AD-only simulation contracts; no executable expressions."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from services.economics.schema import Contract

ConditionType = Literal[
    "ROI_BELOW_MINIMUM",
    "ROI_BELOW_TARGET",
    "CPL_ABOVE_LIMIT",
    "CPS_ABOVE_LIMIT",
    "NO_LEADS_SPEND",
    "NO_APPROVED_SALES_SPEND",
    "MINIMUM_LEADS_GATE",
    "MINIMUM_SALES_GATE",
    "SPEND_THRESHOLD",
]


class Condition(Contract):
    kind: Literal["condition"] = "condition"
    type: ConditionType
    source: Literal["actual", "estimated", "approved", "observed"] = "actual"
    limit: Literal["target", "maximum", "custom", "payout"] = "maximum"
    value: Decimal | None = Field(default=None, ge=0, max_digits=24, decimal_places=8)
    roi: Decimal | None = Field(default=None, gt=-100, le=1000000)
    multiplier: Decimal = Field(default=Decimal(1), gt=0, le=10000)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def meaningful(self) -> Condition:
        if (
            self.type
            in (
                "CPL_ABOVE_LIMIT",
                "NO_LEADS_SPEND",
                "SPEND_THRESHOLD",
                "MINIMUM_LEADS_GATE",
            )
            and self.source != "actual"
        ):
            raise ValueError("This condition uses observed spend and lead facts")
        if (
            self.type in ("CPL_ABOVE_LIMIT", "CPS_ABOVE_LIMIT")
            and self.limit == "payout"
        ):
            raise ValueError("Payout multiples are only valid for spend thresholds")
        if self.type.startswith("ROI_") and self.source not in ("actual", "estimated"):
            raise ValueError("ROI needs actual or estimated source")
        if self.type in (
            "CPS_ABOVE_LIMIT",
            "MINIMUM_SALES_GATE",
        ) and self.source not in ("approved", "observed", "estimated"):
            raise ValueError("Sales need approved, observed or estimated source")
        if self.limit == "custom" and self.value is None:
            raise ValueError("Custom threshold requires a decimal value")
        if self.type in ("NO_LEADS_SPEND", "NO_APPROVED_SALES_SPEND") and (
            self.limit != "custom" or self.value is None or self.value <= 0
        ):
            raise ValueError("Zero-event conditions require a positive spend threshold")
        if self.type in ("MINIMUM_LEADS_GATE", "MINIMUM_SALES_GATE") and (
            self.value is None or self.value != self.value.to_integral_value()
        ):
            raise ValueError("Sample threshold requires an integer count")
        return self


class Group(Contract):
    kind: Literal["group"] = "group"
    operator: Literal["AND", "OR"] = "AND"
    children: list[Condition | Group] = Field(min_length=1, max_length=20)


class Thresholds(Contract):
    minimum_spend: Decimal | None = Field(
        default=None, ge=0, max_digits=24, decimal_places=8
    )
    minimum_leads: int | None = Field(default=None, ge=0, le=100000000, strict=True)
    minimum_approved_sales: int | None = Field(
        default=None, ge=0, le=100000000, strict=True
    )
    minimum_observed_purchases: int | None = Field(
        default=None, ge=0, le=100000000, strict=True
    )
    minimum_processed: int | None = Field(default=None, ge=0, le=100000000, strict=True)
    minimum_data_age_hours: int | None = Field(default=None, ge=0, le=8760, strict=True)
    maturation_hours: int | None = Field(default=None, ge=0, le=8760, strict=True)


class Selection(Contract):
    account_ids: list[str] = Field(default_factory=list, max_length=20)
    provider: Literal["metricflow", "meta"] | None = None
    campaign: str | None = Field(default=None, max_length=36)
    adset: str | None = Field(default=None, max_length=36)
    ad: str | None = Field(default=None, max_length=36)
    offer: str | None = Field(default=None, max_length=128)
    geo: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    status: Literal["ACTIVE", "PAUSED"] | None = None

    @model_validator(mode="after")
    def unique(self) -> Selection:
        if len(set(self.account_ids)) != len(self.account_ids) or any(
            not key or len(key) > 36 for key in self.account_ids
        ):
            raise ValueError("Invalid account selection")
        return self


class SmartRuleInput(Contract):
    schema_version: Literal[3] = 3
    mode: Literal["DRY_RUN"] = "DRY_RUN"
    level: Literal["ad"] = "ad"
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    profile_id: str | None = Field(default=None, min_length=1, max_length=36)
    selection: Selection = Field(default_factory=Selection)
    period: Literal[
        "today", "yesterday", "last_3", "last_7", "last_14", "last_30", "custom"
    ] = "last_7"
    start: date | None = None
    end: date | None = None
    effective_start: date | None = None
    effective_end: date | None = None
    estimated_policy: Literal["review", "allow_simulated"] = "review"
    thresholds: Thresholds = Field(default_factory=Thresholds)
    expression: Group

    @model_validator(mode="after")
    def bounded(self) -> SmartRuleInput:
        if not self.name.strip() or any(ord(c) < 32 for c in self.name):
            raise ValueError("Invalid name")
        if self.period == "custom" and (
            self.start is None
            or self.end is None
            or self.start > self.end
            or (self.end - self.start).days >= 31
        ):
            raise ValueError("Custom period must contain 1 to 31 days")
        if (
            self.effective_start
            and self.effective_end
            and self.effective_start > self.effective_end
        ):
            raise ValueError("Invalid effective dates")
        count = 0

        def visit(node: Condition | Group, depth: int) -> None:
            nonlocal count
            count += 1
            if count > 40 or depth > 3:
                raise ValueError("Maximum 40 nodes and 3 group levels")
            if isinstance(node, Group):
                for child in node.children:
                    visit(child, depth + int(isinstance(child, Group)))

        visit(self.expression, 1)
        return self


class SmartRuleUpdate(SmartRuleInput):
    revision: int = Field(ge=1, strict=True)


def period(rule: SmartRuleInput, now: datetime) -> tuple[date, date]:
    """Completed days in Moscow; today's window remains explicitly incomplete."""
    today = now.astimezone(ZoneInfo("Europe/Moscow")).date()
    if rule.period == "custom":
        assert rule.start is not None and rule.end is not None
        first, last = rule.start, rule.end
    elif rule.period == "today":
        first = last = today
    else:
        days = 1 if rule.period == "yesterday" else int(rule.period[5:])
        last = today - timedelta(days=1)
        first = last - timedelta(days=days - 1)
    if last > today:
        raise ValueError("Future periods are not allowed")
    return first, last
