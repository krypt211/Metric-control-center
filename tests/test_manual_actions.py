"""Local intentions, immutable facts and fail-closed advertising boundaries."""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from test_auth import AuthTests
from test_sync import NOW

from services.actions.engine import ActionEngine, ActionPolicy
from services.actions.manual import ActionExecutionService
from services.actions.manual_models import ManualActionGrant
from services.actions.manual_schema import ManualDraftInput
from services.automation.smart_models import RuleSimulation
from services.metricflow.writer import MetricFlowActionConnector
from services.providers.contracts import WriteDisabled
from services.providers.models import (
    ProviderAccountMapping,
    ProviderConnection,
    ProviderRoutingSetting,
)
from services.storage.database import make_engine, sessions
from services.storage.models import (
    ActionExecution,
    ActionLog,
    Ad,
    AdAccount,
    AdSet,
    Base,
    Campaign,
    Entity,
    EntityCurrentState,
    User,
)

ACTOR = {"id": "admin", "workspace": "default", "role": "admin"}


def seed(factory):
    with factory.begin() as s:
        for role in ("admin", "operator", "viewer"):
            if not s.get(User, role):
                s.add(User(id=role, email=role, workspace_id="default", role=role))
        s.add(
            AdAccount(
                id="account",
                workspace_id="default",
                provider="metricflow",
                external_id="act_100",
                name="Кабинет",
                currency="USD",
                timezone="Europe/Moscow",
                observed_at=NOW,
            )
        )
        s.flush()
        for key, kind, external in (
            ("campaign", "campaign", "1001"),
            ("adset", "adset", "1002"),
            ("ad", "ad", "1003"),
        ):
            s.add(
                Entity(
                    id=key,
                    account_id="account",
                    kind=kind,
                    external_id=external,
                    name=key,
                )
            )
        s.flush()
        s.add(Campaign(entity_id="campaign"))
        s.flush()
        s.add(AdSet(entity_id="adset", campaign_id="campaign"))
        s.flush()
        s.add(Ad(entity_id="ad", adset_id="adset"))
        s.add(
            EntityCurrentState(entity_id="ad", status="ACTIVE", observed_at=NOW, raw={})
        )
        s.add(
            ProviderAccountMapping(
                account_id="account",
                workspace_id="default",
                canonical_id="account",
                meta_account_id="act_100",
                proof="catalog_meta_id",
                updated_at=NOW,
            )
        )
        s.add(
            ProviderConnection(
                workspace_id="default",
                provider="metricflow",
                enabled=True,
                credential_source="server",
                revision=1,
                config={},
                status="healthy",
                permissions={"read": True},
                capabilities={},
                quota={},
                updated_at=NOW,
            )
        )
        s.add(
            ProviderRoutingSetting(
                workspace_id="default",
                scope="workspace",
                primary_provider="metricflow",
                action_provider="disabled",
                updated_at=NOW,
            )
        )


@pytest.fixture
def store(tmp_path):
    db = make_engine(f"sqlite:///{tmp_path / 'manual.db'}")
    Base.metadata.create_all(db)
    factory = sessions(db)
    seed(factory)
    yield factory
    db.dispose()


def command(**changes):
    return ManualDraftInput.model_validate(
        {
            "entity_id": "ad",
            "account_id": "account",
            "meta_ad_id": "1003",
            "provider": "metricflow",
            "operation": "PAUSE_AD",
            "expected_status": "ACTIVE",
            "reason": "Ручная проверка объявления",
            **changes,
        }
    )


def engine(store, clock=lambda: NOW):
    return ActionEngine(store, ActionPolicy(), clock=clock)


def checked(store, **changes):
    e = engine(store)
    r = e.prepare_manual(ACTOR, command(**changes), "one")
    return e, e.transition_manual(ACTOR, r["id"], "preflight", r["revision"])


@pytest.mark.parametrize(
    "operation,status", [("PAUSE_AD", "ACTIVE"), ("ENABLE_AD", "PAUSED")]
)
def test_confirmed_simulation_keeps_ad_facts_unchanged(store, operation, status):
    with store.begin() as s:
        s.get(EntityCurrentState, "ad").status = status
    e, r = checked(store, operation=operation, expected_status=status)
    assert r["status"] == "BLOCKED" and r["preflight"]["local_allowed"]
    assert "WRITE_DISABLED" in r["reason_codes"]
    r = e.transition_manual(ACTOR, r["id"], "confirm", r["revision"])
    assert r["status"] == "CONFIRMED" and r["confirmation_actor"] == "admin"
    r = e.transition_manual(ACTOR, r["id"], "simulate", r["revision"])
    assert r["status"] == "SIMULATED" and r["result"] == "LOCAL_SIMULATION_ONLY"
    with store() as s:
        assert s.get(EntityCurrentState, "ad").status == status
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0
    assert [ev["event"] for ev in r["events"]].count("SIMULATED") == 1
    assert "SUCCEEDED" not in [ev["event"] for ev in r["events"]]


@pytest.mark.parametrize(
    "change,code",
    [
        ({"meta_ad_id": "999"}, "AD_ID_MISMATCH"),
        ({"account_id": "wrong"}, "ACCOUNT_MISMATCH"),
        ({"provider": "meta"}, "PROVIDER_MISMATCH"),
        ({"expected_status": "PAUSED"}, "STATUS_CHANGED"),
    ],
)
def test_identity_mismatch_blocks_even_local_simulation(store, change, code):
    _, r = checked(store, **change)
    assert not r["preflight"]["local_allowed"] and code in r["reason_codes"]


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("stale", "STATUS_STALE"),
        ("future", "STATUS_STALE"),
        ("status", "STATUS_CHANGED"),
        ("credential", "CREDENTIAL_CHANGED"),
        ("routing", "ROUTING_CHANGED"),
        ("provider", "PROVIDER_CHANGED"),
        ("ad_id", "IDENTITY_CHANGED"),
        ("hierarchy", "HIERARCHY_CHANGED"),
        ("unconfirmed", "ACCOUNT_UNCONFIRMED"),
        ("disconnected", "PROVIDER_UNAVAILABLE"),
    ],
)
def test_preflight_rechecks_persisted_evidence(store, mutation, code):
    e = engine(store)
    r = e.prepare_manual(ACTOR, command(), "one")
    with store.begin() as s:
        if mutation in ("stale", "future"):
            s.get(EntityCurrentState, "ad").observed_at = NOW + timedelta(
                seconds=-901 if mutation == "stale" else 61
            )
        elif mutation == "status":
            s.get(EntityCurrentState, "ad").status = "PAUSED"
        elif mutation == "credential":
            s.get(ProviderConnection, ("default", "metricflow")).revision += 1
        elif mutation == "routing":
            s.get(ProviderRoutingSetting, ("default", "workspace")).updated_at = (
                NOW + timedelta(seconds=1)
            )
        elif mutation == "provider":
            s.get(AdAccount, "account").provider = "meta"
        elif mutation == "ad_id":
            s.get(Entity, "ad").external_id = "999"
        elif mutation == "hierarchy":
            s.get(Ad, "ad").adset_id = None
        elif mutation == "unconfirmed":
            s.get(ProviderAccountMapping, "account").meta_account_id = None
        elif mutation == "disconnected":
            s.get(ProviderConnection, ("default", "metricflow")).enabled = False
    r = e.transition_manual(ACTOR, r["id"], "preflight", r["revision"])
    assert not r["preflight"]["local_allowed"] and code in r["reason_codes"]


def test_idempotency_fingerprint_and_pending_conflict(store):
    e = engine(store)
    first = e.prepare_manual(ACTOR, command(), "one")
    assert e.prepare_manual(ACTOR, command(), "one")["id"] == first["id"]
    for body, key in ((command(reason="Другая причина"), "one"), (command(), "two")):
        with pytest.raises(HTTPException) as error:
            e.prepare_manual(ACTOR, body, key)
        assert error.value.status_code == 409


def test_expiry_cancel_and_lock_release(store):
    e = engine(store)
    r = e.prepare_manual(ACTOR, command(), "one")
    later = engine(store, clock=lambda: NOW + timedelta(minutes=16))
    r = later.transition_manual(ACTOR, r["id"], "confirm", r["revision"])
    assert r["status"] == "EXPIRED"
    r = e.prepare_manual(ACTOR, command(), "two")
    assert (
        e.transition_manual(ACTOR, r["id"], "cancel", r["revision"])["status"]
        == "CANCELLED"
    )
    assert e.prepare_manual(ACTOR, command(), "three")["status"] == "DRAFT"


def test_revision_and_confirmation_required(store):
    e, r = checked(store)
    for event, version in (("confirm", 1), ("simulate", r["revision"])):
        with pytest.raises(HTTPException):
            e.transition_manual(ACTOR, r["id"], event, version)


def test_change_after_confirmation_blocks_simulation(store):
    e, r = checked(store)
    r = e.transition_manual(ACTOR, r["id"], "confirm", r["revision"])
    with store.begin() as s:
        s.get(EntityCurrentState, "ad").status = "PAUSED"
    r = e.transition_manual(ACTOR, r["id"], "simulate", r["revision"])
    assert r["status"] == "BLOCKED" and "STATUS_CHANGED" in r["reason_codes"]


@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_separate_manual_permission(store, role):
    a = {**ACTOR, "id": role, "role": role}
    with pytest.raises(HTTPException):
        engine(store).prepare_manual(a, command(), "one")
    if role == "operator":
        with store.begin() as s:
            s.add(
                ManualActionGrant(
                    workspace_id="default", user_id=role, can_control=True
                )
            )
        assert engine(store).prepare_manual(a, command(), "one")["status"] == "DRAFT"


def test_cross_workspace_and_not_ad(store):
    for actor, body in (
        ({**ACTOR, "workspace": "other"}, command()),
        (ACTOR, command(entity_id="adset")),
    ):
        with pytest.raises(HTTPException):
            engine(store).prepare_manual(actor, body, "one")


def test_rule_recommendation_is_explicit_draft_not_execution(store):
    from services.storage.models import Rule

    with store.begin() as s:
        s.add(
            Rule(
                id="rule",
                workspace_id="default",
                status="SMART_DRY_RUN",
                created_at=NOW,
                payload={},
            )
        )
        s.flush()
        s.add(
            RuleSimulation(
                id="sim",
                workspace_id="default",
                rule_id="rule",
                revision=2,
                actor_id="admin",
                created_at=NOW,
                payload={
                    "rows": [
                        {
                            "id": "ad",
                            "external_id": "1003",
                            "account_id": "account",
                            "status": "WOULD_PAUSE",
                            "ad_status": "ACTIVE",
                            "source_provider": "metricflow",
                            "reason_codes": ["CPL_ABOVE_LIMIT"],
                            "credential_revision": 1,
                        }
                    ]
                },
            )
        )
    r = engine(store).prepare_manual(ACTOR, command(simulation_id="sim"), "one")
    assert r["rule_source"]["rule_revision"] == 2
    assert r["status"] == "DRAFT"


def test_rule_api_resolves_provider_identity_and_creates_only_draft(store, monkeypatch):
    from backend import manual_control_api as api
    from services.actions.manual_schema import RuleDraftInput
    from services.storage.models import ActionRequest, Rule

    with store.begin() as s:
        s.add(
            Rule(
                id="rule-api",
                workspace_id="default",
                status="SMART_DRY_RUN",
                created_at=NOW,
                payload={},
            )
        )
        s.flush()
        s.add(
            RuleSimulation(
                id="sim-api",
                workspace_id="default",
                rule_id="rule-api",
                revision=2,
                actor_id="admin",
                created_at=NOW,
                payload={
                    "rows": [
                        {
                            "id": "ad",
                            "external_id": "1003",
                            "account_id": "account",
                            "source_provider": "metricflow",
                            "ad_status": "ACTIVE",
                            "status": "WOULD_PAUSE",
                            "reason_codes": ["THRESHOLD_EXCEEDED"],
                        }
                    ]
                },
            )
        )
    # Authorization/CSRF are exercised separately. This isolated handler test
    # checks its real mapping query and ActionEngine, with no provider client.
    monkeypatch.setattr(api, "actor", lambda request, write=False: ACTOR)
    monkeypatch.setattr(api, "factory", lambda: store)
    result = api.from_rule(
        RuleDraftInput(simulation_id="sim-api", entity_id="ad"), None, "rule-api-one"
    )
    assert result["status"] == "DRAFT"
    assert result["meta_ad_id"] == "1003"
    assert result["rule_source"]["rule_revision"] == 2
    assert result["rule_source"]["reasons"] == ["THRESHOLD_EXCEEDED"]
    with store() as s:
        assert s.scalar(select(func.count()).select_from(ActionRequest)) == 1
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0
        assert s.get(EntityCurrentState, "ad").status == "ACTIVE"


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation", "SET_BID"),
        ("reason", "  "),
        ("meta_ad_id", "name"),
        ("extra", "x"),
    ],
)
def test_strict_command_validation(field, value):
    with pytest.raises(ValidationError):
        command(**{field: value})


async def disabled_write_case(actions, readonly):
    calls = []
    with patch.dict(
        os.environ, {"ACTIONS_ENABLED": actions, "LOCAL_READ_ONLY": readonly}
    ):
        with pytest.raises(WriteDisabled):
            ActionExecutionService.execute()
        async with MetricFlowActionConnector(
            "mfk_test",
            transport=httpx.MockTransport(
                lambda r: calls.append(r) or httpx.Response(200, json={})
            ),
        ) as c:
            with pytest.raises(WriteDisabled):
                await c.pause_entity("1003")
    assert calls == []


@pytest.mark.parametrize(
    "actions,readonly", [("false", "false"), ("true", "true"), ("false", "true")]
)
def test_write_disabled_before_http_and_execution(actions, readonly):
    asyncio.run(disabled_write_case(actions, readonly))


def test_restart_preserves_draft_and_audit(store):
    e, r = checked(store)
    e = engine(store)
    r = e.transition_manual(ACTOR, r["id"], "confirm", r["revision"])
    assert len(r["events"]) >= 6
    assert r["captured"]["provider"] == "metricflow"


class ManualApiTests(AuthTests):
    async def test_roles_csrf_workspace_and_disabled_execution_routes(self):
        base = "/api/manual-control"
        assert (await self.client.get(base + "/settings")).status_code == 401
        for role in ("viewer", "operator", "admin"):
            await self.login(role)
            assert (await self.client.get(base + "/settings")).status_code == 200
            response = await self.client.post(
                base + "/requests",
                headers={**await self.csrf(), "Idempotency-Key": "one"},
                json=command().model_dump(),
            )
            assert response.status_code == (404 if role == "admin" else 403)
        assert (
            await self.client.post(base + "/requests", json=command().model_dump())
        ).status_code == 403
        for path in (
            base + "/execute",
            "/api/actions",
            base + "/requests/missing/execute",
        ):
            response = await self.client.post(
                path, headers=await self.csrf(), json={"revision": 1}
            )
            assert response.status_code in (403, 404)
        with self.sessions() as s:
            assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0
            assert s.scalar(select(func.count()).select_from(ActionLog)) == 0
