"""Only AD pause/enable intentions are accepted in Phase 4A."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ManualDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str = Field(min_length=1, max_length=36)
    account_id: str = Field(min_length=1, max_length=36)
    meta_ad_id: str = Field(pattern=r"^[0-9]{1,128}$")
    provider: Literal["metricflow", "meta"]
    operation: Literal["PAUSE_AD", "ENABLE_AD"]
    expected_status: Literal["ACTIVE", "PAUSED"]
    reason: str = Field(min_length=1, max_length=1000)
    simulation_id: str | None = Field(default=None, min_length=1, max_length=36)

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
