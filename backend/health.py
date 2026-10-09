"""Read-only readiness and synchronization diagnostics; never expose secrets."""
import os
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, select, text

from services.storage.models import Base, SyncRun

router = APIRouter()


def local_read_only():
    return os.environ.get("LOCAL_READ_ONLY", "false").lower() == "true"


def readiness(factory):
    result = {"status": "not_ready", "database": "UNAVAILABLE", "migrations": "UNVERIFIED", "schema": "UNVERIFIED", "redis": "NOT_CONFIGURED"}
    try:
        with factory() as session:
            session.execute(text("SELECT 1"))
            result["database"] = "OK"
            connection = session.connection()
            actual = set(MigrationContext.configure(connection).get_current_heads())
            expected = set(ScriptDirectory(str(Path(__file__).resolve().parents[1] / "migrations")).get_heads())
            result["migrations"] = "OK" if actual == expected else "PENDING"
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            complete = all(table.name in tables and set(table.columns.keys()) <= {c["name"] for c in inspector.get_columns(table.name)} for table in Base.metadata.sorted_tables)
            result["schema"] = "OK" if complete else "INCOMPLETE"
    except Exception:
        # Driver exceptions can contain a DSN/password. Return only fixed labels.
        pass
    broker = os.environ.get("CELERY_BROKER_URL")
    if broker:
        try:
            from redis import Redis
            client = Redis.from_url(broker, socket_connect_timeout=2, socket_timeout=2)
            try:
                result["redis"] = "OK" if client.ping() else "UNAVAILABLE"
            finally:
                client.close()
        except Exception:
            result["redis"] = "UNAVAILABLE"
    ready = all(result[k] == "OK" for k in ("database", "migrations", "schema")) and result["redis"] in ("OK", "NOT_CONFIGURED")
    result["status"] = "ready" if ready else "not_ready"
    return result


@router.get("/health/ready")
def ready():
    from backend.app import database_sessions
    try:
        result = readiness(database_sessions())
    except Exception:
        result = {"status": "not_ready", "database": "UNAVAILABLE", "migrations": "UNVERIFIED", "schema": "UNVERIFIED", "redis": "UNVERIFIED"}
    return JSONResponse(result, status_code=200 if result["status"] == "ready" else 503)


@router.get("/api/system/status")
def system_status():
    from backend.app import database_sessions
    result = {"mode": "LOCAL READ ONLY" if local_read_only() else "STANDARD", "sync_enabled": os.environ.get("SYNC_ENABLED", "false").lower() == "true", "actions_enabled": not local_read_only() and os.environ.get("ACTIONS_ENABLED", "false").lower() == "true", "schema_configured": bool(os.environ.get("METRICFLOW_SCHEMA_FILE") and Path(os.environ["METRICFLOW_SCHEMA_FILE"]).is_file()), "last_sync": None}
    try:
        with database_sessions()() as session:
            run = session.scalar(select(SyncRun).where(SyncRun.workspace_id == os.environ.get("WORKSPACE_ID", "default"), SyncRun.provider == "metricflow").order_by(SyncRun.started_at.desc()).limit(1))
            if run:
                result["last_sync"] = {"status": run.status, "job": run.job, "started_at": run.started_at.isoformat(), "finished_at": run.finished_at.isoformat() if run.finished_at else None, "rows": run.rows, "error_code": run.error_code}
        return result
    except Exception:
        return JSONResponse({**result, "database": "UNAVAILABLE"}, status_code=503)
