"""Request-bound rule admission for the existing single-attempt experimental pilot."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services.actions.reported_spend import POLICY, STRICT
from services.actions.reported_spend import STATEMENT as SPEND_STATEMENT
from services.providers.contracts import WriteDisabled

STATEMENT = "AUTHORIZE_ONE_EXPERIMENTAL_RULE_PAUSE_WITH_UNVERIFIED_ID"


class RulePilotBinding(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    automation_generation: int = Field(ge=0)
    evidence_policy: Literal["STRICT_FINANCIAL", "CREO03_REPORTED_SPEND15_V1"] = STRICT


def require_rule_source(session, row, binding, now: datetime) -> None:
    """Recompute a positive eligible decision; never turn REVIEW into an action."""
    from services.actions.pilot_contract import fingerprint
    from services.automation.control import state
    from services.automation.smart_models import RuleSimulation
    from services.automation.smart_simulation import check_preparation

    source = row.provenance.get("rule_source")
    if not source and binding is None:
        return
    if (
        not isinstance(source, dict)
        or not isinstance(binding, RulePilotBinding)
        or row.action != "PAUSE_AD"
        or source.get("operation") != row.action
        or fingerprint(source) != binding.source_sha256
        or source.get("evidence_policy", STRICT) != binding.evidence_policy
    ):
        raise WriteDisabled("RULE_PILOT_BINDING_CHANGED")
    control = state(session, row.workspace_id)
    if control["stopped"] or control["generation"] != binding.automation_generation:
        raise WriteDisabled("RULE_PILOT_AUTOMATION_CHANGED")
    run = session.get(RuleSimulation, source.get("simulation_id"))
    if (
        not run
        or run.workspace_id != row.workspace_id
        or run.rule_id != source.get("rule_id")
        or run.revision != source.get("rule_revision")
    ):
        raise WriteDisabled("RULE_PILOT_SIMULATION_CHANGED")
    try:
        card = check_preparation(
            session,
            row.workspace_id,
            run,
            row.entity_id,
            row.action,
            now,
            current_request_id=row.id,
            evidence_policy=binding.evidence_policy,
        )
    except HTTPException:
        raise WriteDisabled("RULE_PILOT_CURRENT_DECISION_HELD") from None
    if binding.evidence_policy == POLICY:
        if (
            card.get("decision_key") != source.get("decision_key")
            or card.get("reported_spend_test_eligible") is not True
        ):
            raise WriteDisabled("RULE_PILOT_SPEND_EVIDENCE_HELD")
        return
    if (
        card.get("decision_key") != source.get("decision_key")
        or card.get("status") != "WOULD_PAUSE"
        or card.get("condition_matched") != "TRUE"
        or card.get("safe_to_consider_for_future_action") is not True
    ):
        raise WriteDisabled("RULE_PILOT_EVIDENCE_HELD")


def bind_rule_source(session, row, now: datetime) -> RulePilotBinding | None:
    """Pin a local proposal, without authorizing or dispatching a provider call."""
    from services.actions.pilot_contract import fingerprint
    from services.automation.control import state

    source = row.provenance.get("rule_source")
    if not source:
        return None
    binding = RulePilotBinding(
        source_sha256=fingerprint(source),
        automation_generation=state(session, row.workspace_id)["generation"],
        evidence_policy=source.get("evidence_policy", STRICT),
    )
    require_rule_source(session, row, binding, now)
    return binding


def authorization_statement(source: dict) -> str:
    return SPEND_STATEMENT if source.get("evidence_policy") == POLICY else STATEMENT
