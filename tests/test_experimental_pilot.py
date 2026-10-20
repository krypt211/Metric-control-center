"""Experimental permission is explicit and scoped; all advertising HTTP is mocked."""

from __future__ import annotations

import asyncio
import copy
from datetime import timedelta
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from test_controlled_rehearsal import ACTOR, TOKEN, setup
from test_production_pilot import body

from services.actions.engine import ActionEngine, ActionRejected
from services.actions.experimental import (
    PREPARE,
    REVOKED,
    STATEMENT,
    ExperimentalPrepareInput,
    prepare_experiment,
)
from services.actions.pilot import authorize_pilot, execute_pilot
from services.providers.contracts import WriteDisabled
from services.providers.integration_models import WriteCredentialState
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    ApiQuota,
    EntityCurrentState,
)

__all__ = ["setup"]


def catalogs(now):
    rows = {
        "campaigns": {"id": "1001", "status": "PAUSED", "effective_status": "PAUSED"},
        "adsets": {
            "id": "1002",
            "campaign_id": "1001",
            "parent_id": "1001",
            "status": "PAUSED",
            "effective_status": "PAUSED",
        },
        "ads": {
            "id": "1003",
            "campaign_id": "1001",
            "parent_id": "1002",
            "status": "ACTIVE",
            "effective_status": "ADSET_PAUSED",
        },
    }
    return {
        k: {
            "data": [r],
            "meta": {
                "total": 1,
                "limit": None,
                "offset": None,
                "data_updated_at": now.isoformat(),
            },
        }
        for k, r in rows.items()
    }


@pytest.fixture
def fixture(setup, monkeypatch):
    _engine, sf, _vault, clock = setup
    monkeypatch.setenv("ACTIONS_ENABLED", "false")
    monkeypatch.setenv("LOCAL_READ_ONLY", "true")
    with sf.begin() as s:
        s.get(WriteCredentialState, ACTOR["workspace"]).scopes = [
            "entities:write",
            "campaigns:read",
        ]
        state = s.get(EntityCurrentState, "ad")
        state.status = "ADSET_PAUSED"
        state.raw = {"status": "ADSET_PAUSED"}
        state.observed_at = clock[0] - timedelta(days=5)
    return setup


def input_body(**changes):
    return ExperimentalPrepareInput.model_validate(
        {
            "entity_id": "ad",
            "credential_revision": 1,
            "management_confirmed": True,
            "statement": PREPARE,
            **changes,
        }
    )


def response(payloads, calls, *, post_error=None):
    def respond(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer " + TOKEN
        if request.method == "GET":
            return httpx.Response(
                200, json=payloads[request.url.path.rsplit("/", 1)[-1]]
            )
        assert (
            request.method == "POST"
            and request.url.path == "/api/v1/entities/1003/pause"
        )
        if post_error == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        return httpx.Response(
            post_error or 200,
            json={}
            if post_error
            else {"success": True, "entity_id": "1003", "message": "fixture"},
        )

    return respond


def prepare(fixture, *, payloads=None):
    engine, _sf, vault, clock = fixture
    calls = []
    transport = httpx.MockTransport(response(payloads or catalogs(clock[0]), calls))
    card = asyncio.run(
        prepare_experiment(
            engine, ACTOR, input_body(), vault=vault, transport=transport
        )
    )
    return card, calls


def confirm(engine, card):
    row = {"id": card["request_id"], "revision": card["revision"]}
    for event in ("preflight", "confirm"):
        row = engine.transition_manual(ACTOR, row["id"], event, row["revision"])
    return row


def permit(fixture, monkeypatch):
    engine, _, _, _ = fixture
    card, calls = prepare(fixture)
    row = confirm(engine, card)
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    return authorize_pilot(
        engine, ACTOR, row["id"], body(row, statement=STATEMENT)
    ), calls


def test_prepare_only_reads_and_preserves_delivery_facts(fixture):
    engine, sf, _vault, _ = fixture
    card, calls = prepare(fixture)
    assert len(calls) == 3 and all(r.method == "GET" for r in calls)
    assert (
        card["provider_namespace_confirmed"] is False
        and card["status"] == "PREPARED_NO_POST_AUTHORIZATION"
    )
    with sf() as s:
        row = s.get(ActionRequest, card["request_id"])
        assert row.status == "DRAFT" and not row.provenance.get("controlled")
        assert row.provenance["captured"]["status"] == "ACTIVE"
        assert row.provenance["captured"]["effective_status"] == "ADSET_PAUSED"
        assert s.get(EntityCurrentState, "ad").status == "ADSET_PAUSED"
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0
        assert (
            s.scalar(
                select(func.count())
                .select_from(ActionLog)
                .where(ActionLog.event == "pilot_external_evidence_accepted")
            )
            == 0
        )
    row = confirm(engine, card)
    with pytest.raises(WriteDisabled):
        authorize_pilot(engine, ACTOR, row["id"], body(row, statement=STATEMENT))
    assert row["preflight"]["local_allowed"] is True


def test_preparation_is_not_live_authorization_even_with_enabled_flags(
    fixture, monkeypatch
):
    engine, _, _, _ = fixture
    card, _ = prepare(fixture)
    row = confirm(engine, card)
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    with pytest.raises(ActionRejected, match="PILOT_AUTHORIZATION_STATEMENT_MISMATCH"):
        authorize_pilot(engine, ACTOR, row["id"], body(row))
    v = Mock()
    with pytest.raises(WriteDisabled):
        asyncio.run(
            execute_pilot(
                engine,
                ACTOR,
                row["id"],
                row["revision"],
                vault=v,
                transport=httpx.MockTransport(lambda r: None),
            )
        )
    v.unseal.assert_not_called()


def test_one_pause_requires_three_revalidation_gets_and_never_resends(
    fixture, monkeypatch
):
    engine, sf, vault, clock = fixture
    p, _ = permit(fixture, monkeypatch)
    calls = []
    transport = httpx.MockTransport(response(catalogs(clock[0]), calls))
    assert (
        asyncio.run(
            execute_pilot(
                engine, ACTOR, p["id"], p["revision"], vault=vault, transport=transport
            )
        )
        == p["id"]
    )
    restart = ActionEngine(sf, engine.policy, clock=engine.clock)
    assert (
        asyncio.run(
            execute_pilot(
                restart, ACTOR, p["id"], p["revision"], vault=vault, transport=transport
            )
        )
        is None
    )
    assert [r.method for r in calls] == ["GET", "GET", "GET", "POST"]
    with sf() as s:
        row = s.get(ActionRequest, p["id"])
        c = row.provenance["controlled"]
        assert c["wire_spent"] and c["validation_gets"] == 3
        assert c["provider_contract"]["experimental_unverified_id"] is True
        assert row.status == "verifying"
        assert s.get(EntityCurrentState, "ad").status == "ADSET_PAUSED"


@pytest.mark.parametrize(
    "mutation",
    [
        "campaign_enabled",
        "group_enabled",
        "ad_paused",
        "missing_effective",
        "wrong_parent",
        "duplicate",
        "partial",
        "stale",
        "mixed_snapshot",
    ],
)
def test_invalid_read_cannot_create_draft_or_post(fixture, mutation):
    _engine, sf, _, clock = fixture
    data = catalogs(clock[0])
    if mutation == "campaign_enabled":
        data["campaigns"]["data"][0]["status"] = "ACTIVE"
    elif mutation == "group_enabled":
        data["adsets"]["data"][0]["status"] = "ACTIVE"
    elif mutation == "ad_paused":
        data["ads"]["data"][0]["status"] = "PAUSED"
    elif mutation == "missing_effective":
        data["ads"]["data"][0].pop("effective_status")
    elif mutation == "wrong_parent":
        data["ads"]["data"][0]["parent_id"] = "other"
    elif mutation == "duplicate":
        data["ads"]["data"] *= 2
        data["ads"]["meta"]["total"] = 2
    elif mutation == "partial":
        data["ads"]["meta"]["total"] = 2
    elif mutation == "mixed_snapshot":
        data["ads"]["meta"]["data_updated_at"] = (
            clock[0] - timedelta(seconds=1)
        ).isoformat()
    else:
        for payload in data.values():
            payload["meta"]["data_updated_at"] = (
                clock[0] - timedelta(seconds=901)
            ).isoformat()
    with pytest.raises(WriteDisabled):
        prepare(fixture, payloads=data)
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(ActionRequest)) == 0
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0


@pytest.mark.parametrize(
    "mutation",
    ["parent_enabled", "stale", "revoked", "key_rotation", "different_statement"],
)
def test_changes_before_dispatch_stop_mock_post(fixture, monkeypatch, mutation):
    engine, sf, vault, clock = fixture
    p, _ = permit(fixture, monkeypatch)
    data = catalogs(clock[0])
    calls = []
    if mutation == "parent_enabled":
        data["campaigns"]["data"][0]["status"] = "ACTIVE"
    elif mutation == "stale":
        for payload in data.values():
            payload["meta"]["data_updated_at"] = (
                clock[0] - timedelta(seconds=901)
            ).isoformat()
    else:
        with sf.begin() as s:
            if mutation == "revoked":
                s.add(
                    ActionLog(
                        id="revoked",
                        request_id=p["id"],
                        event=REVOKED,
                        created_at=clock[0],
                        details={},
                    )
                )
            elif mutation == "key_rotation":
                s.get(WriteCredentialState, ACTOR["workspace"]).revision = 2
            else:
                r = s.get(ActionRequest, p["id"])
                c = copy.deepcopy(r.provenance["controlled"])
                c["authorization"]["statement"] = (
                    "AUTHORIZE_ONE_METRICFLOW_AD_STATUS_POST"
                )
                r.provenance = {**r.provenance, "controlled": c}
    try:
        asyncio.run(
            execute_pilot(
                engine,
                ACTOR,
                p["id"],
                p["revision"],
                vault=vault,
                transport=httpx.MockTransport(response(data, calls)),
            )
        )
    except (WriteDisabled, ActionRejected):
        pass
    assert all(r.method == "GET" for r in calls)


@pytest.mark.parametrize("failure", ["timeout", 403, 429, 503])
def test_unknown_post_does_not_repeat_or_restore(fixture, monkeypatch, failure):
    engine, _, vault, clock = fixture
    p, _ = permit(fixture, monkeypatch)
    calls = []
    transport = httpx.MockTransport(
        response(catalogs(clock[0]), calls, post_error=failure)
    )
    asyncio.run(
        execute_pilot(
            engine, ACTOR, p["id"], p["revision"], vault=vault, transport=transport
        )
    )
    assert (
        asyncio.run(
            execute_pilot(
                engine, ACTOR, p["id"], p["revision"], vault=vault, transport=transport
            )
        )
        is None
    )
    assert sum(r.method == "POST" for r in calls) == 1


@pytest.mark.parametrize("value", [False, 1, "true"])
def test_boolean_attestation_cannot_be_coerced(value):
    with pytest.raises(ValidationError):
        input_body(management_confirmed=value)


@pytest.mark.parametrize("failure", [429, 503, "malformed"])
def test_preparation_provider_failure_cannot_create_or_send_command(fixture, failure):
    engine, sf, vault, _clock = fixture
    calls = []

    def fail(request):
        calls.append(request)
        assert request.method == "GET"
        return (
            httpx.Response(200, json=[])
            if failure == "malformed"
            else httpx.Response(failure, json={})
        )

    with pytest.raises(WriteDisabled):
        asyncio.run(
            prepare_experiment(
                engine,
                ACTOR,
                input_body(),
                vault=vault,
                transport=httpx.MockTransport(fail),
            )
        )
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(ActionRequest)) == 0
        if failure == 429:
            quota = s.scalar(select(ApiQuota).where(ApiQuota.provider == "metricflow"))
            assert quota.blocked_until is not None
    assert len(calls) <= 3
