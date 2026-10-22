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
from fastapi import HTTPException
from psycopg import sql
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import sessionmaker

from scripts.check_controlled_rehearsal_postgres import ACTOR as BASE_ACTOR
from scripts.check_controlled_rehearsal_postgres import NOW, TOKEN, seed_rehearsal
from scripts.check_pilot_credential_permissions import denied
from services.actions import reported_spend as spend
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
from services.providers.models import (
    ProviderAccountMapping,
    ProviderConnection,
    ProviderRoutingSetting,
)
from services.storage.credential_permissions import (
    RULE_READ_TABLES,
    grant_credential_access,
)
from services.storage.database import database_url, make_engine
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    AdAccount,
    Base,
    DailyMetric,
    Entity,
    User,
)


def main(*, reported_spend_test: bool = False):
    actor = (
        {**BASE_ACTOR, "workspace": "default"} if reported_spend_test else BASE_ACTOR
    )
    zone = "America/Los_Angeles" if reported_spend_test else "Europe/Moscow"
    ids = (
        (spend.CAMPAIGN, spend.ADSET, spend.AD)
        if reported_spend_test
        else ("1001", "1002", "1003")
    )
    if not database_url().database.startswith("mcc_integrations_"):
        raise RuntimeError("ISOLATED_DATABASE_REQUIRED")
    db = make_engine()
    schema, role = "rule_pilot_" + uuid4().hex, "rule_pilot_" + uuid4().hex
    vault = WriteCredentialVault(Path("/tmp/unused-rule-test"), Fernet.generate_key())
    first, last = (
        (spend.DAY, spend.DAY)
        if reported_spend_test
        else ((NOW - timedelta(days=8)).date(), (NOW - timedelta(days=2)).date())
    )
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
            if reported_spend_test:
                with sf.begin() as s:
                    for model in (
                        User,
                        AdAccount,
                        ProviderAccountMapping,
                        ProviderConnection,
                        ProviderRoutingSetting,
                        WriteCredentialState,
                    ):
                        s.execute(
                            update(model)
                            .where(model.workspace_id == BASE_ACTOR["workspace"])
                            .values(workspace_id=actor["workspace"])
                        )
                    s.get(
                        WriteCredentialState, actor["workspace"]
                    ).encrypted = vault.seal(actor["workspace"], TOKEN, 1).decode()
                    account = s.get(AdAccount, "account")
                    account.external_id = spend.ACCOUNT
                    account.timezone = zone
                    s.get(
                        ProviderAccountMapping, "account"
                    ).meta_account_id = spend.ACCOUNT
                    for key, external in zip(
                        ("campaign", "adset", "ad"), ids, strict=True
                    ):
                        s.get(Entity, key).external_id = external
            with sf.begin() as s:
                s.get(WriteCredentialState, actor["workspace"]).scopes = [
                    "entities:write",
                    "campaigns:read",
                ]
                profile = create_profile(
                    s,
                    actor,
                    ProfileInput(
                        name="Synthetic verified IT",
                        timezone=zone,
                        payout="52",
                        currency="USD",
                        planned_approval_rate="0.2",
                        minimum_roi="18",
                        target_roi="50",
                    ),
                )
                rule = save(
                    s,
                    actor,
                    SmartRuleInput.model_validate(
                        {
                            "name": "Synthetic rule admission",
                            "profile_id": profile["id"],
                            "period": "custom",
                            "start": str(first),
                            "end": str(last),
                            "selection": {
                                "target_mode": True,
                                "targets": [
                                    {
                                        "scope_type": "AD",
                                        "scope_id": "ad",
                                        "account_id": "account",
                                        "provider": "metricflow",
                                    }
                                ],
                            }
                            if reported_spend_test
                            else {},
                            "expression": {
                                "children": [
                                    {
                                        "type": "SPEND_THRESHOLD",
                                        "source": "actual",
                                        "limit": "custom",
                                        "value": "15",
                                        "currency": "USD",
                                    }
                                ]
                                if reported_spend_test
                                else [{"kind": "condition", "type": "CPL_ABOVE_LIMIT"}]
                            },
                        }
                    ),
                )
                if not reported_spend_test:
                    peer = dict(rule["definition"])
                    peer.update(
                        name="Synthetic readonly peer",
                        enabled=True,
                        action="NOTIFY_ONLY",
                    )
                    save(s, actor, SmartRuleInput.model_validate(peer))
                s.add(
                    DailyMetric(
                        entity_id="ad",
                        day=last,
                        source="metricflow",
                        currency="USD",
                        timezone=zone,
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
                    actor["workspace"],
                    SmartRuleInput.model_validate(rule["definition"]),
                    NOW,
                    persist_snapshot=False,
                )
                from services.storage.models import Rule

                assess_scope(
                    s,
                    actor["workspace"],
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
                source_attribution=None
                if reported_spend_test
                else {"action_attribution_windows": ["7d_click"]},
                eligible_for_rule_evaluation=not reported_spend_test,
                actual_cpl="9",
                maximum_cpl="8.81355932",
            )
            if reported_spend_test:
                row.update(spend="16.15", evaluation_timezone=zone)
            engine = ActionEngine(sf, ActionPolicy(enabled=True), clock=lambda: NOW)
            calls = []
            payloads = {
                "campaigns": {
                    "id": ids[0],
                    "status": "PAUSED",
                    "effective_status": "PAUSED",
                },
                "adsets": {
                    "id": ids[1],
                    "campaign_id": ids[0],
                    "parent_id": ids[0],
                    "status": "PAUSED",
                    "effective_status": "PAUSED",
                },
                "ads": {
                    "id": ids[2],
                    "campaign_id": ids[0],
                    "parent_id": ids[1],
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
                assert request.url.path == f"/api/v1/entities/{ids[2]}/pause"
                assert json.loads(request.content) == {"level": "ad"}
                return httpx.Response(
                    200, json={"success": True, "entity_id": ids[2], "message": "mock"}
                )

            with patch(
                "services.automation.smart_simulation.economics_adapter",
                side_effect=lambda *a, **kw: copy.deepcopy(data),
            ):
                # Simulations are prepared by the app role, never by the credential role.
                connection.execute(text("RESET ROLE"))
                with sf.begin() as s:
                    run = simulate(s, actor, rule["id"], 1, now=NOW)
                with connection.connection.driver_connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role))
                    )
                assert run["rows"][0]["safe_to_consider_for_future_action"] is (
                    not reported_spend_test
                )
                with patch.dict(
                    os.environ, {"ACTIONS_ENABLED": "false", "LOCAL_READ_ONLY": "true"}
                ):

                    def prepare_card():
                        return asyncio.run(
                            prepare_experiment(
                                engine,
                                actor,
                                ExperimentalPrepareInput(
                                    entity_id="ad",
                                    simulation_id=run["id"],
                                    credential_revision=1,
                                    management_confirmed=True,
                                    statement="PREPARE_EXPERIMENT_ONLY_NO_POST",
                                    **(
                                        {
                                            "rule_evidence_policy": spend.POLICY,
                                            "reported_spend_acknowledgement": spend.ACK,
                                        }
                                        if reported_spend_test
                                        else {}
                                    ),
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
                    if reported_spend_test:
                        row["source_stale"] = True
                    else:
                        row["eligible_for_rule_evaluation"] = False
                    try:
                        prepare_card()
                    except (WriteDisabled, HTTPException) as error:
                        if reported_spend_test:
                            assert error.detail == "REPORTED_SPEND_TEST_EVIDENCE_HELD"
                        else:
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
                    row["eligible_for_rule_evaluation"] = not reported_spend_test
                    row["source_stale"] = False
                    assert calls == ["GET"] * 3
                    calls.clear()
                    card = prepare_card()
                    cancelled = engine.transition_manual(
                        actor, card["request_id"], "cancel", card["revision"]
                    )
                    assert cancelled["status"] == "CANCELLED"
                    assert calls == ["GET"] * 3
                    calls.clear()
                    retry = prepare_card()
                    assert retry["request_id"] != card["request_id"]
                    card = retry
                    draft = {"id": card["request_id"], "revision": card["revision"]}
                    for event in ("preflight", "confirm"):
                        draft = engine.transition_manual(
                            actor, draft["id"], event, draft["revision"]
                        )
                with patch.dict(
                    os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}
                ):
                    permit = authorize_pilot(
                        engine,
                        actor,
                        draft["id"],
                        PilotAuthorizationInput(
                            revision=draft["revision"],
                            credential_revision=1,
                            account_id=spend.ACCOUNT
                            if reported_spend_test
                            else "act_100",
                            entity_id=ids[2],
                            operation="PAUSE_AD",
                            expected_status="ACTIVE",
                            statement=spend.STATEMENT
                            if reported_spend_test
                            else STATEMENT,
                        ),
                    )
                    assert (
                        asyncio.run(
                            execute_pilot(
                                engine,
                                actor,
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
            # Administrative late group review also runs under the restricted role.
            from services.actions.engine import ActionRejected
            from services.actions.experimental_reconciliation import (
                SPENT_ADSET_REVIEW,
                review_spent_adset_enable,
            )
            from services.actions.manual import snapshot
            from services.actions.pilot import require_workspace_available

            expiry = NOW - timedelta(hours=1)
            with sf.begin() as s:
                captured = snapshot(
                    s, s.get(Entity, "adset"), s.get(AdAccount, "account")
                )
                control = {
                    "mode": "LIVE_SINGLE_OPERATION",
                    "response_mode": "SYNC_200",
                    "attempts": 1,
                    "wire_spent": True,
                    "http_started": True,
                    "expires_at": expiry.isoformat(),
                    "job_id": None,
                    "manual_readback": {
                        "actor_id": actor["id"],
                        "entity_id": ids[1],
                        "account_id": captured["meta_account_id"],
                        "configured_status": "ACTIVE",
                        "observed_at": (expiry + timedelta(minutes=2)).isoformat(),
                        "authoritative_api": False,
                        "creates_pause_ownership": False,
                    },
                }
                s.add(
                    ActionRequest(
                        id="late-group-review",
                        workspace_id=actor["workspace"],
                        initiator_id=actor["id"],
                        entity_id="adset",
                        idempotency_key="late-group-review",
                        action="ENABLE_ADSET",
                        status="unknown",
                        revision=10,
                        created_at=NOW - timedelta(days=1),
                        provenance={
                            "phase": "4A",
                            "captured": captured,
                            "experimental": {"evidence_id": "synthetic-old-proof"},
                            "controlled": control,
                        },
                    )
                )
                s.flush()
                s.add(
                    ActionExecution(
                        id="late-group-execution",
                        request_id="late-group-review",
                        started_at=expiry - timedelta(minutes=10),
                        completed_at=expiry - timedelta(minutes=9),
                        outcome="live_unknown",
                    )
                )
                s.add(
                    ActionLog(
                        id="late-group-ack",
                        request_id="late-group-review",
                        created_at=expiry - timedelta(minutes=9),
                        event="controlled_live_acknowledged",
                        details={},
                    )
                )
            preview = review_spent_adset_enable(engine, actor, "late-group-review", 10)
            assert not preview["applied"]
            with sf() as s:
                assert s.get(ActionRequest, "late-group-review").status == "unknown"
                try:
                    require_workspace_available(s, actor["workspace"], draft["id"])
                except ActionRejected as error:
                    assert str(error) == "PILOT_WORKSPACE_CONFLICT"
                else:
                    raise AssertionError("UNKNOWN_GROUP_DID_NOT_BLOCK")
            reviewed = review_spent_adset_enable(
                engine,
                actor,
                "late-group-review",
                10,
                acknowledgement=SPENT_ADSET_REVIEW,
            )
            assert reviewed["applied"]
            with sf() as s:
                assert (
                    s.get(ActionExecution, "late-group-execution").outcome
                    == "live_unknown"
                )
                assert (
                    s.get(ActionRequest, "late-group-review").provenance["controlled"][
                        "wire_spent"
                    ]
                    is True
                )
                require_workspace_available(s, actor["workspace"], draft["id"])
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
                "reported_spend_test": reported_spend_test,
                "rule_mock_posts": 1,
                "provider_requests": 0,
                "select_only_rule_evaluation": True,
                "failed_preparation_rolled_back": True,
                "unspent_cancelled_draft_reprepared": True,
                "spent_group_review_kept_unknown": True,
                "excess_privilege_checks": 5,
                "schema_and_role_rolled_back": True,
            }
        )
    )


if __name__ == "__main__":
    main()
