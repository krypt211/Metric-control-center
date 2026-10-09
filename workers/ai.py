"""Separate queue/credentials for inference. Advertising writes are absent."""
import asyncio
import os

from services.actions.engine import ActionEngine
from services.actions.settings import policy_from_environment
from services.ai.engine import CopilotEngine
from services.ai.provider import provider_from_environment
from workers.ingestion import app, factory


@app.task(name="ai.process", ignore_result=True)
def process():
    if os.environ.get("AI_ENABLED", "false").lower() != "true":
        return {"status": "disabled"}
    try:
        provider = provider_from_environment()
    except (ValueError, RuntimeError, OSError):
        return {"status": "provider_not_configured"}
    core = CopilotEngine(ActionEngine(factory(), policy_from_environment()))
    from services.ai.agent import AgentService
    async def run_one():
        message = await AgentService(core).process_next(provider)
        return {"message_id": message} if message else {"decision_id": await core.process_next(provider)}
    return asyncio.run(run_one())
