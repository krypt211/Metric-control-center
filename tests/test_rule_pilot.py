"""Rule-to-single-POST admission; every provider request uses MockTransport."""

from __future__ import annotations

import asyncio
import copy
from datetime import timedelta

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from test_economics import CONFIG
from test_experimental_pilot import (
    ACTOR,
    body,
    catalogs,
    confirm,
    fixture,
    input_body,
    response,
    setup,
)
from test_smart_rules import facts

from services.actions.engine import ActionRejected
from services.actions.experimental import STATEMENT as MANUAL_STATEMENT
from services.actions.experimental import prepare_experiment
from services.actions.pilot import authorize_pilot, execute_pilot
from services.actions.rule_pilot import STATEMENT
from services.automation.control import change
from services.automation.smart_schema import SmartRuleInput
from services.automation.smart_simulation import simulate
from services.automation.smart_store import save
from services.economics.schema import ProfileInput
from services.economics.store import create_profile
from services.providers.contracts import WriteDisabled
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    EntityCurrentState,
    Rule,
)

__all__ = ["fixture", "setup"]


@pytest.fixture
def rule_case(fixture, monkeypatch):
    _engine, sf, _vault, clock = fixture
    first = (clock[0] - timedelta(days=8)).date().isoformat()
    last = (clock[0] - timedelta(days=2)).date().isoformat()
    with sf.begin() as s:
        state = s.get(EntityCurrentState, "ad")
        state.status = "ACTIVE"
        state.raw = {}
        state.observed_at = clock[0]
        profile = create_profile(s, ACTOR, ProfileInput.model_validate(CONFIG))
        rule = save(
            s,
            ACTOR,
            SmartRuleInput.model_validate(
                {
                    "name": "Synthetic single rule pause",
                    "profile_id": profile["id"],
                    "period": "custom",
                    "start": first,
                    "end": last,
                    "expression": {
                        "children": [{"kind": "condition", "type": "CPL_ABOVE_LIMIT"}]
                    },
                }
            ),
        )
    row = facts(
        id="ad",
        external_id="1003",
        account_id="account",
        source_provider="metricflow",
        profile_id=profile["id"],
        period_start=first,
        period_end=last,
        eligible_for_rule_evaluation=True,
    )
    data = {"rows": [row], "sources": [], "start": first, "end": last}
    monkeypatch.setattr(
        "services.automation.smart_simulation.economics_adapter",
        lambda *args, **kwargs: copy.deepcopy(data),
    )
    with sf.begin() as s:
        run = simulate(s, ACTOR, rule["id"], 1, now=clock[0])
    assert run["rows"][0]["status"] == "WOULD_PAUSE"
    assert run["rows"][0]["safe_to_consider_for_future_action"] is True
    return run, data, rule["id"]


def prepare_rule(fixture, rule_case):
    engine, _sf, vault, clock = fixture
    calls = []
    card = asyncio.run(
        prepare_experiment(
            engine,
            ACTOR,
            input_body(simulation_id=rule_case[0]["id"]),
            vault=vault,
            transport=httpx.MockTransport(response(catalogs(clock[0]), calls)),
        )
    )
    return card, calls


def authorize_rule(fixture, rule_case, monkeypatch):
    engine, _sf, _vault, _clock = fixture
    card, calls = prepare_rule(fixture, rule_case)
    confirmed = confirm(engine, card)
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    permit = authorize_pilot(
        engine, ACTOR, confirmed["id"], body(confirmed, statement=STATEMENT)
    )
    return permit, calls


def test_rule_preparation_is_read_only_and_requires_distinct_authorization(
    fixture,
    rule_case,
    monkeypatch,
):
    engine, sf, _vault, _clock = fixture
    card, calls = prepare_rule(fixture, rule_case)
    assert len(calls) == 3 and all(c.method == "GET" for c in calls)
    assert card["rule_source"]["simulation_id"] == rule_case[0]["id"]
    assert card["authorization_statement_required"] == STATEMENT
    row = confirm(engine, card)
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    with pytest.raises(ActionRejected, match="PILOT_AUTHORIZATION_STATEMENT_MISMATCH"):
        authorize_pilot(engine, ACTOR, row["id"], body(row, statement=MANUAL_STATEMENT))
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0


@pytest.mark.parametrize("timeout", [False, True])
def test_rule_one_post_and_no_resend_even_after_timeout(
    fixture,
    rule_case,
    monkeypatch,
    timeout,
):
    engine, sf, vault, clock = fixture
    permit, _ = authorize_rule(fixture, rule_case, monkeypatch)
    calls = []
    transport = httpx.MockTransport(
        response(
            catalogs(clock[0]),
            calls,
            post_error="timeout" if timeout else None,
        )
    )
    asyncio.run(
        execute_pilot(
            engine,
            ACTOR,
            permit["id"],
            permit["revision"],
            vault=vault,
            transport=transport,
        )
    )
    assert [r.method for r in calls] == ["GET", "GET", "GET", "POST"]
    try:
        asyncio.run(
            execute_pilot(
                engine,
                ACTOR,
                permit["id"],
                permit["revision"],
                vault=vault,
                transport=transport,
            )
        )
    except (WriteDisabled, ActionRejected):
        pass
    assert sum(r.method == "POST" for r in calls) == 1
    with sf() as s:
        execution = s.scalar(select(ActionExecution))
        assert execution.outcome == ("live_unknown" if timeout else "live_acknowledged")
        assert s.get(EntityCurrentState, "ad").status == "ACTIVE"


@pytest.mark.parametrize(
    "change_kind",
    [
        "condition",
        "rule_revision",
        "attribution",
        "source",
        "stop_resume",
        "source_removed",
    ],
)
def test_changed_rule_evidence_prevents_post(
    fixture, rule_case, monkeypatch, change_kind
):
    engine, sf, vault, clock = fixture
    permit, _ = authorize_rule(fixture, rule_case, monkeypatch)
    if change_kind == "condition":
        rule_case[1]["rows"][0]["actual_cpl"] = "0.01"
    elif change_kind == "attribution":
        rule_case[1]["rows"][0]["source_attribution"] = None
    elif change_kind == "stop_resume":
        stopped = change(sf, ACTOR["workspace"], ACTOR["id"], True, clock=engine.clock)
        change(
            sf,
            ACTOR["workspace"],
            ACTOR["id"],
            False,
            generation=stopped["generation"],
            clock=engine.clock,
        )
    else:
        with sf.begin() as s:
            if change_kind == "rule_revision":
                s.get(Rule, rule_case[2]).revision += 1
            elif change_kind == "source":
                row = s.get(ActionRequest, permit["id"])
                source = dict(row.provenance["rule_source"])
                source["rule_revision"] += 1
                row.provenance = {**row.provenance, "rule_source": source}
            else:
                row = s.get(ActionRequest, permit["id"])
                row.provenance = {
                    k: v for k, v in row.provenance.items() if k != "rule_source"
                }
    calls = []
    with pytest.raises((WriteDisabled, ActionRejected)):
        asyncio.run(
            execute_pilot(
                engine,
                ACTOR,
                permit["id"],
                permit["revision"],
                vault=vault,
                transport=httpx.MockTransport(response(catalogs(clock[0]), calls)),
            )
        )
    assert not calls


def test_condition_changes_after_durable_claim_never_reaches_post(
    fixture,
    rule_case,
    monkeypatch,
):
    engine, sf, vault, clock = fixture
    permit, _ = authorize_rule(fixture, rule_case, monkeypatch)
    calls = []
    original = response(catalogs(clock[0]), calls)

    def changed(request):
        result = original(request)
        if len(calls) == 3:
            rule_case[1]["rows"][0]["actual_cpl"] = "0.01"
        return result

    asyncio.run(
        execute_pilot(
            engine,
            ACTOR,
            permit["id"],
            permit["revision"],
            vault=vault,
            transport=httpx.MockTransport(changed),
        )
    )
    assert [r.method for r in calls] == ["GET", "GET", "GET"]
    rule_case[1]["rows"][0]["actual_cpl"] = "100"
    try:
        asyncio.run(
            execute_pilot(
                engine,
                ACTOR,
                permit["id"],
                permit["revision"],
                vault=vault,
                transport=httpx.MockTransport(original),
            )
        )
    except (WriteDisabled, ActionRejected):
        pass
    assert all(r.method == "GET" for r in calls)
    with sf() as s:
        control = s.get(ActionRequest, permit["id"]).provenance["controlled"]
        assert control["attempts"] == 1
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 1


def test_rule_preparation_cannot_replace_existing_bound_evidence(fixture, rule_case):
    _engine, sf, _vault, _clock = fixture
    card, _ = prepare_rule(fixture, rule_case)
    with sf() as s:
        original = copy.deepcopy(s.get(ActionRequest, card["request_id"]).provenance)
    with pytest.raises(HTTPException, match="PENDING_ACTION_CONFLICT"):
        prepare_rule(fixture, rule_case)
    with sf() as s:
        assert s.get(ActionRequest, card["request_id"]).provenance == original
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0


def test_ineligible_rule_preparation_leaves_no_draft(fixture, rule_case):
    _engine, sf, _vault, _clock = fixture
    rule_case[1]["rows"][0]["eligible_for_rule_evaluation"] = False
    with pytest.raises(WriteDisabled, match="RULE_PILOT_EVIDENCE_HELD"):
        prepare_rule(fixture, rule_case)
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(ActionRequest)) == 0
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0


def test_failed_proof_rolls_back_draft_and_allows_retry(
    fixture, rule_case, monkeypatch
):
    _engine, sf, _vault, _clock = fixture
    from services.actions import experimental

    original = experimental.bind_rule_source

    def fail_proof(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_PROOF_FAILURE")

    monkeypatch.setattr(experimental, "bind_rule_source", fail_proof)
    with pytest.raises(RuntimeError, match="SYNTHETIC_PROOF_FAILURE"):
        prepare_rule(fixture, rule_case)
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(ActionRequest)) == 0
        assert s.scalar(select(func.count()).select_from(ActionLog)) == 0
    monkeypatch.setattr(experimental, "bind_rule_source", original)
    card, calls = prepare_rule(fixture, rule_case)
    assert card["status"] == "PREPARED_NO_POST_AUTHORIZATION"
    assert len(calls) == 3 and all(c.method == "GET" for c in calls)
