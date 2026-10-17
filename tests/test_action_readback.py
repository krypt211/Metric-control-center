"""Documented READ diagnostics on synthetic HTTP and isolated local databases."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from test_action_job_observation import acknowledged, observe, response
from test_controlled_rehearsal import ACTOR, TOKEN, prepared, responder
from test_controlled_rehearsal import mock_gate as rehearsal_mock_gate
from test_controlled_rehearsal import setup as rehearsal_setup
from test_sync import NOW

from services.actions.engine import ActionEngine, ActionRejected
from services.metricflow.errors import InvalidResponse
from services.metricflow.readback import collect_reported_status
from services.metricflow.reader import MetricFlowConnector
from services.providers.contracts import WriteDisabled
from services.providers.models import ProviderConnection
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    ApiQuota,
    EntityCurrentState,
    User,
)

READ_TOKEN = "mfk_fixture_separate_readback_read"


@pytest.fixture
def setup(tmp_path):
    yield from rehearsal_setup.__wrapped__(tmp_path)


@pytest.fixture
def mock_gate(monkeypatch):
    yield from rehearsal_mock_gate.__wrapped__(monkeypatch)


def payload(stamp=NOW, status="PAUSED", effective="PAUSED", **changes):
    value = {
        "data": [
            {
                "ad_account_id": "act_100",
                "ad_id": "1003",
                "adset_id": "1002",
                "campaign_id": "1001",
                "date": NOW.date().isoformat(),
                "status": status,
                "effective_status": effective,
            }
        ],
        "meta": {"data_updated_at": stamp.isoformat() if stamp else None},
        "pagination": {"has_more": False, "cursor": None},
    }
    value.update(changes)
    return value


def collect(handler, operation="PAUSE_AD"):
    async def run():
        async with MetricFlowConnector(
            READ_TOKEN,
            transport=httpx.MockTransport(handler),
            read_retries=0,
        ) as connector:
            return await collect_reported_status(
                connector,
                account_id="act_100",
                ad_id="1003",
                adset_id="1002",
                campaign_id="1001",
                day=NOW.date(),
                operation=operation,
                command_started_at=NOW,
                now=NOW + timedelta(seconds=20),
            )

    return asyncio.run(run())


@pytest.mark.parametrize(
    "operation,status", [("PAUSE_AD", "PAUSED"), ("ENABLE_AD", "ACTIVE")]
)
def test_typed_readback_uses_documented_filter_and_separate_read_key(operation, status):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and request.url.path == "/api/v1/insights"
        assert dict(request.url.params) == {
            "level": "ad",
            "ad_account_ids": "act_100",
            "fields": "spend",
            "currency": "native",
            "limit": "100",
            "from": NOW.date().isoformat(),
            "to": NOW.date().isoformat(),
        }
        assert request.headers["authorization"] == "Bearer " + READ_TOKEN
        assert not request.content
        return httpx.Response(200, json=payload(status=status, effective=status))

    evidence = collect(handler, operation)
    assert evidence.outcome == "REPORTED_STATUS_MATCH_NEEDS_AUTHORITY"
    assert not evidence.authoritative and evidence.pages == len(calls) == 1


@pytest.mark.parametrize(
    "changes,outcome",
    [
        ({"stamp": None}, "FRESHNESS_UNKNOWN"),
        ({"stamp": NOW - timedelta(seconds=1)}, "STALE_SYNC"),
        ({"stamp": NOW + timedelta(hours=1)}, "FUTURE_SYNC"),
        ({"status": None}, "STATUS_UNKNOWN"),
        ({"status": TOKEN}, "STATUS_UNKNOWN"),
        ({"effective": "CAMPAIGN_PAUSED"}, "REPORTED_STATUS_MISMATCH"),
        ({"data": []}, "NOT_FOUND"),
    ],
)
def test_status_and_sync_diagnostics_do_not_claim_authority(changes, outcome):
    evidence = collect(lambda _: httpx.Response(200, json=payload(**changes)))
    assert evidence.outcome == outcome and not evidence.authoritative
    assert TOKEN not in repr(evidence)


@pytest.mark.parametrize(
    "failure",
    [
        "wrong_account",
        "wrong_date",
        "hierarchy",
        "duplicate",
        "naive_stamp",
        "missing_pagination",
        "bad_type",
        "cursor_loop",
        "snapshot_changed",
        "too_many_rows",
    ],
)
def test_invalid_or_ambiguous_readback_is_rejected(failure):
    calls = []

    def handler(_):
        calls.append(1)
        value = payload()
        if failure == "wrong_account":
            value["data"][0]["ad_account_id"] = "act_999"
        if failure == "wrong_date":
            value["data"][0]["date"] = "2000-01-01"
        if failure == "hierarchy":
            value["data"][0]["adset_id"] = "999"
        if failure == "duplicate":
            value["data"] *= 2
        if failure == "too_many_rows":
            value["data"] *= 101
        if failure == "naive_stamp":
            value["meta"]["data_updated_at"] = "2026-10-18T12:00:00"
        if failure == "missing_pagination":
            value["pagination"] = {}
        if failure == "bad_type":
            value["data"][0]["ad_id"] = 1003
        if failure in ("cursor_loop", "snapshot_changed"):
            value["data"] = []
            value["pagination"] = {"has_more": True, "cursor": "same"}
            if failure == "snapshot_changed" and len(calls) > 1:
                value["meta"]["data_updated_at"] = (
                    NOW + timedelta(seconds=1)
                ).isoformat()
        return httpx.Response(200, json=value)

    with pytest.raises(InvalidResponse):
        collect(handler)
    assert len(calls) <= 2


def test_pagination_hard_budget_and_no_false_absence():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json=payload(
                data=[],
                pagination={"has_more": True, "cursor": str(len(calls))},
            ),
        )

    evidence = collect(handler)
    assert evidence.outcome == "PAGE_BUDGET_EXHAUSTED" and len(calls) == 3
    assert calls[1].url.params["cursor"] == "1"


def successful_job(fixture):
    engine, _sf, vault, _clock = fixture
    request_id, posts = acknowledged(fixture)
    observe(
        engine,
        request_id,
        vault,
        httpx.MockTransport(lambda _: httpx.Response(200, json=response())),
    )
    return request_id, posts


def readback(engine, request_id, handler):
    return asyncio.run(
        engine.readback_rehearsal(
            ACTOR,
            request_id,
            read_key=READ_TOKEN,
            transport=httpx.MockTransport(handler),
        )
    )


def stored(sf, request_id):
    with sf() as s:
        row = s.get(ActionRequest, request_id)
        return row.status, row.provenance["controlled"].get("readback")


def test_engine_post_job_readback_match_restart_and_no_ownership(setup, mock_gate):
    engine, sf, _vault, clock = setup
    request_id, posts = successful_job(setup)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer " + READ_TOKEN
        return httpx.Response(200, json=payload(stamp=clock[0]))

    assert readback(engine, request_id, handler) == request_id
    restarted = ActionEngine(sf, engine.policy, clock=engine.clock)
    assert readback(restarted, request_id, handler) is None
    status, evidence = stored(sf, request_id)
    assert status == "unknown" and not evidence["authoritative"]
    assert evidence["outcome"] == "REPORTED_STATUS_MATCH_NEEDS_AUTHORITY"
    assert evidence["attempts"] == 1 and len(calls) == len(posts) == 1
    assert evidence["read_credential_revision"] == 1
    with sf() as s:
        assert s.get(EntityCurrentState, "ad").status == "ACTIVE"
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 1
        assert not any(v.event == "verified" for v in s.scalars(select(ActionLog)))
        assert (
            s.get(
                ApiQuota, (ACTOR["workspace"], "metricflow", clock[0].date())
            ).requests
            == 3
        )
        assert READ_TOKEN not in json.dumps(s.get(ActionRequest, request_id).provenance)
    assert engine.verify_pending() == 0


@pytest.mark.parametrize(
    "failure",
    [401, 403, 429, 503, "timeout", "invalid", "revoke", "rotate", "quota", "deadline"],
)
def test_engine_stops_once_without_retry_or_write(setup, mock_gate, failure):
    engine, sf, _vault, clock = setup
    request_id, posts = successful_job(setup)
    if failure == "revoke":
        with sf.begin() as s:
            s.get(User, ACTOR["id"]).is_active = False
    if failure == "rotate":
        with sf.begin() as s:
            s.get(ProviderConnection, (ACTOR["workspace"], "metricflow")).revision += 1
    if failure == "quota":
        with sf.begin() as s:
            s.get(
                ApiQuota, (ACTOR["workspace"], "metricflow", clock[0].date())
            ).requests = 800
    if failure == "deadline":
        clock[0] += timedelta(seconds=600)
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout(READ_TOKEN, request=request)
        if failure == "invalid":
            return httpx.Response(200, content=READ_TOKEN)
        return httpx.Response(
            failure, json={"secret": READ_TOKEN}, headers={"Retry-After": "90"}
        )

    if failure in ("revoke", "rotate"):
        with pytest.raises((HTTPException, ActionRejected)):
            readback(engine, request_id, handler)
        assert stored(sf, request_id)[1] is None
    else:
        assert readback(engine, request_id, handler) == request_id
        assert readback(engine, request_id, handler) is None
        assert stored(sf, request_id)[0] == "unknown"
    assert len(calls) == (
        0 if failure in ("revoke", "rotate", "quota", "deadline") else 1
    )
    assert len(posts) == 1
    with sf() as s:
        assert READ_TOKEN not in json.dumps(
            [v.details for v in s.scalars(select(ActionLog))]
        )
        if failure == 429:
            assert s.get(
                ApiQuota, (ACTOR["workspace"], "metricflow", clock[0].date())
            ).blocked_until


def test_crash_during_readback_keeps_claim_and_recovers_without_resend(
    setup, mock_gate
):
    engine, sf, _vault, clock = setup
    request_id, _ = successful_job(setup)
    calls = []

    def handler(_):
        calls.append(1)
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        readback(engine, request_id, handler)
    assert stored(sf, request_id)[1]["state"] == "IN_FLIGHT"
    assert readback(engine, request_id, handler) is None and len(calls) == 1
    clock[0] += timedelta(seconds=600)
    assert engine.verify_pending() == 0
    assert stored(sf, request_id)[1]["error_code"] == "READBACK_DEADLINE"
    assert readback(engine, request_id, handler) is None and len(calls) == 1


def test_readback_requires_successful_job_and_explicit_mock(setup, mock_gate):
    engine, _sf, _vault, _clock = setup
    request_id, _ = acknowledged(setup)
    handler = Mock()
    with pytest.raises(ActionRejected, match="SUCCESSFUL_CORRELATED_JOB"):
        readback(engine, request_id, handler)
    with pytest.raises(ActionRejected, match="EXPLICIT_MOCK"):
        asyncio.run(
            engine.readback_rehearsal(
                ACTOR, request_id, read_key=READ_TOKEN, transport=None
            )
        )
    handler.assert_not_called()


def test_real_gate_holds_before_db_or_http(setup):
    engine, _sf, _vault, _clock = setup
    engine.sessions = Mock(side_effect=AssertionError("DB must not open"))
    handler = Mock()
    with pytest.raises(WriteDisabled):
        readback(engine, "any", handler)
    engine.sessions.assert_not_called()
    handler.assert_not_called()


def test_enable_path_uses_active_readback_without_verifying_ownership(setup, mock_gate):
    engine, sf, vault, clock = setup
    with sf.begin() as session:
        session.get(EntityCurrentState, "ad").status = "PAUSED"
    permit = prepared(engine, operation="ENABLE_AD")
    posts = []
    asyncio.run(
        engine.execute_rehearsal(
            ACTOR,
            permit["id"],
            permit["revision"],
            vault=vault,
            transport=responder(posts, operation="enable"),
        )
    )
    clock[0] += timedelta(seconds=10)
    observe(
        engine,
        permit["id"],
        vault,
        httpx.MockTransport(lambda _: httpx.Response(200, json=response())),
    )
    readback(
        engine,
        permit["id"],
        lambda _: httpx.Response(
            200, json=payload(stamp=clock[0], status="ACTIVE", effective="ACTIVE")
        ),
    )
    assert (
        stored(sf, permit["id"])[1]["outcome"]
        == "REPORTED_STATUS_MATCH_NEEDS_AUTHORITY"
    )
    assert engine.verify_pending() == 0 and len(posts) == 1
    with sf() as session:
        assert session.get(EntityCurrentState, "ad").status == "PAUSED"


@pytest.mark.parametrize("change", ["revoke", "rotate", "quota", "timezone"])
def test_between_pages_rechecks_permissions_revision_quota_and_timezone(
    setup, mock_gate, change
):
    from services.storage.models import AdAccount

    engine, sf, _vault, clock = setup
    request_id, _ = successful_job(setup)
    calls = []

    def handler(_):
        calls.append(1)
        with sf.begin() as session:
            if change == "revoke":
                session.get(User, ACTOR["id"]).is_active = False
            if change == "rotate":
                session.get(
                    ProviderConnection, (ACTOR["workspace"], "metricflow")
                ).revision += 1
            if change == "quota":
                session.get(
                    ApiQuota, (ACTOR["workspace"], "metricflow", clock[0].date())
                ).requests = 800
            if change == "timezone":
                session.get(AdAccount, "account").timezone = "UTC"
        return httpx.Response(
            200, json=payload(data=[], pagination={"has_more": True, "cursor": "next"})
        )

    readback(engine, request_id, handler)
    assert len(calls) == 1
    assert stored(sf, request_id)[1]["outcome"] == "OUTCOME_UNKNOWN"


@pytest.mark.parametrize("status", [201, 202, 204, 302])
def test_readback_rejects_undocumented_http_status_without_retry(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, json=payload(), headers={"Location": "https://example.invalid"}
        )

    from services.metricflow.errors import APIError

    with pytest.raises((InvalidResponse, APIError)):
        collect(handler)
    assert len(calls) == 1


def test_readback_refuses_working_database_before_sql():
    from sqlalchemy.orm import sessionmaker

    from services.actions.engine import ActionPolicy
    from services.storage.database import make_engine

    db = make_engine("postgresql+psycopg://invalid:invalid@127.0.0.1:1/metric_control")
    engine = ActionEngine(sessionmaker(db), ActionPolicy(enabled=True))
    handler = Mock()
    from unittest.mock import patch

    with (
        patch("services.actions.safety.ActionSafetyGate.require_write"),
        pytest.raises(ActionRejected, match="ISOLATED_REHEARSAL_REQUIRED"),
    ):
        readback(engine, "not-opened", handler)
    handler.assert_not_called()
    db.dispose()
