"""Real gates and isolated unknown-outcome regressions; no provider network."""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from unittest.mock import patch

import httpx
import pytest
import test_manual_actions as manual_fixtures
from fastapi import HTTPException
from sqlalchemy import func, select
from test_manual_actions import ACTOR, command, engine
from test_sync import NOW

from services.actions.capabilities import ActionCapabilityRegistry
from services.actions.engine import ActionEngine, ActionPolicy, ActionRejected
from services.actions.safety import ActionSafetyGate
from services.metricflow.writer import MetricFlowActionConnector
from services.providers.contracts import ActionProviderRouter, WriteDisabled
from services.providers.models import ProviderConnection
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    EntityCurrentState,
)

store = manual_fixtures.store


@pytest.mark.parametrize(
    "actions,readonly,reason",
    [
        ("false", "true", "WRITE_DISABLED"),
        ("false", "false", "WRITE_DISABLED"),
        ("true", "true", "WRITE_DISABLED"),
        ("true", "false", "WRITE_CONTRACT_UNVERIFIED"),
    ],
)
def test_real_gate_stops_before_http_even_with_enabled_flags(actions, readonly, reason):
    calls = []

    async def run():
        async with MetricFlowActionConnector(
            "mfk_test_phase4b",
            transport=httpx.MockTransport(
                lambda request: calls.append(request) or httpx.Response(200, json={})
            ),
        ) as writer:
            for operation in (writer.pause_entity, writer.enable_entity):
                with pytest.raises(WriteDisabled) as caught:
                    await operation("123")
                assert caught.value.code == reason

    with patch.dict(
        os.environ, {"ACTIONS_ENABLED": actions, "LOCAL_READ_ONLY": readonly}
    ):
        asyncio.run(run())
    assert calls == []


def test_read_permissions_and_key_file_do_not_verify_write(
    store, tmp_path, monkeypatch
):
    monkeypatch.delenv("METRICFLOW_WRITE_KEY_FILE", raising=False)
    with store.begin() as s:
        s.get(ProviderConnection, ("default", "metricflow")).permissions = {
            "read": True,
            "write_permission": True,
        }
    with store() as s:
        missing = ActionCapabilityRegistry.inspect(s, "default", "metricflow")
        assert not missing["write_credentials"] and not missing["write_permission"]
        assert "WRITE_CREDENTIAL_MISSING" in missing["reason_codes"]
    # Legacy plaintext presence is not a supported provisioning source anymore.
    key = tmp_path / "mock-only-key"
    key.write_text("mfk_fixture_legacy_not_supported", encoding="utf-8")
    monkeypatch.setenv("METRICFLOW_WRITE_KEY_FILE", str(key))
    with store() as s:
        present = ActionCapabilityRegistry.inspect(s, "default", "metricflow")
        assert not present["write_credentials"] and not present["write_permission"]
        assert present["required_permission"] == "entities:write"
        assert "WRITE_CREDENTIAL_MISSING" in present["reason_codes"]
        assert set(present["operations"].values()) == {"UNVERIFIED"}
        assert present["live_status"] == "BLOCKED"


def test_unverified_contract_rejects_legacy_queue_before_attempt(store, monkeypatch):
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    e = ActionEngine(store, ActionPolicy(enabled=True), clock=lambda: NOW)
    request = e.enqueue("default", "admin", "ad", "pause", None, "legacy")

    class NeverCalled:
        async def pause_entity(self, entity):
            pytest.fail("Unverified connector was dispatched")

    asyncio.run(e.execute_next(NeverCalled()))
    with store() as s:
        assert s.get(ActionRequest, request).status == "rejected"
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0
        assert "WRITE_CONTRACT_UNVERIFIED" in str(
            s.scalar(select(ActionLog.details).where(ActionLog.event == "rejected"))
        )


@pytest.mark.parametrize(
    "status",
    [
        "EXECUTING",
        "OUTCOME_UNKNOWN",
        "RECONCILIATION_REQUIRED",
        "queued",
        "executing",
        "verifying",
        "unknown",
    ],
)
def test_unresolved_operation_blocks_new_manual_draft_without_auto_expiry(
    store, status
):
    e = engine(store)
    row = e.prepare_manual(ACTOR, command(), "first")
    with store.begin() as s:
        s.get(ActionRequest, row["id"]).status = status
    with pytest.raises(HTTPException) as caught:
        e.prepare_manual(ACTOR, command(), "second")
    assert caught.value.status_code == 409
    assert caught.value.detail == "PENDING_ACTION_CONFLICT"
    with store() as s:
        assert s.get(ActionRequest, row["id"]).status == status
        assert s.scalar(select(func.count()).select_from(ActionRequest)) == 1


@pytest.mark.parametrize("status", ["OUTCOME_UNKNOWN", "RECONCILIATION_REQUIRED"])
def test_existing_draft_preflight_detects_unresolved_outcome(store, status):
    e = engine(store)
    row = e.prepare_manual(ACTOR, command(), "first")
    with store.begin() as s:
        s.add(
            ActionRequest(
                id="unresolved",
                workspace_id="default",
                entity_id="ad",
                initiator_id="admin",
                idempotency_key="old",
                action="PAUSE_AD",
                status=status,
                created_at=NOW,
                provenance={},
            )
        )
    row = e.transition_manual(ACTOR, row["id"], "preflight", row["revision"])
    assert not row["preflight"]["local_allowed"]
    assert "PENDING_ACTION_CONFLICT" in row["reason_codes"]


def test_mock_timeout_reconciles_only_by_read_and_never_resends(store, monkeypatch):
    monkeypatch.setenv("ACTIONS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_READ_ONLY", "false")
    current = [NOW]
    e = ActionEngine(store, ActionPolicy(enabled=True), clock=lambda: current[0])
    request = e.enqueue("default", "admin", "ad", "pause", None, "timeout")
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("mock timeout", request=request)

    async def run():
        # Assumes a synthetic future contract only for this isolated transport test.
        with patch.object(ActionSafetyGate, "require_verified_contract"):
            async with MetricFlowActionConnector(
                "mfk_test_phase4b", transport=httpx.MockTransport(timeout)
            ) as writer:
                await e.execute_next(writer)
                assert await e.execute_next(writer) is None

    asyncio.run(run())
    current[0] += timedelta(minutes=31)
    e.verify_pending()
    with store.begin() as s:
        assert s.get(ActionRequest, request).status == "unknown"
        s.get(EntityCurrentState, "ad").observed_at = current[0]
    with pytest.raises(ActionRejected):
        e.enqueue("default", "admin", "ad", "pause", None, "retry")
    current[0] += timedelta(minutes=1)
    with store.begin() as s:
        state = s.get(EntityCurrentState, "ad")
        state.status, state.observed_at = "PAUSED", current[0]
    assert e.verify_pending() == 1
    with store() as s:
        assert s.get(ActionRequest, request).status == "succeeded"
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 1
    assert len(calls) == 1


@pytest.mark.parametrize("provider", ["metricflow", "meta"])
def test_router_never_dispatches_or_fails_over(provider):
    with pytest.raises(WriteDisabled):
        asyncio.run(ActionProviderRouter().execute(provider, "pause_entity", "123"))
