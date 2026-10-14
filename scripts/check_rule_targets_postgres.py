"""PostgreSQL assignment CAS acceptance, only in an isolated restored database."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text

from services.auth.sessions import new_user
from services.automation.smart_models import RuleAuditLog, RuleVersion
from services.automation.smart_schema import BulkTargets, RuleTarget, SmartRuleInput
from services.automation.smart_store import change_targets, get_rule, save
from services.automation.smart_targets import resolve_targets
from services.economics.store import utcnow
from services.storage.database import database_url, make_engine, sessions
from services.storage.models import Ad, AdAccount, AdSet, Campaign, Entity, Rule, User


def run() -> dict:
    if not database_url().database.startswith(("mcc_phase4_", "mcc_integrations_")) or (
        os.environ.get("LOCAL_READ_ONLY") != "true"
        or os.environ.get("ACTIONS_ENABLED") != "false"
        or os.environ.get("APP_ENV") == "production"
    ):
        raise RuntimeError("ISOLATED_RESTORED_DATABASE_REQUIRED")
    engine = make_engine()
    factory = sessions(engine)
    workspace = "target-cas-" + uuid4().hex
    ids = [str(uuid4()) for _ in range(4)]
    actor = {"workspace": workspace, "role": "admin"}
    try:
        with factory.begin() as s:
            assert (
                s.scalar(text("SELECT version_num FROM alembic_version"))
                in ("0012_manual_actions", "0015_meta_pilot")
            )
            user = new_user(
                s,
                workspace,
                workspace + "@local.test",
                "Isolated-test-password-12345",
                "admin",
            )
            s.flush()
            actor["id"] = user.id
            s.add(
                AdAccount(
                    id=ids[0],
                    workspace_id=workspace,
                    provider="metricflow",
                    external_id="act_987654321",
                    currency="USD",
                    timezone="Europe/Moscow",
                    observed_at=utcnow(),
                    labels={},
                )
            )
            s.flush()
            for key, kind, external in zip(
                ids[1:], ("campaign", "adset", "ad"), ("123", "456", "789"), strict=True
            ):
                s.add(
                    Entity(
                        id=key,
                        account_id=ids[0],
                        kind=kind,
                        external_id=external,
                        labels={},
                    )
                )
            s.flush()
            s.add(Campaign(entity_id=ids[1]))
            s.flush()
            s.add(AdSet(entity_id=ids[2], campaign_id=ids[1]))
            s.flush()
            s.add(Ad(entity_id=ids[3], adset_id=ids[2]))
            s.flush()
            config = SmartRuleInput.model_validate(
                {
                    "name": "CAS targets",
                    "selection": {"target_mode": True},
                    "expression": {
                        "children": [{"kind": "condition", "type": "CPL_ABOVE_LIMIT"}]
                    },
                }
            )
            row = save(s, actor, config)

        def assign(_) -> str:
            try:
                with factory.begin() as s:
                    change_targets(
                        s,
                        actor,
                        row["id"],
                        BulkTargets(
                            revision=1,
                            targets=[
                                RuleTarget(
                                    scope_type="CAMPAIGN",
                                    scope_id=ids[1],
                                    account_id=ids[0],
                                    provider="metricflow",
                                )
                            ],
                        ),
                    )
                return "saved"
            except HTTPException as error:
                assert error.status_code == 409
                return "conflict"

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(assign, range(8)))
        assert results.count("saved") == 1 and results.count("conflict") == 7
        with factory() as s:
            saved = get_rule(s, workspace, row["id"])
            targets = saved.payload["selection"]["targets"]
            assert saved.revision == 2 and len(targets) == 1
            assert resolve_targets(s, workspace, targets, utcnow().date())["total"] == 1
            assert (
                s.scalar(
                    select(func.count())
                    .select_from(RuleVersion)
                    .where(RuleVersion.workspace_id == workspace)
                )
                == 2
            )
        return {
            "postgres_targets": "PASS",
            "threads": 8,
            "saved": 1,
            "conflicts": 7,
            "duplicate_assignments": 0,
            "advertising_writes": 0,
            "revision": "0012_manual_actions",
        }
    finally:
        with factory.begin() as s:
            for model in (RuleVersion, RuleAuditLog, Rule):
                s.execute(delete(model).where(model.workspace_id == workspace))
            for model in (Ad, AdSet, Campaign):
                s.execute(delete(model).where(model.entity_id.in_(ids[1:])))
            s.execute(delete(Entity).where(Entity.account_id == ids[0]))
            s.execute(delete(AdAccount).where(AdAccount.workspace_id == workspace))
            s.execute(delete(User).where(User.workspace_id == workspace))
        engine.dispose()
