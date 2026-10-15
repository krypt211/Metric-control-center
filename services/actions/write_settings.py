"""Independent WRITE lifecycle; metadata cannot authorize advertising execution."""

from __future__ import annotations

import hashlib
from uuid import uuid4

from fastapi import HTTPException

from services.meta.telemetry import lock
from services.metricflow.writer import ENTITY_WRITE_SCOPE
from services.providers.integration_models import (
    WriteCredentialAudit,
    WriteCredentialState,
)
from services.sync.engine import utc_now


def metadata(session, workspace):
    row = session.get(WriteCredentialState, workspace)
    status = row.status if row else "NOT_CONFIGURED"
    scope_verified = bool(row and row.checked_at and ENTITY_WRITE_SCOPE in row.scopes)
    # Reclassify cached scope evidence under the published contract without
    # rewriting encrypted credentials, check timestamps, revisions or audit rows.
    if row and row.checked_at and status in ("SCOPES_VERIFIED", "PERMISSIONS_PARTIAL"):
        status = (
            ("SCOPES_VERIFIED" if scope_verified else "PERMISSIONS_PARTIAL")
            if row.access_state == "active_paid"
            else "PERMISSIONS_UNVERIFIED"
        )
    return {
        "configured": bool(row and row.encrypted),
        "revision": row.revision if row else 0,
        "status": status,
        "fingerprint": row.fingerprint if row else None,
        "checked_at": row.checked_at.isoformat() if row and row.checked_at else None,
        "scopes": row.scopes if row else [],
        "scope_verified": scope_verified,
        "access_state": row.access_state if row else None,
        "permissions": "PERMISSIONS_UNVERIFIED",
        "live_actions": "LIVE_ACTIONS_BLOCKED",
        "reason_codes": ["WRITE_CONTRACT_UNVERIFIED", "WRITE_PERMISSION_UNVERIFIED"],
        "purpose": "ADVERTISING_WRITE",
    }


def change(session, actor, vault, revision, operation, *, token=None, confirm=False):
    workspace = actor["workspace"]
    lock(session, "write-credential:" + workspace)
    row = session.get(WriteCredentialState, workspace)
    if (row.revision if row else 0) != revision:
        raise HTTPException(409, "WRITE_REVISION_CONFLICT")
    if operation == "replace" and (not row or not row.encrypted or not confirm):
        raise HTTPException(409, "WRITE_REPLACE_CONFIRMATION_REQUIRED")
    if operation == "save" and row and row.encrypted:
        raise HTTPException(409, "WRITE_ALREADY_STORED")
    if operation == "delete" and not confirm:
        raise HTTPException(409, "WRITE_DELETE_CONFIRMATION_REQUIRED")
    if not row:
        row = WriteCredentialState(
            workspace_id=workspace, revision=0, status="NOT_CONFIGURED", scopes=[]
        )
        session.add(row)
    row.revision += 1
    row.checked_at = None
    row.scopes = []
    row.access_state = None
    if operation == "delete":
        row.encrypted = None
        row.fingerprint = None
        row.status = "NOT_CONFIGURED"
    else:
        row.encrypted = vault.seal(workspace, token, row.revision).decode("ascii")
        row.fingerprint = hashlib.sha256(token.encode()).hexdigest()[:16]
        row.status = "STORED_UNVERIFIED"
    session.add(
        WriteCredentialAudit(
            id=str(uuid4()),
            workspace_id=workspace,
            actor_id=actor["id"],
            revision=row.revision,
            operation=operation,
            created_at=utc_now(),
        )
    )
    session.flush()
    return metadata(session, workspace)
