"""HTTP entry point. Commands enter a durable queue; no provider write keys."""

from contextlib import asynccontextmanager
from datetime import date
from functools import lru_cache
import os
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from services.analytics.dashboard import dashboard_today, summary
from services.analytics.table import Filters, filter_options, table_data
from services.storage.database import make_engine, sessions

@asynccontextmanager
async def lifespan(app):
    from backend.auth import validate_environment
    from backend.logging_config import configure
    validate_environment()
    configure()
    yield

app = FastAPI(title="Advertising Control Center", version="0.7.0", lifespan=lifespan)
from backend.health import local_read_only, router as health_router
app.include_router(health_router)


@app.middleware("http")
async def read_only_guard(request: Request, call_next):
    if local_read_only() and request.method not in ("GET", "HEAD", "OPTIONS") and not request.url.path.startswith(("/api/auth/", "/api/admin/", "/api/preferences/columns", "/api/economics/")):
        return JSONResponse({"detail": "LOCAL READ ONLY: changes are disabled"}, status_code=403)
    return await call_next(request)

from backend.action_api import router as action_router
app.include_router(action_router)
from backend.automation_api import router as automation_router
app.include_router(automation_router)
from backend.recommendation_api import router as recommendation_router
app.include_router(recommendation_router)
from backend.ai_api import router as ai_router
app.include_router(ai_router)


@app.get("/health/live")
async def liveness() -> dict[str, str]:
    # Liveness only; this does not claim database/API connectivity.
    return {"status": "ok", "stage": "foundation"}


@lru_cache
def database_sessions():
    return sessions(make_engine())


def database_session():
    try:
        factory = database_sessions()
        with factory() as session:
            yield session
    except (SQLAlchemyError, OSError, RuntimeError):
        raise HTTPException(503, "Database is unavailable or not migrated") from None


@app.get("/api/dashboard/today")
def today(level: Literal["campaign", "adset", "ad"] = "ad", session=Depends(database_session)):
    result = {**dashboard_today(session, os.environ.get("WORKSPACE_ID", "default"), level=level), "mode": "LOCAL READ ONLY" if local_read_only() else "STANDARD"}
    session.commit()
    return result


@app.get("/api/stats/summary")
def statistics(start: date, end: date, level: Literal["campaign", "adset", "ad"] = "ad", session=Depends(database_session)):
    if start > end:
        raise HTTPException(422, "start must not exceed end")
    result = {"groups": summary(session, os.environ.get("WORKSPACE_ID", "default"), start, end, level=level)}
    session.commit()
    return result


def filters(
    start: date, end: date, account: str | None = None, campaign: str | None = None,
    adset: str | None = None, ad: str | None = None, creative: str | None = None,
    status: str | None = None, buyer: str | None = None, offer: str | None = None,
    tracker_campaign: str | None = None, geo: str | None = None,
):
    return Filters(start, end, account, campaign, adset, ad, creative, status, buyer, offer, tracker_campaign, geo)


@app.get("/api/stats/table")
def table(
    level: Literal["account", "campaign", "adset", "ad", "creative"] = "account",
    selected: Filters = Depends(filters), offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500), sort_key: str | None = None, sort_direction: Literal["asc","desc"] = "asc", session=Depends(database_session),
):
    try:
        result = table_data(session, os.environ.get("WORKSPACE_ID", "default"), selected, level=level, offset=offset, limit=limit, sort_key=sort_key, sort_direction=sort_direction)
        session.commit()
        return result
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@app.get("/api/stats/filters")
def options(session=Depends(database_session)):
    result = filter_options(session, os.environ.get("WORKSPACE_ID", "default"))
    session.commit()
    return result

@app.get("/api/stats/optional")
def optional_read_statistics(start: date, end: date, kind: Literal["tracker", "creative"],
                             account: str | None = None, scope: Literal["account", "ad"] = "account", offset: int = Query(0,ge=0), limit: int = Query(100,ge=1,le=500), sort_key: str | None = None, sort_direction: Literal["asc","desc"] = "asc", session=Depends(database_session)):
    from services.analytics.optional import optional_statistics
    if start > end:
        raise HTTPException(422, "start must not exceed end")
    try:
        result = optional_statistics(session, os.environ.get("WORKSPACE_ID", "default"), start, end, kind, account, scope, offset=offset,limit=limit,sort_key=sort_key,sort_direction=sort_direction)
        session.commit()
        return result
    except ValueError as error:
        raise HTTPException(422,str(error)) from None


from backend.auth import router as auth_router, protect
app.include_router(auth_router)
app.middleware("http")(protect)

from fastapi.exceptions import RequestValidationError
@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # Pydantic errors can echo password inputs. Never serialize rejected payloads.
    return JSONResponse({"detail": "INVALID_REQUEST"}, status_code=422)

from backend.operations import router as operations_router
app.include_router(operations_router)

from backend.preferences_api import router as preferences_router
app.include_router(preferences_router)

from backend.provider_api import router as provider_router
app.include_router(provider_router)

from backend.economics_api import router as economics_router
app.include_router(economics_router)
