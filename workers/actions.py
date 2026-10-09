"""Dedicated action process polls the durable database queue."""

import asyncio
import os

from celery import Celery

from services.actions.engine import ActionEngine
from services.actions.factory import create_action_connector
from services.actions.settings import policy_from_environment
from services.storage.database import make_engine, sessions

app = Celery("actions", broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"))
app.conf.update(
    task_default_queue="actions",
    accept_content=["json"], task_serializer="json", result_serializer="json",
    timezone="UTC", enable_utc=True,
)


@app.task(name="actions.process", ignore_result=True)
def process():
    policy = policy_from_environment()
    if not policy.enabled:
        return {"status": "disabled"}
    db = make_engine()
    engine = ActionEngine(sessions(db), policy)
    async def execute():
        async with create_action_connector() as connector:
            await engine.execute_next(connector)
    try:
        engine.verify_pending()
        asyncio.run(execute())
    finally:
        db.dispose()
