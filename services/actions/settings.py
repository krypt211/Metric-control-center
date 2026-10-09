from decimal import Decimal
import json
import os
from pathlib import Path

from .engine import ActionPolicy


def policy_from_environment() -> ActionPolicy:
    path = os.environ.get("ACTION_BUDGET_CONTRACT_FILE")
    contract = json.loads(Path(path).read_text(encoding="utf-8-sig")) if path and Path(path).is_file() else None
    return ActionPolicy(
        enabled=os.environ.get("LOCAL_READ_ONLY", "false").lower() != "true" and os.environ.get("ACTIONS_ENABLED", "false").lower() == "true",
        max_budget=Decimal(os.environ.get("ACTION_MAX_BUDGET", "10000")),
        max_change_percent=Decimal(os.environ.get("ACTION_MAX_CHANGE_PERCENT", "20")),
        daily_api_budget=int(os.environ.get("SYNC_DAILY_BUDGET", "800")),
        budget_contract=contract,
    )
