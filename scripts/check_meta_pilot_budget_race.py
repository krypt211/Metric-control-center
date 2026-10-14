"""Process race for durable attempt reservation; no HTTP client or transport."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select, text

from services.meta.pilot_models import MetaPilotSession
from services.providers.integration_models import MetaRequestAttempt
from services.storage.database import database_url, make_engine, sessions
from services.storage.models import Base


def child():
    from services.meta.telemetry import MetaRequestMeter
    from services.providers.contracts import ProviderError

    schema = os.environ["PILOT_TEST_SCHEMA"]
    engine = make_engine(
        database_url().set(query={"options": "-csearch_path=" + schema})
    )
    meter = MetaRequestMeter(
        sessions(engine),
        "default",
        "123",
        pilot_id=os.environ["META_PILOT_AUTHORIZED_SESSION_ID"],
        interval=0,
    )
    meter.interval = 0  # Isolated schema, no HTTP transport.
    reserved = denied = 0
    for _ in range(4):
        import asyncio
        ticket = asyncio.run(meter.acquire())
        try:
            meter.begin_attempt("debug_token", 1, 1, None, ticket=ticket)
            reserved += 1
        except ProviderError as error:
            if error.code != "META_PILOT_ATTEMPT_LIMIT":
                raise
            denied += 1
        finally:
            meter.release(ticket)
    print(json.dumps({"reserved": reserved, "denied": denied}))


def main():
    if not os.environ.get("POSTGRES_DB", "").startswith("mcc_integrations_"):
        raise RuntimeError("ISOLATED_DATABASE_REQUIRED")
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tests"))
    from test_meta_pilot import PilotTests

    fixture = PilotTests()
    admin = make_engine()
    schema = "mcc_pilot_race_" + uuid4().hex
    with admin.begin() as c:
        c.execute(text("CREATE SCHEMA " + schema))

    def setup(f):
        f.directory = tempfile.TemporaryDirectory()
        f.db = make_engine(
            database_url().set(query={"options": "-csearch_path=" + schema})
        )
        Base.metadata.create_all(f.db)
        f.sessions = sessions(f.db)

    from test_sync import StorageFixture

    StorageFixture.setUp = setup
    fixture.setUp()
    try:
        from services.meta import jobs

        identifier = fixture.prepare()
        job = fixture.start(identifier)
        with fixture.sessions.begin() as s:
            jobs.claim(s, "default", job)
        env = os.environ.copy()
        env["PILOT_TEST_SCHEMA"] = schema
        processes = [
            subprocess.Popen(
                [sys.executable, "-m", "scripts.check_meta_pilot_budget_race", "child"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(8)
        ]
        results = []
        for process in processes:
            out, _ = process.communicate(timeout=60)
            if process.returncode:
                raise RuntimeError("PILOT_BUDGET_PROCESS_FAILED")
            results.append(json.loads(out))
        with fixture.sessions() as s:
            used = s.get(MetaPilotSession, identifier).used_attempts
            logged = s.scalar(select(func.count()).select_from(MetaRequestAttempt))
        assert used == logged == 20
        assert sum(r["reserved"] for r in results) == 20
        assert sum(r["denied"] for r in results) == 12
        print(
            "META_PILOT_BUDGET_RACE="
            + json.dumps(
                {
                    "processes": 8,
                    "reserved": used,
                    "logged": logged,
                    "denied": 12,
                    "real_http": 0,
                    "retained_schema": schema,
                }
            )
        )
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    child() if len(sys.argv) > 1 and sys.argv[1] == "child" else main()
