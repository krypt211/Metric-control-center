"""Mock rule pilot and SELECT-only evaluation under an isolated PostgreSQL role."""

from __future__ import annotations

import asyncio
import copy
import json
import os
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet
from psycopg import sql
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from scripts.check_controlled_rehearsal_postgres import ACTOR, NOW, seed_rehearsal
from scripts.check_pilot_credential_permissions import denied
from services.actions.engine import ActionEngine, ActionPolicy
from services.actions.experimental import ExperimentalPrepareInput, prepare_experiment
from services.actions.pilot import (
    PilotAuthorizationInput,
    authorize_pilot,
    execute_pilot,
)
from services.actions.rule_pilot import STATEMENT
from services.actions.write_credentials import WriteCredentialVault
from services.automation.smart_schema import SmartRuleInput
from services.automation.smart_simulation import (
    assess_scope,
    economics_adapter,
    simulate,
)
from services.automation.smart_store import save
from services.economics.models import EconomicsEvaluation
from services.economics.schema import ProfileInput
from services.economics.store import create_profile
from services.providers.contracts import WriteDisabled
from services.providers.integration_models import WriteCredentialState
from services.storage.credential_permissions import (
    RULE_READ_TABLES,
    grant_credential_access,
)
from services.storage.database import database_url, make_engine
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    Base,
    DailyMetric,
)


def main():
    if not database_url().database.startswith("mcc_integrations_"):
        raise RuntimeError("ISOLATED_DATABASE_REQUIRED")
    db = make_engine()
    schema, role = "rule_pilot_" + uuid4().hex, "rule_pilot_" + uuid4().hex
    vault = WriteCredentialVault(Path("/tmp/unused-rule-test"), Fernet.generate_key())
    first, last = (NOW - timedelta(days=8)).date(), (NOW - timedelta(days=2)).date()
    with db.connect() as connection:
        outer = connection.begin()
        try:
            with connection.connection.driver_connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
                )
                cursor.execute(
                    sql.SQL("SET LOCAL search_path TO {}").format(
                        sql.Identifier(schema)
                    )
                )
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE"
                    ).format(sql.Identifier(role))
                )
            Base.metadata.create_all(connection)
            sf = sessionmaker(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            seed_rehearsal(sf, vault, NOW)
            with sf.begin() as s:
                s.get(WriteCredentialState, ACTOR["workspace"]).scopes = [
                    "entities:write",
                    "campaigns:read",
                ]
                profile = create_profile(
                    s,
                    ACTOR,
                    ProfileInput(
                        name="Synthetic verified IT",
                        timezone="Europe/Moscow",
                        payout="52",
                        currency="USD",
                        planned_approval_rate="0.2",
                        minimum_roi="18",
                        target_roi="50",
                    ),
                )
                rule = save(
                    s,
                    ACTOR,
                    SmartRuleInput.model_validate(
                        {
                            "name": "Synthetic rule admission",
                            "profile_id": profile["id"],
                            "period": "custom",
                            "start": str(first),
                            "end": str(last),
                            "expression": {
                                "children": [
                                    {"kind": "condition", "type": "CPL_ABOVE_LIMIT"}
                                ]
                            },
                        }
                    ),
                )
                peer = dict(rule["definition"])
                peer.update(
                    name="Synthetic readonly peer", enabled=True, action="NOTIFY_ONLY"
                )
                save(s, ACTOR, SmartRuleInput.model_validate(peer))
                s.add(
                    DailyMetric(
                        entity_id="ad",
                        day=last,
                        source="metricflow",
                        currency="USD",
                        timezone="Europe/Moscow",
                        spend=90,
                        leads=10,
                        observed_at=NOW,
                        raw={},
                    )
                )
            with connection.connection.driver_connection.cursor() as cursor:
                grant_credential_access(cursor, schema=schema, role=role)
                cursor.execute(
                    sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role))
                )
            for table in RULE_READ_TABLES:
                connection.execute(
                    text('SELECT count(*) FROM "' + table + '"')
                ).scalar()
            for statement in (
                "UPDATE rules SET revision=revision WHERE false",
                "UPDATE economics_profiles SET version=version WHERE false",
                "DELETE FROM daily_metrics WHERE false",
                "INSERT INTO economics_evaluations DEFAULT VALUES",
                "SELECT * FROM provider_credentials",
            ):
                denied(connection, statement)
            # Actual evaluator must work without INSERT access to evaluation history.
            with sf.begin() as s:
                before = s.scalar(select(func.count()).select_from(EconomicsEvaluation))
                data = economics_adapter(
                    s,
                    ACTOR["workspace"],
                    SmartRuleInput.model_validate(rule["definition"]),
                    NOW,
                    persist_snapshot=False,
                )
                from services.storage.models import Rule

                assess_scope(
                    s,
                    ACTOR["workspace"],
                    s.get(Rule, rule["id"]),
                    SmartRuleInput.model_validate(rule["definition"]),
                    data,
                    NOW,
                    persist_snapshot=False,
                )
                assert before == s.scalar(
                    select(func.count()).select_from(EconomicsEvaluation)
                )
            # Supply explicit synthetic complete evidence only to the mock rule test.
            row = data["rows"][0]
            row.update(
                source_stale=False,
                window_complete=True,
                source_window_status="complete",
                source_attribution={"action_attribution_windows": ["7d_click"]},
                eligible_for_rule_evaluation=True,
                actual_cpl="9",
                maximum_cpl="8.81355932",
            )
            engine = ActionEngine(sf, ActionPolicy(enabled=True), clock=lambda: NOW)
            calls = []
            payloads = {
                "campaigns": {
                    "id": "1001",
                    "status": "PAUSED",
                    "effective_status": "PAUSED",
                },
                "adsets": {
                    "id": "1002",
                    "campaign_id": "1001",
                    "parent_id": "1001",
                    "status": "PAUSED",
                    "effective_status": "PAUSED",
                },
                "ads": {
                    "id": "1003",
                    "campaign_id": "1001",
                    "parent_id": "1002",
                    "status": "ACTIVE",
                    "effective_status": "ADSET_PAUSED",
                },
            }

            def respond(request):
                calls.append(request.method)
                if request.method == "GET":
                    return httpx.Response(
                        200,
                        json={
                            "data": [payloads[request.url.path.rsplit("/", 1)[-1]]],
                            "meta": {
                                "total": 1,
                                "limit": None,
                                "offset": None,
                                "data_updated_at": NOW.isoformat(),
                            },
                        },
                    )
                assert request.url.path == "/api/v1/entities/1003/pause"
                assert json.loads(request.content) == {"level": "ad"}
                return httpx.Response(
                    200, json={"success": True, "entity_id": "1003", "message": "mock"}
                )

            with patch(
                "services.automation.smart_simulation.economics_adapter",
                side_effect=lambda *a, **kw: copy.deepcopy(data),
            ):
                # Simulations are prepared by the app role, never by the credential role.
                connection.execute(text("RESET ROLE"))
                with sf.begin() as s:
                    run = simulate(s, ACTOR, rule["id"], 1, now=NOW)
                with connection.connection.driver_connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role))
                    )
                assert run["rows"][0]["safe_to_consider_for_future_action"]
                with patch.dict(
                    os.environ, {"ACTIONS_ENABLED": "false", "LOCAL_READ_ONLY": "true"}
                ):

                    def prepare_card():
                        return asyncio.run(
                            prepare_experiment(
                                engine,
                                ACTOR,
                                ExperimentalPrepareInput(
                                    entity_id="ad",
                                    simulation_id=run["id"],
                                    credential_revision=1,
                                    management_confirmed=True,
                                    statement="PREPARE_EXPERIMENT_ONLY_NO_POST",
                                ),
                                vault=vault,
                                transport=httpx.MockTransport(respond),
                            )
                        )

                    with sf() as s:
                        before_requests = s.scalar(
                            select(func.count()).select_from(ActionRequest)
                        )
                        before_logs = s.scalar(
                            select(func.count()).select_from(ActionLog)
                        )
                    row["eligible_for_rule_evaluation"] = False
                    try:
                        prepare_card()
                    except WriteDisabled as error:
                        assert error.code == "RULE_PILOT_EVIDENCE_HELD"
                    else:
                        raise AssertionError("INELIGIBLE_RULE_ACCEPTED")
                    with sf() as s:
                        assert (
                            s.scalar(select(func.count()).select_from(ActionRequest))
                            == before_requests
                        )
                        assert (
                            s.scalar(select(func.count()).select_from(ActionLog))
                            == before_logs
                        )
                    row["eligible_for_rule_evaluation"] = True
                    assert calls == ["GET"] * 3
                    calls.clear()
                    card = prepare_card()
                    draft = {"id": card["request_id"], "revision": card["revision"]}
                    for event in ("preflight", "confirm"):
                        draft = engine.transition_manual(
                            ACTOR, draft["id"], event, draft["revision"]
                        )
                with patch.dict(
                    os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}
                ):
                    permit = authorize_pilot(
                        engine,
                        ACTOR,
                        draft["id"],
                        PilotAuthorizationInput(
                            revision=draft["revision"],
                            credential_revision=1,
                            account_id="act_100",
                            entity_id="1003",
                            operation="PAUSE_AD",
                            expected_status="ACTIVE",
                            statement=STATEMENT,
                        ),
                    )
                    assert (
                        asyncio.run(
                            execute_pilot(
                                engine,
                                ACTOR,
                                draft["id"],
                                permit["revision"],
                                vault=vault,
                                transport=httpx.MockTransport(respond),
                            )
                        )
                        == draft["id"]
                    )
                assert calls == ["GET"] * 6 + ["POST"]
                with sf() as s:
                    assert (
                        s.scalar(select(func.count()).select_from(ActionExecution)) == 1
                    )
        finally:
            outer.rollback()
        assert not connection.scalar(
            text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:r)"), {"r": role}
        )
        assert not connection.scalar(
            text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:s)"),
            {"s": schema},
        )
    db.dispose()
    print(
        json.dumps(
            {
                "result": "PASS",
                "rule_mock_posts": 1,
                "provider_requests": 0,
                "select_only_rule_evaluation": True,
                "failed_preparation_rolled_back": True,
                "excess_privilege_checks": 5,
                "schema_and_role_rolled_back": True,
            }
        )
    )


if __name__ == "__main__":
    main()
