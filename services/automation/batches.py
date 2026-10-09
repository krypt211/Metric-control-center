from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from services.actions.engine import ActionEngine, ActionRejected
from services.storage.models import BatchAction, BatchItem, EntityCurrentState, User
from .schema import BulkCommand


class BatchEngine:
    def __init__(self, actions: ActionEngine):
        self.actions, self.sessions = actions, actions.sessions

    def submit(self, workspace: str, actor_id: str, command: BulkCommand, key: str):
        if not key or len(key) > 128:
            raise ActionRejected("A valid idempotency key is required")
        payload = command.model_dump(mode="json")
        payload["entity_ids"] = sorted(payload["entity_ids"])
        try:
            with self.sessions.begin() as session:
                actor = session.get(User, actor_id)
                if not actor or actor.workspace_id != workspace or actor.role not in ("admin", "operator"):
                    raise ActionRejected("Operator has no permission")
                existing = session.scalar(select(BatchAction).where(
                    BatchAction.workspace_id == workspace, BatchAction.initiator_id == actor_id,
                    BatchAction.idempotency_key == key))
                if existing:
                    if existing.payload != payload:
                        raise ActionRejected("Batch key was already used for another command")
                    return existing.id
                batch = BatchAction(id=str(uuid4()), workspace_id=workspace, initiator_id=actor_id,
                    idempotency_key=key, created_at=self.actions.clock(), payload=payload)
                session.add(batch)
                session.flush()
                # Savepoints isolate one rejection while the batch and accepted
                # requests remain one transaction. No HTTP calls occur here.
                for entity_id in payload["entity_ids"]:
                    request_id, reason = None, None
                    try:
                        with session.begin_nested():
                            state = session.get(EntityCurrentState, entity_id)
                            action, value = command.operation.command(state.budget if state else None)
                            request_id = self.actions.enqueue_in_session(session, workspace, actor_id, entity_id,
                                action, value, f"batch:{batch.id}:{entity_id}",
                                context={"source": "web", "batch_id": batch.id,
                                         "reason": command.operation.model_dump(mode="json")})
                    except (ActionRejected, ValueError, IntegrityError) as error:
                        reason = "Another action for this entity is pending" if isinstance(error, IntegrityError) else str(error)
                    session.add(BatchItem(batch_id=batch.id, entity_id=entity_id, request_id=request_id,
                        status="queued" if request_id else "rejected", reason=reason))
                return batch.id
        except IntegrityError:
            with self.sessions() as session:
                existing = session.scalar(select(BatchAction).where(BatchAction.workspace_id == workspace,
                    BatchAction.initiator_id == actor_id, BatchAction.idempotency_key == key))
                if existing and existing.payload == payload:
                    return existing.id
            raise ActionRejected("Batch submission conflict") from None
