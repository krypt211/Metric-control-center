"""Run mock-only lifecycle scenarios and process dedup in a restored PostgreSQL DB."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from services.storage.database import database_url, make_engine, sessions
from services.storage.models import Base


def main():
    if not os.environ.get("POSTGRES_DB", "").startswith("mcc_integrations_"):
        raise RuntimeError("ISOLATED_RESTORED_DATABASE_REQUIRED")
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "tests"))
    from test_sync import StorageFixture

    admin = make_engine()
    schemas = []

    def setup(fixture):
        fixture.directory = tempfile.TemporaryDirectory()
        schema = "mcc_meta_test_" + uuid4().hex
        with admin.begin() as connection:
            connection.execute(text("CREATE SCHEMA " + schema))
        schemas.append(schema)
        fixture.db = make_engine(
            database_url().set(query={"options": "-csearch_path=" + schema})
        )
        Base.metadata.create_all(fixture.db)
        fixture.sessions = sessions(fixture.db)

    StorageFixture.setUp = setup
    os.environ["META_LIFECYCLE_TEST_EVIDENCE"] = "/tmp/meta-lifecycle-pg-attempts.json"
    import test_meta_job_lifecycle

    only = os.environ.get("PG_LIFECYCLE_ONLY")
    suite = (
        unittest.defaultTestLoader.loadTestsFromNames(
            [
                "test_meta_job_lifecycle.LifecycleTests." + name
                for name in only.split(",")
            ]
        )
        if only
        else unittest.defaultTestLoader.loadTestsFromTestCase(
            test_meta_job_lifecycle.LifecycleTests
        )
    )
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        return 1
    schema = schemas[-1]
    # A new schema seed avoids coupling process races to the final fixture's state.
    schema = "mcc_meta_race_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text("CREATE SCHEMA " + schema))
    os.environ["PG_META_RACE_SCHEMA"] = schema
    seed = make_engine(database_url().set(query={"options": "-csearch_path=" + schema}))
    Base.metadata.create_all(seed)
    from services.providers.models import ProviderConnection
    from services.storage.models import AdAccount
    from services.sync.engine import utc_now

    with sessions(seed).begin() as session:
        session.add(
            AdAccount(
                id="fixture-account",
                workspace_id="race",
                provider="meta",
                external_id="act_101",
                name="Fixture",
                currency="USD",
                timezone="UTC",
                observed_at=utc_now(),
            )
        )
        session.add(
            ProviderConnection(
                workspace_id="race",
                provider="meta",
                enabled=True,
                revision=1,
                credential_source="encrypted",
                config={"sync_account_ids": ["fixture-account"], "app_id": "9914000"},
                status="healthy",
                permissions={},
                capabilities={},
                quota={},
                updated_at=utc_now(),
            )
        )
    child = """import os,json
from datetime import date
from services.storage.database import database_url,make_engine,sessions
from services.meta.jobs import enqueue
engine=make_engine(database_url().set(query={'options':'-csearch_path='+os.environ['PG_META_RACE_SCHEMA']}))
with sessions(engine).begin() as s:
 j,new=enqueue(s,'race','manual',date(2026,10,13),date(2026,10,13),refresh='same-process-race-slot')
 print(json.dumps({'id':j.id,'created':new}))
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", child],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(8)
    ]
    results = []
    for process in children:
        out, _err = process.communicate(timeout=60)
        if process.returncode:
            raise RuntimeError("PG_DEDUP_PROCESS_FAILED")
        results.append(json.loads(out))
    assert (
        len({r["id"] for r in results}) == 1 and sum(r["created"] for r in results) == 1
    )
    from services.meta import jobs

    factory = sessions(seed)
    from datetime import date

    with factory.begin() as session:
        jobs.cancel(session, "race", results[0]["id"])
        race, _ = jobs.enqueue(
            session,
            "race",
            "manual",
            date(2026, 10, 13),
            date(2026, 10, 13),
            refresh="claim-cancel-race",
        )
    child2 = """import os,json,sys
from services.storage.database import database_url,make_engine,sessions
from services.meta import jobs
f=sessions(make_engine(database_url().set(query={'options':'-csearch_path='+os.environ['PG_META_RACE_SCHEMA']})))
with f.begin() as s:
 if sys.argv[1]=='claim':result={'owner':jobs.claim(s,'race',sys.argv[2])}
 else:jobs.cancel(s,'race',sys.argv[2]);result={'cancel_requested':True}
print(json.dumps(result))
"""
    racers = [
        subprocess.Popen(
            [sys.executable, "-c", child2, operation, race.id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for operation in ("claim", "cancel")
    ]
    outcomes = []
    for process in racers:
        out, _err = process.communicate(timeout=60)
        if process.returncode:
            raise RuntimeError("PG_CANCEL_RACE_FAILED")
        outcomes.append(json.loads(out))
    owner = outcomes[0].get("owner")
    if owner:
        from services.providers.contracts import ProviderError

        try:
            jobs.checkpoint(factory, "race", race.id, owner)
        except ProviderError:
            pass
        else:
            raise RuntimeError("CANCELLED_OWNER_MUST_STOP")
    from services.providers.models import ProviderJob

    with factory() as session:
        assert session.get(ProviderJob, race.id).status == "cancelled"
    report = {
        "scenarios": "PASS",
        "attempts": json.loads(
            Path("/tmp/meta-lifecycle-pg-attempts.json").read_text()
        ),
        "cross_process_contenders": 8,
        "cross_process_created": 1,
        "cross_process_deduplicated": 7,
        "cross_process_http_attempts": 0,
        "claim_cancel_process_race": "PASS",
        "claim_cancel_http_attempts": 0,
        "schemas_retained": len(schemas) + 1,
    }
    print("META_LIFECYCLE_PG_REPORT=" + json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
