"""Synthetic encrypted handoff and durable MOCK_ONLY one-attempt acceptance."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from unittest.mock import Mock, patch

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import func, select, update
from test_manual_actions import command, seed
from test_sync import NOW

from services.actions.capabilities import ActionCapabilityRegistry
from services.actions.engine import ActionEngine, ActionPolicy, ActionRejected
from services.actions.factory import create_action_connector
from services.actions.safety import ActionSafetyGate
from services.actions.write_credentials import (
    WriteCredentialError,
    WriteCredentialVault,
)
from services.providers.contracts import WriteDisabled
from services.providers.integration_models import WriteCredentialState
from services.providers.models import (
    ProviderAccountMapping,
    ProviderConnection,
    ProviderRoutingSetting,
)
from services.storage.database import make_engine, sessions
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    AdAccount,
    ApiQuota,
    Base,
    Entity,
    EntityCurrentState,
    User,
)

WORKSPACE = "write-rehearsal-unit"
ACTOR = {"id": "admin", "workspace": WORKSPACE, "role": "admin"}
TOKEN = "mfk_fixture_encrypted_rehearsal_write"


def seed_rehearsal(factory, vault, now):
    seed(factory)
    with factory.begin() as s:
        for model in (
            User,
            AdAccount,
            ProviderAccountMapping,
            ProviderConnection,
            ProviderRoutingSetting,
        ):
            s.execute(
                update(model)
                .where(model.workspace_id == "default")
                .values(workspace_id=WORKSPACE)
            )
        s.add(
            WriteCredentialState(
                workspace_id=WORKSPACE,
                revision=1,
                encrypted=vault.seal(WORKSPACE, TOKEN, 1).decode(),
                status="SCOPES_VERIFIED",
                scopes=["entities:write"],
                access_state="active_paid",
                checked_at=now,
            )
        )


def prepared(engine, operation="PAUSE_AD", entity_id="ad", external_id="1003"):
    draft = engine.prepare_manual(
        ACTOR,
        command(
            operation=operation,
            entity_id=entity_id,
            meta_ad_id=external_id,
            expected_status="ACTIVE" if operation == "PAUSE_AD" else "PAUSED",
        ),
        "mock-controlled-" + entity_id,
    )
    checked = engine.transition_manual(
        ACTOR, draft["id"], "preflight", draft["revision"]
    )
    confirmed = engine.transition_manual(
        ACTOR, checked["id"], "confirm", checked["revision"]
    )
    return engine.prepare_rehearsal(
        ACTOR,
        confirmed["id"],
        confirmed["revision"],
        1,
        engine.clock() + timedelta(minutes=5),
    )


@pytest.fixture
def setup(tmp_path):
    db = make_engine(f"sqlite:///{tmp_path / 'rehearsal.db'}")
    Base.metadata.create_all(db)
    sf = sessions(db)
    vault = WriteCredentialVault(tmp_path / "write-namespace", Fernet.generate_key())
    seed_rehearsal(sf, vault, NOW)
    clock = [NOW]
    engine = ActionEngine(sf, ActionPolicy(enabled=True), clock=lambda: clock[0])
    yield engine, sf, vault, clock
    db.dispose()


@pytest.fixture
def mock_gate(monkeypatch):
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    with patch.object(ActionSafetyGate, "require_verified_contract"):
        yield


def responder(calls, *, failure=None, after_http=None, operation="pause"):
    def respond(request):
        calls.append(request)
        assert (
            request.method == "POST"
            and request.url.path == f"/api/v1/entities/1003/{operation}"
        )
        assert json.loads(request.content) == {"level": "ad"}
        assert dict(request.url.params) == {"async": "true"}
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        if after_http:
            after_http()
        if failure == "timeout":
            raise httpx.ReadTimeout(TOKEN, request=request)
        if failure:
            return httpx.Response(failure, json={"error": TOKEN})
        return httpx.Response(
            202,
            json={
                "success": True,
                "entity_id": "1003",
                "message": "mock only",
                "job_id": 41,
            },
        )

    return httpx.MockTransport(respond)


@pytest.mark.parametrize("operation", ["PAUSE_AD", "ENABLE_AD"])
def test_encrypted_handoff_one_attempt_correlated_job_and_no_live_verification(
    setup, mock_gate, operation
):
    engine, sf, vault, clock = setup
    if operation == "ENABLE_AD":
        with sf.begin() as s:
            s.get(EntityCurrentState, "ad").status = "PAUSED"
    permit = prepared(engine, operation=operation)
    calls = []
    with sf() as s:
        stored = s.get(WriteCredentialState, WORKSPACE)
        before = stored.encrypted, stored.revision, stored.checked_at
        capability = ActionCapabilityRegistry.inspect(s, WORKSPACE, "metricflow")
        assert capability["write_credentials"] and not capability["write_permission"]
        assert capability["required_permission"] == "entities:write"
        assert capability["live_status"] == "BLOCKED"
    result = asyncio.run(
        engine.execute_rehearsal(
            ACTOR,
            permit["id"],
            permit["revision"],
            vault=vault,
            transport=responder(
                calls, operation="pause" if operation == "PAUSE_AD" else "enable"
            ),
        )
    )
    assert result == permit["id"] and len(calls) == 1
    restart = ActionEngine(sf, engine.policy, clock=engine.clock)
    assert (
        asyncio.run(
            restart.execute_rehearsal(
                ACTOR,
                permit["id"],
                permit["revision"],
                vault=vault,
                transport=responder(
                    calls, operation="pause" if operation == "PAUSE_AD" else "enable"
                ),
            )
        )
        is None
    )
    with sf.begin() as s:
        row = s.get(ActionRequest, result)
        assert row.status == "verifying"
        assert row.provenance["controlled"]["job_id"] == 41
        assert row.provenance["controlled"]["attempts"] == 1
        assert row.provenance["controlled"]["mode"] == "MOCK_ONLY"
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 1
        assert s.get(ApiQuota, (WORKSPACE, "metricflow", NOW.date())).requests == 1
        # Even legacy-normalized actions must retain MOCK_ONLY provenance.
        row.action = "pause" if operation == "PAUSE_AD" else "enable"
        state = s.get(EntityCurrentState, "ad")
        state.status = "PAUSED" if operation == "PAUSE_AD" else "ACTIVE"
        state.observed_at = NOW + timedelta(seconds=1)
    clock[0] += timedelta(hours=1)
    assert restart.verify_pending() == 0  # Mock ACK cannot create MCC pause ownership.
    with sf() as s:
        row = s.get(WriteCredentialState, WORKSPACE)
        assert (row.encrypted, row.revision, row.checked_at) == before
        logs = s.scalars(select(ActionLog)).all()
        assert not any(v.event == "verified" for v in logs)
        assert TOKEN not in json.dumps([v.details for v in logs])
        assert TOKEN not in json.dumps(s.get(ActionRequest, result).provenance)
        # The newly bounded observer expires even if no GET was ever dispatched.
        recovered = s.get(ActionRequest, result)
        assert recovered.status == "unknown"
        assert (
            recovered.provenance["controlled"]["observation"]["error_code"]
            == "OBSERVATION_DEADLINE"
        )
    assert not vault.path.exists()  # SQL envelope, no plaintext or file vault.


@pytest.mark.parametrize("failure", ["timeout", 401, 403, 429, 503])
def test_unknown_or_denied_mock_has_no_resend(setup, mock_gate, failure):
    engine, sf, vault, clock = setup
    p = prepared(engine)
    calls = []
    asyncio.run(
        engine.execute_rehearsal(
            ACTOR,
            p["id"],
            p["revision"],
            vault=vault,
            transport=responder(calls, failure=failure),
        )
    )
    assert len(calls) == 1
    clock[0] += timedelta(minutes=3)
    engine.verify_pending()
    assert (
        asyncio.run(
            engine.execute_rehearsal(
                ACTOR, p["id"], p["revision"], vault=vault, transport=responder(calls)
            )
        )
        is None
    )
    with sf() as s:
        assert s.get(ActionRequest, p["id"]).status == "unknown"
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 1
        assert TOKEN not in json.dumps(s.scalars(select(ActionLog.details)).all())


@pytest.mark.parametrize(
    "actions,readonly",
    [("false", "true"), ("false", "false"), ("true", "true"), ("true", "false")],
)
def test_actual_gate_blocks_before_vault_and_claim(
    setup, monkeypatch, actions, readonly
):
    engine, sf, vault, _clock = setup
    p = prepared(engine)
    monkeypatch.setenv("ACTIONS_ENABLED", actions)
    monkeypatch.setenv("LOCAL_READ_ONLY", readonly)
    private = Mock(wraps=vault)
    calls = []
    with pytest.raises(WriteDisabled):
        asyncio.run(
            engine.execute_rehearsal(
                ACTOR, p["id"], p["revision"], vault=private, transport=responder(calls)
            )
        )
    with pytest.raises(WriteDisabled):
        create_action_connector(
            workspace=WORKSPACE,
            credential_revision=1,
            session_factory=sf,
            vault=private,
            transport=responder(calls),
        )
    private.unseal.assert_not_called()
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0
        assert s.get(ActionRequest, p["id"]).provenance["controlled"]["attempts"] == 0
    assert calls == []


@pytest.mark.parametrize(
    "change",
    [
        "expired",
        "revision",
        "account",
        "external",
        "permission",
        "credential",
        "scope-stale",
    ],
)
def test_changed_bound_scope_held_before_claim(setup, mock_gate, change):
    engine, sf, vault, clock = setup
    p = prepared(engine)
    if change == "expired":
        clock[0] += timedelta(minutes=6)
    else:
        with sf.begin() as s:
            if change == "revision":
                s.get(ActionRequest, p["id"]).revision += 1
            elif change == "account":
                s.get(AdAccount, "account").external_id = "act_999"
            elif change == "external":
                s.get(Entity, "ad").external_id = "9999"
            elif change == "permission":
                s.get(User, "admin").is_active = False
            elif change == "credential":
                s.get(WriteCredentialState, WORKSPACE).revision = 2
            elif change == "scope-stale":
                s.get(WriteCredentialState, WORKSPACE).checked_at = NOW - timedelta(
                    hours=1
                )
    private = Mock(wraps=vault)
    with pytest.raises((ActionRejected, WriteCredentialError, HTTPException)):
        asyncio.run(
            engine.execute_rehearsal(
                ACTOR, p["id"], p["revision"], vault=private, transport=responder([])
            )
        )
    private.unseal.assert_not_called()
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0


def test_factory_rechecks_rotation_after_awaiting_local_guard(setup, mock_gate):
    _engine, sf, vault, _clock = setup
    calls = []

    async def rotate():
        with sf.begin() as s:
            s.get(WriteCredentialState, WORKSPACE).revision = 2

    async def run():
        async with create_action_connector(
            workspace=WORKSPACE,
            credential_revision=1,
            session_factory=sf,
            vault=vault,
            transport=responder(calls),
            before_request=rotate,
            clock=lambda: NOW,
        ) as writer:
            with pytest.raises(WriteCredentialError):
                await writer.pause_entity("1003", asynchronous=True)

    asyncio.run(run())
    assert calls == []


def test_late_ack_is_persisted_even_if_actor_revoked_during_http(setup, mock_gate):
    engine, sf, vault, _clock = setup
    p = prepared(engine)

    def revoke():
        with sf.begin() as s:
            s.get(User, "admin").is_active = False

    calls = []
    asyncio.run(
        engine.execute_rehearsal(
            ACTOR,
            p["id"],
            p["revision"],
            vault=vault,
            transport=responder(calls, after_http=revoke),
        )
    )
    with sf() as s:
        assert s.get(ActionRequest, p["id"]).provenance["controlled"]["job_id"] == 41
    assert len(calls) == 1


@pytest.mark.parametrize("stage", ["vault", "http"])
def test_crash_claim_survives_restart_without_resend(setup, mock_gate, stage):
    class ProcessCrash(BaseException):
        pass

    engine, sf, vault, clock = setup
    p = prepared(engine)
    calls = []
    private = Mock(wraps=vault)
    if stage == "vault":
        private.unseal.side_effect = ProcessCrash()

    def crash(request):
        calls.append(request)
        raise ProcessCrash()

    with pytest.raises(ProcessCrash):
        asyncio.run(
            engine.execute_rehearsal(
                ACTOR,
                p["id"],
                p["revision"],
                vault=private,
                transport=httpx.MockTransport(crash),
            )
        )
    clock[0] += timedelta(seconds=121)
    restarted = ActionEngine(sf, engine.policy, clock=engine.clock)
    assert restarted.verify_pending() == 0
    assert (
        asyncio.run(
            restarted.execute_rehearsal(
                ACTOR, p["id"], p["revision"], vault=vault, transport=responder(calls)
            )
        )
        is None
    )
    with sf() as s:
        assert s.get(ActionRequest, p["id"]).status == "unknown"
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 1
    assert len(calls) == (0 if stage == "vault" else 1)


def test_working_database_and_plaintext_fallback_are_never_admitted(
    setup, mock_gate, monkeypatch
):
    engine, sf, vault, _clock = setup
    db = make_engine("postgresql+psycopg://fixture@127.0.0.1/metric_control")
    private = ActionEngine(sessions(db), engine.policy, clock=engine.clock)
    with (
        patch.object(
            db, "connect", side_effect=AssertionError("NO_WORKING_DB_CONNECTION")
        ),
        pytest.raises(ActionRejected, match="ISOLATED_REHEARSAL"),
    ):
        private.prepare_rehearsal(ACTOR, "x", 1, 1, NOW + timedelta(minutes=1))
    db.dispose()
    with sf.begin() as s:
        s.delete(s.get(WriteCredentialState, WORKSPACE))
    monkeypatch.setenv("METRICFLOW_READ_KEY_FILE", "read-must-not-be-opened")
    monkeypatch.setenv("METRICFLOW_WRITE_KEY_FILE", "plaintext-must-not-be-opened")
    with pytest.raises(WriteCredentialError):
        create_action_connector(
            workspace=WORKSPACE,
            credential_revision=1,
            session_factory=sf,
            vault=vault,
            clock=lambda: NOW,
        )


def test_permit_cannot_be_rearmed_or_sent_via_real_transport(setup, mock_gate):
    engine, sf, vault, _clock = setup
    p = prepared(engine)
    with pytest.raises(ActionRejected, match="ALREADY_PREPARED"):
        engine.prepare_rehearsal(
            ACTOR, p["id"], p["revision"], 1, NOW + timedelta(minutes=4)
        )
    with pytest.raises(ActionRejected, match="EXPLICIT_MOCK"):
        asyncio.run(
            engine.execute_rehearsal(
                ACTOR,
                p["id"],
                p["revision"],
                vault=vault,
                transport=httpx.AsyncHTTPTransport(),
            )
        )
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0


def test_revoked_actor_in_final_guard_stops_http_after_durable_claim(setup, mock_gate):
    engine, sf, vault, _clock = setup
    p = prepared(engine)
    original = vault.unseal

    def unseal_then_revoke(*args):
        credential = original(*args)
        with sf.begin() as s:
            s.get(User, "admin").is_active = False
        return credential

    private = Mock(wraps=vault)
    private.unseal.side_effect = unseal_then_revoke
    calls = []
    asyncio.run(
        engine.execute_rehearsal(
            ACTOR, p["id"], p["revision"], vault=private, transport=responder(calls)
        )
    )
    assert calls == []
    with sf() as s:
        row = s.get(ActionRequest, p["id"])
        assert row.status == "unknown" and row.provenance["controlled"]["attempts"] == 1
        assert not row.provenance["controlled"]["http_started"]


def test_unexpected_error_is_sanitized_but_claim_remains_spent(setup, mock_gate):
    engine, sf, vault, _clock = setup
    p = prepared(engine)

    def fail(request):
        raise ValueError(TOKEN)

    with pytest.raises(ActionRejected) as error:
        asyncio.run(
            engine.execute_rehearsal(
                ACTOR,
                p["id"],
                p["revision"],
                vault=vault,
                transport=httpx.MockTransport(fail),
            )
        )
    assert TOKEN not in str(error.value)
    with sf() as s:
        assert s.get(ActionRequest, p["id"]).status == "unknown"
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 1
