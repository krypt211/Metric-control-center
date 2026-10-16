"""Legacy unbound dispatch stays blocked; controlled execution is not scheduled."""

import os

from celery import Celery

from services.actions.settings import policy_from_environment

app = Celery(
    "actions", broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
)
app.conf.update(
    task_default_queue="actions",
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)


@app.task(name="actions.process", ignore_result=True)
def process():
    policy = policy_from_environment()
    if not policy.enabled:
        return {"status": "disabled"}
    # No unbound legacy queue dispatch. A future LIVE dispatcher requires an
    # accepted provider contract and an explicitly authorized single-AD binding.
    from services.actions.safety import ActionSafetyGate
    from services.providers.contracts import WriteDisabled

    try:
        ActionSafetyGate.require_write()
    except WriteDisabled as error:
        return {"status": "blocked", "reason": error.code}
    return {"status": "blocked", "reason": "CONTROLLED_BINDING_REQUIRED"}
