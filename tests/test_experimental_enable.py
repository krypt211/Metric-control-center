"""Reverse pilot is separately authorized and tied to a locally reviewed spent PAUSE."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from test_experimental_pilot import (
    ACTOR,
    body,
    catalogs,
    confirm,
    fixture,
    input_body,
    permit,
    response,
    setup,
)

from services.actions.engine import ActionRejected
from services.actions.experimental import (
    ENABLE_STATEMENT,
    STATEMENT,
    prepare_experiment,
)
from services.actions.pilot import authorize_pilot, execute_pilot
from services.providers.contracts import WriteDisabled
from services.providers.integration_models import WriteCredentialState
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    EntityCurrentState,
)

__all__ = ["fixture", "setup"]


def prior_pause(fixture, monkeypatch):
    engine, sf, vault, clock = fixture
    p, _ = permit(fixture, monkeypatch)
    asyncio.run(
        execute_pilot(
            engine,
            ACTOR,
            p["id"],
            p["revision"],
            vault=vault,
            transport=httpx.MockTransport(response(catalogs(clock[0]), [])),
        )
    )
    clock[0] += timedelta(seconds=901)
    engine.verify_pending()
    with sf.begin() as s:
        s.get(WriteCredentialState, ACTOR["workspace"]).checked_at = clock[0]
        s.add(
            ActionLog(
                id=str(uuid4()),
                request_id=p["id"],
                event="pilot_late_manual_target_confirmed",
                created_at=clock[0],
                details={
                    "actor_id": ACTOR["id"],
                    "ad_id": "1003",
                    "adset_id": "1002",
                    "campaign_id": "1001",
                    "configured_status": "PAUSED",
                    "matches_target": True,
                    "late_observation": True,
                    "source": "USER_REPLY_AFTER_ID_CLARIFICATION",
                    "authoritative_api": False,
                    "creates_pause_ownership": False,
                },
            )
        )
    monkeypatch.setenv("ACTIONS_ENABLED", "false")
    monkeypatch.setenv("LOCAL_READ_ONLY", "true")
    return p["id"]


def paused_catalogs(now):
    data = catalogs(now)
    data["ads"]["data"][0].update(status="PAUSED", effective_status="PAUSED")
    return data


def enable_response(data, calls):
    def respond(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=data[request.url.path.rsplit("/", 1)[-1]])
        assert request.url.path == "/api/v1/entities/1003/enable"
        return httpx.Response(
            200, json={"success": True, "entity_id": "1003", "message": "fixture"}
        )

    return respond


def prepare_enable(fixture, previous, *, data=None):
    engine, _sf, vault, clock = fixture
    calls = []
    card = asyncio.run(
        prepare_experiment(
            engine,
            ACTOR,
            input_body(operation="ENABLE_AD", previous_pause_request_id=previous),
            vault=vault,
            transport=httpx.MockTransport(
                enable_response(data or paused_catalogs(clock[0]), calls)
            ),
        )
    )
    return card, calls


def test_enable_requires_previous_reference_and_pause_rejects_it():
    with pytest.raises(ValidationError):
        input_body(operation="ENABLE_AD")
    with pytest.raises(ValidationError):
        input_body(previous_pause_request_id="other")


def test_prepare_enable_reconciles_locally_but_preserves_unknown_api_outcome(
    fixture, monkeypatch
):
    engine, sf, _vault, _clock = fixture
    previous = prior_pause(fixture, monkeypatch)
    card, calls = prepare_enable(fixture, previous)
    assert [r.method for r in calls] == ["GET"] * 3
    assert (
        card["operation"] == "ENABLE_AD"
        and card["authorization_statement_required"] == ENABLE_STATEMENT
    )
    with sf() as s:
        old = s.get(ActionRequest, previous)
        assert (
            old.status == "MANUALLY_REVIEWED"
            and old.provenance["controlled"]["wire_spent"] is True
        )
        e = s.scalar(
            select(ActionExecution).where(ActionExecution.request_id == previous)
        )
        assert (
            e.outcome == "live_unknown" and e.error_code == "MANUAL_READBACK_DEADLINE"
        )
        assert s.get(ActionRequest, card["request_id"]).status == "DRAFT"
        assert s.get(EntityCurrentState, "ad").status == "ADSET_PAUSED"
    row = confirm(engine, card)
    with pytest.raises(WriteDisabled):
        authorize_pilot(engine, ACTOR, row["id"], body(row, statement=ENABLE_STATEMENT))


def test_enable_needs_distinct_consent_and_one_mock_post(fixture, monkeypatch):
    engine, _sf, vault, clock = fixture
    previous = prior_pause(fixture, monkeypatch)
    card, _ = prepare_enable(fixture, previous)
    row = confirm(engine, card)
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    with pytest.raises(ActionRejected, match="STATEMENT_MISMATCH"):
        authorize_pilot(engine, ACTOR, row["id"], body(row, statement=STATEMENT))
    p = authorize_pilot(engine, ACTOR, row["id"], body(row, statement=ENABLE_STATEMENT))
    calls = []
    transport = httpx.MockTransport(enable_response(paused_catalogs(clock[0]), calls))
    asyncio.run(
        execute_pilot(
            engine, ACTOR, p["id"], p["revision"], vault=vault, transport=transport
        )
    )
    assert [r.method for r in calls] == ["GET"] * 3 + ["POST"]
    assert (
        asyncio.run(
            execute_pilot(
                engine, ACTOR, p["id"], p["revision"], vault=vault, transport=transport
            )
        )
        is None
    )
    assert len(calls) == 4


@pytest.mark.parametrize(
    "changed",
    ["missing_manual", "negative_manual", "wrong_entity", "unspent", "wrong_error"],
)
def test_previous_pause_cannot_be_guessed_or_unresolved(fixture, monkeypatch, changed):
    _engine, sf, _vault, clock = fixture
    previous = prior_pause(fixture, monkeypatch)
    with sf.begin() as s:
        old = s.get(ActionRequest, previous)
        proof = s.scalar(
            select(ActionLog).where(
                ActionLog.request_id == previous,
                ActionLog.event == "pilot_late_manual_target_confirmed",
            )
        )
        if changed == "missing_manual":
            s.delete(proof)
        elif changed == "negative_manual":
            s.add(
                ActionLog(
                    id=str(uuid4()),
                    request_id=previous,
                    event="pilot_manual_status_mismatch_reported",
                    created_at=clock[0] + timedelta(seconds=1),
                    details={"configured_status": "ACTIVE"},
                )
            )
        elif changed == "wrong_entity":
            old.entity_id = "adset"
        elif changed == "unspent":
            old.provenance = {
                **old.provenance,
                "controlled": {**old.provenance["controlled"], "wire_spent": False},
            }
        else:
            s.scalar(
                select(ActionExecution).where(ActionExecution.request_id == previous)
            ).error_code = "OTHER"
    with pytest.raises(WriteDisabled):
        prepare_enable(fixture, previous)


@pytest.mark.parametrize(
    "changed", ["campaign", "adset", "ad", "effective", "prior_proof"]
)
def test_enable_revalidates_parents_status_and_previous_proof(
    fixture, monkeypatch, changed
):
    engine, sf, vault, clock = fixture
    previous = prior_pause(fixture, monkeypatch)
    card, _ = prepare_enable(fixture, previous)
    row = confirm(engine, card)
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    p = authorize_pilot(engine, ACTOR, row["id"], body(row, statement=ENABLE_STATEMENT))
    data = paused_catalogs(clock[0])
    if changed == "campaign":
        data["campaigns"]["data"][0]["status"] = "ACTIVE"
    elif changed == "adset":
        data["adsets"]["data"][0]["status"] = "ACTIVE"
    elif changed == "ad":
        data["ads"]["data"][0]["status"] = "ACTIVE"
    elif changed == "effective":
        data["ads"]["data"][0]["effective_status"] = "ADSET_PAUSED"
    else:
        with sf.begin() as s:
            proof = s.get(ActionLog, card["previous_pause"]["evidence_id"])
            proof.details = {**proof.details, "reason": "tampered"}
    calls = []
    try:
        asyncio.run(
            execute_pilot(
                engine,
                ACTOR,
                p["id"],
                p["revision"],
                vault=vault,
                transport=httpx.MockTransport(enable_response(data, calls)),
            )
        )
    except WriteDisabled:
        pass
    assert not any(r.method == "POST" for r in calls)
