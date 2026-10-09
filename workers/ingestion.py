"""Smart Sync: one shared worker queue, persistent database quota and lease."""

import asyncio
from datetime import timedelta
from functools import lru_cache
import os
from zoneinfo import ZoneInfo

from celery import Celery
from celery.schedules import crontab

from services.metricflow.secrets import read_key_file
from services.storage.database import make_engine, sessions
from services.sync.engine import SyncEngine, utc_now
from services.sync.schema import InsightSchema

app = Celery("ingestion", broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"))
app.conf.update(
    task_default_queue="ingestion",
    accept_content=["json"], task_serializer="json", result_serializer="json",
    timezone=os.environ.get("SYNC_TIMEZONE", "Europe/Moscow"), enable_utc=True,
    task_ignore_result=True,
    beat_schedule={
        "today": {"task": "sync.insights", "schedule": crontab(minute="*/10"), "args": ["today"], "options": {"expires": 540}},
        "yesterday": {"task": "sync.insights", "schedule": crontab(minute=3), "args": ["yesterday"], "options": {"expires": 3300}},
        "last-seven-days": {"task": "sync.insights", "schedule": crontab(hour=4, minute=7), "args": ["last7"], "options": {"expires": 82800}},
        "actions": {"task": "actions.process", "schedule": 15.0, "options": {"queue": "actions", "expires": 14}},
        "breakdowns": {"task": "sync.insights", "schedule": crontab(hour=4, minute=17), "args": ["breakdowns"], "options": {"expires": 82800}},
        "rules": {"task": "rules.evaluate", "schedule": 60.0, "options": {"expires": 55}},
        "frequency": {"task": "sync.insights", "schedule": crontab(hour=4, minute=27), "args": ["frequency"], "options": {"expires": 82800}},
        "ai": {"task": "ai.process", "schedule": 15.0, "options": {"queue": "ai", "expires": 14}},
    },
)
if os.environ.get("ACTIONS_ENABLED", "false").lower() != "true":
    app.conf.beat_schedule.pop("actions", None)
if os.environ.get("AI_ENABLED", "false").lower() != "true":
    app.conf.beat_schedule.pop("ai", None)


@lru_cache
def factory():
    return sessions(make_engine())


def window(job: str):
    today = utc_now().astimezone(ZoneInfo(app.conf.timezone)).date()
    # ±1 day covers today's dates in other account timezones. Daily totals are
    # not incorrectly rebucketed into a timezone without hourly observations.
    if job == "today":
        return today - timedelta(days=1), today + timedelta(days=1)
    if job == "yesterday":
        return today - timedelta(days=2), today
    if job in ("last7", "breakdowns"):
        return today - timedelta(days=7), today + timedelta(days=1)
    if job == "frequency":
        # Covers up to 14 completed days in all account timezones.
        return today - timedelta(days=15), today
    raise ValueError("Unknown sync job")


@app.task(name="sync.insights", ignore_result=True)
def sync_insights(job: str = "today"):
    if os.environ.get("SYNC_ENABLED", "false").lower() != "true":
        return {"status": "disabled"}
    schema_variable = {"breakdowns": "METRICFLOW_BREAKDOWN_SCHEMA_FILE", "frequency": "METRICFLOW_FREQUENCY_SCHEMA_FILE"}.get(job, "METRICFLOW_SCHEMA_FILE")
    schema_path = os.environ.get(schema_variable)
    if not schema_path or not os.path.isfile(schema_path):
        return {"status": "schema_not_configured"}
    schema = InsightSchema.load(schema_path)
    if job == "frequency" and (schema.config.get("endpoint", "insights") != "insights" or
        schema.kind not in ("adset", "campaign") or "impressions" not in schema.paths or
        not {"frequency", "reach"}.intersection(schema.paths)):
        return {"status": "frequency_schema_not_configured"}
    from services.providers.manager import ProviderManager, ensure
    from services.providers.credentials import load
    from services.providers.models import ProviderConnection
    from services.providers.sync import metricflow_sync
    workspace=os.environ.get("WORKSPACE_ID", "default")
    with factory().begin() as session:
        ensure(session,workspace)
        connection=session.get(ProviderConnection,(workspace,"metricflow"))
        if not connection.enabled:return {"status":"disabled"}
        credentials=load(session,workspace,"metricflow") if connection.credential_source=="encrypted" else {"token":read_key_file(os.environ.get("METRICFLOW_READ_KEY_FILE"))}
    if job in ("today","yesterday","last7"):
        start,end=window(job)
        return asyncio.run(metricflow_sync(ProviderManager(factory(),workspace),job,start,end,schema))
    engine = SyncEngine(
        factory(), schema, credentials["token"],
        workspace=os.environ.get("WORKSPACE_ID", "default"),
        daily_budget=int(os.environ.get("SYNC_DAILY_BUDGET", "800")),
        max_pages=int(os.environ.get("SYNC_MAX_PAGES", "100")),
    )
    start, end = window(job)
    return asyncio.run(engine.run(job, start, end))


if os.environ.get("LOCAL_READ_ONLY", "false").lower() == "true":
    for job in ("actions", "rules", "ai"):
        app.conf.beat_schedule.pop(job, None)


# Register database-only automation alongside ingestion tasks.
import workers.rules  # noqa: E402,F401

import workers.providers  # noqa: E402,F401
app.conf.beat_schedule.update({
    "meta-today":{"task":"providers.meta","schedule":crontab(minute="*/10"),"args":["today"],"options":{"expires":540}},
    "meta-yesterday":{"task":"providers.meta","schedule":crontab(minute=5),"args":["yesterday"],"options":{"expires":3300}},
    "meta-reconciliation":{"task":"providers.meta","schedule":crontab(hour=4,minute=9),"args":["last7"],"options":{"expires":82800}},
    "provider-jobs":{"task":"providers.dispatch","schedule":30.0,"options":{"expires":25}},
})
