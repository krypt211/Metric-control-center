"""Exact-scope spend experiment; every provider request is MockTransport."""

from __future__ import annotations

import asyncio
import copy
from datetime import timedelta

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, update
from test_economics import CONFIG
from test_experimental_pilot import TOKEN, catalogs, fixture, setup
from test_smart_rules import facts

from services.actions.engine import ActionRejected
from services.actions.experimental import ExperimentalPrepareInput, prepare_experiment
from services.actions.pilot import (
    PilotAuthorizationInput,
    authorize_pilot,
    execute_pilot,
)
from services.actions.reported_spend import (
    ACCOUNT,
    ACK,
    AD,
    ADSET,
    CAMPAIGN,
    DAY,
    POLICY,
    STATEMENT,
)
from services.actions.rule_pilot import STATEMENT as STRICT_STATEMENT
from services.automation.smart_schema import SmartRuleInput
from services.automation.smart_simulation import simulate
from services.automation.smart_store import save
from services.economics.schema import ProfileInput
from services.economics.store import create_profile
from services.providers.contracts import WriteDisabled
from services.providers.integration_models import WriteCredentialState
from services.providers.models import (
    ProviderAccountMapping,
    ProviderConnection,
    ProviderRoutingSetting,
)
from services.storage.models import (
    ActionExecution,
    ActionRequest,
    AdAccount,
    Entity,
    EntityCurrentState,
    Rule,
    User,
)

__all__ = ["fixture", "setup"]
ACTOR = {"id": "admin", "workspace": "default", "role": "admin"}


@pytest.fixture
def spend_case(fixture, monkeypatch):
    _engine, sf, vault, clock = fixture
    with sf.begin() as s:
        old = s.get(User, "admin").workspace_id
        for model in (
            User,
            AdAccount,
            ProviderAccountMapping,
            ProviderConnection,
            ProviderRoutingSetting,
            WriteCredentialState,
        ):
            s.execute(
                update(model)
                .where(model.workspace_id == old)
                .values(workspace_id="default")
            )
        s.get(WriteCredentialState, "default").encrypted = vault.seal(
            "default", TOKEN, 1
        ).decode()
        account = s.get(AdAccount, "account")
        account.external_id, account.timezone = ACCOUNT, "America/Los_Angeles"
        s.get(ProviderAccountMapping, "account").meta_account_id = ACCOUNT
        for key, external in (("ad", AD), ("adset", ADSET), ("campaign", CAMPAIGN)):
            s.get(Entity, key).external_id = external
        state = s.get(EntityCurrentState, "ad")
        state.status, state.raw, state.observed_at = "ACTIVE", {}, clock[0]
        profile = create_profile(
            s,
            ACTOR,
            ProfileInput.model_validate({**CONFIG, "timezone": "America/Los_Angeles"}),
        )
        rule = save(
            s,
            ACTOR,
            SmartRuleInput.model_validate(
                {
                    "name": "Synthetic Creo03 spend test",
                    "profile_id": profile["id"],
                    "period": "custom",
                    "start": DAY.isoformat(),
                    "end": DAY.isoformat(),
                    "selection": {
                        "target_mode": True,
                        "targets": [
                            {
                                "scope_type": "AD",
                                "scope_id": "ad",
                                "account_id": "account",
                                "provider": "metricflow",
                            }
                        ],
                    },
                    "expression": {
                        "children": [
                            {
                                "type": "SPEND_THRESHOLD",
                                "source": "actual",
                                "limit": "custom",
                                "value": "15",
                                "currency": "USD",
                            }
                        ]
                    },
                }
            ),
        )
    row = facts(
        id="ad",
        external_id=AD,
        account_id="account",
        source_provider="metricflow",
        profile_id=profile["id"],
        profile_version=1,
        profile_currency="USD",
        timezone="America/Los_Angeles",
        evaluation_timezone="America/Los_Angeles",
        period_start=DAY.isoformat(),
        period_end=DAY.isoformat(),
        source_attribution=None,
        eligible_for_rule_evaluation=False,
        spend="16.15",
        credential_revision=1,
    )
    data = {
        "rows": [row],
        "sources": [],
        "start": DAY.isoformat(),
        "end": DAY.isoformat(),
    }
    monkeypatch.setattr(
        "services.automation.smart_simulation.economics_adapter",
        lambda *a, **kw: copy.deepcopy(data),
    )
    with sf.begin() as s:
        run = simulate(s, ACTOR, rule["id"], 1, now=clock[0])
    assert run["rows"][0]["status"] == "REVIEW"
    assert not run["rows"][0]["safe_to_consider_for_future_action"]
    payloads = catalogs(clock[0])
    for value in payloads.values():
        for item in value["data"]:
            for field in ("id", "campaign_id", "parent_id"):
                if field in item:
                    item[field] = {"1001": CAMPAIGN, "1002": ADSET, "1003": AD}[
                        item[field]
                    ]
    return run, data, payloads


def input_body(case, **changes):
    return ExperimentalPrepareInput.model_validate(
        {
            "entity_id": "ad",
            "credential_revision": 1,
            "management_confirmed": True,
            "statement": "PREPARE_EXPERIMENT_ONLY_NO_POST",
            "simulation_id": case[0]["id"],
            "rule_evidence_policy": POLICY,
            "reported_spend_acknowledgement": ACK,
            **changes,
        }
    )


def transport(case, calls, *, timeout=False, after_get=None):
    def respond(request):
        calls.append(request.method)
        if request.method == "GET":
            result = httpx.Response(
                200, json=case[2][request.url.path.rsplit("/", 1)[-1]]
            )
            if after_get:
                after_get(calls)
            return result
        assert request.url.path == f"/api/v1/entities/{AD}/pause"
        if timeout:
            raise httpx.ReadTimeout("synthetic", request=request)
        return httpx.Response(
            200, json={"success": True, "entity_id": AD, "message": "mock"}
        )

    return httpx.MockTransport(respond)


def prepare(fixture, case, **changes):
    engine, _sf, vault, _clock = fixture
    calls = []
    card = asyncio.run(
        prepare_experiment(
            engine,
            ACTOR,
            input_body(case, **changes),
            vault=vault,
            transport=transport(case, calls),
        )
    )
    return card, calls


def permit(fixture, case, monkeypatch):
    engine, _sf, _vault, _clock = fixture
    card, calls = prepare(fixture, case)
    row = {"id": card["request_id"], "revision": card["revision"]}
    for event in ("preflight", "confirm"):
        row = engine.transition_manual(ACTOR, row["id"], event, row["revision"])
    assert row["preflight"]["local_allowed"], row["preflight"]
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    body = {
        "revision": row["revision"],
        "credential_revision": 1,
        "account_id": ACCOUNT,
        "entity_id": AD,
        "operation": "PAUSE_AD",
        "expected_status": "ACTIVE",
        "statement": STATEMENT,
    }
    with pytest.raises(ActionRejected, match="PILOT_AUTHORIZATION_STATEMENT_MISMATCH"):
        authorize_pilot(
            engine,
            ACTOR,
            row["id"],
            PilotAuthorizationInput.model_validate(
                {**body, "statement": STRICT_STATEMENT}
            ),
        )
    return authorize_pilot(
        engine, ACTOR, row["id"], PilotAuthorizationInput.model_validate(body)
    ), calls


@pytest.mark.parametrize("timeout", [False, True])
def test_spend_test_one_post_preserves_financial_result(
    fixture, spend_case, monkeypatch, timeout
):
    engine, sf, vault, _clock = fixture
    authorized, calls = permit(fixture, spend_case, monkeypatch)
    assert calls == ["GET"] * 3
    calls.clear()
    asyncio.run(
        execute_pilot(
            engine,
            ACTOR,
            authorized["id"],
            authorized["revision"],
            vault=vault,
            transport=transport(spend_case, calls, timeout=timeout),
        )
    )
    assert calls == ["GET"] * 3 + ["POST"]
    try:
        asyncio.run(
            execute_pilot(
                engine,
                ACTOR,
                authorized["id"],
                authorized["revision"],
                vault=vault,
                transport=transport(spend_case, calls),
            )
        )
    except (WriteDisabled, ActionRejected):
        pass
    assert calls.count("POST") == 1
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 1
        assert s.get(EntityCurrentState, "ad").status == "ACTIVE"
    assert spend_case[0]["rows"][0]["status"] == "REVIEW"
    assert spend_case[1]["rows"][0]["source_attribution"] is None
    assert spend_case[1]["rows"][0]["eligible_for_rule_evaluation"] is False


@pytest.mark.parametrize(
    "change",
    [
        "spend",
        "stale",
        "window",
        "currency",
        "manual",
        "status",
        "revision",
        "condition",
        "scope",
        "enabled",
        "peer",
        "policy",
        "already_authorized",
        "composite",
        "threshold",
        "period",
        "timezone",
    ],
)
def test_changed_spend_evidence_never_posts(fixture, spend_case, monkeypatch, change):
    engine, sf, vault, clock = fixture
    authorized, _calls = permit(fixture, spend_case, monkeypatch)
    row = spend_case[1]["rows"][0]
    if change == "spend":
        row["spend"] = "14.99"
    elif change == "stale":
        row["source_stale"] = True
    elif change == "window":
        row["window_complete"] = False
    elif change == "currency":
        row["currency"] = "EUR"
    else:
        with sf.begin() as s:
            rule = s.get(Rule, spend_case[0]["rule_id"])
            if change == "status":
                s.get(EntityCurrentState, "ad").observed_at = clock[0] - timedelta(
                    hours=1
                )
            elif change == "revision":
                rule.revision += 1
            elif change == "manual":
                from services.storage.models import RuleCooldown

                cd = s.get(RuleCooldown, (rule.id, "ad"))
                cd.smart_state = {**cd.smart_state, "manual_blocked": True}
            elif change == "condition":
                payload = copy.deepcopy(rule.payload)
                payload["expression"]["children"][0]["value"] = "14"
                rule.payload = payload
            elif change == "scope":
                s.get(Entity, "ad").external_id = "999"
            elif change == "enabled":
                rule.payload = {**rule.payload, "enabled": True}
            elif change == "peer":
                s.add(
                    Rule(
                        id="enabled-peer",
                        created_at=clock[0],
                        workspace_id="default",
                        status="SMART_DRY_RUN",
                        revision=1,
                        payload={**rule.payload, "enabled": True},
                    )
                )
            elif change == "already_authorized":
                s.add(
                    ActionRequest(
                        id="previous-spend-permit",
                        workspace_id="default",
                        initiator_id="admin",
                        entity_id="ad",
                        idempotency_key="previous-spend-permit",
                        action="PAUSE_AD",
                        status="CANCELLED",
                        revision=1,
                        created_at=clock[0] - timedelta(hours=1),
                        provenance={
                            "rule_source": {"evidence_policy": POLICY},
                            "controlled": {"authorization": {"statement": STATEMENT}},
                        },
                    )
                )
            elif change in ("composite", "threshold", "period"):
                payload = copy.deepcopy(rule.payload)
                if change == "composite":
                    payload["expression"]["children"].append(
                        copy.deepcopy(payload["expression"]["children"][0])
                    )
                elif change == "threshold":
                    payload["expression"]["children"][0]["value"] = "15.01"
                else:
                    payload["end"] = "2026-09-29"
                rule.payload = payload
            elif change == "timezone":
                s.get(AdAccount, "account").timezone = "Europe/Moscow"
            else:
                request = s.get(ActionRequest, authorized["id"])
                source = {
                    **request.provenance["rule_source"],
                    "evidence_policy": "STRICT_FINANCIAL",
                }
                request.provenance = {**request.provenance, "rule_source": source}
    calls = []
    with pytest.raises((WriteDisabled, ActionRejected, HTTPException)):
        asyncio.run(
            execute_pilot(
                engine,
                ACTOR,
                authorized["id"],
                authorized["revision"],
                vault=vault,
                transport=transport(spend_case, calls),
            )
        )
    assert calls == []


def test_spend_preparation_requires_ack_and_strict_default_stays_held(
    fixture, spend_case
):
    with pytest.raises(ValidationError):
        input_body(spend_case, reported_spend_acknowledgement=None)
    with pytest.raises(ValidationError):
        input_body(spend_case, operation="ENABLE_AD")
    with pytest.raises(HTTPException, match="RULE_RECOMMENDATION_MISMATCH"):
        prepare(
            fixture,
            spend_case,
            rule_evidence_policy="STRICT_FINANCIAL",
            reported_spend_acknowledgement=None,
        )
    _engine, sf, _vault, _clock = fixture
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(ActionRequest)) == 0


def test_parent_must_be_off_before_any_draft(fixture, spend_case):
    spend_case[2]["adsets"]["data"][0]["status"] = "ACTIVE"
    with pytest.raises(WriteDisabled):
        prepare(fixture, spend_case)
    _engine, sf, _vault, _clock = fixture
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(ActionRequest)) == 0


def test_condition_changes_after_catalog_gets_prevents_post(
    fixture, spend_case, monkeypatch
):
    engine, sf, vault, _clock = fixture
    authorized, _calls = permit(fixture, spend_case, monkeypatch)
    calls = []

    def change_after_reads(calls):
        if len(calls) == 3:
            spend_case[1]["rows"][0]["spend"] = "14.99"

    asyncio.run(
        execute_pilot(
            engine,
            ACTOR,
            authorized["id"],
            authorized["revision"],
            vault=vault,
            transport=transport(spend_case, calls, after_get=change_after_reads),
        )
    )
    assert calls == ["GET"] * 3
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 1
        assert s.get(EntityCurrentState, "ad").status == "ACTIVE"


@pytest.mark.parametrize("effective", ["CAMPAIGN_PAUSED", "ADSET_PAUSED"])
def test_effective_parent_status_is_not_treated_as_own_switch(
    fixture, spend_case, monkeypatch, effective
):
    engine, sf, vault, _clock = fixture
    with sf.begin() as s:
        s.get(EntityCurrentState, "ad").status = effective
    authorized, _calls = permit(fixture, spend_case, monkeypatch)
    calls = []
    asyncio.run(
        execute_pilot(
            engine,
            ACTOR,
            authorized["id"],
            authorized["revision"],
            vault=vault,
            transport=transport(spend_case, calls),
        )
    )
    assert calls == ["GET"] * 3 + ["POST"]
    with sf() as s:
        assert s.get(EntityCurrentState, "ad").status == effective
    assert spend_case[0]["rows"][0]["status"] == "REVIEW"


@pytest.mark.parametrize("terminal", ["cancel", "expired"])
def test_unspent_terminal_draft_can_be_prepared_again(fixture, spend_case, terminal):
    engine, sf, _vault, clock = fixture
    first, _calls = prepare(fixture, spend_case)
    if terminal == "cancel":
        engine.transition_manual(
            ACTOR, first["request_id"], "cancel", first["revision"]
        )
    else:
        clock[0] += timedelta(minutes=16)
        with sf.begin() as s:
            s.get(EntityCurrentState, "ad").observed_at = clock[0]
            s.get(WriteCredentialState, "default").checked_at = clock[0]
        for payload in spend_case[2].values():
            payload["meta"]["data_updated_at"] = clock[0].isoformat()
    second, calls = prepare(fixture, spend_case)
    assert second["request_id"] != first["request_id"]
    assert calls == ["GET"] * 3
    with sf() as s:
        assert s.get(ActionRequest, first["request_id"]).status == (
            "CANCELLED" if terminal == "cancel" else "EXPIRED"
        )
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0


def test_spend_preparation_refuses_unknown_workspace_before_get(fixture, spend_case):
    engine, sf, vault, clock = fixture
    with sf.begin() as s:
        s.add(
            ActionRequest(
                id="unfinished-parent",
                workspace_id="default",
                entity_id="adset",
                initiator_id="admin",
                idempotency_key="unfinished-parent",
                action="ENABLE_ADSET",
                status="unknown",
                revision=1,
                created_at=clock[0],
                provenance={"controlled": {"mode": "LIVE_SINGLE_OPERATION"}},
            )
        )
    calls = []
    with pytest.raises(ActionRejected, match="PILOT_WORKSPACE_CONFLICT"):
        asyncio.run(
            prepare_experiment(
                engine,
                ACTOR,
                input_body(spend_case),
                vault=vault,
                transport=transport(spend_case, calls),
            )
        )
    assert not calls
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0
