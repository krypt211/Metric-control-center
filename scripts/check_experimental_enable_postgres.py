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
        print(
            json.dumps(
                {
                    "result": "PASS",
                    "enable_mock_gets": 6,
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
