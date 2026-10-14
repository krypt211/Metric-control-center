"""Smart Rules core completion, synthetic DB facts only, no network transport."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from test_economics import CONFIG
from test_manual_actions import ACTOR, NOW, engine
from test_manual_actions import store as manual_store
from test_smart_rules import facts

from services.actions.manual_schema import ManualDraftInput
from services.automation.smart_core import arbitrate, decision
from services.automation.smart_models import RuleAuditLog, RuleSimulation
from services.automation.smart_schema import SmartRuleInput, period
from services.automation.smart_simulation import economics_adapter, simulate
from services.automation.smart_store import ad_control, evaluate_due, save
from services.economics.schema import ProfileInput
from services.economics.store import create_profile
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    EntityCurrentState,
    RuleCooldown,
)


@pytest.fixture
def store(tmp_path):
    yield from manual_store.__wrapped__(tmp_path)


def definition(profile=None, action="PAUSE_AD", **changes):
    return SmartRuleInput.model_validate(
        {
            "name": "Core test",
            "profile_id": profile,
            "period": "custom",
            "start": str(NOW.date() - timedelta(days=7)),
            "end": str(NOW.date() - timedelta(days=1)),
            "action": action,
            "expression": {
                "children": [{"kind": "condition", "type": "CPL_ABOVE_LIMIT"}]
            },
            **changes,
        }
    )


def fact(profile="p", **changes):
    defaults = {
        "id": "ad",
        "external_id": "1003",
        "account_id": "account",
        "source_provider": "metricflow",
        "profile_id": profile,
        "ad_status": "ACTIVE",
        "period_start": str(NOW.date() - timedelta(days=7)),
        "period_end": str(NOW.date() - timedelta(days=1)),
    }
    return facts(**{**defaults, **changes})


def dataset(profile="p", **changes):
    return {
        "rows": [fact(profile, **changes)],
        "sources": [],
        "start": str(NOW.date() - timedelta(days=7)),
        "end": str(NOW.date() - timedelta(days=1)),
        "reporting_timezone": "Europe/Moscow",
    }


def seed_rule(store, action="PAUSE_AD", **changes):
    with (
        store.begin() as s,
        patch("services.automation.smart_store.utcnow", return_value=NOW),
    ):
        p = create_profile(s, ACTOR, ProfileInput.model_validate(CONFIG))
        r = save(s, ACTOR, definition(p["id"], action, **changes))
    return r, p["id"]


@pytest.mark.parametrize(
    "action,status", [("PAUSE_AD", "WOULD_PAUSE"), ("NOTIFY_ONLY", "NOTIFY")]
)
def test_pause_notify_existing_formulas(action, status):
    result = decision(definition(action=action), fact(), CONFIG, NOW)
    assert result["status"] == status and result["real_action"] is False


def enable_definition(profile=None, **changes):
    return definition(
        profile,
        "ENABLE_AD",
        allow_reenable=True,
        expression={
            "children": [
                {
                    "kind": "condition",
                    "type": "CPL_AT_OR_BELOW_LIMIT",
                    "limit": "custom",
                    "value": "100",
                }
            ]
        },
        **changes,
    )


def test_enable_requires_verified_ownership_permissions_parents_and_positive_facts():
    f = fact(
        ad_status="PAUSED",
        paused_by_system=True,
        verified_pause_at=(NOW - timedelta(hours=2)).isoformat(),
        reenable_allowed=True,
        parents_active=True,
    )
    assert decision(enable_definition(), f, CONFIG, NOW)["status"] == "WOULD_ENABLE"
    for field, reason in [
        ("paused_by_system", "PAUSE_OWNERSHIP_UNVERIFIED"),
        ("reenable_allowed", "ENABLE_PERMISSION_REQUIRED"),
        ("parents_active", "PARENT_STATE_UNVERIFIED"),
    ]:
        held = decision(enable_definition(), {**f, field: False}, CONFIG, NOW)
        assert held["status"] == "REVIEW" and reason in held["reason_codes"]
    unsafe = definition(action="ENABLE_AD", allow_reenable=True)
    assert decision(unsafe, f, CONFIG, NOW)["status"] == "REVIEW"


@pytest.mark.parametrize(
    "patches",
    [
        {"source_stale": True},
        {"window_complete": False},
        {"spend": None},
        {"leads": None},
    ],
)
def test_missing_stale_never_actions(patches):
    for action in ("PAUSE_AD", "ENABLE_AD", "NOTIFY_ONLY"):
        result = decision(definition(action=action), fact(**patches), CONFIG, NOW)
        assert result["status"] not in ("WOULD_PAUSE", "WOULD_ENABLE")
        assert result["real_action"] is False


def test_profile_timezone_calendar_dst_and_validation():
    cfg = definition(period="last_7", start=None, end=None)
    now = datetime(2026, 3, 9, 1, tzinfo=UTC)
    first, last = period(cfg, now, "America/Los_Angeles")
    assert str(first) == "2026-03-01" and str(last) == "2026-03-07"
    cfg.period = "today"
    assert str(period(cfg, now, "America/Los_Angeles")[0]) == "2026-03-08"
    with pytest.raises(ValidationError):
        ProfileInput.model_validate({**CONFIG, "timezone": "Invalid/Zone"})
    from zoneinfo import ZoneInfo

    boundary = datetime(2026, 3, 8, tzinfo=ZoneInfo("America/Los_Angeles"))
    next_day = datetime(2026, 3, 9, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert (
        next_day.astimezone(UTC) - boundary.astimezone(UTC)
    ).total_seconds() == 23 * 3600
    fallback_start = datetime(2026, 11, 1, tzinfo=ZoneInfo("America/Los_Angeles"))
    fallback_end = datetime(2026, 11, 2, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert (
        fallback_end.astimezone(UTC) - fallback_start.astimezone(UTC)
    ).total_seconds() == 25 * 3600


def test_conflicts_manual_unknown_pause_before_enable_priority_deterministic():
    def c(key, status, **extra):
        return {"rule_id": key, "status": status, "reason_codes": [], **extra}

    values = arbitrate(
        [
            c("enable", "WOULD_ENABLE", priority=100),
            c("pause", "WOULD_PAUSE", priority=0),
        ]
    )
    assert [x["status"] for x in values] == ["REVIEW", "WOULD_PAUSE"]
    values = arbitrate(
        [c("b", "WOULD_PAUSE", priority=5), c("a", "WOULD_PAUSE", priority=5)]
    )
    assert [x["status"] for x in values] == ["REVIEW", "WOULD_PAUSE"]
    for blocker in (
        c("other", "DATA_STALE"),
        c("other", "KEEP", manual_blocked=True),
        c("other", "KEEP", pause_condition_active=True),
    ):
        assert (
            arbitrate([c("enable", "WOULD_ENABLE"), blocker])[0]["status"] == "REVIEW"
        )


def test_notify_dedup_and_restart_uses_durable_existing_state(store):
    r, p = seed_rule(store, "NOTIFY_ONLY")
    with patch(
        "services.automation.smart_simulation.economics_adapter",
        return_value=dataset(p),
    ):
        with store.begin() as s:
            simulate(s, ACTOR, r["id"], 1, now=NOW)
        with store.begin() as s:
            simulate(s, ACTOR, r["id"], 1, now=NOW + timedelta(minutes=1))
    with store() as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(RuleAuditLog)
                .where(RuleAuditLog.event == "NOTIFY")
            )
            == 1
        )
        state = s.get(RuleCooldown, (r["id"], "ad"))
        assert state.smart_state["last_decision"] == "NOTIFY"
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0


def test_scheduler_due_idempotency_disabled_owner_and_restart(store):
    _r, p = seed_rule(store, "NOTIFY_ONLY", enabled=True)
    with patch(
        "services.automation.smart_simulation.economics_adapter",
        return_value=dataset(p),
    ):
        with store.begin() as s:
            assert evaluate_due(s, "default", now=NOW)["evaluated"] == 1
        with store.begin() as s:
            assert evaluate_due(s, "default", now=NOW)["evaluated"] == 0
        with store.begin() as s:
            assert (
                evaluate_due(s, "default", now=NOW + timedelta(minutes=30))["evaluated"]
                == 1
            )
    with store() as s:
        assert s.scalar(select(func.count()).select_from(RuleSimulation)) == 2
        assert s.scalar(select(func.count()).select_from(ActionRequest)) == 0
        assert (
            s.scalar(
                select(func.count())
                .select_from(RuleAuditLog)
                .where(RuleAuditLog.event == "NOTIFY")
            )
            == 1
        )


def test_controls_permission_workspace_cas_and_manual_conflict(store):
    r, p = seed_rule(store)
    with store.begin() as s:
        with pytest.raises(HTTPException) as e:
            ad_control(s, {**ACTOR, "role": "viewer"}, r["id"], "ad", 1, 0, True, False)
        assert e.value.status_code == 403
        ad_control(s, ACTOR, r["id"], "ad", 1, 0, True, False)
    with store.begin() as s:
        with pytest.raises(HTTPException) as e:
            ad_control(s, ACTOR, r["id"], "ad", 1, 0, False, False)
        assert e.value.status_code == 409
    with (
        patch(
            "services.automation.smart_simulation.economics_adapter",
            return_value=dataset(p),
        ),
        store.begin() as s,
    ):
        run = simulate(s, ACTOR, r["id"], 1, now=NOW)
        assert run["rows"][0]["status"] == "REVIEW"
        assert "MANUAL_OVERRIDE" in run["rows"][0]["reason_codes"]


def test_enable_verified_mock_action_history_through_shared_executor(store):
    with (
        store.begin() as s,
        patch("services.automation.smart_store.utcnow", return_value=NOW),
    ):
        p = create_profile(s, ACTOR, ProfileInput.model_validate(CONFIG))
        r = save(s, ACTOR, enable_definition(p["id"]))
        s.get(EntityCurrentState, "ad").status = "PAUSED"
        for key in ("campaign", "adset"):
            s.add(
                EntityCurrentState(
                    entity_id=key, status="ACTIVE", observed_at=NOW, raw={}
                )
            )
        s.add(
            ActionRequest(
                id="verified-mock-pause",
                workspace_id="default",
                initiator_id="admin",
                entity_id="ad",
                idempotency_key="mock-history",
                action="PAUSE_AD",
                baseline_status="ACTIVE",
                provenance={"mock_only": True},
                status="SUCCEEDED",
                revision=1,
                created_at=NOW - timedelta(hours=2),
            )
        )
        s.flush()
        s.add(
            ActionLog(
                id="mock-verified",
                request_id="verified-mock-pause",
                created_at=NOW - timedelta(hours=2),
                event="verified",
                details={"observed_status": "PAUSED", "mock_only": True},
            )
        )
        ad_control(s, ACTOR, r["id"], "ad", 1, 0, False, True)
    with patch(
        "services.automation.smart_simulation.economics_adapter",
        return_value=dataset(p["id"], ad_status="PAUSED"),
    ):
        with store.begin() as s:
            run = simulate(s, ACTOR, r["id"], 1, now=NOW)
        card = run["rows"][0]
        assert card["status"] == "WOULD_ENABLE"
        cmd = ManualDraftInput(
            entity_id="ad",
            account_id="account",
            meta_ad_id="1003",
            provider="metricflow",
            operation="ENABLE_AD",
            expected_status="PAUSED",
            simulation_id=run["id"],
            reason="Synthetic local ENABLE",
        )
        e = engine(store)
        draft = e.prepare_manual(ACTOR, cmd, "mock-enable")
        assert e.prepare_manual(ACTOR, cmd, "mock-enable")["id"] == draft["id"]
        draft = e.transition_manual(ACTOR, draft["id"], "preflight", draft["revision"])
        assert draft["preflight"]["local_allowed"] is True
        draft = e.transition_manual(ACTOR, draft["id"], "confirm", draft["revision"])
        draft = e.transition_manual(ACTOR, draft["id"], "simulate", draft["revision"])
        assert (
            draft["status"] == "SIMULATED"
            and draft["result"] == "LOCAL_SIMULATION_ONLY"
        )
    with store() as s:
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0
        assert s.get(EntityCurrentState, "ad").status == "PAUSED"


def test_opposite_action_cooldown_survives_sessions(store):
    r, p = seed_rule(store)
    with store.begin() as s:
        s.add(
            ActionRequest(
                id="mock-enable",
                workspace_id="default",
                initiator_id="admin",
                entity_id="ad",
                idempotency_key="mock-enable",
                action="ENABLE_AD",
                baseline_status="PAUSED",
                provenance={},
                status="SIMULATED",
                revision=1,
                created_at=NOW - timedelta(minutes=20),
            )
        )
    with (
        patch(
            "services.automation.smart_simulation.economics_adapter",
            return_value=dataset(p),
        ),
        store.begin() as s,
    ):
        card = simulate(s, ACTOR, r["id"], 1, now=NOW)["rows"][0]
        assert (
            card["status"] == "REVIEW" and "ANTI_LOOP_COOLDOWN" in card["reason_codes"]
        )


def test_pause_api_mapping_current_decision_and_confirmation_manual_override(
    store, monkeypatch
):
    from backend import manual_control_api as api
    from services.actions.manual_schema import RuleDraftInput

    r, p = seed_rule(store)
    e = engine(store)
    monkeypatch.setattr(api, "actor", lambda request, write=False: ACTOR)
    monkeypatch.setattr(api, "factory", lambda: store)
    monkeypatch.setattr(api, "ActionEngine", lambda *args: e)
    with patch(
        "services.automation.smart_simulation.economics_adapter",
        return_value=dataset(p),
    ):
        with store.begin() as s:
            run = simulate(s, ACTOR, r["id"], 1, now=NOW)
        draft = api.from_rule(
            RuleDraftInput(simulation_id=run["id"], entity_id="ad"), None, "api-pause"
        )
        assert draft["status"] == "DRAFT" and draft["operation"] == "PAUSE_AD"
        assert (
            api.from_rule(
                RuleDraftInput(simulation_id=run["id"], entity_id="ad"),
                None,
                "api-pause",
            )["id"]
            == draft["id"]
        )
        with store.begin() as s:
            ad_control(s, ACTOR, r["id"], "ad", 1, 0, True, False)
        result = e.transition_manual(ACTOR, draft["id"], "preflight", draft["revision"])
        assert result["preflight"]["local_allowed"] is False
        assert "RULE_CURRENT_DECISION_HELD" in result["preflight"]["blocking_reasons"]
    with store() as s:
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 0
        assert s.get(EntityCurrentState, "ad").status == "ACTIVE"


def test_enable_simulation_cannot_prove_pause_ownership(store):
    r, p = seed_rule(store)
    with store.begin() as s:
        s.get(EntityCurrentState, "ad").status = "PAUSED"
        s.add(
            ActionRequest(
                id="only-simulation",
                workspace_id="default",
                initiator_id="admin",
                entity_id="ad",
                idempotency_key="only-simulation",
                action="PAUSE_AD",
                baseline_status="ACTIVE",
                provenance={},
                status="SIMULATED",
                revision=1,
                created_at=NOW - timedelta(hours=2),
            )
        )
        from services.automation.smart_simulation import action_context

        context = action_context(s, "default", fact(p), r["id"], NOW)
        assert context["paused_by_system"] is False


def test_paused_parent_and_unknown_outcome_hold_enable(store):
    r, p = seed_rule(store)
    with store.begin() as s:
        s.add(
            EntityCurrentState(
                entity_id="campaign", status="PAUSED", observed_at=NOW, raw={}
            )
        )
        s.add(
            EntityCurrentState(
                entity_id="adset", status="ACTIVE", observed_at=NOW, raw={}
            )
        )
        s.add(
            ActionRequest(
                id="unknown",
                workspace_id="default",
                initiator_id="admin",
                entity_id="ad",
                idempotency_key="unknown",
                action="PAUSE_AD",
                baseline_status="ACTIVE",
                provenance={},
                status="OUTCOME_UNKNOWN",
                revision=1,
                created_at=NOW - timedelta(hours=2),
            )
        )
        from services.automation.smart_simulation import action_context

        context = action_context(s, "default", fact(p), r["id"], NOW)
        assert (
            context["parents_active"] is False and context["unresolved_action"] is True
        )


def test_scheduler_disabled_and_revoked_owner_no_actions(store):
    r, p = seed_rule(store, enabled=False)
    with store.begin() as s:
        assert evaluate_due(s, "default", now=NOW)["evaluated"] == 0
    with (
        store.begin() as s,
        patch("services.automation.smart_store.utcnow", return_value=NOW),
    ):
        cfg = definition(p, enabled=True)
        save(s, ACTOR, cfg, r["id"], 1)
        from services.storage.models import User

        s.get(User, "admin").is_active = False
    with store.begin() as s:
        assert evaluate_due(s, "default", now=NOW)["evaluated"] == 0
        assert s.scalar(select(func.count()).select_from(ActionRequest)) == 0
        assert (
            s.scalar(
                select(RuleAuditLog.event).where(RuleAuditLog.event == "SCHEDULE_HELD")
            )
            == "SCHEDULE_HELD"
        )


def test_no_zero_spend_or_rolling_cost_only_recovery_after_pause():
    f = fact(
        ad_status="PAUSED",
        paused_by_system=True,
        reenable_allowed=True,
        parents_active=True,
        verified_pause_at=(NOW - timedelta(hours=2)).isoformat(),
    )
    assert decision(enable_definition(), f, CONFIG, NOW)["status"] == "WOULD_ENABLE"
    zero = {**f, "spend": "0", "actual_cpl": "0"}
    assert (
        "ENABLE_SPEND_EVIDENCE_REQUIRED"
        in decision(enable_definition(), zero, CONFIG, NOW)["reason_codes"]
    )
    rolling = {**f, "verified_pause_at": (NOW - timedelta(days=3)).isoformat()}
    assert (
        "ENABLE_RECOVERY_EVIDENCE_REQUIRED"
        in decision(enable_definition(), rolling, CONFIG, NOW)["reason_codes"]
    )


@pytest.fixture
def inherited_store():
    from test_economics import store as economics_store

    yield from economics_store.__wrapped__()


def test_inherited_profile_timezone_uses_its_calendar_without_rebucketing(
    inherited_store,
):
    from services.economics.schema import AssignmentInput
    from services.economics.store import assign
    from services.storage.models import AdAccount, DailyMetric

    when = datetime(2026, 10, 11, 1, tzinfo=UTC)
    with inherited_store.begin() as s:
        p = create_profile(
            s,
            ACTOR,
            ProfileInput.model_validate({**CONFIG, "timezone": "America/Los_Angeles"}),
        )
        assign(
            s,
            ACTOR,
            AssignmentInput(
                profile_id=p["id"],
                scope_type="account",
                scope_id="a",
                effective_start="2020-01-01",
            ),
        )
        s.get(AdAccount, "a").timezone = "America/Los_Angeles"
        for metric in s.scalars(select(DailyMetric)):
            metric.timezone = "America/Los_Angeles"
        cfg = definition(period="last_7", start=None, end=None)
        data = economics_adapter(s, "default", cfg, when)
        assert data["rows"]
        row = data["rows"][0]
        assert row["profile_id"] == p["id"]
        assert row["evaluation_timezone"] == "America/Los_Angeles"
        assert row["period_start"] == "2026-10-03" and row["period_end"] == "2026-10-09"
        assert data["reporting_timezone"] == "America/Los_Angeles"
