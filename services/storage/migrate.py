"""Serialized upgrades; an already-current database is never upgraded again."""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from services.storage.database import make_engine
from services.storage.models import Base

logger = logging.getLogger(__name__)


def require_schema(connection: Connection) -> None:
    """Reject a stamped but incomplete database without repairing it implicitly."""
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in tables or not set(table.columns.keys()) <= {
            c["name"] for c in inspector.get_columns(table.name)
        }:
            raise RuntimeError("MIGRATION_SCHEMA_INCOMPLETE")


def migrate(engine: Engine, config: Config) -> str:
    """Upgrade a known revision once, under the same PostgreSQL transaction lock."""
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    if len(heads) != 1:
        raise RuntimeError("MIGRATION_SINGLE_HEAD_REQUIRED")
    known = {r.revision for r in scripts.walk_revisions()}
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("SET LOCAL lock_timeout = '30s'"))
            connection.execute(text("SELECT pg_advisory_xact_lock(7341200412)"))
        actual = MigrationContext.configure(connection).get_current_heads()
        if len(actual) > 1 or any(revision not in known for revision in actual):
            raise RuntimeError("MIGRATION_REVISION_NOT_IN_IMAGE")
        if actual == tuple(heads):
            require_schema(connection)
            return "ALREADY_CURRENT"
        config.attributes["connection"] = connection
        try:
            command.upgrade(config, heads[0])
        finally:
            config.attributes.pop("connection", None)
        if MigrationContext.configure(connection).get_current_heads() != tuple(heads):
            raise RuntimeError("MIGRATION_HEAD_MISMATCH")
        require_schema(connection)
        return "UPGRADED"


def main() -> int:
    """Run the migration container with sanitized fixed result codes."""
    logging.basicConfig(level=logging.INFO)
    engine = None
    try:
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        engine = make_engine()
        logger.info("Migration result: %s", migrate(engine, config))
        return 0
    except (CommandError, SQLAlchemyError, RuntimeError, OSError, ValueError):
        logger.error("MIGRATION_FAILED; inspect image revisions and database readiness")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
