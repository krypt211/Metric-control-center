"""Shared persistent kill switch; ingestion never depends on this gate."""
from uuid import uuid4
from sqlalchemy import select, update

from services.actions.engine import ActionRejected, log
from services.storage.models import AutomationControl, AutomationEvent, ActionRequest, User
from services.storage.repository import insert_for
from services.sync.engine import utc_now

SOURCES = {"ai", "rule", "agent"}


def state(session, workspace):
    row = session.get(AutomationControl, workspace)
    return {"stopped": row.stopped, "generation": row.generation} if row else {"stopped": False, "generation": 0}


def lock_control(session, workspace, now):
    session.execute(insert_for(session, AutomationControl.__table__).values(workspace_id=workspace,
        stopped=False, generation=0, updated_at=now).on_conflict_do_nothing(index_elements=["workspace_id"]))
    return session.scalar(select(AutomationControl).where(AutomationControl.workspace_id == workspace).with_for_update())


def guard(session, workspace, now, generation=None):
    row = lock_control(session, workspace, now)
    if row.stopped:
        raise ActionRejected("Emergency Stop: AI and rule actions are disabled")
    if generation is not None and generation != row.generation:
        raise ActionRejected("Automation was stopped after this proposal; create a new one")
    return row.generation


def change(sessions, workspace, actor_id, stopped, *, generation=None, channel="web", clock=utc_now):
    now = clock()
    with sessions.begin() as session:
        actor = session.get(User, actor_id)
        if not actor or actor.workspace_id != workspace or actor.role not in ("admin", "operator"):
            raise ActionRejected("Operator has no permission")
        session.execute(insert_for(session, AutomationControl.__table__).values(workspace_id=workspace,
            stopped=False, generation=0, updated_at=now).on_conflict_do_nothing(index_elements=["workspace_id"]))
        row = session.scalar(select(AutomationControl).where(AutomationControl.workspace_id == workspace).with_for_update())
        if not stopped and (generation is None or row.generation != generation):
            raise ActionRejected("Automation state changed; reload before resuming")
        if row.stopped != stopped:
            # UPDATE is also a fence for SQLite. Never silently resume a new stop.
            updated = session.execute(update(AutomationControl).where(AutomationControl.workspace_id == workspace,
                AutomationControl.generation == row.generation, AutomationControl.stopped == row.stopped).values(
                    stopped=stopped, generation=row.generation+1, updated_at=now))
            if updated.rowcount != 1:
                raise ActionRejected("Automation state changed concurrently")
            session.add(AutomationEvent(id=str(uuid4()), workspace_id=workspace, actor_id=actor_id, created_at=now,
                payload={"event": "emergency_stop" if stopped else "automation_resume", "channel": channel, "generation": row.generation}))
        if stopped:
            queued = session.scalars(select(ActionRequest).where(ActionRequest.workspace_id == workspace,
                ActionRequest.status == "queued").with_for_update()).all()
            for request in queued:
                if request.provenance.get("source") in SOURCES:
                    request.status = "rejected"
                    log(session, request.id, "emergency_stop", now, actor_id=actor_id, channel=channel)
        return state(session, workspace)
