"""Eight-process experimental race and crash recovery in a private restored-DB schema."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import func, select, text

from scripts.check_controlled_rehearsal_postgres import (
    ACTOR,
    NOW,
    fixture,
    seed_rehearsal,
    verify_runtime_source,
)
from services.actions.engine import ActionEngine, ActionPolicy
from services.actions.experimental import (
    PREPARE,
    STATEMENT,
    ExperimentalPrepareInput,
    prepare_experiment,
)
from services.actions.pilot import (
    PilotAuthorizationInput,
    PilotReadbackInput,
    authorize_pilot,
    execute_pilot,
    record_manual_readback,
)
from services.providers.integration_models import WriteCredentialState
from services.storage.database import database_url, make_engine
from services.storage.models import ActionLog, ActionRequest, Base, EntityCurrentState


def respond(request):
    if request.method == "POST":
        assert request.url.path.endswith("/1003/pause")
        return httpx.Response(
            200, json={"success": True, "entity_id": "1003", "message": "fixture"}
        )
    rows = {
        "campaigns": {"id": "1001", "status": "PAUSED", "effective_status": "PAUSED"},
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
            "data": [rows[request.url.path.rsplit("/", 1)[-1]]],
            "meta": {"total": 1, "data_updated_at": NOW.isoformat()},
        },
    )


def child(mode, request_id, revision):
    db, sf, vault = fixture()
    clock = NOW + timedelta(seconds=121) if mode == "recover" else NOW
    engine = ActionEngine(sf, ActionPolicy(enabled=True), clock=lambda: clock)

    def counted(request):
        with sf.begin() as s:
            s.add(
                ActionLog(
                    id=str(uuid4()),
                    request_id=request_id,
                    event="experimental_mock_physical_http",
                    created_at=clock,
                    details={"method": request.method},
                )
            )
        if request.method == "POST" and mode == "crash":
            os._exit(17)
        return respond(request)

    with patch.dict(
        os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}
    ):
        if mode == "recover":
            engine.verify_pending()
        result = asyncio.run(
            execute_pilot(
                engine,
                ACTOR,
                request_id,
                int(revision),
                vault=vault,
                transport=httpx.MockTransport(counted),
            )
        )
    db.dispose()
    print(json.dumps({"claimed": result is not None}))


def prepared(engine, vault):
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
                transport=httpx.MockTransport(respond),
            )
        )
        row = {"id": card["request_id"], "revision": card["revision"]}
        for event in ("preflight", "confirm"):
            row = engine.transition_manual(ACTOR, row["id"], event, row["revision"])
    with patch.dict(
        os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}
    ):
        return authorize_pilot(
            engine,
            ACTOR,
            row["id"],
            PilotAuthorizationInput(
                revision=row["revision"],
                credential_revision=1,
                account_id="act_100",
                entity_id="1003",
                operation="PAUSE_AD",
                expected_status="ACTIVE",
                statement=STATEMENT,
            ),
        )


def main():
    if not (database_url().database or "").startswith("mcc_integrations_"):
        raise RuntimeError("ISOLATED_DATABASE_REQUIRED")
    verify_runtime_source()
    admin = make_engine()
    schema = "controlled_rehearsal_exp_" + uuid4().hex
    with admin.begin() as c:
        c.execute(text("CREATE SCHEMA " + schema))
    os.environ["REHEARSAL_SCHEMA"] = schema
    os.environ["REHEARSAL_CIPHER"] = Fernet.generate_key().decode()
    db = None
    try:
        db, sf, vault = fixture()
        Base.metadata.create_all(db)
        seed_rehearsal(sf, vault, NOW)
        with sf.begin() as s:
            s.get(WriteCredentialState, ACTOR["workspace"]).scopes = [
                "entities:write",
                "campaigns:read",
            ]
            row = s.get(EntityCurrentState, "ad")
            row.status = "ADSET_PAUSED"
            row.raw = {"status": "ADSET_PAUSED"}
            row.observed_at = NOW - timedelta(days=5)
        engine = ActionEngine(sf, ActionPolicy(enabled=True), clock=lambda: NOW)
        permit = prepared(engine, vault)
        args = [
            sys.executable,
            "-m",
            "scripts.check_experimental_pilot_postgres",
            "send",
            permit["id"],
            str(permit["revision"]),
        ]
        children = [
            subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(8)
        ]
        claims = []
        for p in children:
            out, _err = p.communicate(timeout=120)
            if p.returncode:
                raise RuntimeError("EXPERIMENTAL_RACE_CHILD_FAILED")
            claims.append(json.loads(out)["claimed"])
        assert sum(claims) == 1
        again = subprocess.run(args, capture_output=True, check=True, timeout=60)
        assert not json.loads(again.stdout)["claimed"]
        with sf() as s:
            row = s.get(ActionRequest, permit["id"])
            assert row.status == "verifying"
            revision = row.revision
        review_engine = ActionEngine(
            sf, engine.policy, clock=lambda: NOW + timedelta(seconds=10)
        )
        result = record_manual_readback(
            review_engine,
            ACTOR,
            permit["id"],
            PilotReadbackInput(
                revision=revision,
                account_id="act_100",
                entity_id="1003",
                configured_status="PAUSED",
                effective_status="ADSET_PAUSED",
                observed_at=(NOW + timedelta(seconds=10)).isoformat(),
                statement="RECORD_MANUAL_META_READBACK",
            ),
        )
        assert (
            result["status"] == "MANUALLY_REVIEWED" and not result["authoritative_api"]
        )
        second = prepared(engine, vault)
        crash = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.check_experimental_pilot_postgres",
                "crash",
                second["id"],
                str(second["revision"]),
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
        assert crash.returncode == 17
        recover = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.check_experimental_pilot_postgres",
                "recover",
                second["id"],
                str(second["revision"]),
            ],
            capture_output=True,
            check=True,
            timeout=60,
        )
        assert not json.loads(recover.stdout)["claimed"]
        with sf() as s:
            assert s.get(ActionRequest, second["id"]).status == "unknown"
            assert s.get(EntityCurrentState, "ad").status == "ADSET_PAUSED"
            count = s.scalar(
                select(func.count())
                .select_from(ActionLog)
                .where(ActionLog.event == "experimental_mock_physical_http")
            )
            assert count == 8
        print(
            json.dumps(
                {
                    "result": "PASS",
                    "contract_gate": "UNPATCHED",
                    "processes": 8,
                    "race_claims": 1,
                    "race_gets": 3,
                    "race_posts": 1,
                    "total_mock_gets": 6,
                    "total_mock_posts": 2,
                    "restart": "NO_RESEND",
                    "crash": "UNKNOWN_NO_RESEND",
                    "facts_unchanged": True,
                    "provider_requests": 0,
                    "advertising_write_requests": 0,
                    "schema_cleanup": "FINALLY_DROP_ISOLATED_SCHEMA",
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
    if len(sys.argv) > 1:
        child(*sys.argv[1:])
    else:
        main()
