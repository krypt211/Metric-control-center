"""Mock-only pilot suite in retained schemas of an isolated restored PostgreSQL DB."""

import json
import os
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
        raise RuntimeError("ISOLATED_DATABASE_REQUIRED")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from test_sync import StorageFixture

    admin = make_engine()
    schemas = []

    def setup(fixture):
        fixture.directory = tempfile.TemporaryDirectory()
        schema = "mcc_pilot_test_" + uuid4().hex
        with admin.begin() as c:
            c.execute(text("CREATE SCHEMA " + schema))
        schemas.append(schema)
        fixture.db = make_engine(
            database_url().set(query={"options": "-csearch_path=" + schema})
        )
        Base.metadata.create_all(fixture.db)
        fixture.sessions = sessions(fixture.db)

    StorageFixture.setUp = setup
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        ["test_meta_pilot", "test_meta_pilot_api"]
    )
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(
        "META_PILOT_PG_REPORT="
        + json.dumps(
            {
                "tests": result.testsRun,
                "passed": result.wasSuccessful(),
                "retained_schemas": schemas,
                "transport": "MockTransport",
            }
        )
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
