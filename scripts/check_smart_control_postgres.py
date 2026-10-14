"""Process-level Smart Rules DRY RUN race in an isolated restored PostgreSQL DB."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import func, select, text

from services.automation.smart_models import RuleAuditLog, RuleSimulation
from services.automation.smart_schema import SmartRuleInput
from services.automation.smart_store import evaluate_due, save
from services.economics.schema import ProfileInput
from services.economics.store import create_profile, utcnow
from services.providers.models import ProviderAccountMapping
from services.storage.database import database_url, make_engine, sessions
from services.storage.models import (
    Ad,
    AdAccount,
    Base,
    Entity,
    EntityCurrentState,
    RuleCooldown,
    User,
)


def engine():
    return make_engine(
        database_url().set(
            query={"options": "-csearch_path=" + os.environ["SMART_TEST_SCHEMA"]}
        )
    )


def fake_data():
    now = utcnow()
    first, last = now.date() - timedelta(days=7), now.date() - timedelta(days=1)
    return {
        "start": str(first),
        "end": str(last),
        "sources": [],
        "reporting_timezone": "Europe/Moscow",
        "rows": [
            {
                "id": "ad",
                "external_id": "1003",
                "account_id": "account",
                "source_provider": "metricflow",
                "name": "Synthetic PostgreSQL AD",
                "profile_id": os.environ["SMART_TEST_PROFILE"],
                "profile_currency": "USD",
                "currency": "USD",
                "timezone": "Europe/Moscow",
                "evaluation_timezone": "Europe/Moscow",
                "period_start": str(first),
                "period_end": str(last),
                "spend": "10",
                "leads": 1,
                "ad_status": "ACTIVE",
                "source_attribution": "7d_click",
                "source_stale": False,
                "window_complete": True,
                "eligible_for_rule_evaluation": True,
            }
        ],
    }


def child():
    db = engine()
    with (
        sessions(db).begin() as s,
        patch(
            "services.automation.smart_simulation.economics_adapter",
            return_value=fake_data(),
        ),
    ):
        result = evaluate_due(s, "smart-test")
    print(json.dumps(result))
    db.dispose()


def main():
    if not database_url().database.startswith("mcc_integrations_"):
        raise RuntimeError("ISOLATED_DATABASE_REQUIRED")
    admin = make_engine()
    with admin.begin() as c:
        assert (
            c.scalar(text("SELECT version_num FROM alembic_version"))
            == "0016_smart_control"
        )
        schema = "smart_core_" + uuid4().hex
        c.execute(text("CREATE SCHEMA " + schema))
    os.environ["SMART_TEST_SCHEMA"] = schema
    db = engine()
    Base.metadata.create_all(db)
    actor = {"id": "admin", "workspace": "smart-test", "role": "admin"}
    with sessions(db).begin() as s:
        s.add(
            User(
                id="admin",
                workspace_id="smart-test",
                email="admin@smart-test.invalid",
                role="admin",
            )
        )
        s.add(
            AdAccount(
                id="account",
                workspace_id="smart-test",
                provider="metricflow",
                external_id="act_100",
                name="Synthetic account",
                currency="USD",
                timezone="Europe/Moscow",
                observed_at=utcnow(),
            )
        )
        s.flush()
        s.add(
            Entity(
                id="ad",
                account_id="account",
                kind="ad",
                external_id="1003",
                name="Synthetic AD",
                labels={},
            )
        )
        s.flush()
        s.add(Ad(entity_id="ad"))
        s.add(
            EntityCurrentState(
                entity_id="ad", status="ACTIVE", observed_at=utcnow(), raw={}
            )
        )
        s.add(
            ProviderAccountMapping(
                account_id="account",
                workspace_id="smart-test",
                canonical_id="account",
                meta_account_id="act_100",
                proof="synthetic",
                updated_at=utcnow(),
            )
        )
        p = create_profile(
            s,
            actor,
            ProfileInput.model_validate(
                {
                    "name": "Synthetic",
                    "payout": "16",
                    "currency": "USD",
                    "target_roi": "20",
                    "minimum_roi": "0",
                    "planned_approval_rate": "0.3",
                    "minimum_leads": 1,
                    "maturation_hours": 0,
                }
            ),
        )
        os.environ["SMART_TEST_PROFILE"] = p["id"]
        cfg = SmartRuleInput.model_validate(
            {
                "name": "Synthetic notify",
                "enabled": True,
                "action": "NOTIFY_ONLY",
                "profile_id": p["id"],
                "expression": {
                    "children": [
                        {
                            "kind": "condition",
                            "type": "SPEND_THRESHOLD",
                            "limit": "custom",
                            "value": "1",
                        }
                    ]
                },
            }
        )
        r = save(s, actor, cfg)
    env = {**os.environ}
    children = [
        subprocess.Popen(
            [sys.executable, "-m", "scripts.check_smart_control_postgres", "child"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(8)
    ]
    outcomes = []
    for process in children:
        stdout, _ = process.communicate(timeout=120)
        assert process.returncode == 0, "SCHEDULER_CHILD_FAILED"
        outcomes.append(json.loads(stdout))
    assert sum(v["evaluated"] for v in outcomes) == 1, "DUPLICATE_EVALUATION"
    restarted = subprocess.run(
        [sys.executable, "-m", "scripts.check_smart_control_postgres", "child"],
        env=env,
        capture_output=True,
        check=True,
    )
    assert json.loads(restarted.stdout)["evaluated"] == 0
    with sessions(db)() as s:
        assert s.scalar(select(func.count()).select_from(RuleSimulation)) == 1
        assert (
            s.scalar(
                select(func.count())
                .select_from(RuleAuditLog)
                .where(RuleAuditLog.event == "NOTIFY")
            )
            == 1
        )
        assert (
            s.get(RuleCooldown, (r["id"], "ad")).smart_state["last_decision"]
            == "NOTIFY"
        )
    print(
        json.dumps(
            {
                "processes": 8,
                "evaluations": 1,
                "duplicate_evaluations": 0,
                "restart": "HELD",
                "notifications": 1,
                "advertising_write": 0,
                "meta_live": 0,
                "retained_schema": schema,
            }
        )
    )


if __name__ == "__main__":
    child() if len(sys.argv) > 1 else main()
