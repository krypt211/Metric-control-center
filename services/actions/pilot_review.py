"""Read-only manual review card. It is never a permit or provider operation."""

from __future__ import annotations

import os
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.actions.factory import checked_write_state
from services.actions.job_observation import (
    INTERVAL_SECONDS,
    MAX_ATTEMPTS,
    TIMEOUT_SECONDS,
)
from services.actions.manual import IN_FLIGHT, PENDING, permitted, snapshot
from services.actions.write_credentials import WriteCredentialError
from services.metricflow.readback import KNOWN_STATUSES, MAX_PAGES
from services.providers.integration_models import WriteCredentialState
from services.providers.models import ProviderConnection
from services.storage.models import ActionRequest, AdAccount, Entity
from services.sync.engine import aware

MANUAL_CHECKS = (
    "MATCH_ACCOUNT_AND_AD_IN_METRICFLOW",
    "CHECK_BASELINE_IN_ADS_MANAGER",
    "CHECK_METRICFLOW_ACTING_USER_AND_ASSET_ACCESS",
)
UNRESOLVED_CONTRACT = (
    "WRITE_ENTITY_ID_NAMESPACE_UNVERIFIED",
    "WRITE_OBJECT_PERMISSION_UNVERIFIED",
    "ASYNC_ACK_CONTRACT_PARTIAL",
    "AUTHORITATIVE_READBACK_UNVERIFIED",
    "PRODUCTION_DISPATCH_NOT_IMPLEMENTED",
)


def build_review(
    session: Session,
    actor: dict,
    entity_id: str,
    operation: str,
    now: datetime,
    *,
    max_status_age_seconds: int = 900,
) -> dict:
    """Read existing metadata only; do not create a draft, permit or credential check."""
    if not permitted(session, actor):
        raise HTTPException(403, "MANUAL_CONTROL_PERMISSION_REQUIRED")
    if operation not in ("PAUSE_AD", "ENABLE_AD"):
        raise HTTPException(422, "AD_PAUSE_ENABLE_ONLY")
    entity = session.get(Entity, entity_id)
    account = session.get(AdAccount, entity.account_id) if entity else None
    if (
        not entity
        or entity.kind != "ad"
        or not account
        or (
            account.workspace_id != actor["workspace"]
            or account.provider != "metricflow"
        )
    ):
        raise HTTPException(404, "METRICFLOW_AD_NOT_FOUND")
    captured = snapshot(session, entity, account)
    read = session.get(ProviderConnection, (actor["workspace"], "metricflow"))
    write = session.get(WriteCredentialState, actor["workspace"])
    fresh_write, write_reason = False, "WRITE_NOT_CONFIGURED"
    if write:
        try:
            checked_write_state(session, actor["workspace"], write.revision, now)
            fresh_write, write_reason = True, None
        except WriteCredentialError as error:
            write_reason = str(error)
    observed = captured["status_refreshed_at"]
    fresh_status = bool(
        observed
        and -60
        <= (now - datetime.fromisoformat(observed)).total_seconds()
        <= max_status_age_seconds
    )
    expected = "ACTIVE" if operation == "PAUSE_AD" else "PAUSED"
    pending = session.scalars(
        select(ActionRequest).where(
            ActionRequest.workspace_id == actor["workspace"],
            ActionRequest.entity_id == entity_id,
            ActionRequest.status.in_((*PENDING, *IN_FLIGHT)),
        )
    ).all()
    checks = {
        "READ_CONNECTED_HEALTHY": bool(
            read and read.enabled and read.status == "healthy"
        ),
        "STATUS_FRESH": fresh_status,
        "BASELINE_MATCHES_OPERATION": captured["status"] == expected,
        "ACCOUNT_MAPPING_CONFIRMED": captured["account_confirmed"],
        "HIERARCHY_MAPPING_CONFIRMED": captured["hierarchy_confirmed"],
        "PRIMARY_PROVIDER_METRICFLOW": captured["routing"]["primary_provider"]
        == "metricflow",
        "WRITE_CREDENTIAL_CONFIGURED": bool(write and write.encrypted),
        "WRITE_SCOPE_EVIDENCE_FRESH": fresh_write,
        "NO_PENDING_ACTION": not pending,
    }
    # Explicit allowlist: no encrypted envelope, key fingerprint, raw permissions or payload.
    return {
        "mode": "MANUAL_REVIEW_ONLY",
        "execution_allowed": False,
        "generated_at": now.isoformat(),
        "operation": operation,
        "target_status": "PAUSED" if operation == "PAUSE_AD" else "ACTIVE",
        "entity": {
            "id": entity.id,
            "name": entity.name or entity.external_id,
            "ad_id": entity.external_id,
            "account_id": account.external_id,
            "account_name": account.name or account.external_id,
            "adset_id": captured["hierarchy"][0],
            "campaign_id": captured["hierarchy"][1],
            "timezone": account.timezone,
            "status": captured["status"]
            if captured["status"] in KNOWN_STATUSES
            else None,
            "effective_status": captured["effective_status"]
            if isinstance(captured["effective_status"], str)
            and captured["effective_status"] in KNOWN_STATUSES
            else None,
            "observed_at": observed,
        },
        "read_connection": {
            "revision": read.revision if read else None,
            "last_success_at": aware(read.last_success_at).isoformat()
            if read and read.last_success_at
            else None,
        },
        "write_connection": {
            "revision": write.revision if write else 0,
            "checked_at": aware(write.checked_at).isoformat()
            if write and write.checked_at
            else None,
            "fresh_scope_evidence": fresh_write,
            "reason_code": write_reason,
        },
        "local_checks": checks,
        "manual_checks": list(MANUAL_CHECKS),
        "unresolved_contract": list(UNRESOLVED_CONTRACT),
        "pending_actions": [{"id": row.id, "status": row.status} for row in pending],
        "proposed_limits": {
            "post_attempts": 1,
            "job_get_attempts": MAX_ATTEMPTS,
            "readback_get_attempts": MAX_PAGES,
            "total_http_attempts": 1 + MAX_ATTEMPTS + MAX_PAGES,
            "job_interval_seconds": INTERVAL_SECONDS,
            "timeout_seconds": TIMEOUT_SECONDS,
        },
        "flags": {
            key: os.environ.get(key, default).lower() == "true"
            for key, default in (
                ("ACTIONS_ENABLED", "false"),
                ("LOCAL_READ_ONLY", "true"),
                ("AI_ENABLED", "false"),
                ("AI_AUTOPILOT_ALLOWED", "false"),
            )
        },
    }
