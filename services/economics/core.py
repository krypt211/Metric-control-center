"""Pure Decimal calculations. Observed purchases never imply approved sales."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

from services.economics.schema import ProfileInput

D = Decimal
HUNDRED = D(100)


def serial(value: Decimal | None) -> str | None:
    """Return a stable decimal string without a binary float conversion."""
    with localcontext() as context:
        context.prec = 64
        return (
            format(value.quantize(D("0.00000001"), rounding=ROUND_HALF_UP), "f")
            if value is not None
            else None
        )


def ratio(
    numerator: Decimal | None, denominator: Decimal | int | None
) -> Decimal | None:
    """Preserve unknown values and avoid dividing by zero."""
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / D(denominator)


@dataclass(frozen=True)
class Evidence:
    spend: Decimal | None
    leads: int | None
    purchases: int | None
    approved: int | None = None
    rejected: int | None = None
    pending: int | None = None
    actual_revenue: Decimal | None = None
    compatible: bool = False
    mature: bool = False
    inherited: bool = False
    observed_rate: Decimal | None = None
    processed: int = 0
    source: str = "PLANNED"
    facts_source: str = "metricflow"
    reason_codes: tuple[str, ...] = ()


def calculate(profile: ProfileInput, facts: Evidence) -> dict[str, Any]:
    """Use enough precision for the full validated monetary domain."""
    with localcontext() as context:
        context.prec = 64
        return _calculate(profile, facts)


def _calculate(profile: ProfileInput, facts: Evidence) -> dict[str, Any]:
    """Calculate forecast and separately proven manual financial results."""
    rate = profile.planned_approval_rate
    applied_source = "PLANNED"
    reasons = list(facts.reason_codes)
    if profile.actual_approval_policy == "mature_actual":
        if (
            facts.observed_rate is not None
            and facts.processed >= profile.minimum_processed
            and facts.mature
        ):
            rate = facts.observed_rate
            applied_source = "GROUP_MANUAL" if facts.inherited else "ACTUAL_MANUAL"
        else:
            reasons.append("ACTUAL_APPROVAL_INSUFFICIENT")
    expected_per_lead = profile.payout * rate
    target_cpl = expected_per_lead / (1 + profile.target_roi / HUNDRED)
    maximum_cpl = expected_per_lead / (1 + profile.minimum_roi / HUNDRED)
    estimated_sales = D(facts.leads) * rate if facts.leads is not None else None
    estimated_revenue = (
        estimated_sales * profile.payout if estimated_sales is not None else None
    )
    estimated_roi = ratio(
        estimated_revenue - facts.spend
        if estimated_revenue is not None and facts.spend is not None
        else None,
        facts.spend,
    )
    actual_revenue = (
        facts.actual_revenue if facts.compatible and not facts.inherited else None
    )
    approved = facts.approved if facts.compatible and not facts.inherited else None
    actual_roi = ratio(
        actual_revenue - facts.spend
        if actual_revenue is not None and facts.spend is not None
        else None,
        facts.spend,
    )
    approved_cps = ratio(facts.spend, approved)
    sales = {
        "approved": approved,
        "observed": facts.purchases,
        "estimated": estimated_sales,
    }[profile.sale_threshold_type]
    lead_sample = facts.leads is not None and facts.leads >= profile.minimum_leads
    sale_sample = sales is not None and sales >= profile.minimum_sales
    sample = lead_sample and sale_sample
    score = actual_roi if actual_roi is not None else estimated_roi
    if not facts.compatible and actual_revenue is None:
        reasons.append("ACTUAL_REVENUE_UNCONFIRMED")
    if facts.spend is None or facts.leads is None:
        reasons.append("UNKNOWN_FACTS")
    if facts.spend == 0:
        reasons.append("ZERO_SPEND")
    if not sample:
        reasons.append("INSUFFICIENT_SAMPLE")
    if not facts.mature:
        reasons.append("IMMATURE_DATA")
    if score is None:
        status = "UNKNOWN"
    elif not facts.mature:
        status = "AWAITING_CONFIRMATION"
    elif not sample:
        status = "INSUFFICIENT_DATA"
    elif score * HUNDRED >= profile.target_roi:
        status = "TARGET_MET"
    elif score * HUNDRED >= profile.minimum_roi:
        status = "WITHIN_MINIMUM"
    else:
        status = "BELOW_MINIMUM"
    eligible = bool(
        not {
            "SOURCE_STALE",
            "UNKNOWN_FACTS",
            "OBSERVATION_SOURCE_MISMATCH",
        }.intersection(reasons)
        and facts.mature
        and facts.compatible
        and not facts.inherited
        and actual_roi is not None
        and lead_sample
        and approved is not None
        and approved >= profile.minimum_sales
    )
    quality = (
        "ACTUAL_MANUAL"
        if actual_roi is not None
        else "ESTIMATED"
        if estimated_roi is not None
        else "UNKNOWN"
    )
    actual_cpl = ratio(facts.spend, facts.leads)
    numeric = {
        "payout": profile.payout,
        "planned_approval_rate": profile.planned_approval_rate,
        "applied_approval_rate": rate,
        "observed_approval_rate": facts.observed_rate,
        "expected_revenue_per_lead": expected_per_lead,
        "target_roi": profile.target_roi,
        "minimum_roi": profile.minimum_roi,
        "target_cpl": target_cpl,
        "maximum_cpl": maximum_cpl,
        "target_approved_cps": profile.payout / (1 + profile.target_roi / HUNDRED),
        "maximum_approved_cps": profile.payout / (1 + profile.minimum_roi / HUNDRED),
        "actual_cpl": actual_cpl,
        "observed_purchase_cost": ratio(facts.spend, facts.purchases),
        "approved_cps": approved_cps,
        "estimated_sales": estimated_sales,
        "estimated_revenue": estimated_revenue,
        "actual_revenue": actual_revenue,
        "estimated_roi": estimated_roi * HUNDRED if estimated_roi is not None else None,
        "actual_roi": actual_roi * HUNDRED if actual_roi is not None else None,
        "cpl_deviation": actual_cpl - target_cpl if actual_cpl is not None else None,
    }
    values: dict[str, Any] = {key: serial(value) for key, value in numeric.items()}
    values.update(
        {
            "approved_sales": approved,
            "rejected_sales": facts.rejected if not facts.inherited else None,
            "pending_sales": facts.pending if not facts.inherited else None,
            "approval_source": applied_source,
            "approval_observation_source": facts.source,
            "processed_decisions": facts.processed,
            "minimum_processed": profile.minimum_processed,
            "minimum_leads": profile.minimum_leads,
            "minimum_sales": profile.minimum_sales,
            "sale_threshold_type": profile.sale_threshold_type,
            "sample_sufficient": sample,
            "maturity_status": "MATURE" if facts.mature else "IMMATURE",
            "economics_status": status,
            "economics_data_quality": quality,
            "status_basis": "ACTUAL_MANUAL" if actual_roi is not None else "ESTIMATED",
            "eligible_for_rule_evaluation": eligible,
            "actions_enabled": False,
            "reason_codes": sorted(set(reasons)),
            "currency": profile.currency,
        }
    )
    values["metric_provenance"] = {
        key: {
            "source": facts.source
            if key in {"actual_revenue", "actual_roi", "approved_cps"}
            else applied_source,
            "quality": "UNKNOWN"
            if value is None
            else "ACTUAL_MANUAL"
            if key in {"actual_revenue", "actual_roi", "approved_cps"}
            else "ESTIMATED",
        }
        for key, value in values.items()
        if key in numeric
    }
    for key in ("actual_cpl", "observed_purchase_cost"):
        values["metric_provenance"][key] = {
            "source": facts.facts_source,
            "quality": "ACTUAL_VERIFIED" if values[key] is not None else "UNKNOWN",
        }
    values["metric_provenance"]["observed_approval_rate"] = {
        "source": facts.source,
        "quality": "ACTUAL_MANUAL" if facts.observed_rate is not None else "UNKNOWN",
    }
    return values
