"""Mock ENABLE roundtrip and late local review inside an isolated restored-DB schema."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select, text

from scripts.check_controlled_rehearsal_postgres import (
    ACTOR,
    NOW,
    fixture,
    seed_rehearsal,
    verify_runtime_source,
)
from scripts.check_experimental_pilot_postgres import prepared, respond
from services.actions.engine import ActionEngine, ActionPolicy
from services.actions.experimental import (
    ADSET_STATEMENT,
    ENABLE_STATEMENT,
    PREPARE,
    ExperimentalPrepareInput,
    prepare_experiment,
)
from services.actions.pilot import (
    PilotAuthorizationInput,
    authorize_pilot,
    execute_pilot,
)
from services.providers.integration_models import WriteCredentialState
from services.storage.database import database_url, make_engine
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    Base,
    EntityCurrentState,
)


def main():
    if not (database_url().database or "").startswith("mcc_integrations_"):
        raise RuntimeError("ISOLATED_DATABASE_REQUIRED")
    verify_runtime_source()
    admin = make_engine()
    schema = "controlled_rehearsal_enable_" + uuid4().hex
    db = None
    with admin.begin() as c:
        c.execute(text("CREATE SCHEMA " + schema))
    os.environ["REHEARSAL_SCHEMA"] = schema
    os.environ["REHEARSAL_CIPHER"] = Fernet.generate_key().decode()
    try:
        db, sf, vault = fixture()
        Base.metadata.create_all(db)
        seed_rehearsal(sf, vault, NOW)
        with sf.begin() as s:
            s.get(WriteCredentialState, ACTOR["workspace"]).scopes = [
                "entities:write",
                "campaigns:read",
            ]
            r = s.get(EntityCurrentState, "ad")
            r.status = "ADSET_PAUSED"
            r.raw = {"status": "ADSET_PAUSED"}
        engine = ActionEngine(sf, ActionPolicy(enabled=True), clock=lambda: NOW)
        with patch.dict(
            os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}
        ):
            p = prepared(engine, vault)
            asyncio.run(
                execute_pilot(
                    engine,
                    ACTOR,
                    p["id"],
                    p["revision"],
                    vault=vault,
                    transport=httpx.MockTransport(respond),
                )
            )
        now = NOW + timedelta(seconds=901)
        engine = ActionEngine(sf, engine.policy, clock=lambda: now)
        engine.verify_pending()
        with sf.begin() as s:
            s.get(WriteCredentialState, ACTOR["workspace"]).checked_at = now
            s.add(
                ActionLog(
                    id=str(uuid4()),
                    request_id=p["id"],
                    event="pilot_late_manual_target_confirmed",
                    created_at=now,
                    details={
                        "actor_id": ACTOR["id"],
                        "ad_id": "1003",
                        "adset_id": "1002",
                        "campaign_id": "1001",
                        "configured_status": "PAUSED",
                        "matches_target": True,
                        "late_observation": True,
                        "source": "USER_REPLY_AFTER_ID_CLARIFICATION",
                        "authoritative_api": False,
                        "creates_pause_ownership": False,
                    },
                )
            )
        calls = []

        def enabled_response(request):
            calls.append(request.method)
            if request.method == "GET":
                payload = json.loads(respond(request).content)
                payload["meta"]["data_updated_at"] = now.isoformat()
                if request.url.path.endswith("/ads"):
                    payload["data"][0].update(
                        status="PAUSED", effective_status="PAUSED"
                    )
                return httpx.Response(200, json=payload)
            assert request.url.path == "/api/v1/entities/1003/enable"
            return httpx.Response(
                200, json={"success": True, "entity_id": "1003", "message": "fixture"}
            )

        transport = httpx.MockTransport(enabled_response)
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
                        operation="ENABLE_AD",
                        previous_pause_request_id=p["id"],
                    ),
                    vault=vault,
                    transport=transport,
                )
            )
            row = {"id": card["request_id"], "revision": card["revision"]}
            for event in ("preflight", "confirm"):
                row = engine.transition_manual(ACTOR, row["id"], event, row["revision"])
        with patch.dict(
            os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}
        ):
            permit = authorize_pilot(
                engine,
                ACTOR,
                row["id"],
                PilotAuthorizationInput(
                    revision=row["revision"],
                    credential_revision=1,
                    account_id="act_100",
                    entity_id="1003",
                    operation="ENABLE_AD",
                    expected_status="PAUSED",
                    statement=ENABLE_STATEMENT,
                ),
            )
            asyncio.run(
                execute_pilot(
                    engine,
                    ACTOR,
                    permit["id"],
                    permit["revision"],
                    vault=vault,
                    transport=transport,
                )
            )
            assert (
                asyncio.run(
                    execute_pilot(
                        engine,
                        ACTOR,
                        permit["id"],
                        permit["revision"],
                        vault=vault,
                        transport=transport,
                    )
                )
                is None
            )
        assert calls == ["GET"] * 6 + ["POST"]
        with sf() as s:
            assert s.get(ActionRequest, p["id"]).status == "MANUALLY_REVIEWED"
            old = s.scalar(
                select(ActionExecution).where(ActionExecution.request_id == p["id"])
            )
            assert (
                old.outcome == "live_unknown"
                and old.error_code == "MANUAL_READBACK_DEADLINE"
            )
            assert s.get(EntityCurrentState, "ad").status == "ADSET_PAUSED"
        previous_enable_id = permit["id"]
        now = now + timedelta(seconds=901)
        engine.verify_pending()
        with sf.begin() as s:
            s.get(WriteCredentialState, ACTOR["workspace"]).checked_at = now
            for event in (
                "pilot_manual_enable_target_confirmed",
                "pilot_manual_enable_parents_confirmed",
                "pilot_manual_effective_status_confirmed",
            ):
                s.add(
                    ActionLog(
                        id=str(uuid4()),
                        request_id=previous_enable_id,
                        event=event,
                        created_at=now,
                        details={
                            "actor_id": ACTOR["id"],
                            "ad_id": "1003",
                            "configured_status": "ACTIVE",
                            "campaign_status": "PAUSED",
                            "adset_status": "PAUSED",
                            "effective_status": "ADSET_PAUSED",
                        },
                    )
                )
        group_calls = []

        def group_response(request):
            group_calls.append(request.method)
            if request.method == "GET":
                payload = json.loads(respond(request).content)
                payload["meta"]["data_updated_at"] = now.isoformat()
                return httpx.Response(200, json=payload)
            assert request.url.path == "/api/v1/entities/1002/enable"
            assert json.loads(request.content) == {"level": "adset"}
            return httpx.Response(
                200, json={"success": True, "entity_id": "1002", "message": "fixture"}
            )

        group_transport = httpx.MockTransport(group_response)
        with patch.dict(
            os.environ, {"ACTIONS_ENABLED": "false", "LOCAL_READ_ONLY": "true"}
        ):
            group_card = asyncio.run(
                prepare_experiment(
                    engine,
                    ACTOR,
                    ExperimentalPrepareInput(
                        entity_id="adset",
                        credential_revision=1,
                        management_confirmed=True,
                        statement=PREPARE,
                        operation="ENABLE_ADSET",
                        previous_ad_request_id=previous_enable_id,
                    ),
                    vault=vault,
                    transport=group_transport,
                )
            )
            group_row = {
                "id": group_card["request_id"],
                "revision": group_card["revision"],
            }
            for event in ("preflight", "confirm"):
                group_row = engine.transition_manual(
                    ACTOR, group_row["id"], event, group_row["revision"]
                )
        with patch.dict(
            os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}
        ):
            group_permit = authorize_pilot(
                engine,
                ACTOR,
                group_row["id"],
                PilotAuthorizationInput(
                    revision=group_row["revision"],
                    credential_revision=1,
                    account_id="act_100",
                    entity_id="1002",
                    operation="ENABLE_ADSET",
                    expected_status="PAUSED",
                    statement=ADSET_STATEMENT,
                ),
            )
            asyncio.run(
                execute_pilot(
                    engine,
                    ACTOR,
                    group_permit["id"],
                    group_permit["revision"],
                    vault=vault,
                    transport=group_transport,
                )
            )
            assert (
                asyncio.run(
                    execute_pilot(
                        engine,
                        ACTOR,
                        group_permit["id"],
                        group_permit["revision"],
                        vault=vault,
                        transport=group_transport,
                    )
                )
                is None
            )
        assert group_calls == ["GET"] * 6 + ["POST"]
        with sf() as s:
            assert (
                s.get(ActionRequest, previous_enable_id).status == "MANUALLY_REVIEWED"
            )
            previous_execution = s.scalar(
                select(ActionExecution).where(
                    ActionExecution.request_id == previous_enable_id
                )
            )
            assert (
                previous_execution.outcome == "live_unknown"
                and previous_execution.error_code == "MANUAL_READBACK_DEADLINE"
            )
            assert s.get(EntityCurrentState, "ad").status == "ADSET_PAUSED"
        print(
            json.dumps(
                {
                    "result": "PASS",
                    "enable_mock_gets": 6,
                    "adset_mock_gets": 6,
                    "adset_mock_posts": 1,
                    "enable_mock_posts": 1,
                    "repeat": "NO_RESEND",
                    "old_outcome": "UNKNOWN_PRESERVED",
                    "facts_unchanged": True,
                    "provider_requests": 0,
                    "advertising_write_requests": 0,
                }
            )
        )
    finally:
        if db:
            db.dispose()
        with admin.begin() as c:
            c.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        admin.dispose()


if __name__ == "__main__":
    main()
