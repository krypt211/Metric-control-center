"""Documented synchronous status path; encrypted fixtures and MockTransport only."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy import func, select
from test_controlled_rehearsal import ACTOR, TOKEN, mock_gate, setup
from test_manual_actions import command

from services.actions.engine import ActionEngine, ActionRejected
from services.providers.contracts import WriteDisabled
from services.storage.models import ActionExecution, ActionRequest, EntityCurrentState

__all__ = ["mock_gate", "setup"]
LEVELS = [("campaign", "1001"), ("adset", "1002"), ("ad", "1003")]


def prepare_sync(engine, sf, level="ad", external="1003", operation="PAUSE"):
    baseline = "ACTIVE" if operation == "PAUSE" else "PAUSED"
    with sf.begin() as session:
        state = session.get(EntityCurrentState, level)
        if state:
            state.status = baseline
        else:
            session.add(
                EntityCurrentState(
                    entity_id=level, status=baseline, observed_at=engine.clock(), raw={}
                )
            )
    row = engine.prepare_manual(
        ACTOR,
        command(
            entity_id=level,
            entity_level=level,
            meta_ad_id=external,
            operation=f"{operation}_{level.upper()}",
            expected_status=baseline,
        ),
        "sync-one-" + level,
    )
    for event in ("preflight", "confirm"):
        row = engine.transition_manual(ACTOR, row["id"], event, row["revision"])
    return engine.prepare_rehearsal(
        ACTOR,
        row["id"],
        row["revision"],
        1,
        engine.clock() + timedelta(minutes=5),
        asynchronous=False,
    )


def transport(calls, external="1003", *, status=200, payload=None, after=None):
    def respond(request):
        calls.append(request)
        if after:
            after()
        return httpx.Response(
            status,
            json=payload
            if payload is not None
            else {
                "success": True,
                "entity_id": external,
                "message": "synthetic sync",
            },
        )

    return httpx.MockTransport(respond)


def execute(engine, vault, permit, wire):
    return asyncio.run(
        engine.execute_rehearsal(
            ACTOR,
            permit["id"],
            permit["revision"],
            vault=vault,
            transport=wire,
        )
    )


@pytest.mark.parametrize("level,external", LEVELS)
@pytest.mark.parametrize("operation", ["PAUSE", "ENABLE"])
def test_six_sync_encrypted_single_attempt_paths(
    setup, mock_gate, level, external, operation
):
    engine, sf, vault, clock = setup
    permit = prepare_sync(engine, sf, level, external, operation)
    calls = []
    wire = transport(calls, external)
    assert execute(engine, vault, permit, wire) == permit["id"]
    restart = ActionEngine(sf, engine.policy, clock=engine.clock)
    assert execute(restart, vault, permit, wire) is None
    assert len(calls) == 1
    request = calls[0]
    assert request.method == "POST"
    assert request.url.path == f"/api/v1/entities/{external}/{operation.lower()}"
    assert not request.url.params
    assert json.loads(request.content) == {"level": level}
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    with sf.begin() as session:
        row = session.get(ActionRequest, permit["id"])
        control = row.provenance["controlled"]
        assert row.status == "verifying"
        assert control["state"] == "SYNC_ACKNOWLEDGED_NEEDS_MANUAL_READBACK"
        assert control["mode"] == "MOCK_ONLY" and control["response_mode"] == "SYNC_200"
        assert control["attempts"] == 1 and control["job_id"] is None
        assert control["observation"]["state"] == "NOT_APPLICABLE"
        assert control["observation"]["attempts"] == 0
        assert control["binding"]["entity_level"] == level
        assert session.scalar(select(func.count()).select_from(ActionExecution)) == 1
        # A later READ match cannot be mistaken for authoritative confirmation.
        state = session.get(EntityCurrentState, level)
        state.status = "PAUSED" if operation == "PAUSE" else "ACTIVE"
        state.observed_at = clock[0] + timedelta(seconds=1)
    clock[0] += timedelta(seconds=20)
    assert restart.verify_pending() == 0
    with pytest.raises(ActionRejected, match="ACKNOWLEDGED_JOB_REQUIRED"):
        asyncio.run(
            restart.observe_rehearsal_job(
                ACTOR, permit["id"], vault=vault, transport=wire
            )
        )
    clock[0] += timedelta(minutes=6)
    assert restart.verify_pending() == 0
    with sf() as session:
        row = session.get(ActionRequest, permit["id"])
        execution = session.scalar(select(ActionExecution))
        assert row.status == "unknown"
        assert row.provenance["controlled"]["state"] == "OUTCOME_UNKNOWN"
        assert execution.error_code == "MANUAL_READBACK_DEADLINE"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status,payload",
    [
        (
            202,
            {"success": True, "entity_id": "1003", "message": "queued", "job_id": 41},
        ),
        (
            200,
            {"success": True, "entity_id": "1003", "message": "queued", "job_id": 41},
        ),
        (200, {"success": False, "entity_id": "1003", "message": TOKEN}),
        (200, {"success": True, "entity_id": "wrong", "message": TOKEN}),
        (200, {"success": True}),
        (403, {"detail": TOKEN}),
        (429, {"detail": TOKEN}),
        (503, {"detail": TOKEN}),
    ],
)
def test_sync_unknown_ack_is_never_switched_to_async_or_retried(
    setup, mock_gate, status, payload
):
    engine, sf, vault, _ = setup
    permit = prepare_sync(engine, sf)
    calls = []
    wire = transport(calls, status=status, payload=payload)
    execute(engine, vault, permit, wire)
    assert execute(engine, vault, permit, wire) is None
    with sf() as session:
        row = session.get(ActionRequest, permit["id"])
        assert row.status == "unknown"
        assert row.provenance["controlled"]["observation"]["attempts"] == 0
        assert TOKEN not in json.dumps(row.provenance)
    assert len(calls) == 1


@pytest.mark.parametrize("level,external", LEVELS)
def test_sync_contract_gate_is_still_closed_before_vault_and_http(
    setup, monkeypatch, level, external
):
    engine, sf, _, _ = setup
    permit = prepare_sync(engine, sf, level, external)
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    calls, vault = [], Mock()
    with pytest.raises(WriteDisabled):
        execute(engine, vault, permit, transport(calls, external))
    vault.unseal.assert_not_called()
    assert calls == []
    with sf() as session:
        assert session.scalar(select(func.count()).select_from(ActionExecution)) == 0


def test_sync_late_ack_is_unknown_without_job_observer(setup, mock_gate):
    engine, sf, vault, clock = setup
    permit = prepare_sync(engine, sf)
    calls = []

    def late():
        clock[0] += timedelta(minutes=6)

    execute(engine, vault, permit, transport(calls, after=late))
    with sf() as session:
        row = session.get(ActionRequest, permit["id"])
        assert row.status == "unknown"
        assert session.scalar(select(ActionExecution)).error_code == "POST_DEADLINE"
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["ASYNC_JOB", "garbage", None])
def test_bound_sync_response_mode_cannot_be_changed_before_claim(
    setup, mock_gate, mode
):
    engine, sf, vault, _ = setup
    permit = prepare_sync(engine, sf)
    with sf.begin() as session:
        row = session.get(ActionRequest, permit["id"])
        row.provenance = {
            **row.provenance,
            "controlled": {**row.provenance["controlled"], "response_mode": mode},
        }
    calls = []
    with pytest.raises(ActionRejected):
        execute(engine, vault, permit, transport(calls))
    assert calls == []


def test_sync_preparation_does_not_admit_real_transport(setup, mock_gate):
    engine, sf, vault, _ = setup
    permit = prepare_sync(engine, sf)
    with pytest.raises(ActionRejected, match="EXPLICIT_MOCK_TRANSPORT_REQUIRED"):
        execute(engine, vault, permit, None)
