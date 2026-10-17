"""Mock readback race/crash acceptance in private schemas of a restored DB."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import httpx
from check_controlled_rehearsal_postgres import (
    ACTOR,
    NOW,
    TOKEN,
    fixture,
    prepared,
    seed_rehearsal,
)
from cryptography.fernet import Fernet
from sqlalchemy import func, select, text

from services.actions.engine import ActionEngine, ActionPolicy
from services.actions.safety import ActionSafetyGate
from services.storage.database import database_url, make_engine
from services.storage.models import ActionExecution, ActionLog, ActionRequest, Base

READ_TOKEN = "mfk_fixture_postgres_readback_read"


def mocked_gate():
    return patch.object(ActionSafetyGate, "require_verified_contract")


def child(mode, request_id):
    db, sf, _vault = fixture()
    now = NOW + timedelta(seconds=601 if mode == "recover" else 10)
    engine = ActionEngine(sf, ActionPolicy(enabled=True), clock=lambda: now)

    def handler(request):
        assert request.method == "GET" and request.url.path == "/api/v1/insights"
        assert request.headers["authorization"] == "Bearer " + READ_TOKEN
        assert request.url.params["ad_account_ids"] == "act_100"
        with sf.begin() as session:
            session.add(
                ActionLog(
                    id=str(uuid4()),
                    request_id=request_id,
                    event="mock_physical_readback_get",
                    created_at=now,
                    details={"mode": "MOCK_ONLY"},
                )
            )
        if mode == "crash":
            os._exit(17)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "ad_account_id": "act_100",
                        "ad_id": "1003",
                        "adset_id": "1002",
                        "campaign_id": "1001",
                        "date": NOW.date().isoformat(),
                        "status": "PAUSED",
                        "effective_status": "PAUSED",
                    }
                ],
                "meta": {"data_updated_at": now.isoformat()},
                "pagination": {"has_more": False, "cursor": None},
            },
        )

    if mode == "recover":
        engine.verify_pending()
    with (
        patch.dict(os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}),
        mocked_gate(),
    ):
        result = asyncio.run(
            engine.readback_rehearsal(
                ACTOR,
                request_id,
                read_key=READ_TOKEN,
                transport=httpx.MockTransport(handler),
            )
        )
    db.dispose()
    print(json.dumps({"claimed": result is not None}))


def case(admin, mode):
    schema = "controlled_rehearsal_readback_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text("CREATE SCHEMA " + schema))
    os.environ["REHEARSAL_SCHEMA"] = schema
    os.environ["REHEARSAL_CIPHER"] = Fernet.generate_key().decode()
    db, sf, vault = fixture()
    Base.metadata.create_all(db)
    seed_rehearsal(sf, vault, NOW)
    clock = [NOW]
    engine = ActionEngine(sf, ActionPolicy(enabled=True), clock=lambda: clock[0])
    permit = prepared(engine)
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            assert request.headers["authorization"] == "Bearer " + TOKEN
            return httpx.Response(
                202,
                json={
                    "success": True,
                    "entity_id": "1003",
                    "message": "mock",
                    "job_id": 41,
                },
            )
        assert request.url.path == "/api/v1/jobs/41"
        return httpx.Response(
            200,
            json={
                "job_id": 41,
                "action_type": "status",
                "status": "success",
                "total": 1,
                "done": 1,
                "succeeded": 1,
                "failed": 0,
                "results": [{"entity_id": "1003", "success": True}],
                "created_at": NOW.isoformat(),
                "meta": {},
            },
        )

    with (
        patch.dict(os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}),
        mocked_gate(),
    ):
        asyncio.run(
            engine.execute_rehearsal(
                ACTOR,
                permit["id"],
                permit["revision"],
                vault=vault,
                transport=httpx.MockTransport(handler),
            )
        )
        clock[0] += timedelta(seconds=10)
        asyncio.run(
            engine.observe_rehearsal_job(
                ACTOR, permit["id"], vault=vault, transport=httpx.MockTransport(handler)
            )
        )
    assert calls == ["POST", "GET"]
    args = [sys.executable, __file__, mode, permit["id"]]
    if mode == "race":
        processes = [
            subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(8)
        ]
        claims = []
        for process in processes:
            output, errors = process.communicate(timeout=90)
            if process.returncode:
                diagnostic = errors.decode("utf-8", errors="replace")
                print(
                    json.dumps(
                        {
                            "exception_types": re.findall(
                                r"^(\w+(?:Error|Exception)):", diagnostic, re.MULTILINE
                            ),
                            "error_kinds": [
                                v
                                for v in (
                                    "DeadlockDetected",
                                    "UndefinedTable",
                                    "UndefinedColumn",
                                    "InvalidTextRepresentation",
                                    "ForeignKeyViolation",
                                    "UniqueViolation",
                                    "ProgrammingError",
                                    "OperationalError",
                                    "DataError",
                                    "IntegrityError",
                                )
                                if v in diagnostic
                            ],
                            "frames": re.findall(
                                r'File "([^"\n]+\.py)", line (\d+)', diagnostic
                            )[:12],
                        }
                    ),
                    flush=True,
                )
                raise RuntimeError("READBACK_CHILD_FAILED")
            claims.append(json.loads(output)["claimed"])
        assert sum(claims) == 1
    else:
        crashed = subprocess.run(args, capture_output=True, timeout=90, check=False)
        assert crashed.returncode == 17
        for next_mode in ("repeat", "recover"):
            result = subprocess.run(
                [sys.executable, __file__, next_mode, permit["id"]],
                capture_output=True,
                timeout=90,
                check=False,
            )
            assert result.returncode == 0 and not json.loads(result.stdout)["claimed"]
    with sf() as session:
        row = session.get(ActionRequest, permit["id"])
        evidence = row.provenance["controlled"]["readback"]
        assert row.status == "unknown" and not evidence["authoritative"]
        assert evidence["attempts"] == 1
        expected = (
            "REPORTED_STATUS_MATCH_NEEDS_AUTHORITY"
            if mode == "race"
            else "OUTCOME_UNKNOWN"
        )
        assert evidence["outcome"] == expected
        assert session.scalar(select(func.count()).select_from(ActionExecution)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(ActionLog)
                .where(ActionLog.event == "mock_physical_readback_get")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ActionLog)
                .where(ActionLog.event == "verified")
            )
            == 0
        )
    db.dispose()
    return {
        "schema": schema,
        "case": mode,
        "physical_mock_gets": 1,
        "verified": 0,
        "outcome": expected,
    }


def main():
    if not hasattr(ActionEngine, "readback_rehearsal"):
        raise RuntimeError("CURRENT_SOURCE_REQUIRED_SET_PYTHONPATH")
    if not (database_url().database or "").startswith("mcc_integrations_"):
        raise RuntimeError("ISOLATED_DATABASE_REQUIRED")
    admin = make_engine()
    with admin.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "0016_smart_control"
        )
    results = [case(admin, mode) for mode in ("race", "crash")]
    admin.dispose()
    print(
        json.dumps(
            {
                "database": database_url().database,
                "concurrent_processes": 8,
                "results": results,
                "advertising_live_requests": 0,
            }
        )
    )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        child(sys.argv[1], sys.argv[2])
    else:
        main()
