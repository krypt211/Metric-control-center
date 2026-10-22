"""Single-operation private handoff with request-bound contract admission."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.actions.capabilities import ActionCapabilityRegistry
from services.actions.engine import ActionEngine, ActionRejected
from services.actions.manual import snapshot
from services.actions.safety import ActionSafetyGate
from services.metricflow.readback import KNOWN_STATUSES
from services.providers.integration_models import WriteCredentialState
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    AdAccount,
    Entity,
    User,
)
from services.sync.engine import aware

MODE = "LIVE_SINGLE_OPERATION"
STATEMENT = "AUTHORIZE_ONE_METRICFLOW_AD_STATUS_POST"
EVIDENCE_EVENT = "pilot_external_evidence_accepted"


class PilotAuthorizationInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    revision: int = Field(ge=1)
    credential_revision: int = Field(ge=1)
    account_id: str = Field(pattern=r"^act_[0-9]{1,128}$")
    entity_id: str = Field(pattern=r"^[0-9]{1,128}$")
    operation: Literal["PAUSE_AD", "ENABLE_AD", "ENABLE_ADSET"]
    expected_status: Literal["ACTIVE", "PAUSED"]
    statement: Literal[
        "AUTHORIZE_ONE_METRICFLOW_AD_STATUS_POST",
        "AUTHORIZE_ONE_EXPERIMENTAL_PAUSE_WITH_UNVERIFIED_ID",
        "AUTHORIZE_ONE_EXPERIMENTAL_ENABLE_WITH_UNVERIFIED_ID",
        "AUTHORIZE_ONE_EXPERIMENTAL_ENABLE_ADSET_WITH_UNVERIFIED_ID",
        "AUTHORIZE_ONE_EXPERIMENTAL_RULE_PAUSE_WITH_UNVERIFIED_ID",
    ]


class PilotExecuteInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    revision: int = Field(ge=1)


def require_ready(
    session: Session, actor: dict, row: ActionRequest, now: datetime, contract=None
) -> str:
    """No route writes acceptance evidence or promotes an unknown object permission."""
    user = session.get(User, actor["id"])
    entity = session.get(Entity, row.entity_id)
    account = session.get(AdAccount, entity.account_id) if entity else None
    if not user or user.role != "admin":
        raise ActionRejected("PILOT_ADMIN_REQUIRED")
    if (
        not entity
        or entity.kind
        != (
            "adset"
            if row.action == "ENABLE_ADSET" and bool(contract and contract.experimental)
            else "ad"
        )
        or not account
        or account.provider != "metricflow"
        or row.value is not None
        or row.action
        not in (
            ("ENABLE_ADSET",)
            if row.action == "ENABLE_ADSET" and bool(contract and contract.experimental)
            else ("PAUSE_AD", "ENABLE_AD")
        )
    ):
        raise ActionRejected("MANUAL_SINGLE_AD_STATUS_ONLY")
    if contract is None:
        capability = ActionCapabilityRegistry.inspect(
            session, actor["workspace"], "metricflow"
        )
        if (
            not capability.get("write_permission")
            or capability.get("operations", {}).get(row.action) != "VERIFIED"
        ):
            raise ActionRejected("PILOT_WRITE_PERMISSION_UNVERIFIED")
    else:
        contract.require_identity(actor, row)
    return require_external_evidence(
        session, actor, row, now, experimental=bool(contract and contract.experimental)
    )


def require_external_evidence(
    session: Session,
    actor: dict,
    row: ActionRequest,
    now: datetime,
    *,
    experimental=False,
) -> str:
    """Check object permission and namespace proof without granting a global capability."""
    user = session.get(User, actor["id"])
    entity = session.get(Entity, row.entity_id)
    account = session.get(AdAccount, entity.account_id) if entity else None
    if (
        not user
        or not user.is_active
        or user.role != "admin"
        or user.workspace_id != actor["workspace"]
        or row.workspace_id != actor["workspace"]
        or row.initiator_id != actor["id"]
        or not entity
        or entity.kind
        != ("adset" if row.action == "ENABLE_ADSET" and experimental else "ad")
        or not account
        or account.workspace_id != actor["workspace"]
        or account.provider != "metricflow"
        or row.value is not None
        or row.action
        not in (
            ("ENABLE_ADSET",)
            if row.action == "ENABLE_ADSET" and experimental
            else ("PAUSE_AD", "ENABLE_AD")
        )
    ):
        raise ActionRejected("PILOT_IDENTITY_OR_PERMISSION_CHANGED")
    if experimental:
        from services.actions.experimental import (
            ADSET_NAMESPACE,
            EVENT,
            NAMESPACE,
            REVOKED,
        )

        events = (EVENT, REVOKED)
        accepted_event, namespace = (
            EVENT,
            ADSET_NAMESPACE if row.action == "ENABLE_ADSET" else NAMESPACE,
        )
    else:
        events = (EVIDENCE_EVENT, "pilot_external_evidence_revoked")
        accepted_event, namespace = EVIDENCE_EVENT, "PROVIDER_AD_ID"
    credential = session.get(WriteCredentialState, actor["workspace"])
    evidence = session.scalars(
        select(ActionLog)
        .where(
            ActionLog.request_id == row.id,
            ActionLog.event.in_(events),
        )
        .order_by(ActionLog.created_at.desc(), ActionLog.event.desc())
    ).first()
    proof = evidence.details if evidence and isinstance(evidence.details, dict) else {}
    expected = {
        "actor_id": actor["id"],
        "account_id": account.external_id,
        "entity_id": entity.external_id,
        "operation": row.action,
        "credential_revision": credential.revision if credential else None,
        "read_revision": row.provenance["captured"].get("credential_revision"),
        "entity_id_namespace": namespace,
        "configured_status": row.baseline_status,
    }
    manual_permission = proof.get(
        "permission_source"
    ) == "MANUAL_META_ACCESS_REVIEW" and proof.get("permission") in (
        "MANAGE_CAMPAIGNS",
        "FULL_CONTROL",
    )
    user_permission = (
        proof.get("permission_source") == "USER_ATTESTED"
        and proof.get("management_confirmed") is True
    )
    if (
        not evidence
        or evidence.event != accepted_event
        or any(
            type(proof.get(k)) is not type(v) or proof.get(k) != v
            for k, v in expected.items()
        )
        or not -60 <= (now - aware(evidence.created_at)).total_seconds() <= 900
        or not (manual_permission or user_permission)
        or (
            not experimental
            and (
                type(proof.get("profile_id")) is not int
                or proof["profile_id"] < 1
                or not isinstance(proof.get("namespace_source"), str)
                or not proof["namespace_source"].strip()
            )
        )
        or proof.get("effective_status") not in KNOWN_STATUSES
    ):
        raise ActionRejected("PILOT_EXTERNAL_EVIDENCE_REQUIRED")
    if row.provenance.get("rule_source"):
        if not experimental:
            raise ActionRejected("RULE_PILOT_EXPERIMENTAL_REVIEW_REQUIRED")
        from services.actions.experimental import review_for

        review_for(session, row, row.provenance["captured"], now)
    control = row.provenance.get("controlled") or {}
    if control.get("mode") == MODE and control.get("evidence_id") != evidence.id:
        raise ActionRejected("PILOT_EVIDENCE_CHANGED")
    return evidence.id


def bind_authorization(
    value: dict,
    binding: dict,
    actor: dict,
    now: datetime,
    revision: int,
    credential_revision: int,
) -> dict:
    """Bind an explicit live statement independently of a local simulation confirmation."""
    if not isinstance(value, dict):
        raise ActionRejected("EXPLICIT_PILOT_AUTHORIZATION_REQUIRED")
    try:
        body = PilotAuthorizationInput.model_validate(value)
    except ValueError:
        raise ActionRejected("EXPLICIT_PILOT_AUTHORIZATION_REQUIRED") from None
    expected = {
        "revision": revision,
        "credential_revision": credential_revision,
        "account_id": binding["snapshot"]["meta_account_id"],
        "entity_id": binding["external_id"],
        "operation": binding["action"],
        "expected_status": binding["snapshot"]["status"],
    }
    if any(getattr(body, key) != expected[key] for key in expected):
        raise ActionRejected("PILOT_AUTHORIZATION_BINDING_MISMATCH")
    return {
        **body.model_dump(),
        "actor_id": actor["id"],
        "workspace": actor["workspace"],
        "authorized_at": now.isoformat(),
    }


def check_authorization(control: dict, actor: dict) -> None:
    saved = control.get("authorization") or {}
    value = {key: saved.get(key) for key in PilotAuthorizationInput.model_fields}
    try:
        at = datetime.fromisoformat(saved["authorized_at"])
        if at.tzinfo is None:
            raise ValueError()
        rebound = bind_authorization(
            value,
            control["binding"],
            actor,
            at,
            saved.get("revision"),
            control["credential_revision"],
        )
    except (KeyError, TypeError, ValueError):
        raise ActionRejected("PILOT_AUTHORIZATION_BINDING_MISMATCH") from None
    if rebound != saved:
        raise ActionRejected("PILOT_AUTHORIZATION_BINDING_MISMATCH")


def authorize_pilot(
    engine: ActionEngine, actor: dict, request_id: str, body: PilotAuthorizationInput
) -> dict:
    from services.actions.pilot_contract import load_contract

    if not ActionSafetyGate.allowed():
        ActionSafetyGate.require_write()
    contract = load_contract(engine, actor, request_id, phase="AUTHORIZE")
    ActionSafetyGate.require_write(contract)
    expected_statement = contract.authorization_statement if contract else STATEMENT
    if body.statement != expected_statement:
        raise ActionRejected("PILOT_AUTHORIZATION_STATEMENT_MISMATCH")
    with engine.sessions() as session:
        row = session.get(ActionRequest, request_id)
        if not row or row.workspace_id != actor["workspace"]:
            raise ActionRejected("PILOT_REQUEST_NOT_FOUND")
        draft_expiry = datetime.fromisoformat(row.provenance["expires_at"])
    return engine._prepare_controlled(
        actor,
        request_id,
        body.revision,
        body.credential_revision,
        min(engine.clock() + timedelta(seconds=600), draft_expiry, contract.expires_at)
        if contract
        else min(engine.clock() + timedelta(seconds=600), draft_expiry),
        asynchronous=False,
        mode=MODE,
        authorization=body.model_dump(),
        contract=contract,
    )


async def execute_pilot(
    engine: ActionEngine,
    actor: dict,
    request_id: str,
    revision: int,
    *,
    vault,
    transport=None,
) -> str | None:
    from services.actions.pilot_contract import load_contract

    if not ActionSafetyGate.allowed():
        ActionSafetyGate.require_write()
    contract = load_contract(engine, actor, request_id, phase="EXECUTE")
    ActionSafetyGate.require_write(contract)
    return await engine._execute_controlled(
        actor,
        request_id,
        revision,
        vault=vault,
        transport=transport,
        mode=MODE,
        contract=contract,
    )


class PilotReadbackInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    revision: int = Field(ge=1)
    account_id: str = Field(pattern=r"^act_[0-9]{1,128}$")
    entity_id: str = Field(pattern=r"^[0-9]{1,128}$")
    configured_status: Literal["ACTIVE", "PAUSED"]
    effective_status: str = Field(min_length=1, max_length=64)
    observed_at: str = Field(min_length=20, max_length=40)
    statement: Literal["RECORD_MANUAL_META_READBACK"]


def record_manual_readback(
    engine: ActionEngine, actor: dict, request_id: str, body: PilotReadbackInput
) -> dict:
    """Local audit, even after WRITE is disabled; never API authority or MCC ownership."""
    from services.actions.engine import log

    try:
        observed = datetime.fromisoformat(body.observed_at)
    except ValueError:
        raise ActionRejected("PILOT_READBACK_TIME_INVALID") from None
    now = engine.clock()
    if observed.tzinfo is None or not 0 <= (now - observed).total_seconds() <= 900:
        raise ActionRejected("PILOT_READBACK_TIME_INVALID")
    if body.effective_status not in KNOWN_STATUSES:
        raise ActionRejected("PILOT_READBACK_STATUS_INVALID")
    with engine.sessions.begin() as session:
        row = engine._locked_manual_row(session, actor, request_id)
        if session.get(User, actor["id"]).role != "admin":
            raise ActionRejected("PILOT_ADMIN_REQUIRED")
        control = dict(row.provenance.get("controlled") or {})
        binding = control.get("binding") or {}
        execution = session.scalar(
            select(ActionExecution).where(ActionExecution.request_id == row.id)
        )
        if (
            control.get("mode") != MODE
            or control.get("response_mode") != "SYNC_200"
            or row.revision != body.revision
            or row.status not in ("verifying", "unknown")
            or control.get("attempts") != 1
            or not control.get("http_started")
            or not execution
            or observed < aware(execution.completed_at or execution.started_at)
            or binding.get("external_id") != body.entity_id
            or binding.get("snapshot", {}).get("meta_account_id") != body.account_id
        ):
            raise ActionRejected("PILOT_READBACK_BINDING_MISMATCH")
        entity = session.get(Entity, row.entity_id)
        account = session.get(AdAccount, entity.account_id)
        current = snapshot(session, entity, account)
        stable = (
            "entity_id",
            "meta_ad_id",
            "account_id",
            "meta_account_id",
            "hierarchy",
            "provider",
            "routing",
        )
        if any(current[k] != binding["snapshot"].get(k) for k in stable):
            raise ActionRejected("PILOT_READBACK_BINDING_MISMATCH")
        target = "PAUSED" if row.action == "PAUSE_AD" else "ACTIVE"
        matches = body.configured_status == target
        can_close = (
            matches
            and execution.outcome == "live_acknowledged"
            and now < datetime.fromisoformat(control["expires_at"])
        )
        control.update(
            state="MANUAL_READBACK_MATCHED"
            if can_close
            else "MANUAL_OBSERVATION_OUTCOME_UNKNOWN",
            manual_readback={
                **body.model_dump(exclude={"revision", "statement"}),
                "actor_id": actor["id"],
                "recorded_at": now.isoformat(),
                "authoritative_api": False,
                "creates_pause_ownership": False,
            },
        )
        row.provenance = {**row.provenance, "controlled": control}
        row.status = "MANUALLY_REVIEWED" if can_close else "unknown"
        row.revision += 1
        execution.outcome = "live_manually_reviewed" if can_close else "live_unknown"
        log(
            session,
            row.id,
            "controlled_live_manual_readback",
            now,
            actor_id=actor["id"],
            matches_target=matches,
            authoritative_api=False,
            creates_pause_ownership=False,
        )
        return {
            "id": row.id,
            "revision": row.revision,
            "status": row.status,
            "matches_target": matches,
            "authoritative_api": False,
        }
