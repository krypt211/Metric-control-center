"""Local acknowledgment of a spent late-readback group pilot; no transport exists."""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from test_experimental_pilot import ACTOR, fixture, setup

from services.actions.engine import ActionRejected
from services.actions.experimental_reconciliation import (
    SPENT_ADSET_REVIEW,
    review_spent_adset_enable,
)
from services.actions.manual import snapshot
from services.actions.pilot import require_workspace_available
from services.providers.contracts import WriteDisabled
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    AdAccount,
    Entity,
)

__all__ = ["fixture", "setup"]


@pytest.fixture
def late_group(fixture):
    _engine, sf, _vault, clock = fixture
    expiry = clock[0] - timedelta(hours=1)
    with sf.begin() as s:
        captured = snapshot(s, s.get(Entity, "adset"), s.get(AdAccount, "account"))
        control = {
            "mode": "LIVE_SINGLE_OPERATION",
            "response_mode": "SYNC_200",
            "attempts": 1,
            "wire_spent": True,
            "http_started": True,
            "expires_at": expiry.isoformat(),
            "job_id": None,
            "manual_readback": {
                "actor_id": ACTOR["id"],
                "entity_id": "1002",
                "account_id": "act_100",
                "configured_status": "ACTIVE",
                "observed_at": (expiry + timedelta(minutes=2)).isoformat(),
                "authoritative_api": False,
                "creates_pause_ownership": False,
            },
        }
        s.add(
            ActionRequest(
                id="late-group",
                workspace_id=ACTOR["workspace"],
                initiator_id=ACTOR["id"],
                entity_id="adset",
                idempotency_key="late-group",
                action="ENABLE_ADSET",
                status="unknown",
                revision=10,
                created_at=clock[0] - timedelta(days=1),
                provenance={
                    "phase": "4A",
                    "captured": captured,
                    "experimental": {"evidence_id": "old-proof"},
                    "controlled": control,
                },
            )
        )
        s.flush()
        s.add(
            ActionExecution(
                id="spent-attempt",
                request_id="late-group",
                started_at=expiry - timedelta(minutes=10),
                completed_at=expiry - timedelta(minutes=9),
                outcome="live_unknown",
                error_code=None,
            )
        )
        s.add(
            ActionLog(
                id="old-ack",
                request_id="late-group",
                created_at=expiry - timedelta(minutes=9),
                event="controlled_live_acknowledged",
                details={},
            )
        )
    return "late-group"


def test_preview_requires_ack_and_preserves_unknown_execution(fixture, late_group):
    engine, sf, _vault, _clock = fixture
    with sf() as s:
        before = copy.deepcopy(s.get(ActionRequest, late_group).provenance)
    card = review_spent_adset_enable(engine, ACTOR, late_group, 10)
    assert not card["applied"]
    with sf() as s:
        assert s.get(ActionRequest, late_group).status == "unknown"
        assert s.get(ActionRequest, late_group).provenance == before
        with pytest.raises(ActionRejected, match="PILOT_WORKSPACE_CONFLICT"):
            require_workspace_available(s, ACTOR["workspace"], "new")
    result = review_spent_adset_enable(
        engine, ACTOR, late_group, 10, acknowledgement=SPENT_ADSET_REVIEW
    )
    assert result["applied"] and result["status"] == "MANUALLY_REVIEWED"
    assert review_spent_adset_enable(
        engine, ACTOR, late_group, 10, acknowledgement=SPENT_ADSET_REVIEW
    )["idempotent"]
    with sf() as s:
        require_workspace_available(s, ACTOR["workspace"], "new")
        e = s.get(ActionExecution, "spent-attempt")
        assert e.outcome == "live_unknown" and e.error_code is None
        row = s.get(ActionRequest, late_group)
        assert row.provenance["controlled"]["wire_spent"] is True
        assert row.provenance["controlled"]["attempts"] == 1
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 1
        assert (
            s.scalar(
                select(func.count())
                .select_from(ActionLog)
                .where(ActionLog.event == "pilot_spent_adset_outcome_locally_reviewed")
            )
            == 1
        )


@pytest.mark.parametrize(
    "change",
    [
        "unspent",
        "no_ack",
        "timeout",
        "open_window",
        "wrong_manual",
        "wrong_operation",
        "revision",
        "statement",
    ],
)
def test_invalid_review_cannot_close_unknown(fixture, late_group, change):
    engine, sf, _vault, clock = fixture
    with sf.begin() as s:
        row = s.get(ActionRequest, late_group)
        data = copy.deepcopy(row.provenance)
        if change == "unspent":
            data["controlled"]["wire_spent"] = False
        elif change == "no_ack":
            s.delete(s.get(ActionLog, "old-ack"))
        elif change == "timeout":
            s.get(ActionExecution, "spent-attempt").error_code = "READ_TIMEOUT"
        elif change == "open_window":
            data["controlled"]["expires_at"] = (
                clock[0] + timedelta(minutes=1)
            ).isoformat()
        elif change == "wrong_manual":
            data["controlled"]["manual_readback"]["entity_id"] = "999"
        elif change == "wrong_operation":
            row.action = "ENABLE_AD"
        elif change == "revision":
            row.revision = 11
        row.provenance = data
    with pytest.raises(WriteDisabled):
        review_spent_adset_enable(
            engine,
            ACTOR,
            late_group,
            10,
            acknowledgement="wrong" if change == "statement" else SPENT_ADSET_REVIEW,
        )
    with sf() as s:
        assert s.get(ActionRequest, late_group).status == "unknown"
