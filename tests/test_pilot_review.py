"""Review cards never authorize HTTP, unseal credentials or mutate action state."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select
from test_auth import AuthTests
from test_manual_actions import ACTOR, seed
from test_manual_actions import store as manual_store
from test_sync import NOW

from services.actions.manual_models import ManualActionGrant
from services.actions.pilot_review import build_review
from services.providers.integration_models import WriteCredentialState
from services.providers.models import ProviderAccountMapping, ProviderConnection
from services.storage.models import (
    ActionExecution,
    ActionRequest,
    AdAccount,
    EntityCurrentState,
)


@pytest.fixture
def store(tmp_path):
    yield from manual_store.__wrapped__(tmp_path)


def review(store, **changes):
    with store() as session:
        return build_review(session, ACTOR, "ad", "PAUSE_AD", NOW, **changes)


def test_read_only_card_has_exact_identity_and_never_opens_vault_or_http(store):
    with store.begin() as session:
        session.add(
            WriteCredentialState(
                workspace_id="default",
                revision=3,
                encrypted="secret-ciphertext-marker",
                fingerprint="secret-fingerprint-marker",
                status="SCOPES_VERIFIED",
                scopes=["entities:write"],
                access_state="active_paid",
                checked_at=NOW,
            )
        )
    statements = []
    db = store.kw["bind"]

    def captured(_connection, _cursor, statement, _params, _context, _many):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(db, "before_cursor_execute", captured)
    try:
        with (
            patch(
                "services.actions.write_credentials.WriteCredentialVault.unseal",
                side_effect=AssertionError("vault forbidden"),
            ),
            patch(
                "services.metricflow.transport.MetricFlowTransport.request",
                side_effect=AssertionError("provider forbidden"),
            ),
        ):
            card = review(store)
    finally:
        event.remove(db, "before_cursor_execute", captured)
    assert set(statements) == {"SELECT"}
    assert card["execution_allowed"] is False and card["mode"] == "MANUAL_REVIEW_ONLY"
    assert (
        card["entity"]["ad_id"] == "1003" and card["entity"]["account_id"] == "act_100"
    )
    assert (
        card["entity"]["adset_id"] == "1002" and card["entity"]["campaign_id"] == "1001"
    )
    assert card["write_connection"]["revision"] == 3
    assert card["write_connection"]["fresh_scope_evidence"]
    assert card["proposed_limits"]["total_http_attempts"] == 10
    assert len(card["manual_checks"]) == 3 and len(card["unresolved_contract"]) == 5
    assert "secret-" not in json.dumps(card)
    assert "encrypted" not in card["write_connection"]
    with store() as session:
        assert session.scalar(select(func.count()).select_from(ActionExecution)) == 0
        assert session.scalar(select(func.count()).select_from(ActionRequest)) == 0


@pytest.mark.parametrize(
    "change,check",
    [
        ("stale", "STATUS_FRESH"),
        ("read_off", "READ_CONNECTED_HEALTHY"),
        ("mapping", "ACCOUNT_MAPPING_CONFIRMED"),
        ("baseline", "BASELINE_MATCHES_OPERATION"),
    ],
)
def test_missing_local_prerequisites_are_not_ready(store, change, check):
    with store.begin() as session:
        if change == "stale":
            session.get(EntityCurrentState, "ad").observed_at = NOW - timedelta(hours=1)
        if change == "read_off":
            session.get(ProviderConnection, ("default", "metricflow")).enabled = False
        if change == "mapping":
            session.get(ProviderAccountMapping, "account").meta_account_id = "act_999"
        if change == "baseline":
            session.get(EntityCurrentState, "ad").status = "PAUSED"
    card = review(store)
    assert not card["local_checks"][check] and not card["execution_allowed"]


@pytest.mark.parametrize(
    "age,scope,expected",
    [
        (901, "entities:write", False),
        (0, "campaigns:write", False),
        (0, "entities:write", True),
    ],
)
def test_write_scope_must_be_current_but_never_grants_asset_permission(
    store, age, scope, expected
):
    with store.begin() as session:
        session.add(
            WriteCredentialState(
                workspace_id="default",
                revision=1,
                encrypted="not-opened",
                status="SCOPES_VERIFIED",
                scopes=[scope],
                access_state="active_paid",
                checked_at=NOW - timedelta(seconds=age),
            )
        )
    card = review(store)
    assert card["write_connection"]["fresh_scope_evidence"] is expected
    assert "WRITE_OBJECT_PERMISSION_UNVERIFIED" in card["unresolved_contract"]
    assert not card["execution_allowed"]


def test_enable_card_is_separate_and_missing_key_remains_not_configured(store):
    with store.begin() as session:
        session.get(EntityCurrentState, "ad").status = "PAUSED"
    with store() as session:
        card = build_review(session, ACTOR, "ad", "ENABLE_AD", NOW)
    assert card["target_status"] == "ACTIVE"
    assert card["local_checks"]["BASELINE_MATCHES_OPERATION"]
    assert card["write_connection"]["reason_code"] == "WRITE_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "role,grant,allowed",
    [
        ("admin", False, True),
        ("operator", False, False),
        ("operator", True, True),
        ("viewer", True, False),
    ],
)
def test_control_permission_enforced_from_database(store, role, grant, allowed):
    if grant:
        with store.begin() as session:
            session.add(
                ManualActionGrant(
                    workspace_id="default", user_id=role, can_control=True
                )
            )
    actor = {"id": role, "workspace": "default", "role": "admin"}
    with store() as session:
        if allowed:
            assert not build_review(session, actor, "ad", "PAUSE_AD", NOW)[
                "execution_allowed"
            ]
        else:
            with pytest.raises(HTTPException) as caught:
                build_review(session, actor, "ad", "PAUSE_AD", NOW)
            assert caught.value.status_code == 403


@pytest.mark.parametrize("entity_id", ["campaign", "missing", "ad"])
def test_no_cross_workspace_or_non_ad_enumeration(store, entity_id):
    if entity_id == "ad":
        with store.begin() as session:
            session.get(AdAccount, "account").workspace_id = "other"
    with store() as session:
        with pytest.raises(HTTPException) as caught:
            build_review(session, ACTOR, entity_id, "PAUSE_AD", NOW)
        assert caught.value.status_code == 404


class PilotReviewApiTests(AuthTests):
    async def test_session_query_validation_no_store_and_no_execution(self):
        path = "/api/manual-control/pilot-review/ad"
        assert (await self.client.get(path)).status_code == 401
        seed(self.sessions, include_users=False)
        await self.login("viewer")
        assert (await self.client.get(path)).status_code == 403
        await self.login("admin")
        response = await self.client.get(path)
        assert (
            response.status_code == 200
            and response.headers["cache-control"] == "no-store"
        )
        assert not response.json()["execution_allowed"]
        assert (await self.client.get(path + "?operation=BUDGET")).status_code == 422
        assert (
            await self.client.post(
                path, headers=await self.csrf(), json={"confirm": True}
            )
        ).status_code == 405
        with self.sessions() as session:
            assert (
                session.scalar(select(func.count()).select_from(ActionExecution)) == 0
            )
            assert session.scalar(select(func.count()).select_from(ActionRequest)) == 0


def test_changing_flags_cannot_turn_review_into_authorization(store, monkeypatch):
    for key, value in (
        ("ACTIONS_ENABLED", "true"),
        ("LOCAL_READ_ONLY", "false"),
        ("AI_ENABLED", "true"),
        ("AI_AUTOPILOT_ALLOWED", "true"),
    ):
        monkeypatch.setenv(key, value)
    card = review(store)
    assert card["flags"]["ACTIONS_ENABLED"]
    assert card["execution_allowed"] is False
    assert "PRODUCTION_DISPATCH_NOT_IMPLEMENTED" in card["unresolved_contract"]


def test_unknown_raw_effective_status_is_not_exposed_as_a_contract_or_secret(store):
    with store.begin() as session:
        session.get(EntityCurrentState, "ad").raw = {
            "effective_status": {"secret": "provider-body-marker"}
        }
    card = review(store)
    assert card["entity"]["effective_status"] is None
    assert "provider-body-marker" not in json.dumps(card)
