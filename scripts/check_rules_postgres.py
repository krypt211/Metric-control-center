"""Isolated PostgreSQL CAS/schema acceptance; refuses live database names."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, inspect, select, text

from services.auth.sessions import new_user
from services.automation.smart_models import RuleAuditLog, RuleVersion
from services.automation.smart_schema import SmartRuleInput
from services.automation.smart_store import get_rule, save
from services.storage.database import database_url, make_engine, sessions
from services.storage.models import Base, Rule, User


def run() -> dict:
    if (
        not database_url().database.startswith("mcc_rules_")
        or os.environ.get("LOCAL_READ_ONLY") != "true"
        or os.environ.get("ACTIONS_ENABLED") != "false"
        or os.environ.get("APP_ENV") == "production"
    ):
        raise RuntimeError("ISOLATED_RULE_DATABASE_REQUIRED")
    engine = make_engine()
    factory = sessions(engine)
    workspace = "rule-test-" + uuid4().hex
    actor = {"workspace": workspace, "role": "admin"}
    config = SmartRuleInput.model_validate(
        {
            "name": "CAS",
            "expression": {
                "children": [{"kind": "condition", "type": "CPL_ABOVE_LIMIT"}]
            },
        }
    )
    try:
        with factory.begin() as s:
            assert (
                s.scalar(text("SELECT version_num FROM alembic_version"))
                == "0011_smart_rules"
            )
            user = new_user(
                s,
                workspace,
                workspace + "@local.test",
                "Test-only-password-12345",
                "admin",
            )
            s.flush()
            actor["id"] = user.id
            row = save(s, actor, config)

        def update() -> str:
            try:
                with factory.begin() as s:
                    save(s, actor, config, row["id"], 1)
                return "updated"
            except HTTPException as e:
                assert e.status_code == 409
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = sorted(pool.map(lambda _: update(), range(2)))
        assert result == ["conflict", "updated"]
        with factory() as s:
            assert get_rule(s, workspace, row["id"]).revision == 2
            try:
                get_rule(s, "foreign", row["id"])
                raise AssertionError("Workspace leak")
            except HTTPException as e:
                assert e.status_code == 404
            assert (
                len(
                    s.scalars(
                        select(RuleVersion).where(RuleVersion.workspace_id == workspace)
                    ).all()
                )
                == 2
            )
            inspector = inspect(s.connection())
            for table in Base.metadata.sorted_tables:
                assert table.name in inspector.get_table_names()
                assert set(table.columns.keys()) <= {
                    c["name"] for c in inspector.get_columns(table.name)
                }
        return {
            "postgres_rules": "PASS",
            "cas": result,
            "workspace_isolation": "PASS",
            "schema_tables": len(Base.metadata.tables),
            "advertising_writes": 0,
        }
    finally:
        with factory.begin() as s:
            for model in (RuleVersion, RuleAuditLog, Rule, User):
                s.execute(delete(model).where(model.workspace_id == workspace))
        engine.dispose()
