"""Verify the global Meta permit across processes in an isolated PostgreSQL schema."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import func, select, text

from services.meta.telemetry import MetaRequestMeter
from services.providers.contracts import ProviderError
from services.providers.integration_models import MetaRateState, MetaRequestAttempt
from services.storage.database import database_url, make_engine, sessions
from services.storage.models import Base


def child() -> None:
    engine = make_engine(
        database_url().set(
            query={"options": "-csearch_path=" + os.environ["META_RATE_TEST_SCHEMA"]}
        )
    )
    meter = MetaRequestMeter(
        sessions(engine), str(os.getpid()), str(os.getpid()), interval=0
    )
    ticket = None
    try:
        ticket = asyncio.run(meter.acquire())
        meter.begin_attempt("debug_token", 1, 1, None, ticket=ticket)
        print("RESERVED")
    except ProviderError as error:
        assert error.code == "META_PACING_WAIT", error.code
        print("DENIED")
    finally:
        if ticket:
            meter.release(ticket)
        engine.dispose()


def main() -> None:
    if not str(database_url().database).startswith("mcc_integrations_"):
        raise RuntimeError("ISOLATED_DATABASE_REQUIRED")
    schema = "meta_global_" + uuid4().hex
    admin = make_engine()
    with admin.begin() as c:
        c.execute(text("CREATE SCHEMA " + schema))
    engine = make_engine(
        database_url().set(query={"options": "-csearch_path=" + schema})
    )
    Base.metadata.create_all(engine)
    env = {**os.environ, "META_RATE_TEST_SCHEMA": schema}
    children = [
        subprocess.Popen(
            [sys.executable, "-m", "scripts.check_meta_global_limit_postgres", "child"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(8)
    ]
    outcomes = []
    for process in children:
        out, _ = process.communicate(timeout=120)
        assert process.returncode == 0, "RATE_LIMIT_CHILD_FAILED"
        outcomes.append(out.decode().strip())
    assert outcomes.count("RESERVED") == 1 and outcomes.count("DENIED") == 7
    # A completely new process must still observe the persisted permit.
    restarted = subprocess.run(
        [sys.executable, "-m", "scripts.check_meta_global_limit_postgres", "child"],
        env=env,
        capture_output=True,
        check=True,
    )
    assert restarted.stdout.decode().strip() == "DENIED"
    with sessions(engine)() as s:
        assert s.scalar(select(func.count()).select_from(MetaRequestAttempt)) == 1
        state = s.get(MetaRateState, "meta-global")
        assert (state.next_start - state.updated_at).total_seconds() == 1800
        assert state.owner is None
    print(
        json.dumps(
            {
                "processes": 8,
                "reserved": 1,
                "denied": 7,
                "restart": "DENIED",
                "interval_seconds": 1800,
                "http_requests": 0,
                "retained_schema": schema,
            }
        )
    )


if __name__ == "__main__":
    child() if len(sys.argv) > 1 else main()
