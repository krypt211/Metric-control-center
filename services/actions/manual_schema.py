"""Local status intentions; no provider execution or permission is conferred."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

STATUS_OPERATIONS = {
    "PAUSE_AD": "ad",
    "ENABLE_AD": "ad",
    "PAUSE_ADSET": "adset",
    "ENABLE_ADSET": "adset",
    "PAUSE_CAMPAIGN": "campaign",
    "ENABLE_CAMPAIGN": "campaign",
}


class ManualDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str = Field(min_length=1, max_length=36)
    account_id: str = Field(min_length=1, max_length=36)
    # Retain the original AD input name and fingerprint for existing drafts.
    meta_ad_id: str = Field(
        pattern=r"^[0-9]{1,128}$",
        validation_alias=AliasChoices("external_id", "meta_ad_id"),
    )
    entity_level: Literal["campaign", "adset", "ad"] = "ad"
    provider: Literal["metricflow", "meta"]
    operation: Literal[
        "PAUSE_AD",
        "ENABLE_AD",
        "PAUSE_ADSET",
        "ENABLE_ADSET",
        "PAUSE_CAMPAIGN",
        "ENABLE_CAMPAIGN",
    ]
    expected_status: Literal["ACTIVE", "PAUSED"]
    reason: str = Field(min_length=1, max_length=1000)
    simulation_id: str | None = Field(default=None, min_length=1, max_length=36)

    @model_validator(mode="after")
    def matching_level(self) -> Self:
        if STATUS_OPERATIONS[self.operation] != self.entity_level:
            raise ValueError("Operation and entity level must match")
        if self.entity_level != "ad" and (
            self.provider != "metricflow" or self.simulation_id
        ):
            raise ValueError(
                "Parent-level local commands require MetricFlow and no AD rule source"
            )
        return self

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("A meaningful reason is required")
        return value.strip()


class ManualTransitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)


class RuleDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    simulation_id: str = Field(min_length=1, max_length=36)
    entity_id: str = Field(min_length=1, max_length=36)
