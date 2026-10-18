"""Six local status operations and closed transport gates; no real provider calls."""

from __future__ import annotations

import asyncio
import hashlib
import json

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from test_manual_actions import ACTOR, NOW, command, engine, store
from test_metricflow_write_contract import mock_gate

from services.actions.catalog import catalog
from services.actions.safety import ActionSafetyGate
from services.metricflow.errors import ActionOutcomeUnknown
from services.metricflow.writer import MetricFlowActionConnector
from services.providers.contracts import WriteDisabled
from services.storage.models import ActionExecution, Entity, EntityCurrentState

__all__ = ["mock_gate", "store"]

LEVELS = [("campaign", "1001"), ("adset", "1002"), ("ad", "1003")]


@pytest.mark.parametrize("level,external", LEVELS)
@pytest.mark.parametrize(
    "operation,baseline,target",
    [("PAUSE", "ACTIVE", "PAUSED"), ("ENABLE", "PAUSED", "ACTIVE")],
)
def test_six_local_lifecycles_preserve_status_and_never_execute(
    store, level, external, operation, baseline, target
):
    with store.begin() as session:
        for kind, _ in LEVELS:
            state = session.get(EntityCurrentState, kind)
            if state:
                state.status = baseline
            else:
                session.add(
                    EntityCurrentState(
                        entity_id=kind, status=baseline, observed_at=NOW, raw={}
                    )
                )
    body = command(
        entity_id=level,
        entity_level=level,
        meta_ad_id=external,
        operation=f"{operation}_{level.upper()}",
        expected_status=baseline,
    )
    action_engine = engine(store)
    row = action_engine.prepare_manual(ACTOR, body, "one")
    assert row["entity_level"] == level and row["target_status"] == target
    assert row["provider_entity_id"] == external
    for event in ("preflight", "confirm", "simulate"):
        row = action_engine.transition_manual(ACTOR, row["id"], event, row["revision"])
        assert row["preflight"]["local_allowed"]
        assert row["preflight"]["live_allowed"] is False
    assert row["status"] == "SIMULATED" and row["result"] == "LOCAL_SIMULATION_ONLY"
    with store() as session:
        assert all(
            session.get(EntityCurrentState, kind).status == baseline
            for kind, _ in LEVELS
        )
        assert session.scalar(select(func.count()).select_from(ActionExecution)) == 0
        result = catalog(session, "default", NOW, account_id="account", level=level)
        assert [item["entity_level"] for item in result["rows"]] == [level]
        assert result["rows"][0]["external_id"] == external


@pytest.mark.parametrize("level,external", LEVELS[:2])
def test_parent_intent_cannot_bind_an_ad_or_change_level_after_prepare(
    store, level, external
):
    with pytest.raises(HTTPException):
        engine(store).prepare_manual(
            ACTOR,
            command(entity_level=level, operation=f"PAUSE_{level.upper()}"),
            "wrong",
        )
    with store.begin() as session:
        session.add(
            EntityCurrentState(
                entity_id=level, status="ACTIVE", observed_at=NOW, raw={}
            )
        )
    action_engine = engine(store)
    row = action_engine.prepare_manual(
        ACTOR,
        command(
            entity_id=level,
            entity_level=level,
            meta_ad_id=external,
            operation=f"PAUSE_{level.upper()}",
        ),
        "valid",
    )
    with store.begin() as session:
        session.get(Entity, level).kind = "ad"
    row = action_engine.transition_manual(
        ACTOR, row["id"], "preflight", row["revision"]
    )
    assert row["preflight"]["local_allowed"] is False
    assert "ENTITY_UNAVAILABLE" in row["reason_codes"]


@pytest.mark.parametrize(
    "changes",
    [
        {"entity_level": "campaign"},
        {"operation": "PAUSE_CAMPAIGN"},
        {"entity_level": "adset", "operation": "ENABLE_CAMPAIGN"},
        {"entity_level": "campaign", "operation": "PAUSE_CAMPAIGN", "provider": "meta"},
        {
            "entity_level": "campaign",
            "operation": "PAUSE_CAMPAIGN",
            "simulation_id": "ad-rule",
        },
    ],
)
def test_level_and_rule_source_mismatches_are_rejected(changes):
    with pytest.raises(ValidationError):
        command(**changes)


def test_original_ad_idempotency_fingerprint_remains_compatible(store):
    body = command()
    legacy = body.model_dump(exclude={"entity_level"})
    expected = hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
    row = engine(store).prepare_manual(ACTOR, body, "legacy")
    assert row["fingerprint"] == expected
    assert engine(store).prepare_manual(ACTOR, command(), "legacy")["id"] == row["id"]


@pytest.mark.parametrize("level,external", LEVELS)
@pytest.mark.parametrize("operation", ["pause", "enable"])
def test_exact_six_wire_requests_only_use_mock_transport(
    mock_gate, level, external, operation
):
    calls = []

    def respond(request):
        calls.append(request)
        assert request.method == "POST"
        assert request.url.path == f"/api/v1/entities/{external}/{operation}"
        assert json.loads(request.content) == {"level": level}
        return httpx.Response(
            200, json={"success": True, "entity_id": external, "message": "synthetic"}
        )

    async def run():
        async with MetricFlowActionConnector(
            "mfk_fixture_multilevel", transport=httpx.MockTransport(respond)
        ) as writer:
            await getattr(writer, operation + "_entity")(external, level=level)

    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize("level,external", LEVELS)
def test_parent_and_ad_timeouts_never_resend(mock_gate, level, external):
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    async def run():
        async with MetricFlowActionConnector(
            "mfk_fixture_multilevel", transport=httpx.MockTransport(respond)
        ) as writer:
            with pytest.raises(ActionOutcomeUnknown):
                await writer.pause_entity(external, level=level)

    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize("level", ["campaign", "adset", "ad"])
def test_real_contract_gate_blocks_all_levels_even_with_permissive_flags(
    monkeypatch, level
):
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    calls = []

    async def run():
        async with MetricFlowActionConnector(
            "mfk_fixture_multilevel",
            transport=httpx.MockTransport(lambda request: calls.append(request)),
        ) as writer:
            for operation in (writer.pause_entity, writer.enable_entity):
                with pytest.raises(WriteDisabled):
                    await operation("123", level=level)

    asyncio.run(run())
    assert calls == []
    with pytest.raises(WriteDisabled):
        ActionSafetyGate.require_write()


@pytest.mark.parametrize(
    "level", ["account", "creative", "AD", "adset/../ad", None, True]
)
def test_unknown_wire_level_fails_before_any_transport(level):
    calls = []

    async def run():
        async with MetricFlowActionConnector(
            "mfk_fixture_multilevel",
            transport=httpx.MockTransport(lambda request: calls.append(request)),
        ) as writer:
            with pytest.raises(ValueError):
                await writer.pause_entity("123", level=level)

    asyncio.run(run())
    assert calls == []
