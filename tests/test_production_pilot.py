"""Production handoff under synthetic accepted gates; all provider I/O is mocked."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from unittest.mock import Mock, patch

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from test_controlled_rehearsal import ACTOR, TOKEN, mock_gate, setup
from test_manual_actions import command

from services.actions.capabilities import ActionCapabilityRegistry
from services.actions.engine import ActionEngine, ActionRejected
from services.actions.pilot import (
    EVIDENCE_EVENT,
    MODE,
    STATEMENT,
    PilotAuthorizationInput,
    PilotReadbackInput,
    authorize_pilot,
    execute_pilot,
    record_manual_readback,
)
from services.providers.contracts import WriteDisabled
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    EntityCurrentState,
)

__all__ = ["mock_gate", "setup"]


@pytest.fixture
def accepted_capability():
    original = ActionCapabilityRegistry.inspect

    def verified(*args):
        value = original(*args)
        return {
            **value,
            "write_permission": True,
            "operations": {"PAUSE_AD": "VERIFIED", "ENABLE_AD": "VERIFIED"},
        }

    with patch.object(ActionCapabilityRegistry, "inspect", side_effect=verified):
        yield


def confirmed(engine, operation="PAUSE_AD"):
    row = engine.prepare_manual(
        ACTOR,
        command(
            operation=operation,
            expected_status="ACTIVE" if operation == "PAUSE_AD" else "PAUSED",
        ),
        "pilot-single",
    )
    for event in ("preflight", "confirm"):
        row = engine.transition_manual(ACTOR, row["id"], event, row["revision"])
    return row


def body(row, **changes):
    return PilotAuthorizationInput.model_validate(
        {
            "revision": row["revision"],
            "credential_revision": 1,
            "account_id": "act_100",
            "entity_id": "1003",
            "operation": row["operation"],
            "expected_status": row["expected_status"],
            "statement": STATEMENT,
            **changes,
        }
    )


def evidence(sf, row, now, *, audit_id="pilot-proof", **changes):
    with sf.begin() as session:
        session.add(
            ActionLog(
                id=audit_id,
                request_id=row["id"],
                event=EVIDENCE_EVENT,
                created_at=now,
                details={
                    "actor_id": ACTOR["id"],
                    "account_id": "act_100",
                    "entity_id": "1003",
                    "operation": row["operation"],
                    "credential_revision": 1,
                    "read_revision": 1,
                    "entity_id_namespace": "PROVIDER_AD_ID",
                    "configured_status": row["expected_status"],
                    "effective_status": "ACTIVE",
                    "permission": "MANAGE_CAMPAIGNS",
                    "permission_source": "MANUAL_META_ACCESS_REVIEW",
                    "profile_id": 123,
                    "namespace_source": "synthetic fixture, never provider evidence",
                    **changes,
                },
            )
        )


def send(engine, vault, permit, calls, *, failure=None, hook=None):
    def respond(request):
        calls.append(request)
        assert request.method == "POST" and not request.url.params
        assert json.loads(request.content) == {"level": "ad"}
        if hook:
            hook()
        if failure == "timeout":
            raise httpx.ReadTimeout(TOKEN, request=request)
        if failure:
            return httpx.Response(failure, json={"message": TOKEN})
        return httpx.Response(
            200, json={"success": True, "entity_id": "1003", "message": TOKEN}
        )

    return asyncio.run(
        execute_pilot(
            engine,
            ACTOR,
            permit["id"],
            permit["revision"],
            vault=vault,
            transport=httpx.MockTransport(respond),
        )
    )


@pytest.mark.parametrize("operation", ["PAUSE_AD", "ENABLE_AD"])
def test_one_live_shaped_permit_consumed_once_then_manual_record_without_ownership(
    setup,
    mock_gate,
    accepted_capability,
    monkeypatch,
    operation,
):
    engine, sf, vault, clock = setup
    if operation == "ENABLE_AD":
        with sf.begin() as s:
            s.get(EntityCurrentState, "ad").status = "PAUSED"
    row = confirmed(engine, operation)
    evidence(sf, row, clock[0])
    permit = authorize_pilot(engine, ACTOR, row["id"], body(row))
    assert permit["mode"] == MODE and permit["max_attempts"] == 1
    calls = []
    assert send(engine, vault, permit, calls) == permit["id"]
    assert calls[0].url.path.endswith(
        "/pause" if operation == "PAUSE_AD" else "/enable"
    )
    restart = ActionEngine(sf, engine.policy, clock=engine.clock)
    assert send(restart, vault, permit, calls) is None
    assert len(calls) == 1
    with sf() as s:
        saved = s.get(ActionRequest, permit["id"])
        revision = saved.revision
        assert saved.status == "verifying"
        assert saved.provenance["controlled"]["authorization"]["statement"] == STATEMENT
        assert saved.provenance["controlled"]["evidence_id"] == "pilot-proof"
        assert TOKEN not in json.dumps(saved.provenance)
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 1
    clock[0] += timedelta(seconds=10)
    # Recording local evidence remains possible after an emergency WRITE shutdown.
    monkeypatch.setenv("ACTIONS_ENABLED", "false")
    monkeypatch.setenv("LOCAL_READ_ONLY", "true")
    result = record_manual_readback(
        restart,
        ACTOR,
        permit["id"],
        PilotReadbackInput(
            revision=revision,
            account_id="act_100",
            entity_id="1003",
            configured_status="PAUSED" if operation == "PAUSE_AD" else "ACTIVE",
            effective_status="PAUSED",
            observed_at=clock[0].isoformat(),
            statement="RECORD_MANUAL_META_READBACK",
        ),
    )
    assert result["status"] == "MANUALLY_REVIEWED" and not result["authoritative_api"]
    clock[0] += timedelta(hours=1)
    assert restart.verify_pending() == 0
    with sf() as s:
        assert s.get(ActionRequest, permit["id"]).status == "MANUALLY_REVIEWED"
        assert not s.scalar(select(ActionLog).where(ActionLog.event == "verified"))


def test_flags_do_not_release_actual_contract_gate_or_open_vault(setup, monkeypatch):
    engine, sf, _, _ = setup
    row = confirmed(engine)
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    with pytest.raises(WriteDisabled):
        authorize_pilot(engine, ACTOR, row["id"], body(row))
    vault, calls = Mock(), []
    with pytest.raises(WriteDisabled):
        send(engine, vault, row, calls)
    vault.unseal.assert_not_called()
    assert calls == []
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0
        assert "controlled" not in s.get(ActionRequest, row["id"]).provenance


def test_patching_contract_alone_does_not_release_permission_gate(setup, mock_gate):
    engine, _, _, _ = setup
    row = confirmed(engine)
    with pytest.raises(ActionRejected, match="PILOT_WRITE_PERMISSION_UNVERIFIED"):
        authorize_pilot(engine, ACTOR, row["id"], body(row))


@pytest.mark.parametrize(
    "changes",
    [
        None,
        {"entity_id": "other"},
        {"account_id": "act_999"},
        {"credential_revision": 2},
        {"credential_revision": True},
        {"read_revision": True},
        {"configured_status": "PAUSED"},
        {"profile_id": True},
        {"effective_status": "UNKNOWN"},
        {"namespace_source": ""},
    ],
)
def test_external_proof_cannot_be_inferred_from_scope_or_statement(
    setup, mock_gate, accepted_capability, changes
):
    engine, sf, _, clock = setup
    row = confirmed(engine)
    if changes is not None:
        evidence(sf, row, clock[0], **changes)
    with pytest.raises(ActionRejected, match="PILOT_EXTERNAL_EVIDENCE_REQUIRED"):
        authorize_pilot(engine, ACTOR, row["id"], body(row))


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_id", "act_999"),
        ("entity_id", "999"),
        ("operation", "ENABLE_AD"),
        ("expected_status", "PAUSED"),
    ],
)
def test_explicit_statement_is_bound_to_exact_action(
    setup, mock_gate, accepted_capability, field, value
):
    engine, sf, _, clock = setup
    row = confirmed(engine)
    evidence(sf, row, clock[0])
    with pytest.raises(ActionRejected, match="PILOT_AUTHORIZATION_BINDING_MISMATCH"):
        authorize_pilot(engine, ACTOR, row["id"], body(row, **{field: value}))


@pytest.mark.parametrize("failure", ["timeout", 403, 429, 503])
def test_unknown_production_shaped_attempt_is_not_retried(
    setup, mock_gate, accepted_capability, failure
):
    engine, sf, vault, clock = setup
    row = confirmed(engine)
    evidence(sf, row, clock[0])
    permit = authorize_pilot(engine, ACTOR, row["id"], body(row))
    calls = []
    send(engine, vault, permit, calls, failure=failure)
    assert send(engine, vault, permit, calls) is None
    with sf() as s:
        saved = s.get(ActionRequest, row["id"])
        assert (
            saved.status == "unknown"
            and saved.provenance["controlled"]["attempts"] == 1
        )
    assert len(calls) == 1


def test_revocation_between_authorization_and_dispatch_blocks_before_vault(
    setup, mock_gate, accepted_capability
):
    engine, sf, _, clock = setup
    row = confirmed(engine)
    evidence(sf, row, clock[0])
    permit = authorize_pilot(engine, ACTOR, row["id"], body(row))
    with sf.begin() as s:
        s.add(
            ActionLog(
                id="revoked",
                request_id=row["id"],
                created_at=clock[0],
                event="pilot_external_evidence_revoked",
                details={},
            )
        )
    vault, calls = Mock(), []
    with pytest.raises(ActionRejected, match="PILOT_EXTERNAL_EVIDENCE_REQUIRED"):
        send(engine, vault, permit, calls)
    vault.unseal.assert_not_called()
    assert not calls


def test_simulated_terminal_row_is_never_promoted_to_live(
    setup, mock_gate, accepted_capability
):
    engine, sf, _, clock = setup
    row = confirmed(engine)
    row = engine.transition_manual(ACTOR, row["id"], "simulate", row["revision"])
    evidence(sf, row, clock[0])
    with pytest.raises(ActionRejected, match="CONFIRMED_REVISION_REQUIRED"):
        authorize_pilot(engine, ACTOR, row["id"], body(row))


@pytest.mark.parametrize(
    "changes",
    [
        {"revision": True},
        {"revision": "1"},
        {"operation": "PAUSE_CAMPAIGN"},
        {"statement": "confirm"},
        {"asset_permission": True},
    ],
)
def test_no_extra_permission_flags_or_coerced_authorization_values(changes):
    with pytest.raises(ValidationError):
        body(
            {"revision": 1, "operation": "PAUSE_AD", "expected_status": "ACTIVE"},
            **changes,
        )


def test_unknown_post_cannot_be_closed_by_matching_manual_observation(
    setup, mock_gate, accepted_capability
):
    engine, sf, vault, clock = setup
    row = confirmed(engine)
    evidence(sf, row, clock[0])
    permit = authorize_pilot(engine, ACTOR, row["id"], body(row))
    send(engine, vault, permit, [], failure="timeout")
    with sf() as s:
        revision = s.get(ActionRequest, row["id"]).revision
    clock[0] += timedelta(seconds=1)
    result = record_manual_readback(
        engine,
        ACTOR,
        row["id"],
        PilotReadbackInput(
            revision=revision,
            account_id="act_100",
            entity_id="1003",
            configured_status="PAUSED",
            effective_status="PAUSED",
            observed_at=clock[0].isoformat(),
            statement="RECORD_MANUAL_META_READBACK",
        ),
    )
    assert result["matches_target"] and result["status"] == "unknown"


def test_rate_limit_sets_shared_cooldown_without_replacing_read_connection(
    setup, mock_gate, accepted_capability
):
    from services.providers.models import ProviderConnection
    from services.storage.models import ApiQuota

    engine, sf, vault, clock = setup
    row = confirmed(engine)
    evidence(sf, row, clock[0])
    permit = authorize_pilot(engine, ACTOR, row["id"], body(row))
    calls = []
    with patch("services.providers.manager.utc_now", side_effect=engine.clock):
        send(engine, vault, permit, calls, failure=429)
    with sf() as s:
        quota = s.get(ApiQuota, (ACTOR["workspace"], "metricflow", clock[0].date()))
        assert quota.blocked_until is not None
        assert (
            s.get(ProviderConnection, (ACTOR["workspace"], "metricflow")).status
            == "healthy"
        )
    assert len(calls) == 1


def test_second_live_permit_cannot_compete_in_same_workspace(
    setup, mock_gate, accepted_capability
):
    from services.storage.models import Ad, Entity

    engine, sf, _, clock = setup
    row = confirmed(engine)
    evidence(sf, row, clock[0])
    authorize_pilot(engine, ACTOR, row["id"], body(row))
    with sf.begin() as s:
        s.add(
            Entity(
                id="other-ad",
                account_id="account",
                kind="ad",
                external_id="1004",
                name="fixture",
            )
        )
        s.flush()
        s.add(Ad(entity_id="other-ad", adset_id="adset"))
        s.add(
            EntityCurrentState(
                entity_id="other-ad", status="ACTIVE", observed_at=clock[0], raw={}
            )
        )
    second = engine.prepare_manual(
        ACTOR, command(entity_id="other-ad", meta_ad_id="1004"), "other-pilot"
    )
    for event in ("preflight", "confirm"):
        second = engine.transition_manual(
            ACTOR, second["id"], event, second["revision"]
        )
    evidence(sf, second, clock[0], audit_id="second-proof", entity_id="1004")
    with pytest.raises(ActionRejected, match="PILOT_WORKSPACE_CONFLICT"):
        authorize_pilot(engine, ACTOR, second["id"], body(second, entity_id="1004"))


def test_manual_match_after_deadline_cannot_close_unreconciled_pilot(
    setup, mock_gate, accepted_capability
):
    engine, sf, vault, clock = setup
    row = confirmed(engine)
    evidence(sf, row, clock[0])
    permit = authorize_pilot(engine, ACTOR, row["id"], body(row))
    calls = []
    send(engine, vault, permit, calls)
    clock[0] += timedelta(seconds=601)
    with sf() as session:
        revision = session.get(ActionRequest, row["id"]).revision
    result = record_manual_readback(
        engine,
        ACTOR,
        row["id"],
        PilotReadbackInput(
            revision=revision,
            account_id="act_100",
            entity_id="1003",
            configured_status="PAUSED",
            effective_status="PAUSED",
            observed_at=clock[0].isoformat(),
            statement="RECORD_MANUAL_META_READBACK",
        ),
    )
    assert result["matches_target"] and result["status"] == "unknown"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status", ["queued", "unknown", "EXECUTING", "RECONCILIATION_REQUIRED"]
)
def test_unfinished_nonpilot_command_also_blocks_workspace(
    setup, mock_gate, accepted_capability, status
):
    engine, sf, _, clock = setup
    row = confirmed(engine)
    evidence(sf, row, clock[0])
    with sf.begin() as session:
        session.add(
            ActionRequest(
                id="other-command",
                workspace_id=ACTOR["workspace"],
                entity_id="adset",
                initiator_id=ACTOR["id"],
                idempotency_key="legacy-command",
                action="pause",
                baseline_status="ACTIVE",
                provenance={"source": "web"},
                status=status,
                created_at=clock[0],
            )
        )
    with pytest.raises(ActionRejected, match="PILOT_WORKSPACE_CONFLICT"):
        authorize_pilot(engine, ACTOR, row["id"], body(row))
