"""Rule truth tables, unknown facts, safeguards and immutable database history."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from test_economics import (
    ACTOR,
    CONFIG,
    DAY,
    END,
    NOW,
    EconomicsApiTests,
)
from test_economics import (
    store as economics_store,
)

from services.automation.smart_core import combine, condition, decision
from services.automation.smart_models import RuleSimulation, RuleVersion
from services.automation.smart_schema import Condition, SmartRuleInput, period
from services.automation.smart_simulation import simulate
from services.automation.smart_store import get_rule, save
from services.economics.core import Evidence, calculate
from services.economics.models import EconomicsEvaluation
from services.economics.schema import ProfileInput
from services.economics.store import change_profile, create_profile
from services.storage.models import ActionExecution, ActionRequest, DailyMetric


@pytest.fixture(name="store")
def rule_store():
    yield from economics_store.__wrapped__()


def config(**changes):
    return SmartRuleInput.model_validate(
        {
            "name": "Проверка",
            "period": "custom",
            "start": str(DAY),
            "end": str(END),
            "expression": {
                "children": [{"kind": "condition", "type": "CPL_ABOVE_LIMIT"}]
            },
            **changes,
        }
    )


def facts(**changes):
    return {
        "id": "d",
        "profile_id": "p",
        "profile_currency": "USD",
        "currency": "USD",
        "timezone": "Europe/Moscow",
        "period_start": str(DAY),
        "period_end": str(END),
        "source_attribution": "7d_click",
        "source_stale": False,
        "window_complete": True,
        "spend": "58",
        "leads": 10,
        "observed_meta_purchases": 5,
        **calculate(
            ProfileInput.model_validate(CONFIG), Evidence(D(58), 10, 5, mature=True)
        ),
        **changes,
    }


@pytest.mark.parametrize(
    "op,a,b,expected",
    [
        ("AND", "TRUE", "TRUE", "TRUE"),
        ("AND", "TRUE", "FALSE", "FALSE"),
        ("AND", "TRUE", "UNKNOWN", "UNKNOWN"),
        ("AND", "FALSE", "UNKNOWN", "FALSE"),
        ("AND", "UNKNOWN", "UNKNOWN", "UNKNOWN"),
        ("OR", "TRUE", "UNKNOWN", "TRUE"),
        ("OR", "FALSE", "UNKNOWN", "UNKNOWN"),
        ("OR", "FALSE", "FALSE", "FALSE"),
        ("OR", "UNKNOWN", "UNKNOWN", "UNKNOWN"),
    ],
)
def test_truth_tables(op, a, b, expected):
    assert combine(op, [a, b]) == expected
    assert combine(op, [b, a]) == expected


def test_forecast_signal_and_simulation_policy():
    row = facts()
    assert row["actual_cpl"] == "5.80000000"
    assert row["maximum_cpl"] == "4.80000000"
    assert row["estimated_roi"] == "-17.24137931"
    r = config(
        expression={
            "children": [
                {
                    "kind": "condition",
                    "type": "ROI_BELOW_MINIMUM",
                    "source": "estimated",
                }
            ]
        }
    )
    result = decision(r, row, CONFIG, NOW)
    assert result["condition_matched"] == "TRUE" and result["status"] == "REVIEW"
    result = decision(
        r.model_copy(update={"estimated_policy": "allow_simulated"}), row, CONFIG, NOW
    )
    assert result["status"] == "WOULD_PAUSE"
    assert result["action_eligibility"] is False and result["real_action"] is False
    assert not result["safe_to_consider_for_future_action"]


def test_zero_leads_exception_and_unknown_not_zero():
    r = config(
        expression={
            "children": [
                {
                    "kind": "condition",
                    "type": "NO_LEADS_SPEND",
                    "limit": "custom",
                    "value": "20",
                }
            ]
        }
    )
    row = facts(spend="25", leads=0)
    assert decision(r, row, CONFIG, NOW)["status"] == "WOULD_PAUSE"
    row["leads"] = None
    assert decision(r, row, CONFIG, NOW)["condition_matched"] == "UNKNOWN"
    assert decision(r, row, CONFIG, NOW)["status"] == "INSUFFICIENT_DATA"


def test_unknown_actual_and_three_value_expression():
    row = facts()
    assert row["approved_cps"] is None and row["actual_roi"] is None
    children = [
        {"kind": "condition", "type": "CPL_ABOVE_LIMIT"},
        {"kind": "condition", "type": "ROI_BELOW_MINIMUM"},
    ]
    assert (
        decision(
            config(expression={"operator": "AND", "children": children}),
            row,
            CONFIG,
            NOW,
        )["condition_matched"]
        == "UNKNOWN"
    )
    result = decision(
        config(
            expression={"operator": "OR", "children": children},
            thresholds={"minimum_approved_sales": 0, "minimum_processed": 0},
        ),
        row,
        CONFIG,
        NOW,
    )
    assert result["condition_matched"] == "TRUE" and result["status"] != "WOULD_PAUSE"


@pytest.mark.parametrize(
    "type,source",
    [
        ("CPL_ABOVE_LIMIT", "actual"),
        ("ROI_BELOW_MINIMUM", "estimated"),
        ("CPS_ABOVE_LIMIT", "approved"),
        ("SPEND_THRESHOLD", "actual"),
    ],
)
def test_currency_and_incomplete_guard(type, source):
    c = Condition(type=type, source=source)
    assert condition(c, facts(currency="EUR"))["truth"] == "UNKNOWN"
    assert condition(c, facts(window_complete=False))["truth"] == "UNKNOWN"
    assert (
        decision(config(), facts(window_complete=False), CONFIG, NOW)["status"]
        == "DATA_STALE"
    )


def test_cps_sources_and_maturity():
    row = facts(approved_sales=3, approved_cps="19.33333333", pending_sales=0)
    assert (
        condition(Condition(type="CPS_ABOVE_LIMIT", source="approved"), row)["truth"]
        == "TRUE"
    )
    assert (
        condition(Condition(type="CPS_ABOVE_LIMIT", source="observed"), row)["value"]
        == "11.60000000"
    )
    assert (
        condition(Condition(type="CPS_ABOVE_LIMIT", source="estimated"), row)["value"]
        == "19.33333333"
    )
    row["pending_sales"] = 5
    assert (
        condition(Condition(type="CPS_ABOVE_LIMIT", source="approved"), row)["truth"]
        == "UNKNOWN"
    )
    row["approved_sales"] = None
    assert (
        condition(
            Condition(type="NO_APPROVED_SALES_SPEND", limit="custom", value="20"), row
        )["truth"]
        == "UNKNOWN"
    )


def test_profile_approval_policy_reused():
    p = ProfileInput.model_validate(
        {**CONFIG, "actual_approval_policy": "mature_actual", "minimum_processed": 10}
    )
    matured = calculate(
        p,
        Evidence(
            D(58),
            10,
            5,
            approved=3,
            rejected=7,
            pending=0,
            mature=True,
            compatible=True,
            observed_rate=D("0.3"),
            processed=10,
        ),
    )
    assert matured["applied_approval_rate"] == "0.30000000"
    pending = calculate(
        p,
        Evidence(
            D(58),
            15,
            5,
            approved=3,
            rejected=7,
            pending=5,
            mature=False,
            compatible=True,
            observed_rate=D("0.3"),
            processed=10,
        ),
    )
    assert pending["approval_source"] == "PLANNED"
    assert "ACTUAL_APPROVAL_INSUFFICIENT" in pending["reason_codes"]


def test_missing_catalog_facts_remain_unknown_and_visible(store):
    with store.begin() as s:
        s.query(DailyMetric).delete()
        r = save(s, ACTOR, config())
        result = simulate(s, ACTOR, r["id"], 1, now=NOW)
        assert result["total"] == 1
        assert result["rows"][0]["leads"] is None
        assert result["rows"][0]["spend"] is None
        assert result["rows"][0]["status"] == "DATA_STALE"


def test_real_profile_revision_and_late_leads_preserve_rule_history(store):
    with store.begin() as s:
        p = create_profile(s, ACTOR, ProfileInput.model_validate(CONFIG))
        r = save(s, ACTOR, config(profile_id=p["id"]))
        first = simulate(s, ACTOR, r["id"], 1, now=NOW)
        old = deepcopy(first["rows"][0])
        assert old["profile_version"] == 1 and old["leads"] == 10
        change_profile(
            s,
            ACTOR,
            p["id"],
            1,
            ProfileInput.model_validate({**CONFIG, "payout": "20"}),
        )
        revised = simulate(s, ACTOR, r["id"], 1, now=NOW + timedelta(minutes=1))
        assert revised["rows"][0]["profile_version"] == 2
        assert revised["rows"][0]["economics_inputs"]["profile"]["payout"] == "20"
        metric = s.scalar(
            select(DailyMetric).where(
                DailyMetric.entity_id == "d", DailyMetric.day == DAY
            )
        )
        metric.leads += 2
        s.flush()
        late = simulate(s, ACTOR, r["id"], 1, now=NOW + timedelta(minutes=2))
        assert late["rows"][0]["leads"] == 12
        assert late["rows"][0]["actual_cpl"] != old["actual_cpl"]
        assert late["rows"][0]["changes_since_previous"]["leads"]["delta"] == "2"
        assert s.get(RuleSimulation, first["id"]).payload["rows"][0] == old
        assert old["economics_inputs"]["profile"]["payout"] == "16"
        assert late["rows"][0]["action_eligibility"] is False


def test_zero_rule_or_non_matching_count_does_not_require_leads():
    r = config(
        expression={
            "operator": "OR",
            "children": [
                {
                    "kind": "condition",
                    "type": "NO_LEADS_SPEND",
                    "limit": "custom",
                    "value": "20",
                },
                {
                    "kind": "condition",
                    "type": "MINIMUM_LEADS_GATE",
                    "limit": "custom",
                    "value": "10",
                },
            ],
        }
    )
    assert (
        decision(r, facts(spend="25", leads=0), CONFIG, NOW)["status"] == "WOULD_PAUSE"
    )


def test_simulation_time_and_selection_bounds_roll_back(store):
    with store.begin() as s:
        r = save(s, ACTOR, config())
    with pytest.raises(HTTPException) as e, store.begin() as s:  # noqa: SIM117 - assert transaction rollback around mocked deadline
        with (
            patch(
                "services.automation.smart_simulation.economics_adapter",
                return_value={
                    "rows": [facts()],
                    "start": str(DAY),
                    "end": str(END),
                    "sources": [],
                },
            ),
            patch(
                "services.automation.smart_simulation.monotonic", side_effect=[0, 11]
            ),
        ):
            simulate(s, ACTOR, r["id"], 1, now=NOW)
    assert e.value.detail == "SIMULATION_TIME_LIMIT_SELECT_SCOPE"
    with store() as s:
        assert s.scalar(select(func.count()).select_from(RuleSimulation)) == 0


def test_windows_and_schema_are_bounded():
    seven = config(period="last_7", start=None, end=None)
    assert period(seven, NOW) == (
        NOW.date() - timedelta(days=7),
        NOW.date() - timedelta(days=1),
    )
    for payload in (
        {"level": "adset"},
        {"mode": "ACTIVE"},
        {"period": "custom", "start": "2026-01-01", "end": "2026-10-01"},
        {"expression": {"children": [{"kind": "condition", "type": "eval('x')"}]}},
        {
            "expression": {
                "children": [
                    {
                        "kind": "condition",
                        "type": "CPL_ABOVE_LIMIT",
                        "limit": "custom",
                        "value": 1.5,
                    }
                ]
            }
        },
    ):
        with pytest.raises(ValidationError):
            config(**payload)
    expression = {"children": [{"kind": "condition", "type": "CPL_ABOVE_LIMIT"}]}
    for _ in range(3):
        expression = {"kind": "group", "children": [expression]}
    with pytest.raises(ValidationError):
        config(expression=expression)
    with pytest.raises(ValueError):
        period(config(start="2099-01-01", end="2099-01-02"), NOW)


def test_versions_cas_workspace_and_immutable_simulations(store):
    with store.begin() as s:
        p = create_profile(s, ACTOR, ProfileInput.model_validate(CONFIG))
        r = save(s, ACTOR, config(profile_id=p["id"]))
    with store.begin() as s:
        with pytest.raises(HTTPException) as e:
            save(s, ACTOR, config(), r["id"], 9)
        assert e.value.status_code == 409
    with store.begin() as s:
        with patch(
            "services.automation.smart_simulation.economics_adapter",
            return_value={
                "rows": [facts(profile_id=p["id"])],
                "start": str(DAY),
                "end": str(END),
                "sources": [],
            },
        ):
            first = simulate(s, ACTOR, r["id"], 1, now=NOW)
        frozen = deepcopy(first)
        updated = save(
            s, ACTOR, config(name="Изменено", profile_id=p["id"]), r["id"], 1
        )
        with patch(
            "services.automation.smart_simulation.economics_adapter",
            return_value={
                "rows": [facts(profile_id=p["id"], leads=12, actual_cpl="4.83333333")],
                "start": str(DAY),
                "end": str(END),
                "sources": [],
            },
        ):
            second = simulate(
                s, ACTOR, r["id"], updated["revision"], now=NOW + timedelta(minutes=1)
            )
        assert second["rows"][0]["changes_since_previous"]["leads"]["delta"] == "2"
        assert s.get(RuleSimulation, first["id"]).payload["rows"] == frozen["rows"]
        assert s.scalar(select(func.count()).select_from(RuleVersion)) == 2
        for model in (ActionRequest, ActionExecution):
            assert s.scalar(select(func.count()).select_from(model)) == 0
        with pytest.raises(HTTPException) as e:
            get_rule(s, "other", r["id"])
        assert e.value.status_code == 404
    with store.begin() as s:
        archived = save(s, ACTOR, None, r["id"], 2, deleted=True)
        assert archived["deleted"]
        restored = save(s, ACTOR, None, r["id"], 3, restore_revision=1)
        assert (
            restored["definition"]["name"] == "Проверка" and restored["revision"] == 4
        )


def test_real_economics_adapter_snapshot_and_no_fake_source(store):
    with store.begin() as s:
        p = create_profile(s, ACTOR, ProfileInput.model_validate(CONFIG))
        r = save(s, ACTOR, config(profile_id=p["id"]))
        result = simulate(s, ACTOR, r["id"], 1, now=NOW)
        assert result["total"] == 1
        row = result["rows"][0]
        assert (
            row["source_provider"] == "metricflow" and row["window_complete"] is False
        )
        assert row["status"] == "DATA_STALE"
        assert row["economics_inputs"]["profile"]["payout"] == "16"
        assert s.get(EconomicsEvaluation, row["evaluation_id"])
        assert not row["real_action"]
        meta = save(
            s, ACTOR, config(profile_id=p["id"], selection={"provider": "meta"})
        )
        assert simulate(s, ACTOR, meta["id"], 1, now=NOW)["total"] == 0


class SmartRulesApiTests(EconomicsApiTests):
    async def test_smart_rules_api_roles_history_csrf_and_no_actions(self):
        path = "/api/smart-rules"
        body = config().model_dump(mode="json")
        assert (await self.client.get(path)).status_code == 401
        for role in ("viewer", "operator"):
            await self.login(role)
            assert (await self.client.get(path)).status_code == 200
            assert (
                await self.client.post(path, headers=await self.csrf(), json=body)
            ).status_code == 403
        await self.login()
        assert (await self.client.post(path, json=body)).status_code == 403
        r = await self.client.post(path, headers=await self.csrf(), json=body)
        assert r.status_code == 201, r.text
        rule = r.json()
        endpoint = path + "/" + rule["id"]
        assert (
            await self.client.put(
                endpoint, headers=await self.csrf(), json={**body, "revision": 9}
            )
        ).status_code == 409
        result = await self.client.post(
            endpoint + "/simulate", headers=await self.csrf(), json={"version": 1}
        )
        assert result.status_code == 200, result.text
        assert result.json()["action_eligibility"] is False
        history = (await self.client.get(endpoint + "/history")).json()
        assert len(history["versions"]) == len(history["simulations"]) == 1
        assert (
            await self.client.post(
                path, headers=await self.csrf(), json={**body, "workspace_id": "other"}
            )
        ).status_code == 422
        assert (
            await self.client.post("/api/rules", headers=await self.csrf(), json={})
        ).status_code == 403
        assert (
            await self.client.post("/api/actions", headers=await self.csrf(), json={})
        ).status_code == 403
        with self.sessions() as s:
            assert s.scalar(select(func.count()).select_from(ActionRequest)) == 0
            oid = s.scalar(select(User.id).where(User.email == "operator"))
        response = await self.client.put(
            path + "/grants",
            headers=await self.csrf(),
            json={"user_id": oid, "can_edit": True},
        )
        assert response.status_code == 200
        await self.login("operator")
        assert (
            await self.client.post(path, headers=await self.csrf(), json=body)
        ).status_code == 201


from services.storage.models import User
