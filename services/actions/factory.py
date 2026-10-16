"""Purpose-bound encrypted WRITE handoff; never uses a plaintext/READ fallback."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from services.actions.safety import ActionSafetyGate
from services.actions.write_credentials import (
    WriteCredentialError,
    WriteCredentialVault,
)
from services.metricflow.errors import ConfigurationError
from services.metricflow.writer import ENTITY_WRITE_SCOPE, MetricFlowActionConnector
from services.providers.integration_models import WriteCredentialState
from services.storage.database import make_engine, sessions
from services.sync.engine import aware, utc_now


def checked_write_state(
    session: Session, workspace: str, revision: int, now: datetime
) -> WriteCredentialState:
    """Validate cached WRITE evidence without decrypting or changing its revision."""
    if (
        not isinstance(workspace, str)
        or not workspace
        or type(revision) is not int
        or revision < 1
    ):
        raise WriteCredentialError("WRITE_BINDING_REQUIRED")
    row = session.get(WriteCredentialState, workspace)
    if not row or not row.encrypted:
        raise WriteCredentialError("WRITE_NOT_CONFIGURED")
    if row.revision != revision:
        raise WriteCredentialError("WRITE_REVISION_CONFLICT")
    if (
        row.status not in ("SCOPES_VERIFIED", "PERMISSIONS_PARTIAL")
        or ENTITY_WRITE_SCOPE not in (row.scopes or [])
        or row.access_state != "active_paid"
        or not row.checked_at
        or not -60 <= (now - aware(row.checked_at)).total_seconds() <= 900
    ):
        raise WriteCredentialError("FRESH_WRITE_SCOPE_EVIDENCE_REQUIRED")
    return row


def credential_digest(row: WriteCredentialState) -> str:
    """Fingerprint ciphertext, never a plaintext credential."""
    return hashlib.sha256(row.encrypted.encode()).hexdigest()


def create_action_connector(
    *,
    workspace: str | None = None,
    credential_revision: int | None = None,
    session_factory=None,
    vault: WriteCredentialVault | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    before_request: Callable[[], Awaitable[None]] | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> MetricFlowActionConnector:
    """Load only an explicitly bound encrypted WRITE record after the hard gate.

    Production still fails the unverified-contract gate before opening any vault.
    Tests supply isolated sessions, a synthetic vault and MockTransport explicitly.
    """
    if not workspace or type(credential_revision) is not int or credential_revision < 1:
        raise ConfigurationError("Explicit encrypted WRITE binding is required")
    ActionSafetyGate.require_write()
    factory = session_factory or sessions(make_engine())
    with factory() as session:
        row = checked_write_state(session, workspace, credential_revision, clock())
        encrypted, digest = row.encrypted, credential_digest(row)
    private_vault = vault or WriteCredentialVault.from_environment()
    token = private_vault.unseal(
        encrypted.encode(), workspace, credential_revision
    ).token

    def check_current():
        with factory() as session:
            current = checked_write_state(
                session, workspace, credential_revision, clock()
            )
            if credential_digest(current) != digest:
                raise WriteCredentialError("WRITE_CREDENTIAL_CHANGED")

    async def guard():
        await asyncio.to_thread(check_current)
        if before_request:
            await before_request()
        # Rotation/deletion during a preceding local guard must also stop HTTP.
        await asyncio.to_thread(check_current)

    return MetricFlowActionConnector(token, transport=transport, before_request=guard)
