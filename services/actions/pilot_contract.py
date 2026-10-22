"""Private, revocable admission for one explicitly authorized synchronous AD POST.

No HTTP endpoint creates contract acceptance. Only a trusted review of actual
provider evidence may populate contract_review in the existing acceptance audit.
A documented path or an enabled feature flag alone never grants this admission.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from services.providers.contracts import WriteDisabled
from services.storage.models import ActionExecution, ActionLog, ActionRequest
from services.sync.engine import aware


class ProviderContractReview(BaseModel):
    """Operator-reviewed provider evidence; not a user assertion about API identity."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    provider: Literal["metricflow"]
    wire_revision: Literal["status-sync-v1"]
    operation: Literal["PAUSE_AD", "ENABLE_AD"]
    entity_id_namespace: Literal["PROVIDER_AD_ID"]
    source_kind: Literal["PROVIDER_DOCUMENTATION", "PROVIDER_CLARIFICATION"]
    source_reference: str = Field(min_length=1, max_length=2048, pattern=r"\S")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_by: str = Field(min_length=1, max_length=36)


def fingerprint(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class PilotContract:
    """Non-serializable server object. Global capability inspection stays blocked."""

    sessions: sessionmaker[Session] = field(repr=False, compare=False)
    clock: Callable[[], datetime] = field(repr=False, compare=False)
    workspace: str
    actor_id: str
    request_id: str
    entity_id: str
    operation: str
    credential_revision: int
    credential_digest: str
    evidence_id: str
    evidence_sha256: str
    expires_at: datetime
    phase: Literal["AUTHORIZE", "EXECUTE"]
    experimental: bool = False
    entity_level: Literal["ad", "adset"] = "ad"

    @property
    def actor(self) -> dict:
        return {"workspace": self.workspace, "id": self.actor_id, "role": "admin"}

    def pin(self) -> dict:
        """Persist only immutable metadata, never a token or a callable permit."""
        return {
            "wire_revision": "status-sync-v1",
            "experimental_unverified_id": self.experimental,
            "workspace": self.workspace,
            "actor_id": self.actor_id,
            "request_id": self.request_id,
            "entity_id": self.entity_id,
            "operation": self.operation,
            "entity_level": self.entity_level,
            "credential_revision": self.credential_revision,
            "credential_digest": self.credential_digest,
            "evidence_id": self.evidence_id,
            "evidence_sha256": self.evidence_sha256,
            "expires_at": self.expires_at.isoformat(),
        }

    @property
    def authorization_statement(self) -> str:
        from services.actions.experimental import authorization_statement
        from services.actions.rule_pilot import (
            authorization_statement as rule_statement,
        )

        with self.sessions() as session:
            row = session.get(ActionRequest, self.request_id)
            rule_source = row.provenance.get("rule_source") if row else None
        if self.experimental and rule_source:
            return rule_statement(rule_source)
        return (
            authorization_statement(self.operation)
            if self.experimental
            else "AUTHORIZE_ONE_METRICFLOW_AD_STATUS_POST"
        )

    def require_identity(self, actor: dict, row: ActionRequest) -> None:
        if (
            actor.get("id") != self.actor_id
            or actor.get("workspace") != self.workspace
            or row.id != self.request_id
            or row.workspace_id != self.workspace
            or row.initiator_id != self.actor_id
            or row.action != self.operation
        ):
            raise WriteDisabled("PILOT_CONTRACT_BINDING_MISMATCH")

    def require_credential(self, workspace: str, revision: int) -> None:
        if (
            workspace != self.workspace
            or type(revision) is not int
            or revision != self.credential_revision
        ):
            raise WriteDisabled("PILOT_CONTRACT_CREDENTIAL_MISMATCH")

        # Loading accepted metadata is not authorization to decrypt a key.
        with self.sessions() as session:
            self._require_wire_budget(session)

    def verify(self) -> None:
        """Re-read revocation, identity, expiry and key metadata at each boundary."""
        with self.sessions() as session:
            self._verify(session)

    def _verify(self, session) -> ActionRequest:
        from services.actions.factory import checked_write_state, credential_digest
        from services.actions.pilot import (
            check_authorization,
            require_external_evidence,
        )

        now = self.clock()
        if now >= self.expires_at:
            raise WriteDisabled("PILOT_CONTRACT_EXPIRED")
        row = session.get(ActionRequest, self.request_id)
        if not row:
            raise WriteDisabled("PILOT_CONTRACT_REQUEST_MISSING")
        self.require_identity(self.actor, row)
        evidence_id = require_external_evidence(
            session, self.actor, row, now, experimental=self.experimental
        )
        proof = session.get(ActionLog, evidence_id)
        if self.experimental:
            from services.actions.experimental import (
                ADSET_NAMESPACE,
                NAMESPACE,
                review_for,
            )
            from services.actions.manual import snapshot
            from services.storage.models import AdAccount, Entity

            entity = session.get(Entity, row.entity_id)
            current = snapshot(
                session, entity, session.get(AdAccount, entity.account_id)
            )
            review = review_for(session, row, current, now)
            namespace = (
                ADSET_NAMESPACE if self.operation == "ENABLE_ADSET" else NAMESPACE
            )
            if current["entity_level"] != self.entity_level:
                raise WriteDisabled("PILOT_LEVEL_CHANGED")
        else:
            review = reviewed_contract(proof.details, self.actor_id, self.operation)
            namespace = "PROVIDER_AD_ID"
        if (
            evidence_id != self.evidence_id
            or fingerprint(proof.details) != self.evidence_sha256
            or review.entity_id_namespace != namespace
            or proof.details["entity_id"] != self.entity_id
        ):
            raise WriteDisabled("PILOT_CONTRACT_EVIDENCE_CHANGED")
        state = checked_write_state(
            session, self.workspace, self.credential_revision, now
        )
        if credential_digest(state) != self.credential_digest:
            raise WriteDisabled("PILOT_CONTRACT_CREDENTIAL_CHANGED")
        control = row.provenance.get("controlled") or {}
        if control:
            if control.get("provider_contract") != self.pin():
                raise WriteDisabled("PILOT_CONTRACT_PIN_CHANGED")
            check_authorization(control, self.actor)
            expected_statement = self.authorization_statement
            if control["authorization"]["statement"] != expected_statement:
                raise WriteDisabled("PILOT_AUTHORIZATION_STATEMENT_MISMATCH")
            authorized_at = datetime.fromisoformat(
                control["authorization"]["authorized_at"]
            )
            if (
                control.get("mode") != "LIVE_SINGLE_OPERATION"
                or control.get("response_mode") != "SYNC_200"
                or control.get("expires_at") != self.expires_at.isoformat()
                or authorized_at > now + timedelta(seconds=60)
                or self.expires_at
                > min(
                    authorized_at + timedelta(seconds=600),
                    datetime.fromisoformat(row.provenance["expires_at"]),
                    aware(proof.created_at) + timedelta(seconds=900),
                )
            ):
                raise WriteDisabled("PILOT_CONTRACT_WINDOW_CHANGED")
        elif self.phase == "EXECUTE":
            raise WriteDisabled("EXPLICIT_PILOT_AUTHORIZATION_REQUIRED")
        return row

    def check_request(self, method: str, path: str, payload, params) -> None:
        operation = "pause" if self.operation == "PAUSE_AD" else "enable"
        if (
            self.phase != "EXECUTE"
            or method != "POST"
            or path != f"entities/{self.entity_id}/{operation}"
            or (
                self.experimental
                and self.operation not in ("PAUSE_AD", "ENABLE_AD", "ENABLE_ADSET")
            )
            or self.entity_level
            != ("adset" if self.operation == "ENABLE_ADSET" else "ad")
            or payload != {"level": self.entity_level}
            or params not in (None, {})
        ):
            raise WriteDisabled("PILOT_WIRE_CONTRACT_MISMATCH")

    def _require_wire_budget(self, session) -> ActionRequest:
        if self.phase != "EXECUTE":
            raise WriteDisabled("EXPLICIT_PILOT_AUTHORIZATION_REQUIRED")
        row = self._verify(session)
        control = row.provenance.get("controlled") or {}
        execution = session.scalar(
            select(ActionExecution).where(ActionExecution.request_id == self.request_id)
        )
        if (
            row.status != "executing"
            or control.get("mode") != "LIVE_SINGLE_OPERATION"
            or control.get("response_mode") != "SYNC_200"
            or type(control.get("attempts")) is not int
            or control["attempts"] != 1
            or control.get("wire_spent")
            or not execution
            or execution.outcome != "live_started"
            or execution.completed_at is not None
        ):
            raise WriteDisabled("PILOT_WIRE_BUDGET_UNAVAILABLE")
        return row

    async def refresh_before_write(self, token: str, *, transport=None) -> None:
        if self.experimental:
            from services.actions.experimental import revalidate_before_post

            await revalidate_before_post(self, token, transport=transport)

    def consume_before_http(self) -> None:
        """Atomically spend the wire budget; crashes/reconstructed scopes cannot resend."""
        from services.actions.manual import require_permission
        from services.economics.store import lock

        with self.sessions.begin() as session:
            lock(session, self.workspace)
            require_permission(session, self.actor)
            session.scalar(
                select(ActionRequest)
                .where(ActionRequest.id == self.request_id)
                .with_for_update()
            )
            row = self._require_wire_budget(session)
            control = dict(row.provenance["controlled"])
            if control.get("http_started") is not True:
                raise WriteDisabled("PILOT_WIRE_BUDGET_UNAVAILABLE")
            if self.experimental:
                check = control.get("experimental_revalidation") or {}
                try:
                    checked_at = datetime.fromisoformat(check["checked_at"])
                    valid = (
                        checked_at.tzinfo is not None
                        and 0 <= (self.clock() - checked_at).total_seconds() <= 30
                    )
                except (KeyError, TypeError, ValueError):
                    valid = False
                if (
                    not valid
                    or check.get("claim_id") != control.get("claim_id")
                    or control.get("validation_gets") != 3
                ):
                    raise WriteDisabled("EXPERIMENTAL_PREPOST_READ_REQUIRED")
            control["wire_spent"] = True
            row.provenance = {**row.provenance, "controlled": control}


def reviewed_contract(
    proof: dict, actor_id: str, operation: str
) -> ProviderContractReview:
    try:
        review = ProviderContractReview.model_validate(proof.get("contract_review"))
    except ValidationError:
        raise WriteDisabled("PROVIDER_CONTRACT_REVIEW_REQUIRED") from None
    if review.reviewed_by != actor_id or review.operation != operation:
        raise WriteDisabled("PROVIDER_CONTRACT_REVIEW_MISMATCH")
    return review


def load_contract(
    engine, actor: dict, request_id: str, *, phase: str
) -> PilotContract | None:
    """Load trusted proof, never accept evidence from the authorization request body."""
    from services.actions.factory import checked_write_state, credential_digest
    from services.actions.pilot import (
        EVIDENCE_EVENT,
        require_external_evidence,
        require_workspace_available,
    )

    if phase not in ("AUTHORIZE", "EXECUTE"):
        raise WriteDisabled("PILOT_CONTRACT_PHASE_INVALID")
    with engine.sessions() as session:
        row = session.get(ActionRequest, request_id)
        if not row or row.workspace_id != actor["workspace"]:
            return None
        experimental = bool(row.provenance.get("experimental"))
        if experimental:
            from services.actions.experimental import EVENT, REVOKED

            events = (EVENT, REVOKED)
        else:
            events = (EVIDENCE_EVENT, "pilot_external_evidence_revoked")
        evidence = session.scalars(
            select(ActionLog)
            .where(
                ActionLog.request_id == request_id,
                ActionLog.event.in_(events),
            )
            .order_by(ActionLog.created_at.desc(), ActionLog.event.desc())
        ).first()
        if (
            not evidence
            or not isinstance(evidence.details, dict)
            or "contract_review" not in evidence.details
        ):
            return None  # Scope/tariff/manual consent alone cannot release the gate.
        require_workspace_available(session, actor["workspace"], request_id)
        now = engine.clock()
        require_external_evidence(session, actor, row, now, experimental=experimental)
        if not experimental:
            reviewed_contract(evidence.details, actor["id"], row.action)
        state = checked_write_state(
            session, actor["workspace"], evidence.details["credential_revision"], now
        )
        expiry = min(
            now + timedelta(seconds=600),
            aware(evidence.created_at) + timedelta(seconds=900),
            datetime.fromisoformat(row.provenance["expires_at"]),
        )
        if experimental:
            baseline_at = datetime.fromisoformat(
                evidence.details["contract_review"]["baseline"]["source_updated_at"]
            )
            expiry = min(expiry, baseline_at + timedelta(seconds=900))
        if phase == "EXECUTE":
            pin = (row.provenance.get("controlled") or {}).get(
                "provider_contract"
            ) or {}
            try:
                expiry = datetime.fromisoformat(pin["expires_at"])
                if expiry.tzinfo is None:
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise WriteDisabled("EXPLICIT_PILOT_AUTHORIZATION_REQUIRED") from None
        contract = PilotContract(
            sessions=engine.sessions,
            clock=engine.clock,
            workspace=actor["workspace"],
            actor_id=actor["id"],
            request_id=request_id,
            entity_id=evidence.details["entity_id"],
            operation=row.action,
            credential_revision=state.revision,
            credential_digest=credential_digest(state),
            evidence_id=evidence.id,
            evidence_sha256=fingerprint(evidence.details),
            expires_at=expiry,
            phase=phase,
            experimental=experimental,
            entity_level="adset" if row.action == "ENABLE_ADSET" else "ad",
        )
        contract._verify(session)
        return contract
