"""Validated contracts. All money and percentages enter as Decimal strings."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

Scope = Literal["profile", "account", "campaign", "adset", "ad"]
Money = Decimal


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @field_validator("*", mode="before")
    @classmethod
    def no_float(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("Use decimal strings, not floating point numbers")  # noqa: TRY004 - Pydantic validation must use ValueError
        return value


class ProfileInput(Contract):
    name: str = Field(min_length=1, max_length=120)
    offer: str = Field(default="", max_length=128)
    geo: str = Field(default="", pattern=r"^([A-Z]{2})?$")
    payout: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    target_roi: Decimal = Field(gt=-100, le=1000000, max_digits=16, decimal_places=8)
    minimum_roi: Decimal = Field(gt=-100, le=1000000, max_digits=16, decimal_places=8)
    planned_approval_rate: Decimal = Field(ge=0, le=1, max_digits=9, decimal_places=8)
    lead_source: Literal["meta", "tracker"] = "meta"
    minimum_leads: int = Field(default=10, ge=1, le=100000000, strict=True)
    minimum_spend: Decimal = Field(
        default=Decimal(0), ge=0, max_digits=24, decimal_places=8
    )
    minimum_observed_purchases: int = Field(default=0, ge=0, le=100000000, strict=True)
    minimum_data_age_hours: int = Field(default=0, ge=0, le=8760, strict=True)
    minimum_sales: int = Field(default=2, ge=0, le=100000000, strict=True)
    sale_threshold_type: Literal["approved", "observed", "estimated"] = "approved"
    minimum_processed: int = Field(default=30, ge=1, le=100000000, strict=True)
    maturation_hours: int = Field(default=72, ge=0, le=8760, strict=True)
    actual_approval_policy: Literal["planned", "mature_actual"] = "planned"

    @model_validator(mode="after")
    def ordered_roi(self) -> ProfileInput:
        if self.target_roi < self.minimum_roi:
            raise ValueError("Target ROI must be at least Minimum ROI")
        if not self.name.strip():
            raise ValueError("Profile name cannot be blank")
        return self


class ProfileUpdate(ProfileInput):
    version: int = Field(ge=1, strict=True)


class VersionInput(Contract):
    version: int = Field(ge=1, strict=True)


class RestoreInput(VersionInput):
    restore_version: int = Field(ge=1, strict=True)


class AssignmentInput(Contract):
    profile_id: str = Field(min_length=1, max_length=36)
    scope_type: Scope
    scope_id: str = Field(default="", max_length=36)
    effective_start: date
    effective_end: date | None = None

    @model_validator(mode="after")
    def dates(self) -> AssignmentInput:
        if self.effective_end and self.effective_end < self.effective_start:
            raise ValueError("Invalid effective dates")
        if (self.scope_type == "profile") != (self.scope_id == ""):
            raise ValueError("Entity scopes require an explicit entity ID")
        return self


class ObservationInput(Contract):
    profile_id: str = Field(min_length=1, max_length=36)
    scope_type: Scope = "profile"
    scope_id: str = Field(default="", max_length=36)
    cohort: str = Field(min_length=1, max_length=120)
    start: date
    end: date
    approved: int = Field(ge=0, le=100000000, strict=True)
    rejected: int = Field(ge=0, le=100000000, strict=True)
    pending: int = Field(ge=0, le=100000000, strict=True)
    payout: Decimal = Field(ge=0, max_digits=24, decimal_places=8)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    timezone: str = Field(min_length=1, max_length=64)
    source_provider: Literal["metricflow", "meta"]
    lead_source: Literal["meta", "tracker"] = "meta"
    decision_definition: Literal["lead_cohort"] = "lead_cohort"
    attribution_confirmed: StrictBool = False
    revenue_confirmed: StrictBool = False
    actual_revenue: Decimal | None = Field(
        default=None, ge=0, max_digits=24, decimal_places=8
    )
    comment: str = Field(default="", max_length=2000)
    version: int = Field(default=0, ge=0, strict=True)

    @model_validator(mode="after")
    def coherent(self) -> ObservationInput:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        if self.start > self.end:
            raise ValueError("Invalid cohort dates")
        if (self.scope_type == "profile") != (self.scope_id == ""):
            raise ValueError("Scope requires an explicit entity ID")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("Unknown timezone") from None
        if self.actual_revenue is not None and not self.revenue_confirmed:
            raise ValueError("Revenue requires explicit confirmation")
        return self


class GrantInput(Contract):
    user_id: str = Field(min_length=1, max_length=36)
    can_edit: StrictBool
