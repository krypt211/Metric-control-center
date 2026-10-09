"""Recommendation read model: isolation, rechecks, pagination and immutability."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from test_economics import ACTOR, CONFIG, NOW, EconomicsApiTests
from test_economics import store as economics_store
from test_smart_rules import config

from services.automation.smart_models import RuleAuditLog, RuleSimulation
from services.automation.smart_recommendations import recommendation_summary
from services.automation.smart_simulation import simulate
from services.automation.smart_store import save
from services.economics.schema import ProfileInput
from services.economics.store import change_profile, create_profile
from services.storage.models import ActionRequest, Rule


@pytest.fixture(name="store")
def storage():
    yield from economics_store.__wrapped__()


def seed(s):
    p = create_profile(s, ACTOR, ProfileInput.model_validate(CONFIG))
    rule = save(s, ACTOR, config(profile_id=p["id"]))
    run = simulate(s, ACTOR, rule["id"], 1, now=NOW)
    return p, rule, run


def test_latest_only_no_write_or_duplicate_counts(store):
    with store.begin() as s:
        _, rule, first = seed(s)
        second = simulate(s, ACTOR, rule["id"], 1, now=NOW + timedelta(minutes=1))
        old = deepcopy(s.get(RuleSimulation, first["id"]).payload)
        audits = s.scalar(select(func.count()).select_from(RuleAuditLog))
        actions = s.scalar(select(func.count()).select_from(ActionRequest))
        response = recommendation_summary(s, "default", now=NOW + timedelta(minutes=2))
        assert response["rows"][0]["simulation_id"] == second["id"]
        assert sum(response["counts"].values()) == second["total"]
        assert response["real_action"] is False
        assert response["count_semantics"] == "rule_ad_occurrences_on_page"
        assert s.scalar(select(func.count()).select_from(RuleAuditLog)) == audits
        assert s.scalar(select(func.count()).select_from(ActionRequest)) == actions
        assert s.get(RuleSimulation, first["id"]).payload == old


def test_rechecks_keep_saved_decision_and_detect_economics_and_revision(store):
    with store.begin() as s:
        p, rule, run = seed(s)
        original = deepcopy(s.get(RuleSimulation, run["id"]).payload)
        change_profile(
            s,
            ACTOR,
            p["id"],
            1,
            ProfileInput.model_validate({**CONFIG, "payout": "20"}),
        )
        save(s, ACTOR, config(profile_id=p["id"], name="Changed"), rule["id"], 1)
        # These fixture writes use wall clock; pin their metadata for the test.
        from services.economics.models import EconomicsProfile

        s.get(EconomicsProfile, p["id"]).updated_at = NOW + timedelta(hours=1)
        row = recommendation_summary(s, "default", now=NOW + timedelta(hours=40))[
            "rows"
        ][0]
        assert {"RULE_CHANGED", "SNAPSHOT_OLD", "ECONOMICS_CHANGED"} <= set(
            row["recheck_reasons"]
        )
        assert row["simulation_revision"] == 1 and row["rule_revision"] == 2
        assert s.get(RuleSimulation, run["id"]).payload == original


def test_period_shift_and_effective_dates(store):
    with store.begin() as s:
        rule = save(s, ACTOR, config(period="last_7", start=None, end=None))
        simulate(s, ACTOR, rule["id"], 1, now=NOW)
        row = recommendation_summary(s, "default", now=NOW + timedelta(days=1))["rows"][
            0
        ]
        assert "PERIOD_CHANGED" in row["recheck_reasons"]
        pending = save(
            s, ACTOR, config(effective_start=(NOW + timedelta(days=2)).date())
        )
        row = next(
            r
            for r in recommendation_summary(s, "default", now=NOW)["rows"]
            if r["rule_id"] == pending["id"]
        )
        assert row["recheck_reasons"] == ["NOT_EVALUATED", "OUTSIDE_EFFECTIVE_DATES"]


def test_workspace_archive_legacy_and_deterministic_pagination(store):
    with store.begin() as s:
        keys = [save(s, ACTOR, config(name=str(n)))["id"] for n in range(4)]
        save(s, ACTOR, None, keys[0], 1, deleted=True)
        s.get(Rule, keys[1]).workspace_id = "other"
        s.get(Rule, keys[2]).status = "ACTIVE"
        response = recommendation_summary(s, "default", now=NOW, limit=1)
        assert response["total_rules"] == 1
        assert response["rows"][0]["rule_id"] == keys[3]
        assert response["rows"][0]["simulation_id"] is None
        assert sum(response["counts"].values()) == 0
        assert response["next_offset"] is None
        assert recommendation_summary(s, "empty", now=NOW)["rows"] == []
        save(s, ACTOR, config(name="Next"))
        first = recommendation_summary(s, "default", now=NOW, limit=1)
        second = recommendation_summary(s, "default", now=NOW, limit=1, offset=1)
        assert first["next_offset"] == 1
        assert second["next_offset"] is None
        assert first["rows"][0]["rule_id"] != second["rows"][0]["rule_id"]


class RecommendationApiTests(EconomicsApiTests):
    async def test_authenticated_read_all_roles_and_range(self):
        path = "/api/smart-rules/recommendations"
        self.assertEqual((await self.client.get(path)).status_code, 401)
        for role in ("admin", "operator", "viewer"):
            await self.login(role)
            result = await self.client.get(path)
            self.assertEqual(result.status_code, 200)
            self.assertFalse(result.json()["real_action"])
            self.assertEqual(
                (await self.client.get(path + "?limit=101")).status_code, 422
            )
            self.assertEqual(
                (await self.client.get(path + "?offset=-1")).status_code, 422
            )
