"""Reference monetary examples and critical unknown/maturity boundaries."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from services.economics.core import Evidence, calculate
from services.economics.schema import ObservationInput, ProfileInput


def profile(**kwargs: object) -> ProfileInput:
    return ProfileInput.model_validate(
        {
            "name": "Test",
            "payout": "16",
            "currency": "USD",
            "target_roi": "20",
            "minimum_roi": "0",
            "planned_approval_rate": "0.30",
            **kwargs,
        }
    )


@pytest.mark.parametrize(
    "approval,target,maximum",
    [
        ("0.2", "2.66666667", "3.20000000"),
        ("0.3", "4.00000000", "4.80000000"),
        ("0", "0.00000000", "0.00000000"),
    ],
)
def test_reference_cpl(approval: str, target: str, maximum: str) -> None:
    result = calculate(profile(planned_approval_rate=approval), Evidence(D(40), 10, 2))
    assert result["target_cpl"] == target
    assert result["maximum_cpl"] == maximum
    assert result["target_approved_cps"] == "13.33333333"
    assert result["maximum_approved_cps"] == "16.00000000"


def test_forecast_and_manual_actual_are_separate() -> None:
    facts = Evidence(D(40), 10, 9)
    result = calculate(profile(), facts)
    assert result["estimated_revenue"] == "48.00000000"
    assert result["estimated_roi"] == "20.00000000"
    assert result["actual_roi"] is None
    assert result["approved_sales"] is None
    assert result["eligible_for_rule_evaluation"] is False
    actual = calculate(
        profile(),
        replace(
            facts,
            spend=D(60),
            approved=3,
            rejected=7,
            pending=0,
            actual_revenue=D(48),
            compatible=True,
            mature=True,
            source="ACTUAL_MANUAL",
        ),
    )
    assert actual["actual_roi"] == "-20.00000000"
    assert actual["approved_cps"] == "20.00000000"
    assert actual["economics_status"] == "BELOW_MINIMUM"
    assert actual["economics_data_quality"] == "ACTUAL_MANUAL"


@pytest.mark.parametrize("spend,leads", [(None, 10), (D(0), 10), (D(10), None)])
def test_unknown_and_zero_spend(spend: D | None, leads: int | None) -> None:
    result = calculate(profile(), Evidence(spend, leads, 100))
    assert result["actual_roi"] is None
    if spend is None or spend == 0 or leads is None:
        assert result["estimated_roi"] is None
    assert result["eligible_for_rule_evaluation"] is False


@pytest.mark.parametrize("roi", ["-100", "-101", "NaN", "Infinity"])
def test_invalid_roi_denominator(roi: str) -> None:
    with pytest.raises(ValidationError):
        profile(minimum_roi=roi)


@pytest.mark.parametrize(
    "values",
    [
        {"target_roi": "-1", "minimum_roi": "0"},
        {"payout": 16.1},
        {"planned_approval_rate": "1.01"},
        {"minimum_leads": True},
        {"minimum_sales": -1},
    ],
)
def test_validation(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        profile(**values)


@pytest.mark.parametrize(
    "processed,mature,source",
    [(29, True, "PLANNED"), (30, False, "PLANNED"), (30, True, "ACTUAL_MANUAL")],
)
def test_actual_approval_requires_explicit_policy_and_mature_sample(
    processed: int, mature: bool, source: str
) -> None:
    facts = Evidence(
        D(40),
        10,
        9,
        observed_rate=D("0.4"),
        processed=processed,
        mature=mature,
        source="ACTUAL_MANUAL",
    )
    result = calculate(profile(actual_approval_policy="mature_actual"), facts)
    assert result["approval_source"] == source
    expected = "5.33333333" if source == "ACTUAL_MANUAL" else "4.00000000"
    assert result["target_cpl"] == expected
    assert calculate(profile(), facts)["approval_source"] == "PLANNED"


def test_inherited_approval_never_creates_ad_revenue_or_sales() -> None:
    result = calculate(
        profile(actual_approval_policy="mature_actual"),
        Evidence(
            D(40),
            10,
            3,
            approved=12,
            actual_revenue=D(192),
            compatible=True,
            inherited=True,
            mature=True,
            processed=40,
            observed_rate=D(".3"),
        ),
    )
    assert result["approval_source"] == "GROUP_MANUAL"
    assert result["actual_roi"] is None
    assert result["actual_revenue"] is None
    assert result["approved_sales"] is None
    assert result["eligible_for_rule_evaluation"] is False


def test_immature_loss_is_not_negative_assessment() -> None:
    result = calculate(
        profile(sale_threshold_type="observed"), Evidence(D(100), 10, 3, mature=False)
    )
    assert D(result["estimated_roi"]) < 0
    assert result["economics_status"] == "AWAITING_CONFIRMATION"


def test_manual_zero_revenue_is_a_real_zero() -> None:
    result = calculate(
        profile(),
        Evidence(
            D(40), 10, 0, approved=0, actual_revenue=D(0), compatible=True, mature=True
        ),
    )
    assert result["actual_roi"] == "-100.00000000"
    assert result["estimated_roi"] == "20.00000000"
    assert result["economics_status"] == "INSUFFICIENT_DATA"


def test_large_valid_money_uses_decimal_precision() -> None:
    result = calculate(
        profile(payout="9999999999999999.99999999", minimum_roi="-99.99999999"),
        Evidence(D(1), 100000000, 0),
    )
    assert D(result["estimated_revenue"]) > D("1e23")
    assert D(result["maximum_cpl"]) > D("1e25")


def test_observations_require_cohort_and_revenue_confirmation() -> None:
    data = {
        "profile_id": "p",
        "cohort": "c",
        "start": "2026-10-01",
        "end": "2026-10-07",
        "approved": 3,
        "rejected": 7,
        "pending": 0,
        "payout": "16",
        "currency": "USD",
        "timezone": "Europe/Moscow",
        "source_provider": "metricflow",
    }
    observation = ObservationInput.model_validate(data)
    assert observation.revenue_confirmed is False
    with pytest.raises(ValidationError):
        ObservationInput.model_validate({**data, "actual_revenue": "48"})
    with pytest.raises(ValidationError):
        ObservationInput.model_validate({**data, "timezone": "invalid/zone"})
