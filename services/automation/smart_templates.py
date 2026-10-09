"""Unassigned editable template configurations, never automatically scheduled."""

from __future__ import annotations

from services.automation.smart_schema import SmartRuleInput


def templates() -> list[dict]:
    result = []
    for name, conditions in (
        ("Высокая цена лида", [{"type": "CPL_ABOVE_LIMIT"}]),
        (
            "Прогнозный ROI ниже минимума",
            [{"type": "ROI_BELOW_MINIMUM", "source": "estimated"}],
        ),
        (
            "Расход без лидов",
            [{"type": "NO_LEADS_SPEND", "limit": "custom", "value": "20"}],
        ),
        (
            "Высокая стоимость подтверждённой продажи",
            [{"type": "CPS_ABOVE_LIMIT", "source": "approved"}],
        ),
        (
            "CPL и прогнозный ROI",
            [
                {"type": "CPL_ABOVE_LIMIT"},
                {"type": "ROI_BELOW_MINIMUM", "source": "estimated"},
            ],
        ),
    ):
        rule = SmartRuleInput.model_validate(
            {
                "name": name,
                "expression": {
                    "children": [{"kind": "condition", **c} for c in conditions]
                },
            }
        )
        result.append(rule.model_dump(mode="json"))
    return result
