import os

from services.actions.engine import ActionEngine
from services.actions.settings import policy_from_environment
from services.automation.rules import RuleEngine
from workers.ingestion import app, factory


@app.task(name="rules.evaluate", ignore_result=True)
def evaluate_rules():
    if os.environ.get("LOCAL_READ_ONLY", "false").lower() == "true":
        return {"status": "disabled_read_only"}
    # No HTTP connector or MetricFlow key is passed to this engine.
    return RuleEngine(ActionEngine(factory(), policy_from_environment())).evaluate_due(
        os.environ.get("WORKSPACE_ID", "default"))
