"""LLM output expresses intent; all permissions and calculations stay in Python."""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CopilotPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["OFF", "READ_ONLY", "RECOMMEND", "APPROVAL", "AUTOPILOT"] = "OFF"
    allow_enable: bool = False
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    max_change_percent: Decimal = Field(default=Decimal("20"), gt=0, le=20, allow_inf_nan=False)
    max_daily_budget: Decimal = Field(default=Decimal("300"), gt=0, le=300, allow_inf_nan=False)
    max_actions_per_day: int = Field(default=30, ge=1, le=30)
    max_analyses_per_day: int = Field(default=20, ge=1, le=100)
    # A verified daily budget interpretation is required separately from the
    # provider's encoding contract. Lifetime budgets cannot use this ceiling.
    daily_budget_verified: bool = False
    proposal_ttl_minutes: int = Field(default=15, ge=1, le=30)

    @model_validator(mode="before")
    @classmethod
    def legacy_mode(cls, data):
        if isinstance(data, dict) and data.get("mode") == "COPILOT":
            return {**data, "mode": "RECOMMEND"}
        return data

    @property
    def autonomy_level(self):
        return {"READ_ONLY": 0, "RECOMMEND": 1, "APPROVAL": 2, "AUTOPILOT": 3}.get(self.mode)


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str = Field(min_length=1, max_length=36)
    action: Literal["leave_unchanged", "pause", "enable", "budget_change"]
    change_percent: float | None = Field(ge=-100, le=100, allow_inf_nan=False)
    confidence: int = Field(ge=0, le=100)
    reason: str = Field(min_length=1, max_length=1200)
    evidence: list[str] = Field(min_length=1, max_length=12)
    priority: int = Field(ge=1, le=5)

    @model_validator(mode="after")
    def operation(self):
        if (self.action == "budget_change") != (self.change_percent is not None):
            raise ValueError("Only budget_change takes a percentage")
        if self.change_percent == 0:
            raise ValueError("Budget change cannot be zero")
        return self


class CopilotOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=2000)
    proposals: list[Proposal] = Field(max_length=30)


def output_schema():
    """Required, nullable percentage is compatible with strict Structured Outputs."""
    return CopilotOutput.model_json_schema()
