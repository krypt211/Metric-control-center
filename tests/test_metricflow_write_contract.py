"""Pinned provider contract and mock-only AD transport acceptance."""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from services.actions.safety import ActionSafetyGate
from services.metricflow.errors import (
    ActionOutcomeUnknown,
    APIError,
    InvalidResponse,
    RateLimitExceeded,
)
from services.metricflow.writer import (
    ENTITY_WRITE_SCOPE,
    ActionAcknowledgement,
    MetricFlowActionConnector,
    decode_action_job,
)
from services.providers.contracts import WriteDisabled

TOKEN = "mfk_fixture_contract_write_only"
AD = "opaque_ad-123"


def ack(**changes):
    return {
        "success": True,
        "entity_id": AD,
        "message": "mock acknowledgement",
        **changes,
    }


def job(**changes):
    return {
        "job_id": 17,
        "action_type": "status",
        "status": "success",
        "total": 1,
        "done": 1,
        "succeeded": 1,
        "failed": 0,
        "results": [{"entity_id": AD, "success": True}],
        "created_at": "2026-10-15T00:00:00Z",
        "meta": {},
        **changes,
    }


@pytest.fixture
def mock_gate(monkeypatch):
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    # Only this file's explicit MockTransport callers use this synthetic permit.
    with patch.object(ActionSafetyGate, "require_verified_contract"):
        yield


@pytest.mark.parametrize("operation", ["pause", "enable"])
@pytest.mark.parametrize(
    "asynchronous,status", [(False, 200), (True, 202), (True, 200)]
)
def test_exact_ad_wire_and_typed_acknowledgement(
    mock_gate, operation, asynchronous, status
):
    calls = []

    def respond(request):
        calls.append(request)
        assert request.method == "POST"
        assert request.url.path == f"/api/v1/entities/{AD}/{operation}"
        assert dict(request.url.params) == ({"async": "true"} if asynchronous else {})
        assert json.loads(request.content) == {"level": "ad"}
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert "idempotency-key" not in request.headers  # Not documented by provider.
        return httpx.Response(status, json=ack(job_id=17 if asynchronous else None))

    async def run():
        async with MetricFlowActionConnector(
            TOKEN, transport=httpx.MockTransport(respond)
        ) as writer:
            return await getattr(writer, operation + "_entity")(
                AD, asynchronous=asynchronous
            )

    result = asyncio.run(run())
    assert result["success"] is True and result["entity_id"] == AD
    assert len(calls) == 1  # No implicit polling or readback.


@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        ack(success="true"),
        ack(success=False),
        ack(entity_id="other"),
        ack(message=None),
        ack(job_id=True),
        ack(job_id=-1),
        ack(job_id=9),
    ],
)
def test_bad_sync_ack_is_unknown_never_retried_or_leaked(mock_gate, body):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=body)

    async def run():
        async with MetricFlowActionConnector(
            TOKEN, transport=httpx.MockTransport(respond)
        ) as writer:
            with pytest.raises(ActionOutcomeUnknown) as error:
                await writer.pause_entity(AD)
            assert TOKEN not in str(error.value)

    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status,asynchronous,body",
    [
        (204, False, None),
        (201, False, ack()),
        (202, False, ack(job_id=17)),
        (202, True, ack()),
        (200, True, ack(job_id=None)),
        (200, False, {"message": TOKEN}),
    ],
)
def test_unsupported_or_incomplete_success_is_unknown(
    mock_gate, status, asynchronous, body
):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)

    async def run():
        async with MetricFlowActionConnector(
            TOKEN, transport=httpx.MockTransport(respond)
        ) as writer:
            with pytest.raises(ActionOutcomeUnknown) as error:
                await writer.enable_entity(AD, asynchronous=asynchronous)
            assert TOKEN not in str(error.value)

    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422, 429])
def test_http_rejection_is_sanitized_and_never_retried(mock_gate, status):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status, json={"error": TOKEN}, headers={"Retry-After": "60"}
        )

    async def run():
        async with MetricFlowActionConnector(
            TOKEN, transport=httpx.MockTransport(respond)
        ) as writer:
            with pytest.raises(APIError) as error:
                await writer.pause_entity(AD)
            assert error.value.status_code == status and TOKEN not in str(error.value)
            if status == 429:
                assert isinstance(error.value, RateLimitExceeded)
                assert error.value.retry_after_seconds == 60

    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure", ["connect", "timeout", "408", "503", "invalid-json"]
)
def test_uncertain_transport_has_one_attempt_and_no_secret(mock_gate, failure):
    calls = []

    def respond(request):
        calls.append(request)
        if failure == "connect":
            raise httpx.ConnectError(TOKEN, request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout(TOKEN, request=request)
        if failure == "invalid-json":
            return httpx.Response(200, text=TOKEN)
        return httpx.Response(int(failure), json={"error": TOKEN})

    async def run():
        async with MetricFlowActionConnector(
            TOKEN, transport=httpx.MockTransport(respond)
        ) as writer:
            with pytest.raises(ActionOutcomeUnknown) as error:
                await writer.pause_entity(AD, asynchronous=True)
            assert TOKEN not in str(error.value)

    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"job_id": 18},
        {"job_id": True},
        {"action_type": "budget"},
        {"total": 2},
        {"done": -1},
        {"succeeded": True},
        {"done": 0},
        {"results": None},
        {"results": [{"entity_id": "other", "success": True}]},
        {"results": [{"entity_id": AD, "success": False}]},
        {"status": "new-provider-state"},
        {"meta": None},
    ],
)
def test_job_decoder_holds_invalid_or_uncorrelated_results(changes):
    with pytest.raises(InvalidResponse):
        decode_action_job(job(**changes), job_id=17, entity_id=AD)


@pytest.mark.parametrize(
    "state", ["pending", "running", "success", "partial", "failed", "expired"]
)
def test_documented_job_states_are_local_decoding_only(state):
    value = job(status=state)
    if state != "success":
        value.update(done=0, succeeded=0, results=None)
    decoded = decode_action_job(value, job_id=17, entity_id=AD)
    assert decoded.status == state
    assert not hasattr(
        decoded, "verified"
    )  # Fresh authoritative readback is still required.


@pytest.mark.parametrize(
    "enabled,readonly",
    [("false", "true"), ("false", "false"), ("true", "true"), ("true", "false")],
)
def test_actual_runtime_gate_blocks_both_modes_before_http(
    monkeypatch, enabled, readonly
):
    monkeypatch.setenv("ACTIONS_ENABLED", enabled)
    monkeypatch.setenv("LOCAL_READ_ONLY", readonly)
    calls = []

    async def run():
        async with MetricFlowActionConnector(
            TOKEN, transport=httpx.MockTransport(lambda r: calls.append(r))
        ) as writer:
            for operation in (writer.pause_entity, writer.enable_entity):
                for asynchronous in (False, True):
                    with pytest.raises(WriteDisabled):
                        await operation(AD, asynchronous=asynchronous)

    asyncio.run(run())
    assert calls == []


def test_snapshot_matches_exact_supported_contract():
    root = Path(__file__).resolve().parents[1]
    snapshot = json.loads(
        (root / "docs/integrations/METRICFLOW_WRITE_OPENAPI_2026-10-15.json").read_text(
            encoding="utf-8"
        )
    )
    schemas = snapshot["components"]["schemas"]
    assert (
        snapshot["openapi"] == "3.1.0"
        and ENTITY_WRITE_SCOPE in snapshot["info"]["description"]
    )
    assert schemas["EntityActionRequest"]["required"] == ["level"]
    assert set(schemas["EntityActionResponse"]["required"]) == {
        "success",
        "entity_id",
        "message",
    }
    assert set(snapshot["paths"]) == {
        "/api/v1/entities/{entity_id}/pause",
        "/api/v1/entities/{entity_id}/enable",
        "/api/v1/jobs/{job_id}",
    }
    # Keep the source's 202 discrepancy visible; do not manufacture a schema.
    for op in ("pause", "enable"):
        operation = snapshot["paths"][f"/api/v1/entities/{{entity_id}}/{op}"]["post"]
        assert "202" not in operation["responses"] and "202" in operation["description"]


def test_provider_message_is_not_in_model_repr_and_extras_are_dropped():
    body = ack(message=TOKEN, undocumented_secret=TOKEN)
    result = ActionAcknowledgement.model_validate(copy.deepcopy(body))
    assert TOKEN not in repr(result)
    assert "undocumented_secret" not in result.model_dump()
