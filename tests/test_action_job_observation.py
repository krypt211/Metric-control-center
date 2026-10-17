"""Bounded GET observation uses synthetic credentials and explicit MockTransport only."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from test_controlled_rehearsal import ACTOR, TOKEN, prepared, responder
from test_controlled_rehearsal import mock_gate as rehearsal_mock_gate
from test_controlled_rehearsal import setup as rehearsal_setup
from test_metricflow_write_contract import job

from services.actions.engine import ActionEngine, ActionRejected
from services.actions.job_observation import MAX_ATTEMPTS
from services.actions.write_credentials import WriteCredentialError
from services.metricflow.writer import MetricFlowActionConnector
from services.providers.contracts import WriteDisabled
from services.providers.integration_models import WriteCredentialState
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    ApiQuota,
    Entity,
    EntityCurrentState,
    User,
)


@pytest.fixture
def setup(tmp_path):
    yield from rehearsal_setup.__wrapped__(tmp_path)


@pytest.fixture
def mock_gate(monkeypatch):
    yield from rehearsal_mock_gate.__wrapped__(monkeypatch)


def acknowledged(fixture):
    engine, _sf, vault, clock = fixture
    permit = prepared(engine)
    posts = []
    asyncio.run(
        engine.execute_rehearsal(
            ACTOR,
            permit["id"],
            permit["revision"],
            vault=vault,
            transport=responder(posts),
        )
    )
    assert len(posts) == 1
    clock[0] += timedelta(seconds=10)
    return permit["id"], posts


def response(state="success", **changes):
    value = job(
        job_id=41, results=[{"entity_id": "1003", "success": True}], status=state
    )
    if state != "success":
        value.update(done=0, succeeded=0, results=None)
    value.update(changes)
    return value


def observe(engine, request_id, vault, transport):
    return asyncio.run(
        engine.observe_rehearsal_job(
            ACTOR, request_id, vault=vault, transport=transport
        )
    )


def saved(sf, request_id):
    with sf() as s:
        row = s.get(ActionRequest, request_id)
        return row.status, row.provenance["controlled"]["observation"]


def test_pending_restart_running_success_needs_readback(setup, mock_gate):
    engine, sf, vault, clock = setup
    request_id, posts = acknowledged(setup)
    calls, states = [], iter(["pending", "running", "success"])

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and request.url.path == "/api/v1/jobs/41"
        assert not request.content and not request.url.query
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(200, json=response(next(states)))

    for _ in range(3):
        restarted = ActionEngine(sf, engine.policy, clock=engine.clock)
        assert (
            observe(restarted, request_id, vault, httpx.MockTransport(handler))
            == request_id
        )
        # No new request while not due, or after terminal job success.
        assert (
            observe(restarted, request_id, vault, httpx.MockTransport(handler)) is None
        )
        clock[0] += timedelta(seconds=10)
    status, observation = saved(sf, request_id)
    assert (
        status == "verifying" and observation["state"] == "JOB_SUCCESS_NEEDS_READBACK"
    )
    assert observation["attempts"] == 3 and len(calls) == 3 and len(posts) == 1
    with sf.begin() as s:
        s.get(EntityCurrentState, "ad").status = "PAUSED"
        s.get(EntityCurrentState, "ad").observed_at = clock[0]
    assert engine.verify_pending() == 0
    with sf() as s:
        assert (
            s.get(
                ApiQuota, (ACTOR["workspace"], "metricflow", clock[0].date())
            ).requests
            == 4
        )
        logs = s.scalars(select(ActionLog)).all()
        assert not any(v.event == "verified" for v in logs)
        assert TOKEN not in json.dumps([v.details for v in logs])
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 1


@pytest.mark.parametrize("state", ["partial", "failed", "expired"])
def test_terminal_failure_is_unknown_not_a_proven_rejection(setup, mock_gate, state):
    engine, sf, vault, _ = setup
    request_id, posts = acknowledged(setup)
    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(200, json=response(state, error_message=TOKEN))

    assert (
        observe(engine, request_id, vault, httpx.MockTransport(handler)) == request_id
    )
    assert observe(engine, request_id, vault, httpx.MockTransport(handler)) is None
    status, observed = saved(sf, request_id)
    assert status == "unknown" and observed["error_code"] == "JOB_" + state.upper()
    assert len(calls) == 1 and len(posts) == 1
    assert TOKEN not in json.dumps(observed)


@pytest.mark.parametrize(
    "failure",
    [
        401,
        402,
        403,
        404,
        429,
        503,
        "timeout",
        "json",
        "wrong_job",
        "wrong_ad",
        "wrong_type",
        "204",
    ],
)
def test_one_get_failure_stops_without_retry_or_secret(setup, mock_gate, failure):
    engine, sf, vault, clock = setup
    request_id, posts = acknowledged(setup)
    calls = []

    def handler(r):
        calls.append(r)
        if failure == "timeout":
            raise httpx.ReadTimeout(TOKEN, request=r)
        if failure == "json":
            return httpx.Response(200, content=TOKEN)
        if failure == "204":
            return httpx.Response(204)
        if isinstance(failure, int):
            return httpx.Response(
                failure, json={"error": TOKEN}, headers={"Retry-After": "90"}
            )
        return httpx.Response(
            200,
            json=response(
                **{
                    "wrong_job": {"job_id": 42},
                    "wrong_ad": {"results": [{"entity_id": "other", "success": True}]},
                    "wrong_type": {"action_type": "budget"},
                }[failure]
            ),
        )

    observe(engine, request_id, vault, httpx.MockTransport(handler))
    assert saved(sf, request_id)[0] == "unknown" and len(calls) == 1 and len(posts) == 1
    assert (
        observe(
            ActionEngine(sf, engine.policy, clock=engine.clock),
            request_id,
            vault,
            httpx.MockTransport(handler),
        )
        is None
    )
    with sf() as s:
        stored = s.get(ActionRequest, request_id)
        assert TOKEN not in json.dumps(stored.provenance)
        assert TOKEN not in json.dumps(
            [v.details for v in s.scalars(select(ActionLog))]
        )
        if failure == 429:
            assert s.get(
                ApiQuota, (ACTOR["workspace"], "metricflow", clock[0].date())
            ).blocked_until
    if failure == 429:
        with pytest.raises(ActionRejected):
            engine.reserve_api_request(ACTOR["workspace"])


def test_attempt_budget_and_interval_survive_restart(setup, mock_gate):
    engine, sf, vault, clock = setup
    request_id, posts = acknowledged(setup)
    calls = []

    def handler(r):
        calls.append(r)
        return httpx.Response(200, json=response("pending"))

    for i in range(MAX_ATTEMPTS):
        restarted = ActionEngine(sf, engine.policy, clock=engine.clock)
        observe(restarted, request_id, vault, httpx.MockTransport(handler))
        if i < MAX_ATTEMPTS - 1:
            clock[0] += timedelta(seconds=9)
            assert (
                observe(restarted, request_id, vault, httpx.MockTransport(handler))
                is None
            )
            clock[0] += timedelta(seconds=1)
    status, observed = saved(sf, request_id)
    assert status == "unknown" and observed["attempts"] == MAX_ATTEMPTS
    assert observed["error_code"] == "OBSERVATION_ATTEMPTS_EXHAUSTED"
    clock[0] += timedelta(seconds=10)
    assert observe(restarted, request_id, vault, httpx.MockTransport(handler)) is None
    assert len(calls) == MAX_ATTEMPTS and len(posts) == 1


def test_deadline_stops_without_get(setup, mock_gate):
    engine, sf, vault, clock = setup
    request_id, _ = acknowledged(setup)
    clock[0] += timedelta(minutes=5)
    handler = Mock()
    observe(engine, request_id, vault, httpx.MockTransport(handler))
    assert saved(sf, request_id)[0] == "unknown" and not handler.called


def test_crash_does_not_resend_get_or_post_and_existing_recovery_closes(
    setup, mock_gate
):
    engine, sf, vault, clock = setup
    request_id, posts = acknowledged(setup)

    class Crash(BaseException):
        pass

    calls = []

    def handler(r):
        calls.append(r)
        raise Crash()

    with pytest.raises(Crash):
        observe(engine, request_id, vault, httpx.MockTransport(handler))
    assert saved(sf, request_id)[1]["state"] == "IN_FLIGHT"
    assert (
        observe(
            ActionEngine(sf, engine.policy, clock=engine.clock),
            request_id,
            vault,
            httpx.MockTransport(handler),
        )
        is None
    )
    clock[0] += timedelta(minutes=5)
    assert engine.verify_pending() == 0
    assert saved(sf, request_id)[0] == "unknown" and len(calls) == 1 and len(posts) == 1


@pytest.mark.parametrize("change", ["identity", "actor", "credential", "policy", "job"])
def test_changed_scope_or_bounds_stop_before_get(setup, mock_gate, change):
    engine, sf, vault, _ = setup
    request_id, _ = acknowledged(setup)
    with sf.begin() as s:
        if change == "identity":
            s.get(Entity, "ad").external_id = "9999"
        elif change == "actor":
            s.get(User, ACTOR["id"]).is_active = False
        elif change == "credential":
            s.get(WriteCredentialState, ACTOR["workspace"]).revision = 2
        else:
            row = s.get(ActionRequest, request_id)
            control = dict(row.provenance["controlled"])
            if change == "job":
                control["job_id"] = 42
            else:
                control["observation"] = {**control["observation"], "max_attempts": 7}
            row.provenance = {**row.provenance, "controlled": control}
    handler = Mock()
    with pytest.raises((ActionRejected, WriteCredentialError, HTTPException)):
        observe(engine, request_id, vault, httpx.MockTransport(handler))
    assert not handler.called


def test_legitimate_status_change_does_not_break_job_identity(setup, mock_gate):
    engine, sf, vault, clock = setup
    request_id, _ = acknowledged(setup)
    with sf.begin() as s:
        state = s.get(EntityCurrentState, "ad")
        state.status, state.observed_at = "PAUSED", clock[0]
    observe(
        engine,
        request_id,
        vault,
        httpx.MockTransport(lambda r: httpx.Response(200, json=response())),
    )
    assert saved(sf, request_id)[1]["state"] == "JOB_SUCCESS_NEEDS_READBACK"


def test_late_success_after_deadline_is_unknown(setup, mock_gate):
    engine, sf, vault, clock = setup
    request_id, _ = acknowledged(setup)

    def handler(r):
        clock[0] += timedelta(minutes=6)
        return httpx.Response(200, json=response())

    observe(engine, request_id, vault, httpx.MockTransport(handler))
    assert saved(sf, request_id)[0] == "unknown"


@pytest.mark.parametrize("enabled,readonly", [("false", "true"), ("true", "false")])
def test_real_gate_stops_observation_before_vault_or_http(
    setup, monkeypatch, enabled, readonly
):
    engine, _, _, _ = setup
    monkeypatch.setenv("ACTIONS_ENABLED", enabled)
    monkeypatch.setenv("LOCAL_READ_ONLY", readonly)
    vault, handler = Mock(), Mock()
    with pytest.raises(WriteDisabled):
        observe(engine, "not-used", vault, httpx.MockTransport(handler))
    assert not vault.unseal.called and not handler.called

    async def run():
        async with MetricFlowActionConnector(
            TOKEN, transport=httpx.MockTransport(handler)
        ) as connector:
            with pytest.raises(WriteDisabled):
                await connector.get_action_job(41, entity_id="1003")

    asyncio.run(run())
    assert not handler.called


def test_real_transport_is_never_admitted(setup):
    engine, _, _, _ = setup
    transport = httpx.AsyncHTTPTransport()
    try:
        with pytest.raises(ActionRejected, match="EXPLICIT_MOCK_TRANSPORT_REQUIRED"):
            observe(engine, "not-used", Mock(), transport)
    finally:
        asyncio.run(transport.aclose())


@pytest.mark.parametrize("change", ["actor", "credential"])
def test_change_while_opening_vault_stops_get_after_durable_slot(
    setup, mock_gate, change
):
    engine, sf, vault, _ = setup
    request_id, posts = acknowledged(setup)
    private = Mock(wraps=vault)

    def unseal(*args):
        value = vault.unseal(*args)
        with sf.begin() as session:
            if change == "actor":
                session.get(User, ACTOR["id"]).is_active = False
            else:
                session.get(WriteCredentialState, ACTOR["workspace"]).revision = 2
        return value

    private.unseal.side_effect = unseal
    handler = Mock()
    observe(engine, request_id, private, httpx.MockTransport(handler))
    assert saved(sf, request_id)[0] == "unknown"
    assert saved(sf, request_id)[1]["attempts"] == 1
    assert not handler.called and len(posts) == 1


def test_late_response_is_retained_after_actor_revocation(setup, mock_gate):
    engine, sf, vault, _ = setup
    request_id, _ = acknowledged(setup)

    def handler(_request):
        with sf.begin() as session:
            session.get(User, ACTOR["id"]).is_active = False
        return httpx.Response(200, json=response())

    observe(engine, request_id, vault, httpx.MockTransport(handler))
    assert saved(sf, request_id)[1]["state"] == "JOB_SUCCESS_NEEDS_READBACK"
    assert engine.verify_pending() == 0


def test_exhausted_shared_quota_stops_before_get(setup, mock_gate):
    engine, sf, vault, clock = setup
    request_id, _ = acknowledged(setup)
    with sf.begin() as session:
        quota = session.get(
            ApiQuota, (ACTOR["workspace"], "metricflow", clock[0].date())
        )
        quota.requests = engine.policy.daily_api_budget
    handler = Mock()
    observe(engine, request_id, vault, httpx.MockTransport(handler))
    assert saved(sf, request_id)[0] == "unknown" and not handler.called


def test_working_database_guard_precedes_any_observer_query(setup, mock_gate):
    engine, _, _, _ = setup
    session = Mock()
    session.bind.dialect.name = "postgresql"
    session.bind.url.database = "metric_control"
    engine.sessions = Mock()
    engine.sessions.begin.return_value.__enter__ = Mock(return_value=session)
    engine.sessions.begin.return_value.__exit__ = Mock(return_value=False)
    handler, vault = Mock(), Mock()
    with pytest.raises(ActionRejected, match="ISOLATED_REHEARSAL_REQUIRED"):
        observe(engine, "unused", vault, httpx.MockTransport(handler))
    assert not session.scalar.called and not vault.unseal.called and not handler.called


def test_job_binding_change_during_get_is_not_recorded_as_success(setup, mock_gate):
    engine, sf, vault, _ = setup
    request_id, _ = acknowledged(setup)

    def handler(_request):
        with sf.begin() as session:
            row = session.get(ActionRequest, request_id)
            row.provenance = {
                **row.provenance,
                "controlled": {**row.provenance["controlled"], "job_id": 42},
            }
        return httpx.Response(200, json=response())

    observe(engine, request_id, vault, httpx.MockTransport(handler))
    status, observation = saved(sf, request_id)
    assert status == "unknown"
    assert observation["error_code"] == "OBSERVATION_CORRELATION_CHANGED"
    assert observation["job_id"] == 41
    with sf() as session:
        event = session.scalars(
            select(ActionLog).where(
                ActionLog.event == "controlled_mock_job_observation"
            )
        ).one()
        assert event.details["job_id"] == 41
