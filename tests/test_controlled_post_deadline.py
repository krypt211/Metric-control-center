"""One spent mock command remains UNKNOWN on timeout, late ACK or recovery."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from test_controlled_rehearsal import (
    ACTOR,
    mock_gate,
    prepared,
    responder,
    setup,
)

from services.actions import engine as engine_module
from services.storage.models import ActionExecution, ActionLog, ActionRequest

__all__ = ["mock_gate", "setup"]


def assert_held(fixture, permit, calls, *, job_id):
    engine, sf, vault, _clock = fixture
    with sf() as session:
        row = session.get(ActionRequest, permit["id"])
        control = row.provenance["controlled"]
        assert row.status == "unknown"
        assert control["state"] == "OUTCOME_UNKNOWN"
        assert control["attempts"] == 1
        assert control["job_id"] == job_id
        assert control["observation"]["state"] == "UNARMED"
        execution = session.scalar(
            select(ActionExecution).where(ActionExecution.request_id == row.id)
        )
        assert execution.outcome == "mock_unknown"
        assert not any(
            entry.event in ("controlled_mock_acknowledged", "verified")
            for entry in session.scalars(select(ActionLog))
        )
    assert (
        asyncio.run(
            engine.execute_rehearsal(
                ACTOR,
                permit["id"],
                permit["revision"],
                vault=vault,
                transport=responder(calls),
            )
        )
        is None
    )


@pytest.mark.parametrize("reason", ["deadline", "recovery"])
def test_late_ack_cannot_arm_observation_or_reopen_unknown(setup, mock_gate, reason):
    engine, _sf, vault, clock = setup
    permit = prepared(engine)
    calls = []

    def after_http():
        clock[0] += (
            timedelta(minutes=6) if reason == "deadline" else timedelta(seconds=121)
        )
        if reason == "recovery":
            engine.verify_pending()

    assert (
        asyncio.run(
            engine.execute_rehearsal(
                ACTOR,
                permit["id"],
                permit["revision"],
                vault=vault,
                transport=responder(calls, after_http=after_http),
            )
        )
        == permit["id"]
    )
    assert_held(setup, permit, calls, job_id=41)
    assert len(calls) == 1


@pytest.mark.parametrize("suppressed", [False, True])
def test_monotonic_post_timeout_holds_unknown_even_if_cancel_is_suppressed(
    setup, mock_gate, monkeypatch, suppressed
):
    engine, _sf, vault, _clock = setup
    permit = prepared(engine)
    monkeypatch.setattr(engine_module, "CONTROLLED_POST_TIMEOUT_SECONDS", 0.5)
    calls = []

    async def respond(request):
        calls.append(request)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if not suppressed:
                raise
        return httpx.Response(
            202,
            json={
                "success": True,
                "entity_id": "1003",
                "message": "synthetic",
                "job_id": 41,
            },
        )

    async def run():
        async with asyncio.timeout(5):
            return await engine.execute_rehearsal(
                ACTOR,
                permit["id"],
                permit["revision"],
                vault=vault,
                transport=httpx.MockTransport(respond),
            )

    assert asyncio.run(run()) == permit["id"]
    assert_held(setup, permit, calls, job_id=41 if suppressed else None)
    assert len(calls) == 1


def test_shorter_remaining_permit_bounds_the_post(setup, mock_gate):
    engine, sf, vault, clock = setup
    permit = prepared(engine)
    with sf.begin() as session:
        row = session.get(ActionRequest, permit["id"])
        control = dict(row.provenance["controlled"])
        control["expires_at"] = (clock[0] + timedelta(seconds=0.5)).isoformat()
        row.provenance = {**row.provenance, "controlled": control}
    calls = []

    async def respond(request):
        calls.append(request)
        await asyncio.Event().wait()

    async def run():
        async with asyncio.timeout(5):
            return await engine.execute_rehearsal(
                ACTOR,
                permit["id"],
                permit["revision"],
                vault=vault,
                transport=httpx.MockTransport(respond),
            )

    assert asyncio.run(run()) == permit["id"]
    assert_held(setup, permit, calls, job_id=None)
    assert len(calls) == 1


def test_expiry_during_reservation_stops_before_opening_the_vault(
    setup, mock_gate, monkeypatch
):
    from unittest.mock import Mock

    engine, _sf, vault, clock = setup
    permit = prepared(engine)
    reserve = engine.reserve_api_request

    def expire(workspace):
        reserve(workspace)
        clock[0] += timedelta(minutes=6)

    monkeypatch.setattr(engine, "reserve_api_request", expire)
    private = Mock(wraps=vault)
    calls = []
    assert (
        asyncio.run(
            engine.execute_rehearsal(
                ACTOR,
                permit["id"],
                permit["revision"],
                vault=private,
                transport=responder(calls),
            )
        )
        == permit["id"]
    )
    private.unseal.assert_not_called()
    assert_held(setup, permit, calls, job_id=None)
    assert calls == []


def test_caller_cancellation_leaves_spent_claim_for_no_resend_recovery(
    setup, mock_gate
):
    engine, _sf, vault, clock = setup
    permit = prepared(engine)
    calls = []

    async def run():
        entered = asyncio.Event()

        async def respond(request):
            calls.append(request)
            entered.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(
            engine.execute_rehearsal(
                ACTOR,
                permit["id"],
                permit["revision"],
                vault=vault,
                transport=httpx.MockTransport(respond),
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    clock[0] += timedelta(seconds=121)
    engine.verify_pending()
    assert_held(setup, permit, calls, job_id=None)
    assert len(calls) == 1
