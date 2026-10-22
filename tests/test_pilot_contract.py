"""Unpatched contract admission. Synthetic provider evidence and MockTransport only."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import Mock

import httpx
import pytest
from test_controlled_rehearsal import ACTOR, TOKEN, setup
from test_production_pilot import body, confirmed, evidence, send

from services.actions.capabilities import ActionCapabilityRegistry
from services.actions.engine import ActionEngine, ActionRejected
from services.actions.factory import create_action_connector
from services.actions.pilot import authorize_pilot
from services.actions.pilot_contract import load_contract
from services.actions.safety import ActionSafetyGate
from services.metricflow.writer import MetricFlowActionConnector
from services.providers.contracts import WriteDisabled
from services.providers.integration_models import WriteCredentialState
from services.storage.models import ActionLog, ActionRequest, EntityCurrentState, User

__all__ = ["setup"]


def review(**changes):
    return {
        "provider": "metricflow",
        "wire_revision": "status-sync-v1",
        "operation": "PAUSE_AD",
        "entity_id_namespace": "PROVIDER_AD_ID",
        "source_kind": "PROVIDER_CLARIFICATION",
        "source_reference": "synthetic fixture, never actual provider evidence",
        "source_sha256": "a" * 64,
        "reviewed_by": ACTOR["id"],
        **changes,
    }


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")


def accepted(setup, *, operation="PAUSE_AD", changes=None):
    engine, sf, _, clock = setup
    if operation == "ENABLE_AD":
        with sf.begin() as s:
            s.get(EntityCurrentState, "ad").status = "PAUSED"
    row = confirmed(engine, operation)
    evidence(
        sf,
        row,
        clock[0],
        contract_review=review(operation=operation, **(changes or {})),
    )
    return row


@pytest.mark.parametrize("operation", ["PAUSE_AD", "ENABLE_AD"])
def test_real_gates_admit_one_mock_post_without_global_capability(
    setup, enabled, operation
):
    engine, sf, vault, _ = setup
    row = accepted(setup, operation=operation)
    permit = authorize_pilot(engine, ACTOR, row["id"], body(row))
    with sf() as s:
        assert not ActionCapabilityRegistry.inspect(
            s, ACTOR["workspace"], "metricflow"
        )["write_permission"]
    calls = []
    assert send(engine, vault, permit, calls) == row["id"]
    restart = ActionEngine(sf, engine.policy, clock=engine.clock)
    assert send(restart, vault, permit, calls) is None
    assert len(calls) == 1
    with sf() as s:
        control = s.get(ActionRequest, row["id"]).provenance["controlled"]
        assert control["wire_spent"] is True
        assert control["provider_contract"]["evidence_id"] == "pilot-proof"
        assert control["state"] == "SYNC_ACKNOWLEDGED_NEEDS_MANUAL_READBACK"


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "meta"},
        {"wire_revision": "guess"},
        {"entity_id_namespace": "INTERNAL_ID"},
        {"reviewed_by": "other"},
        {"source_kind": "USER_ATTESTED"},
        {"source_sha256": "not-a-hash"},
        {"source_reference": "   "},
        {"extra": True},
    ],
)
def test_untrusted_or_incomplete_contract_is_rejected_before_vault(
    setup, enabled, change
):
    engine, _, _, _ = setup
    row = accepted(setup, changes=change)
    vault = Mock()
    with pytest.raises(WriteDisabled):
        authorize_pilot(engine, ACTOR, row["id"], body(row))
    with pytest.raises(WriteDisabled):
        send(engine, vault, row, [])
    vault.unseal.assert_not_called()


def test_auth_phase_cannot_send_and_execution_requires_explicit_bound_authorization(
    setup, enabled
):
    engine, _, _, _ = setup
    row = accepted(setup)
    contract = load_contract(engine, ACTOR, row["id"], phase="AUTHORIZE")
    with pytest.raises(WriteDisabled, match="PILOT_WIRE_CONTRACT_MISMATCH"):
        contract.check_request("POST", "entities/1003/pause", {"level": "ad"}, None)
    with pytest.raises(WriteDisabled, match="EXPLICIT_PILOT_AUTHORIZATION_REQUIRED"):
        load_contract(engine, ACTOR, row["id"], phase="EXECUTE")
    with pytest.raises(WriteDisabled):
        ActionSafetyGate.require_write(contract.pin())


@pytest.mark.parametrize(
    "mutation", ["proof", "revoked", "key", "user", "authorization", "pin", "expired"]
)
def test_changed_approval_cannot_open_vault(setup, enabled, mutation):
    engine, sf, _, clock = setup
    row = accepted(setup)
    permit = authorize_pilot(engine, ACTOR, row["id"], body(row))
    with sf.begin() as s:
        if mutation == "proof":
            saved = s.get(ActionLog, "pilot-proof")
            saved.details = {**saved.details, "namespace_source": "changed"}
        elif mutation == "revoked":
            s.add(
                ActionLog(
                    id="revoke",
                    request_id=row["id"],
                    event="pilot_external_evidence_revoked",
                    created_at=clock[0],
                    details={},
                )
            )
        elif mutation == "key":
            s.get(WriteCredentialState, ACTOR["workspace"]).revision = 2
        elif mutation == "user":
            s.get(User, ACTOR["id"]).is_active = False
        elif mutation in ("authorization", "pin"):
            saved = s.get(ActionRequest, row["id"])
            control = dict(saved.provenance["controlled"])
            control[
                "authorization" if mutation == "authorization" else "provider_contract"
            ] = {}
            saved.provenance = {**saved.provenance, "controlled": control}
        else:
            clock[0] += timedelta(seconds=601)
    vault, calls = Mock(), []
    with pytest.raises((WriteDisabled, ActionRejected)):
        send(engine, vault, permit, calls)
    vault.unseal.assert_not_called()
    assert not calls


@pytest.mark.parametrize(
    "method,path,payload,params",
    [
        ("POST", "entities/other/pause", {"level": "ad"}, None),
        ("POST", "entities/1003/enable", {"level": "ad"}, None),
        ("POST", "entities/1003/budget", {"amount": 10}, None),
        ("POST", "entities/1003/pause", {"level": "campaign"}, None),
        ("POST", "entities/1003/pause", {"level": "ad", "extra": True}, None),
        ("POST", "entities/1003/pause", {"level": "ad"}, {"async": "true"}),
        ("GET", "jobs/1", None, None),
    ],
)
def test_scope_rejects_other_wire_contracts(
    setup, enabled, method, path, payload, params
):
    engine, _, _, _ = setup
    row = accepted(setup)
    authorize_pilot(engine, ACTOR, row["id"], body(row))
    contract = load_contract(engine, ACTOR, row["id"], phase="EXECUTE")
    with pytest.raises(WriteDisabled, match="PILOT_WIRE_CONTRACT_MISMATCH"):
        contract.check_request(method, path, payload, params)
    with pytest.raises(WriteDisabled):
        create_action_connector(
            workspace="other", credential_revision=1, contract=contract
        )
    with pytest.raises(WriteDisabled):
        create_action_connector(
            workspace=ACTOR["workspace"], credential_revision=2, contract=contract
        )


def test_transport_checks_payload_before_guard_and_binds_durable_wire_budget(
    setup, enabled
):
    engine, _, vault, _ = setup
    row = accepted(setup)
    permit = authorize_pilot(engine, ACTOR, row["id"], body(row))
    contract = load_contract(engine, ACTOR, row["id"], phase="EXECUTE")
    calls, guard = [], Mock()

    async def before():
        guard()

    async def rejected():
        async with MetricFlowActionConnector(
            TOKEN,
            transport=httpx.MockTransport(lambda r: calls.append(r)),
            before_request=before,
            contract=contract,
        ) as client:
            with pytest.raises(WriteDisabled):
                await client.pause_entity("other")
            with pytest.raises(WriteDisabled):
                await client.pause_entity("1003", asynchronous=True)
            with pytest.raises(WriteDisabled):
                await client.change_budget("1003", provider_payload={"amount": 10})
            with pytest.raises(WriteDisabled):
                await client.get_action_job(1, entity_id="1003")
            # Correct path, but no durable engine claim: cannot dispatch via factory alone.
            with pytest.raises(WriteDisabled, match="PILOT_WIRE_BUDGET_UNAVAILABLE"):
                await client.pause_entity("1003")

    asyncio.run(rejected())
    assert guard.call_count == 1 and not calls
    assert send(engine, vault, permit, calls) == row["id"]
    assert len(calls) == 1
    with pytest.raises(WriteDisabled, match="PILOT_WIRE_BUDGET_UNAVAILABLE"):
        contract.consume_before_http()
    # A newly loaded scope cannot reset the committed wire budget.
    with pytest.raises(WriteDisabled, match="PILOT_WIRE_BUDGET_UNAVAILABLE"):
        load_contract(engine, ACTOR, row["id"], phase="EXECUTE").consume_before_http()


def test_flags_and_direct_adapter_stay_closed(setup, enabled, monkeypatch):
    engine, _, _, _ = setup
    row = accepted(setup)
    with pytest.raises(WriteDisabled, match="WRITE_CONTRACT_UNVERIFIED"):
        create_action_connector(workspace=ACTOR["workspace"], credential_revision=1)
    monkeypatch.setenv("ACTIONS_ENABLED", "false")
    monkeypatch.setenv("LOCAL_READ_ONLY", "true")
    with pytest.raises(WriteDisabled):
        authorize_pilot(engine, ACTOR, row["id"], body(row))


@pytest.mark.parametrize("failure", ["timeout", 403, 429, 503])
def test_real_gates_do_not_retry_unknown_mock_outcome(setup, enabled, failure):
    engine, _, vault, _ = setup
    row = accepted(setup)
    permit = authorize_pilot(engine, ACTOR, row["id"], body(row))
    calls = []
    assert send(engine, vault, permit, calls, failure=failure) == row["id"]
    assert send(engine, vault, permit, calls) is None
    assert len(calls) == 1


@pytest.mark.parametrize("both", [False, True])
def test_saved_pin_cannot_extend_original_authorization_window(setup, enabled, both):
    engine, sf, _, clock = setup
    row = accepted(setup)
    permit = authorize_pilot(engine, ACTOR, row["id"], body(row))
    with sf.begin() as s:
        saved = s.get(ActionRequest, row["id"])
        control = dict(saved.provenance["controlled"])
        pin = dict(control["provider_contract"])
        pin["expires_at"] = (clock[0] + timedelta(seconds=700)).isoformat()
        control["provider_contract"] = pin
        if both:
            control["expires_at"] = pin["expires_at"]
        saved.provenance = {**saved.provenance, "controlled": control}
    vault = Mock()
    with pytest.raises(WriteDisabled, match="PILOT_CONTRACT_WINDOW_CHANGED"):
        send(engine, vault, permit, [])
    vault.unseal.assert_not_called()


@pytest.mark.parametrize("authorized", [False, True])
def test_factory_cannot_decrypt_before_durable_execution_claim(
    setup, enabled, authorized
):
    engine, sf, _, _ = setup
    row = accepted(setup)
    if authorized:
        authorize_pilot(engine, ACTOR, row["id"], body(row))
    contract = load_contract(
        engine, ACTOR, row["id"], phase="EXECUTE" if authorized else "AUTHORIZE"
    )
    vault = Mock()
    with pytest.raises(WriteDisabled):
        create_action_connector(
            workspace=ACTOR["workspace"],
            credential_revision=1,
            session_factory=sf,
            vault=vault,
            contract=contract,
        )
    vault.unseal.assert_not_called()


@pytest.mark.parametrize("status", ["unknown", "queued", "CONFIRMED"])
def test_contract_review_refuses_workspace_conflict_before_user_authorization(
    setup, status
):
    engine, sf, _vault, clock = setup
    row = accepted(setup)
    with sf.begin() as s:
        s.add(
            ActionRequest(
                id="unfinished-workspace",
                workspace_id=ACTOR["workspace"],
                entity_id="adset",
                initiator_id=ACTOR["id"],
                idempotency_key="unfinished-workspace",
                action="ENABLE_ADSET",
                status=status,
                revision=1,
                created_at=clock[0],
                provenance={"controlled": {"mode": "LIVE_SINGLE_OPERATION"}},
            )
        )
    with pytest.raises(ActionRejected, match="PILOT_WORKSPACE_CONFLICT"):
        load_contract(engine, ACTOR, row["id"], phase="AUTHORIZE")
    with sf() as s:
        assert not s.get(ActionRequest, row["id"]).provenance.get("controlled")
