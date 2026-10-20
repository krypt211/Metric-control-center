"""Credential-role acceptance on a restored DB; all DDL/data roll back."""

from __future__ import annotations

import asyncio
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
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from scripts.check_controlled_rehearsal_postgres import (
    ACTOR,
    NOW,
    seed_rehearsal,
    verify_runtime_source,
)
from services.actions.engine import ActionEngine, ActionPolicy
from services.actions.experimental import (
    PREPARE,
    ExperimentalPrepareInput,
    prepare_experiment,
)
from services.actions.experimental import STATEMENT as EXPERIMENTAL_STATEMENT
from services.actions.manual_schema import ManualDraftInput
from services.actions.pilot import (
    EVIDENCE_EVENT,
    PilotAuthorizationInput,
    PilotReadbackInput,
    authorize_pilot,
    execute_pilot,
    record_manual_readback,
)
from services.actions.write_credentials import WriteCredentialVault
from services.providers.integration_models import WriteCredentialState
from services.storage.credential_permissions import grant_credential_access
from services.storage.database import database_url, make_engine
from services.storage.models import ActionExecution, ActionLog, ActionRequest, Base


def denied(connection, statement):
    try:
        with connection.begin_nested():
            connection.execute(text(statement))
    except DBAPIError as error:
        assert getattr(error.orig, "sqlstate", None) == "42501"
    else:
        raise AssertionError("EXCESSIVE_SERVICE_PRIVILEGE")


def main():
    if not (database_url().database or "").startswith("mcc_integrations_"):
        raise RuntimeError("ISOLATED_DATABASE_REQUIRED")
    verify_runtime_source()
    db = make_engine()
    schema = "pilot_role_" + uuid4().hex
    role = "pilot_role_" + uuid4().hex
    vault = WriteCredentialVault(
        Path("/tmp/synthetic-pilot-role"), Fernet.generate_key()
    )
    clock = [NOW]
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
                        "CREATE ROLE {} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE"
                    ).format(sql.Identifier(role))
                )
            Base.metadata.create_all(connection)
            sf = sessionmaker(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            seed_rehearsal(sf, vault, NOW)
            with sf.begin() as session:
                session.get(WriteCredentialState, ACTOR["workspace"]).scopes = [
                    "entities:write",
                    "campaigns:read",
                ]
            engine = ActionEngine(
                sf, ActionPolicy(enabled=True), clock=lambda: clock[0]
            )
            draft = engine.prepare_manual(
                ACTOR,
                ManualDraftInput(
                    entity_id="ad",
                    account_id="account",
                    meta_ad_id="1003",
                    provider="metricflow",
                    operation="PAUSE_AD",
                    expected_status="ACTIVE",
                    reason="Synthetic least-privilege acceptance",
                ),
                "private-role-pilot",
            )
            for event in ("preflight", "confirm"):
                draft = engine.transition_manual(
                    ACTOR, draft["id"], event, draft["revision"]
                )
            with sf.begin() as session:
                session.add(
                    ActionLog(
                        id="synthetic-proof",
                        request_id=draft["id"],
                        event=EVIDENCE_EVENT,
                        created_at=NOW,
                        details={
                            "actor_id": ACTOR["id"],
                            "account_id": "act_100",
                            "entity_id": "1003",
                            "operation": "PAUSE_AD",
                            "credential_revision": 1,
                            "read_revision": 1,
                            "entity_id_namespace": "PROVIDER_AD_ID",
                            "configured_status": "ACTIVE",
                            "effective_status": "ACTIVE",
                            "permission_source": "USER_ATTESTED",
                            "management_confirmed": True,
                            "profile_id": 123,
                            "namespace_source": "Synthetic fixture only",
                            "contract_review": {
                                "provider": "metricflow",
                                "wire_revision": "status-sync-v1",
                                "operation": "PAUSE_AD",
                                "entity_id_namespace": "PROVIDER_AD_ID",
                                "source_kind": "PROVIDER_CLARIFICATION",
                                "source_reference": "Synthetic fixture, not provider evidence",
                                "source_sha256": "a" * 64,
                                "reviewed_by": ACTOR["id"],
                            },
                        },
                    )
                )
            with connection.connection.driver_connection.cursor() as cursor:
                grant_credential_access(cursor, schema=schema, role=role)
                grant_credential_access(cursor, schema=schema, role=role)  # Idempotent.
                cursor.execute(
                    sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role))
                )
            assert connection.scalar(text("SELECT current_user")) == role
            for statement in (
                "UPDATE users SET role='viewer' WHERE id='admin'",
                "UPDATE entities SET name='unexpected' WHERE id='ad'",
                "UPDATE entity_current_state SET status='PAUSED' WHERE entity_id='ad'",
                "DELETE FROM action_logs WHERE false",
                "SELECT * FROM provider_credentials",
                "SELECT * FROM daily_metrics",
            ):
                denied(connection, statement)
            calls = []

            def respond(request):
                calls.append(request)
                assert request.method == "POST" and request.url.path.endswith(
                    "/1003/pause"
                )
                assert json.loads(request.content) == {"level": "ad"}
                return httpx.Response(
                    200,
                    json={"success": True, "entity_id": "1003", "message": "fixture"},
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
                        statement="AUTHORIZE_ONE_METRICFLOW_AD_STATUS_POST",
                    ),
                )
                for expected in (draft["id"], None):
                    result = asyncio.run(
                        execute_pilot(
                            engine,
                            ACTOR,
                            draft["id"],
                            permit["revision"],
                            vault=vault,
                            transport=httpx.MockTransport(respond),
                        )
                    )
                    assert result == expected
            clock[0] += timedelta(seconds=10)
            with sf() as session:
                revision = session.get(ActionRequest, draft["id"]).revision
            result = record_manual_readback(
                engine,
                ACTOR,
                draft["id"],
                PilotReadbackInput(
                    revision=revision,
                    account_id="act_100",
                    entity_id="1003",
                    configured_status="PAUSED",
                    effective_status="PAUSED",
                    observed_at=clock[0].isoformat(),
                    statement="RECORD_MANUAL_META_READBACK",
                ),
            )
            assert (
                result["status"] == "MANUALLY_REVIEWED"
                and not result["authoritative_api"]
            )
            assert len(calls) == 1
            with sf() as session:
                assert (
                    session.scalar(select(func.count()).select_from(ActionExecution))
                    == 1
                )
            assert (
                connection.scalar(text("SELECT role FROM users WHERE id='admin'"))
                == "admin"
            )
            assert (
                connection.scalar(
                    text("SELECT status FROM entity_current_state WHERE entity_id='ad'")
                )
                == "ACTIVE"
            )
            # Real experimental gates under the restricted role, including INSERT draft.
            experimental_calls = []

            def experimental_response(request):
                experimental_calls.append(request.method)
                if request.method == "POST":
                    assert request.url.path.endswith("/1003/pause")
                    return httpx.Response(
                        200,
                        json={
                            "success": True,
                            "entity_id": "1003",
                            "message": "fixture",
                        },
                    )
                kind = request.url.path.rsplit("/", 1)[-1]
                rows = {
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
                return httpx.Response(
                    200,
                    json={
                        "data": [rows[kind]],
                        "meta": {"total": 1, "data_updated_at": clock[0].isoformat()},
                    },
                )

            with patch.dict(
                os.environ, {"ACTIONS_ENABLED": "false", "LOCAL_READ_ONLY": "true"}
            ):
                card = asyncio.run(
                    prepare_experiment(
                        engine,
                        ACTOR,
                        ExperimentalPrepareInput(
                            entity_id="ad",
                            credential_revision=1,
                            management_confirmed=True,
                            statement=PREPARE,
                        ),
                        vault=vault,
                        transport=httpx.MockTransport(experimental_response),
                    )
                )
                local = {"id": card["request_id"], "revision": card["revision"]}
                for event in ("preflight", "confirm"):
                    local = engine.transition_manual(
                        ACTOR, local["id"], event, local["revision"]
                    )
            with patch.dict(
                os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}
            ):
                permit = authorize_pilot(
                    engine,
                    ACTOR,
                    local["id"],
                    PilotAuthorizationInput(
                        revision=local["revision"],
                        credential_revision=1,
                        account_id="act_100",
                        entity_id="1003",
                        operation="PAUSE_AD",
                        expected_status="ACTIVE",
                        statement=EXPERIMENTAL_STATEMENT,
                    ),
                )
                for expected in (local["id"], None):
                    assert (
                        asyncio.run(
                            execute_pilot(
                                engine,
                                ACTOR,
                                local["id"],
                                permit["revision"],
                                vault=vault,
                                transport=httpx.MockTransport(experimental_response),
                            )
                        )
                        == expected
                    )
            assert experimental_calls == ["GET"] * 6 + ["POST"]
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
                "scope": "RESTORED_DB_TRANSACTION",
                "role": "NOLOGIN_NOSUPERUSER",
                "excess_privilege_checks": 6,
                "single_use_mock_attempts": 1,
                "experimental_mock_post_attempts": 1,
                "experimental_get_attempts": 6,
                "contract_gate": "UNPATCHED",
                "resend": False,
                "manual_record": "NON_AUTHORITATIVE",
                "facts_unchanged": True,
                "role_and_schema_rolled_back": True,
                "provider_requests": 0,
                "advertising_write_requests": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
