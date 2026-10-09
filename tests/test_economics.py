"""Isolated economics integration: source separation, late events, roles and audit."""

from __future__ import annotations

import os
import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from test_auth import MemoryLimits
from test_sync import StorageFixture

from backend.app import app
from services.analytics.table import Filters
from services.auth.sessions import new_user
from services.economics.evaluation import evaluate
from services.economics.models import EconomicsAuditLog, EconomicsEvaluation
from services.economics.schema import AssignmentInput, ObservationInput, ProfileInput
from services.economics.store import assign, change_profile, create_profile, observe
from services.storage.models import (
    Ad,
    AdAccount,
    AdSet,
    Campaign,
    DailyMetric,
    Entity,
    TrackerMetric,
    User,
)

DAY = date(2026, 10, 1)
END = date(2026, 10, 7)
NOW = datetime(2026, 10, 11, tzinfo=UTC)
CONFIG = {
    "name": "Test",
    "offer": "",
    "geo": "",
    "payout": "16",
    "currency": "USD",
    "target_roi": "20",
    "minimum_roi": "0",
    "planned_approval_rate": "0.30",
    "maturation_hours": 0,
    "minimum_processed": 10,
}
ACTOR = {"id": "admin", "workspace": "default", "role": "admin"}


def seed(s):
    s.add(
        AdAccount(
            id="a",
            workspace_id="default",
            provider="metricflow",
            external_id="act_1",
            currency="USD",
            timezone="Europe/Moscow",
            observed_at=NOW,
            labels={},
        )
    )
    s.flush()
    for key, kind in [("c", "campaign"), ("g", "adset"), ("d", "ad")]:
        s.add(Entity(id=key, account_id="a", kind=kind, external_id=key, labels={}))
    s.flush()
    s.add(Campaign(entity_id="c"))
    s.flush()
    s.add(AdSet(entity_id="g", campaign_id="c"))
    s.flush()
    s.add(Ad(entity_id="d", adset_id="g"))
    s.flush()
    for n in range(7):
        s.add(
            DailyMetric(
                entity_id="d",
                day=DAY + timedelta(days=n),
                source="metricflow",
                currency="USD",
                timezone="Europe/Moscow",
                spend=D(34) if n == 0 else D(1),
                leads=4 if n == 0 else 1,
                sales=3 if n == 0 else 0,
                conversions=5 if n == 0 else 0,
                raw={},
                observed_at=NOW,
            )
        )
        s.add(
            TrackerMetric(
                entity_id="d",
                day=DAY + timedelta(days=n),
                source="metricflow",
                currency="USD",
                timezone="Europe/Moscow",
                leads=10,
                sales=8,
                raw={},
                observed_at=NOW,
            )
        )
    s.flush()


@pytest.fixture
def store():
    f = StorageFixture()
    f.setUp()
    with f.sessions.begin() as s:
        seed(s)
    try:
        yield f.sessions
    finally:
        f.tearDown()


def observation(key, **updates):
    return ObservationInput.model_validate(
        {
            "profile_id": key,
            "scope_type": "account",
            "scope_id": "a",
            "cohort": "week1",
            "start": str(DAY),
            "end": str(END),
            "approved": 3,
            "rejected": 7,
            "pending": 0,
            "payout": "16",
            "currency": "USD",
            "timezone": "Europe/Moscow",
            "source_provider": "metricflow",
            "attribution_confirmed": True,
            "revenue_confirmed": True,
            **updates,
        }
    )


def evaluated(s, key, level="account"):
    return evaluate(
        s, "default", Filters(DAY, END), selected=key, level=level, now=NOW
    )["rows"][0]


def test_meta_tracker_and_unknown_revenue(store):
    with store.begin() as s:
        p = create_profile(s, ACTOR, ProfileInput.model_validate(CONFIG))
        r = evaluated(s, p["id"])
        assert r["meta_leads"] == 10 and r["tracker_leads"] == 70
        assert r["observed_meta_purchases"] == 3
        assert (
            r["actual_cpl"] == "4.00000000" and r["estimated_revenue"] == "48.00000000"
        )
        assert r["actual_roi"] is None


def test_revised_cohort_is_not_added_twice_and_has_audit(store):
    with store.begin() as s:
        p = create_profile(s, ACTOR, ProfileInput.model_validate(CONFIG))
        first = observe(s, ACTOR, observation(p["id"]))
        second = observe(
            s, ACTOR, observation(p["id"], approved=4, rejected=6, version=1)
        )
        r = evaluated(s, p["id"])
        assert first["id"] == second["id"] and second["version"] == 2
        assert r["approved_sales"] == 4 and r["actual_roi"] == "60.00000000"
        assert s.scalar(select(func.count()).select_from(EconomicsAuditLog)) == 3


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"currency": "EUR"}, "ECONOMICS_OBSERVATION_PROFILE_MISMATCH"),
        ({"scope_id": "foreign"}, "ECONOMICS_SCOPE_NOT_FOUND"),
        ({"version": 1}, "ECONOMICS_VERSION_CONFLICT"),
    ],
)
def test_invalid_observation(store, updates, reason):
    with store.begin() as s:
        p = create_profile(s, ACTOR, ProfileInput.model_validate(CONFIG))
        with pytest.raises(HTTPException) as error:
            observe(s, ACTOR, observation(p["id"], **updates))
        assert error.value.detail == reason


def test_overlap_is_rejected(store):
    with store.begin() as s:
        p = create_profile(s, ACTOR, ProfileInput.model_validate(CONFIG))
        observe(s, ACTOR, observation(p["id"]))
        with pytest.raises(HTTPException) as error:
            observe(
                s,
                ACTOR,
                observation(
                    p["id"], cohort="other", start="2026-10-06", end="2026-10-12"
                ),
            )
        assert error.value.detail == "ECONOMICS_OBSERVATION_OVERLAP"


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"timezone": "UTC"}, "OBSERVATION_SOURCE_MISMATCH"),
        ({"source_provider": "meta"}, "OBSERVATION_SOURCE_MISMATCH"),
        ({"attribution_confirmed": False}, "ATTRIBUTION_UNCONFIRMED"),
        ({"approved": 4}, "COHORT_BASE_MISMATCH"),
        ({"revenue_confirmed": False}, "REVENUE_NOT_CONFIRMED"),
    ],
)
def test_actual_roi_fails_closed(store, updates, reason):
    with store.begin() as s:
        p = create_profile(s, ACTOR, ProfileInput.model_validate(CONFIG))
        observe(s, ACTOR, observation(p["id"], **updates))
        r = evaluated(s, p["id"])
        assert r["actual_roi"] is None and reason in r["reason_codes"]


def test_small_pending_sample_stays_planned(store):
    with store.begin() as s:
        p = create_profile(
            s,
            ACTOR,
            ProfileInput.model_validate(
                {
                    **CONFIG,
                    "actual_approval_policy": "mature_actual",
                    "minimum_processed": 20,
                }
            ),
        )
        observe(s, ACTOR, observation(p["id"], rejected=6, pending=1))
        r = evaluated(s, p["id"])
        assert r["approval_source"] == "PLANNED" and r["pending_sales"] == 1
        assert (
            r["maturity_status"] == "IMMATURE" and not r["eligible_for_rule_evaluation"]
        )


def test_inherited_approval_is_forecast_only_for_ad(store):
    with store.begin() as s:
        p = create_profile(
            s,
            ACTOR,
            ProfileInput.model_validate(
                {**CONFIG, "actual_approval_policy": "mature_actual"}
            ),
        )
        observe(s, ACTOR, observation(p["id"]))
        r = evaluated(s, p["id"], "ad")
        assert r["approval_source"] == "GROUP_MANUAL"
        assert r["actual_roi"] is None and r["approved_sales"] is None


def test_assignment_versions_restore_and_ad_hierarchy(store):
    with store.begin() as s:
        p = create_profile(s, ACTOR, ProfileInput.model_validate(CONFIG))
        assign(
            s,
            ACTOR,
            AssignmentInput(
                profile_id=p["id"],
                scope_type="account",
                scope_id="a",
                effective_start=DAY,
            ),
        )
        r = evaluate(s, "default", Filters(DAY, END), level="ad", now=NOW)["rows"][0]
        assert r["profile_id"] == p["id"] and r["assignment_source"] == "account"
        changed = change_profile(
            s,
            ACTOR,
            p["id"],
            1,
            ProfileInput.model_validate({**CONFIG, "payout": "20"}),
        )
        with pytest.raises(HTTPException):
            change_profile(s, ACTOR, p["id"], 1, None, delete=True)
        restored = change_profile(
            s, ACTOR, p["id"], changed["version"], None, restore_version=1
        )
        assert restored["payout"] == "16" and restored["version"] == 3


def test_late_events_retain_old_inputs_and_delta(store):
    with store.begin() as s:
        p = create_profile(s, ACTOR, ProfileInput.model_validate(CONFIG))
        first = evaluated(s, p["id"])
        fact = s.get(DailyMetric, ("d", DAY, "metricflow"))
        fact.leads = 5
        fact.sales = 4
        s.flush()
        second = evaluated(s, p["id"])
        assert (
            second["event_changes"]["meta_leads"]["delta"] == 1
            and second["event_changes"]["meta_purchases"]["delta"] == 1
        )
        assert second["evaluation_id"] != first["evaluation_id"]
        assert (
            s.get(EconomicsEvaluation, first["evaluation_id"]).payload["inputs"][
                "facts"
            ]["meta_leads"]
            == 10
        )


def test_currency_mismatch_does_not_relabel_spend(store):
    with store.begin() as s:
        p = create_profile(
            s, ACTOR, ProfileInput.model_validate({**CONFIG, "currency": "EUR"})
        )
        r = evaluated(s, p["id"])
        assert r["currency"] == "USD" and r["profile_currency"] == "EUR"
        assert (
            r["actual_roi"] is None
            and r["estimated_roi"] is None
            and r["target_cpl"] is None
        )


class EconomicsApiTests(StorageFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        secret = Path(self.directory.name) / "session"
        secret.write_text("s" * 48)
        self.env = patch.dict(
            os.environ,
            {
                "AUTH_ENABLED": "true",
                "APP_ENV": "development",
                "SESSION_SECRET_FILE": str(secret),
                "APP_ORIGIN": "http://test",
                "WORKSPACE_ID": "default",
                "LOCAL_READ_ONLY": "true",
                "ACTIONS_ENABLED": "false",
            },
        )
        self.env.start()
        self.patches = [
            patch("backend.app.database_sessions", return_value=self.sessions),
            patch("backend.auth.limiter", return_value=MemoryLimits()),
        ]
        for p in self.patches:
            p.start()
        with self.sessions.begin() as s:
            seed(s)
            for role in ("admin", "operator", "viewer"):
                new_user(s, "default", role, "Strong-password-12345", role)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.env.stop()
        super().tearDown()

    async def csrf(self):
        r = await self.client.get("/api/auth/csrf")
        return {"Origin": "http://test", "X-CSRF-Token": r.json()["csrf_token"]}

    async def login(self, role="admin"):
        r = await self.client.post(
            "/api/auth/login",
            headers=await self.csrf(),
            json={"login": role, "password": "Strong-password-12345"},
        )
        self.assertEqual(r.status_code, 200)

    async def test_roles_csrf_grant_and_advertising_prohibitions(self):
        self.assertEqual(
            (await self.client.get("/api/economics/settings")).status_code, 401
        )
        for role in ("viewer", "operator"):
            await self.login(role)
            self.assertEqual(
                (await self.client.get("/api/economics/settings")).status_code, 200
            )
            self.assertEqual(
                (
                    await self.client.post(
                        "/api/economics/profiles",
                        headers=await self.csrf(),
                        json=CONFIG,
                    )
                ).status_code,
                403,
            )
        await self.login()
        self.assertEqual(
            (
                await self.client.post("/api/economics/profiles", json=CONFIG)
            ).status_code,
            403,
        )
        with self.sessions() as s:
            operator = s.scalar(select(User).where(User.email == "operator"))
            oid = operator.id
        r = await self.client.put(
            "/api/economics/grants",
            headers=await self.csrf(),
            json={"user_id": oid, "can_edit": True},
        )
        self.assertEqual(r.status_code, 200, r.text)
        await self.login("operator")
        self.assertEqual(
            (
                await self.client.post(
                    "/api/economics/profiles", headers=await self.csrf(), json=CONFIG
                )
            ).status_code,
            201,
        )
        self.assertEqual(
            (
                await self.client.put(
                    "/api/economics/grants",
                    headers=await self.csrf(),
                    json={"user_id": oid, "can_edit": False},
                )
            ).status_code,
            403,
        )
        for path in ("/api/actions", "/api/automation/control", "/api/ai/analyses"):
            self.assertEqual(
                (
                    await self.client.post(path, headers=await self.csrf(), json={})
                ).status_code,
                403,
            )

    async def test_crud_versions_and_workspace_isolation(self):
        await self.login()
        r = await self.client.post(
            "/api/economics/profiles", headers=await self.csrf(), json=CONFIG
        )
        self.assertEqual(r.status_code, 201, r.text)
        p = r.json()
        path = "/api/economics/profiles/" + p["id"]
        r = await self.client.put(
            path,
            headers=await self.csrf(),
            json={**CONFIG, "payout": "20", "version": 1},
        )
        self.assertEqual(r.status_code, 200, r.text)
        r = await self.client.put(
            path, headers=await self.csrf(), json={**CONFIG, "version": 1}
        )
        self.assertEqual(r.status_code, 409)
        r = await self.client.post(
            path + "/copy", headers=await self.csrf(), json={"version": 2}
        )
        self.assertEqual(r.status_code, 201, r.text)
        r = await self.client.request(
            "DELETE", path, headers=await self.csrf(), json={"version": 2}
        )
        self.assertEqual(r.status_code, 200)
        r = await self.client.post(
            path + "/restore",
            headers=await self.csrf(),
            json={"version": 3, "restore_version": 1},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["payout"], "16")
        with self.sessions.begin() as s:
            foreign = create_profile(
                s,
                {"id": "other", "workspace": "other", "role": "admin"},
                ProfileInput.model_validate(CONFIG),
            )
        self.assertEqual(
            (
                await self.client.get(
                    "/api/economics/evaluate", params={"profile_id": foreign["id"]}
                )
            ).status_code,
            404,
        )
        self.assertEqual(
            (
                await self.client.post(
                    "/api/economics/profiles",
                    headers=await self.csrf(),
                    json={**CONFIG, "workspace_id": "other"},
                )
            ).status_code,
            422,
        )

    async def test_preview_default_seven_days_and_audit(self):
        await self.login()
        r = await self.client.post(
            "/api/economics/preview", headers=await self.csrf(), json=CONFIG
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["target_cpl"], "4.00000000")
        r = await self.client.get("/api/economics/evaluate")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(
            (
                date.fromisoformat(r.json()["end"])
                - date.fromisoformat(r.json()["start"])
            ).days,
            6,
        )
        await self.client.post(
            "/api/economics/profiles", headers=await self.csrf(), json=CONFIG
        )
        self.assertEqual(
            (await self.client.get("/api/economics/audit")).json()["rows"][0]["event"],
            "PROFILE_CREATE",
        )


def test_economic_registry_preserves_old_presets_and_separates_scopes():
    from services.preferences.registry import normalize_config, system_presets

    old = {
        "version": 1,
        "columns": [{"key": "name", "width": 400}, {"key": "roi", "width": 200}],
        "widths": {"roi": 200},
        "sorting": {"key": "roi", "direction": "asc"},
    }
    assert normalize_config(old, "ad") == old
    for level in ("account", "campaign", "adset", "ad"):
        keys = [
            c["key"] for c in system_presets("eco_" + level)[0]["config"]["columns"]
        ]
        assert "actual_roi" in keys and "estimated_roi" in keys
        assert "roi" not in keys
        assert len("eco_" + level) <= 16


def test_snapshot_changes_when_maturity_changes_without_new_events(store):
    with store.begin() as s:
        p = create_profile(
            s, ACTOR, ProfileInput.model_validate({**CONFIG, "maturation_hours": 72})
        )
        early = evaluate(
            s,
            "default",
            Filters(DAY, END),
            selected=p["id"],
            now=datetime(2026, 10, 8, tzinfo=UTC),
        )["rows"][0]
        late = evaluated(s, p["id"])
        assert early["maturity_status"] == "IMMATURE"
        assert late["maturity_status"] == "MATURE"
        assert early["evaluation_id"] != late["evaluation_id"]
        assert (
            s.get(EconomicsEvaluation, early["evaluation_id"]).payload["result"][
                "maturity_status"
            ]
            == "IMMATURE"
        )
        again = evaluated(s, p["id"])
        assert again["evaluation_id"] == late["evaluation_id"]


def test_snapshot_keeps_selection_context(store):
    with store.begin() as s:
        p = create_profile(s, ACTOR, ProfileInput.model_validate(CONFIG))
        row = evaluate(
            s,
            "default",
            Filters(DAY, END, account="a", campaign="c"),
            selected=p["id"],
            level="ad",
            now=NOW,
        )["rows"][0]
        inputs = s.get(EconomicsEvaluation, row["evaluation_id"]).payload["inputs"]
        assert inputs["selection"]["campaign"] == "c"
        assert inputs["selection"]["level"] == "ad"
