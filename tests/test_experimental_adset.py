"""One group ENABLE under a paused campaign; existing executor and mocked transport."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from test_experimental_enable import (
    enable_response,
    paused_catalogs,
    prepare_enable,
    prior_pause,
)
from test_experimental_pilot import (
    ACTOR,
    body,
    catalogs,
    confirm,
    fixture,
    input_body,
    setup,
)

from services.actions.engine import ActionRejected
from services.actions.experimental import (
    ADSET_STATEMENT,
    ENABLE_STATEMENT,
    prepare_experiment,
)
from services.actions.pilot import (
    PilotAuthorizationInput,
    authorize_pilot,
    execute_pilot,
)
from services.providers.contracts import WriteDisabled
from services.providers.integration_models import WriteCredentialState
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    EntityCurrentState,
)

__all__ = ["fixture", "setup"]


def previous_enable(fixture, monkeypatch):
    engine, sf, vault, clock = fixture
    previous = prior_pause(fixture, monkeypatch)
    card, _ = prepare_enable(fixture, previous)
    row = confirm(engine, card)
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    p = authorize_pilot(engine, ACTOR, row["id"], body(row, statement=ENABLE_STATEMENT))
    asyncio.run(
        execute_pilot(
            engine,
            ACTOR,
            p["id"],
            p["revision"],
            vault=vault,
            transport=httpx.MockTransport(
                enable_response(paused_catalogs(clock[0]), [])
            ),
        )
    )
    clock[0] += timedelta(seconds=901)
    engine.verify_pending()
    with sf.begin() as s:
        s.get(WriteCredentialState, ACTOR["workspace"]).checked_at = clock[0]
        for event in (
            "pilot_manual_enable_target_confirmed",
            "pilot_manual_enable_parents_confirmed",
            "pilot_manual_effective_status_confirmed",
        ):
            s.add(
                ActionLog(
                    id=str(uuid4()),
                    request_id=p["id"],
                    event=event,
                    created_at=clock[0],
                    details={
                        "actor_id": ACTOR["id"],
                        "ad_id": "1003",
                        "configured_status": "ACTIVE",
                        "campaign_status": "PAUSED",
                        "adset_status": "PAUSED",
                        "effective_status": "ADSET_PAUSED",
                    },
                )
            )
    monkeypatch.setenv("ACTIONS_ENABLED", "false")
    monkeypatch.setenv("LOCAL_READ_ONLY", "true")
    return p["id"]


def respond(data, calls):
    def response(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=data[request.url.path.rsplit("/", 1)[-1]])
        assert request.url.path == "/api/v1/entities/1002/enable" and json.loads(
            request.content
        ) == {"level": "adset"}
        return httpx.Response(
            200, json={"success": True, "entity_id": "1002", "message": "fixture"}
        )

    return response


def prepare_group(fixture, previous, data=None):
    engine, _sf, vault, clock = fixture
    calls = []
    card = asyncio.run(
        prepare_experiment(
            engine,
            ACTOR,
            input_body(
                entity_id="adset",
                operation="ENABLE_ADSET",
                previous_ad_request_id=previous,
            ),
            vault=vault,
            transport=httpx.MockTransport(respond(data or catalogs(clock[0]), calls)),
        )
    )
    return card, calls


def authorize_group(engine, row, statement=ADSET_STATEMENT):
    return authorize_pilot(
        engine,
        ACTOR,
        row["id"],
        PilotAuthorizationInput(
            revision=row["revision"],
            credential_revision=1,
            account_id="act_100",
            entity_id="1002",
            operation="ENABLE_ADSET",
            expected_status="PAUSED",
            statement=statement,
        ),
    )


def test_group_preparation_is_only_read_and_preserves_ad_unknown(fixture, monkeypatch):
    engine, sf, _vault, _clock = fixture
    previous = previous_enable(fixture, monkeypatch)
    card, calls = prepare_group(fixture, previous)
    assert [r.method for r in calls] == ["GET"] * 3
    assert (
        card["namespace"] == "UNVERIFIED_CANDIDATE_FACEBOOK_ADSET_ID"
        and card["operation"] == "ENABLE_ADSET"
    )
    assert card["baseline"]["children"] == [{"id": "1003", "status": "ACTIVE"}]
    with sf() as s:
        assert s.get(ActionRequest, previous).status == "MANUALLY_REVIEWED"
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
        authorize_group(engine, row)


def test_group_requires_own_consent_and_one_group_post(fixture, monkeypatch):
    engine, _sf, vault, clock = fixture
    previous = previous_enable(fixture, monkeypatch)
    card, _ = prepare_group(fixture, previous)
    row = confirm(engine, card)
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    with pytest.raises(ActionRejected, match="STATEMENT_MISMATCH"):
        authorize_group(engine, row, ENABLE_STATEMENT)
    permit = authorize_group(engine, row)
    calls = []
    transport = httpx.MockTransport(respond(catalogs(clock[0]), calls))
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
    assert [r.method for r in calls] == ["GET"] * 3 + ["POST"]
    assert (
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
        is None
    )
    assert len(calls) == 4


@pytest.mark.parametrize(
    "change",
    [
        "campaign_active",
        "group_active",
        "children_changed",
        "child_removed",
        "foreign_child_campaign",
    ],
)
def test_recheck_holds_group_before_post(fixture, monkeypatch, change):
    engine, _sf, vault, clock = fixture
    previous = previous_enable(fixture, monkeypatch)
    card, _ = prepare_group(fixture, previous)
    row = confirm(engine, card)
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    permit = authorize_group(engine, row)
    data = catalogs(clock[0])
    if change == "campaign_active":
        data["campaigns"]["data"][0]["status"] = "ACTIVE"
    elif change == "group_active":
        data["adsets"]["data"][0]["status"] = "ACTIVE"
    elif change == "children_changed":
        data["ads"]["data"][0]["status"] = "PAUSED"
    elif change == "child_removed":
        data["ads"]["data"][0]["parent_id"] = "other"
    else:
        data["ads"]["data"][0]["campaign_id"] = "other"
    calls = []
    asyncio.run(
        execute_pilot(
            engine,
            ACTOR,
            permit["id"],
            permit["revision"],
            vault=vault,
            transport=httpx.MockTransport(respond(data, calls)),
        )
    )
    assert not any(r.method == "POST" for r in calls)


def test_group_requires_completed_child_reference():
    with pytest.raises(ValidationError):
        input_body(entity_id="adset", operation="ENABLE_ADSET")
    with pytest.raises(ValidationError):
        input_body(operation="PAUSE_ADSET")
    with pytest.raises(ValidationError):
        input_body(operation="ENABLE_CAMPAIGN")


def test_group_contract_rejects_wrong_level_id_and_method(fixture, monkeypatch):
    from services.actions.pilot_contract import load_contract

    engine, _sf, _vault, _clock = fixture
    previous = previous_enable(fixture, monkeypatch)
    card, _ = prepare_group(fixture, previous)
    row = confirm(engine, card)
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    permit = authorize_group(engine, row)
    contract = load_contract(engine, ACTOR, permit["id"], phase="EXECUTE")
    for method, path, payload in (
        ("POST", "entities/1002/enable", {"level": "ad"}),
        ("POST", "entities/1003/enable", {"level": "adset"}),
        ("POST", "entities/1002/pause", {"level": "adset"}),
        ("GET", "entities/1002/enable", {"level": "adset"}),
    ):
        with pytest.raises(WriteDisabled):
            contract.check_request(method, path, payload, None)


def test_group_post_timeout_is_unknown_and_never_retried(fixture, monkeypatch):
    engine, sf, vault, clock = fixture
    previous = previous_enable(fixture, monkeypatch)
    card, _ = prepare_group(fixture, previous)
    row = confirm(engine, card)
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    permit = authorize_group(engine, row)
    calls = []
    regular = respond(catalogs(clock[0]), calls)

    def timeout(request):
        if request.method == "POST":
            calls.append(request)
            raise httpx.ReadTimeout("synthetic", request=request)
        return regular(request)

    transport = httpx.MockTransport(timeout)
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
    assert [r.method for r in calls] == ["GET"] * 3 + ["POST"]
    with sf() as session:
        assert session.get(ActionRequest, permit["id"]).status == "unknown"
    assert (
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
        is None
    )
    assert len(calls) == 4
