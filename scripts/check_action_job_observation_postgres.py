"""Eight-process mock GET race and abrupt-death recovery in an isolated PostgreSQL schema."""

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


def child(mode: str, request_id: str) -> None:
    db, sf, vault = fixture()
    seconds = 601 if mode == "recover" else 20 if mode in ("crash", "repeat") else 10
    now = NOW + timedelta(seconds=seconds)
    engine = ActionEngine(sf, ActionPolicy(enabled=True), clock=lambda: now)

    def handler(request):
        assert request.method == "GET" and request.url.path == "/api/v1/jobs/41"
        assert request.headers["authorization"] == "Bearer " + TOKEN
        with sf.begin() as session:
            session.add(
                ActionLog(
                    id=str(uuid4()),
                    request_id=request_id,
                    event="mock_physical_job_get",
                    created_at=now,
                    details={"mode": "MOCK_ONLY"},
                )
            )
        if mode == "crash":
            os._exit(17)
        return httpx.Response(
            200,
            json={
                "job_id": 41,
                "action_type": "status",
                "status": "pending",
                "total": 1,
                "done": 0,
                "succeeded": 0,
                "failed": 0,
                "results": None,
                "created_at": NOW.isoformat(),
                "meta": {},
            },
        )

    if mode == "recover":
        engine.verify_pending()
    with (
        patch.dict(os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}),
        patch.object(ActionSafetyGate, "require_verified_contract"),
    ):
        result = asyncio.run(
            engine.observe_rehearsal_job(
                ACTOR, request_id, vault=vault, transport=httpx.MockTransport(handler)
            )
        )
    db.dispose()
    print(json.dumps({"claimed": result is not None}))


def main() -> None:
    if not hasattr(ActionEngine, "observe_rehearsal_job"):
        raise RuntimeError("CURRENT_SOURCE_REQUIRED_SET_PYTHONPATH")
    if not (database_url().database or "").startswith("mcc_integrations_"):
        raise RuntimeError("ISOLATED_DATABASE_REQUIRED")
    admin = make_engine()
    schema = "controlled_rehearsal_jobs_" + uuid4().hex
    with admin.begin() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "0016_smart_control"
        )
        connection.execute(text("CREATE SCHEMA " + schema))
    os.environ["REHEARSAL_SCHEMA"] = schema
    os.environ["REHEARSAL_CIPHER"] = Fernet.generate_key().decode()
    db, sf, vault = fixture()
    Base.metadata.create_all(db)
    seed_rehearsal(sf, vault, NOW)
    engine = ActionEngine(sf, ActionPolicy(enabled=True), clock=lambda: NOW)
    permit = prepared(engine)
    posts = []

    def post_handler(request):
        posts.append(request)
        assert (
            request.method == "POST"
            and request.url.path == "/api/v1/entities/1003/pause"
        )
        return httpx.Response(
            202,
            json={
                "success": True,
                "entity_id": "1003",
                "message": "mock only",
                "job_id": 41,
            },
        )

    with (
        patch.dict(os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}),
        patch.object(ActionSafetyGate, "require_verified_contract"),
    ):
        asyncio.run(
            engine.execute_rehearsal(
                ACTOR,
                permit["id"],
                permit["revision"],
                vault=vault,
                transport=httpx.MockTransport(post_handler),
            )
        )
    args = [sys.executable, __file__, "observe", permit["id"]]
    processes = [
        subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(8)
    ]
    results = []
    for process in processes:
        out, _err = process.communicate(timeout=90)
        if process.returncode:
            diagnostic = _err.decode("utf-8", errors="replace")
            print(
                json.dumps(
                    {
                        "attribute_error": re.findall(
                            r"AttributeError: ([^\n]+)", diagnostic
                        ),
                        "child_exception_types": re.findall(
                            r"^(\w+(?:Error|Exception)):", diagnostic, re.MULTILINE
                        ),
                        "child_frames": re.findall(
                            r'File "([^"\n]+\.py)", line (\d+)', diagnostic
                        )[-5:],
                    }
                ),
                flush=True,
            )
            raise RuntimeError("MOCK_OBSERVER_CHILD_FAILED")
        results.append(json.loads(out))
    assert sum(row["claimed"] for row in results) == 1
    with sf() as session:
        row = session.get(ActionRequest, permit["id"])
        assert row.provenance["controlled"]["observation"]["attempts"] == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(ActionLog)
                .where(ActionLog.event == "mock_physical_job_get")
            )
            == 1
        )
    crash = subprocess.run(
        [sys.executable, __file__, "crash", permit["id"]],
        capture_output=True,
        timeout=90,
        check=False,
    )
    assert crash.returncode == 17
    for mode in ("repeat", "recover"):
        repeated = subprocess.run(
            [sys.executable, __file__, mode, permit["id"]],
            capture_output=True,
            timeout=90,
            check=False,
        )
        assert repeated.returncode == 0 and not json.loads(repeated.stdout)["claimed"]
    with sf() as session:
        row = session.get(ActionRequest, permit["id"])
        assert row.status == "unknown"
        assert row.provenance["controlled"]["attempts"] == 1
        assert row.provenance["controlled"]["observation"]["attempts"] == 2
        assert session.scalar(select(func.count()).select_from(ActionExecution)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(ActionLog)
                .where(ActionLog.event == "mock_physical_job_get")
            )
            == 2
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ActionLog)
                .where(ActionLog.event == "verified")
            )
            == 0
        )
    assert len(posts) == 1
    db.dispose()
    admin.dispose()
    print(
        json.dumps(
            {
                "database": database_url().database,
                "schema": schema,
                "concurrent_processes": 8,
                "race_claims": 1,
                "race_gets": 1,
                "mock_posts": 1,
                "total_mock_gets": 2,
                "abrupt_exit": 17,
                "recovery": "UNKNOWN_NO_RESEND",
                "verified_events": 0,
            }
        )
    )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        child(sys.argv[1], sys.argv[2])
    else:
        main()
