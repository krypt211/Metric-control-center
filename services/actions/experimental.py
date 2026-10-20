"""Explicitly unverified-ID preparation; shares the existing single-use executor."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select

from services.actions.factory import checked_write_state, credential_digest
from services.actions.manual import snapshot
from services.actions.manual_schema import ManualDraftInput
from services.metricflow.errors import MetricFlowError, RateLimitExceeded
from services.metricflow.reader import MetricFlowConnector
from services.providers.contracts import WriteDisabled
from services.providers.manager import ProviderManager
from services.providers.models import ProviderConnection
from services.storage.models import ActionLog, ActionRequest, AdAccount, Entity, User

EVENT = "pilot_experimental_prepared"
REVOKED = "pilot_experimental_revoked"
STATEMENT = "AUTHORIZE_ONE_EXPERIMENTAL_PAUSE_WITH_UNVERIFIED_ID"
PREPARE = "PREPARE_EXPERIMENT_ONLY_NO_POST"
NAMESPACE = "UNVERIFIED_CANDIDATE_FACEBOOK_AD_ID"


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class ExperimentalPrepareInput(StrictModel):
    entity_id: str = Field(min_length=1, max_length=36)
    credential_revision: int = Field(ge=1)
    management_confirmed: Literal[True]
    statement: Literal["PREPARE_EXPERIMENT_ONLY_NO_POST"]

    @field_validator("management_confirmed", mode="before")
    @classmethod
    def exact_attestation(cls, value):
        if value is not True:
            raise ValueError("Explicit boolean confirmation required")
        return value


class Baseline(StrictModel):
    account_id: str = Field(pattern=r"^act_[0-9]{1,128}$")
    campaign_id: str = Field(pattern=r"^[0-9]{1,128}$")
    adset_id: str = Field(pattern=r"^[0-9]{1,128}$")
    ad_id: str = Field(pattern=r"^[0-9]{1,128}$")
    campaign_status: Literal["PAUSED"]
    campaign_effective: Literal["PAUSED"]
    adset_status: Literal["PAUSED"]
    adset_effective: Literal["PAUSED"]
    ad_status: Literal["ACTIVE"]
    ad_effective: Literal["ADSET_PAUSED"]
    source_updated_at: str

    def fresh(self, now: datetime) -> None:
        try:
            at = datetime.fromisoformat(self.source_updated_at)
            if at.tzinfo is None or not -60 <= (now - at).total_seconds() <= 900:
                raise ValueError()
        except (TypeError, ValueError):
            raise WriteDisabled("EXPERIMENTAL_BASELINE_STALE") from None


class ExperimentalReview(StrictModel):
    provider: Literal["metricflow"] = "metricflow"
    wire_revision: Literal["status-sync-v1"] = "status-sync-v1"
    operation: Literal["PAUSE_AD"] = "PAUSE_AD"
    entity_id_namespace: Literal["UNVERIFIED_CANDIDATE_FACEBOOK_AD_ID"] = NAMESPACE
    source_kind: Literal["USER_REQUESTED_EXPERIMENT"] = "USER_REQUESTED_EXPERIMENT"
    preparation_statement: Literal["PREPARE_EXPERIMENT_ONLY_NO_POST"]
    reviewed_by: str
    baseline: Baseline


def selected(payload: dict, entity_id: str) -> dict:
    if not isinstance(payload, dict):
        raise WriteDisabled("EXPERIMENTAL_CATALOG_INCOMPLETE")
    rows = payload.get("data")
    meta = payload.get("meta")
    if (
        not isinstance(rows, list)
        or not isinstance(meta, dict)
        or type(meta.get("total")) is not int
        or meta["total"] != len(rows)
        or meta.get("limit") is not None
        or meta.get("offset") is not None
        or any(not isinstance(r, dict) for r in rows)
    ):
        raise WriteDisabled("EXPERIMENTAL_CATALOG_INCOMPLETE")
    matches = [r for r in rows if r.get("id") == entity_id]
    if len(matches) != 1:
        raise WriteDisabled("EXPERIMENTAL_ENTITY_NOT_UNIQUE")
    return matches[0]


async def collect_baseline(
    token, identity: dict, day, now, *, before_request, transport=None
) -> Baseline:
    """Exactly three documented GETs, no pagination guessing or retries."""
    payloads = []
    async with MetricFlowConnector(
        token, read_retries=0, before_request=before_request, transport=transport
    ) as client:
        for kind in ("campaigns", "adsets", "ads"):
            payloads.append(
                await getattr(client, "get_" + kind)(identity["account_id"], day, day)
            )
    try:
        c, a, ad = [
            selected(p, identity[k])
            for p, k in zip(payloads, ("campaign_id", "adset_id", "ad_id"), strict=True)
        ]
        stamps = [p["meta"].get("data_updated_at") for p in payloads]
        if not isinstance(stamps[0], str) or len(set(stamps)) != 1:
            raise WriteDisabled("EXPERIMENTAL_SNAPSHOT_CHANGED")
        if (
            a.get("campaign_id") != identity["campaign_id"]
            or a.get("parent_id") != identity["campaign_id"]
            or ad.get("campaign_id") != identity["campaign_id"]
            or ad.get("parent_id") != identity["adset_id"]
        ):
            raise WriteDisabled("EXPERIMENTAL_HIERARCHY_CHANGED")
        value = Baseline.model_validate(
            {
                **identity,
                "campaign_status": c.get("status"),
                "campaign_effective": c.get("effective_status"),
                "adset_status": a.get("status"),
                "adset_effective": a.get("effective_status"),
                "ad_status": ad.get("status"),
                "ad_effective": ad.get("effective_status"),
                "source_updated_at": stamps[0],
            }
        )
    except (ValidationError, TypeError, KeyError):
        raise WriteDisabled("EXPERIMENTAL_STATUS_OR_SHAPE_CHANGED") from None
    value.fresh(now())
    return value


def identity_for(captured: dict) -> dict:
    return {
        "account_id": captured["meta_account_id"],
        "ad_id": captured["meta_ad_id"],
        "adset_id": captured["hierarchy"][0],
        "campaign_id": captured["hierarchy"][1],
    }


def review_for(session, row, current: dict, now: datetime) -> ExperimentalReview:
    """Only trusted prepared audit can supply configured status, never HTTP body."""
    from services.actions.pilot_contract import fingerprint

    saved = row.provenance.get("experimental") or {}
    evidence = session.scalars(
        select(ActionLog)
        .where(ActionLog.request_id == row.id, ActionLog.event.in_((EVENT, REVOKED)))
        .order_by(ActionLog.created_at.desc(), ActionLog.event.desc())
    ).first()
    if (
        not evidence
        or evidence.event != EVENT
        or evidence.id != saved.get("evidence_id")
        or fingerprint(evidence.details) != saved.get("evidence_sha256")
    ):
        raise WriteDisabled("EXPERIMENTAL_PREPARATION_CHANGED")
    try:
        review = ExperimentalReview.model_validate(evidence.details["contract_review"])
    except (ValidationError, KeyError):
        raise WriteDisabled("EXPERIMENTAL_PREPARATION_INVALID") from None
    expected = identity_for(current)
    if (
        row.action != "PAUSE_AD"
        or row.value is not None
        or row.provenance.get("rule_source")
        or review.reviewed_by != row.initiator_id
        or any(getattr(review.baseline, k) != v for k, v in expected.items())
        or evidence.details.get("read_revision") != current["credential_revision"]
    ):
        raise WriteDisabled("EXPERIMENTAL_BINDING_CHANGED")
    review.baseline.fresh(now)
    return review


def execution_snapshot(session, row, current: dict, now: datetime) -> dict:
    if not row.provenance.get("experimental"):
        return current
    review = review_for(session, row, current, now)
    b = review.baseline
    return {
        **current,
        "status": b.ad_status,
        "effective_status": b.ad_effective,
        "status_refreshed_at": b.source_updated_at,
        "status_source": "METRICFLOW_CATALOG_STATUS",
        "experimental_parent_statuses": {
            "campaign": b.campaign_status,
            "adset": b.adset_status,
        },
    }


async def prepare_experiment(
    engine, actor: dict, body: ExperimentalPrepareInput, *, vault, transport=None
) -> dict:
    """READ + local DRAFT only, including when all advertising flags are disabled."""
    from services.actions.pilot_contract import fingerprint

    with engine.sessions() as s:
        user = s.get(User, actor["id"])
        entity = s.get(Entity, body.entity_id)
        account = s.get(AdAccount, entity.account_id) if entity else None
        if (
            not user
            or not user.is_active
            or user.role != "admin"
            or user.workspace_id != actor["workspace"]
        ):
            raise WriteDisabled("PILOT_ADMIN_REQUIRED")
        if (
            not entity
            or entity.kind != "ad"
            or not account
            or account.workspace_id != actor["workspace"]
            or account.provider != "metricflow"
        ):
            raise WriteDisabled("EXPERIMENTAL_SINGLE_AD_REQUIRED")
        current = snapshot(s, entity, account)
        if not current["hierarchy_confirmed"] or not current["account_confirmed"]:
            raise WriteDisabled("EXPERIMENTAL_IDENTITY_UNCONFIRMED")
        read = s.get(ProviderConnection, (actor["workspace"], "metricflow"))
        if not read or not read.enabled or read.status != "healthy":
            raise WriteDisabled("EXPERIMENTAL_READ_UNAVAILABLE")
        state = checked_write_state(
            s, actor["workspace"], body.credential_revision, engine.clock()
        )
        if "campaigns:read" not in state.scopes:
            raise WriteDisabled("EXPERIMENTAL_READ_SCOPE_REQUIRED")
        encrypted, digest = state.encrypted, credential_digest(state)
        day = engine.clock().astimezone(ZoneInfo(account.timezone)).date()
        account_local_id = account.id
    token = vault.unseal(
        encrypted.encode(), actor["workspace"], body.credential_revision
    ).token
    manager = ProviderManager(engine.sessions, actor["workspace"])
    count = 0

    async def reserve():
        nonlocal count
        if count >= 3:
            raise WriteDisabled("EXPERIMENTAL_GET_BUDGET_EXHAUSTED")
        await asyncio.to_thread(manager.reserve, "metricflow")
        count += 1

    try:
        baseline = await collect_baseline(
            token,
            identity_for(current),
            day,
            engine.clock,
            before_request=reserve,
            transport=transport,
        )
    except RateLimitExceeded as error:
        await asyncio.to_thread(manager.failure, "metricflow", error, revision=-1)
        raise WriteDisabled("EXPERIMENTAL_PROVIDER_RATE_LIMIT") from None
    except MetricFlowError:
        raise WriteDisabled("EXPERIMENTAL_READ_FAILED") from None
    finally:
        token = None
    # Recheck key/routing/identity before committing preparation. No token in evidence.
    with engine.sessions() as s:
        state = checked_write_state(
            s, actor["workspace"], body.credential_revision, engine.clock()
        )
        if (
            credential_digest(state) != digest
            or snapshot(
                s, s.get(Entity, body.entity_id), s.get(AdAccount, account_local_id)
            )
            != current
        ):
            raise WriteDisabled("EXPERIMENTAL_PREPARATION_RACE")
    draft = engine.prepare_manual(
        actor,
        ManualDraftInput(
            entity_id=body.entity_id,
            account_id=account_local_id,
            meta_ad_id=baseline.ad_id,
            provider="metricflow",
            operation="PAUSE_AD",
            expected_status="ACTIVE",
            reason="Experimental pilot preparation only; WRITE ID is unverified",
        ),
        "experimental-" + str(uuid4()),
    )
    with engine.sessions.begin() as s:
        row = engine._locked_manual_row(s, actor, draft["id"])
        eid = str(uuid4())
        review = ExperimentalReview(
            preparation_statement=PREPARE, reviewed_by=actor["id"], baseline=baseline
        )
        proof = {
            "actor_id": actor["id"],
            "account_id": baseline.account_id,
            "entity_id": baseline.ad_id,
            "operation": "PAUSE_AD",
            "credential_revision": body.credential_revision,
            "read_revision": current["credential_revision"],
            "entity_id_namespace": NAMESPACE,
            "configured_status": "ACTIVE",
            "effective_status": baseline.ad_effective,
            "permission_source": "USER_ATTESTED",
            "management_confirmed": True,
            "namespace_source": "EXPLICITLY_UNVERIFIED",
            "contract_review": review.model_dump(),
        }
        s.add(
            ActionLog(
                id=eid,
                request_id=row.id,
                event=EVENT,
                created_at=engine.clock(),
                details=proof,
            )
        )
        row.provenance = {
            **row.provenance,
            "experimental": {"evidence_id": eid, "evidence_sha256": fingerprint(proof)},
            "captured": {
                **current,
                "status": "ACTIVE",
                "effective_status": baseline.ad_effective,
                "status_refreshed_at": baseline.source_updated_at,
                "status_source": "METRICFLOW_CATALOG_STATUS",
                "experimental_parent_statuses": {
                    "campaign": "PAUSED",
                    "adset": "PAUSED",
                },
            },
        }
        s.flush()
        return {
            "request_id": row.id,
            "revision": row.revision,
            "status": "PREPARED_NO_POST_AUTHORIZATION",
            "namespace": NAMESPACE,
            "provider_namespace_confirmed": False,
            "baseline": baseline.model_dump(),
            "expires_at": row.provenance["expires_at"],
            "baseline_expires_at": (
                datetime.fromisoformat(baseline.source_updated_at)
                + timedelta(seconds=900)
            ).isoformat(),
            "max_post_attempts": 1,
            "max_prepost_get_attempts": 3,
            "authorization_statement_required": STATEMENT,
            "advertising_write_requests": 0,
        }


async def revalidate_before_post(contract, token: str, *, transport=None) -> None:
    """Re-read both paused parents and own AD status after the durable claim."""
    from services.actions.pilot_contract import fingerprint

    manager = ProviderManager(contract.sessions, contract.workspace)
    with contract.sessions() as s:
        row = contract._require_wire_budget(s)
        captured = row.provenance["captured"]
        review = review_for(s, row, captured, contract.clock())
        account = s.get(AdAccount, row.provenance["account_id"])
        day = contract.clock().astimezone(ZoneInfo(account.timezone)).date()
        claim = row.provenance["controlled"]["claim_id"]

    async def reserve():
        with contract.sessions.begin() as s:
            row = s.scalar(
                select(ActionRequest)
                .where(ActionRequest.id == contract.request_id)
                .with_for_update()
            )
            contract._require_wire_budget(s)
            c = dict(row.provenance["controlled"])
            n = c.get("validation_gets", 0)
            if (
                type(n) is not int
                or n >= 3
                or c.get("http_started")
                or c.get("claim_id") != claim
            ):
                raise WriteDisabled("EXPERIMENTAL_GET_BUDGET_EXHAUSTED")
            c["validation_gets"] = n + 1
            row.provenance = {**row.provenance, "controlled": c}
        await asyncio.to_thread(manager.reserve, "metricflow")

    b = review.baseline
    baseline = await collect_baseline(
        token,
        {k: getattr(b, k) for k in ("account_id", "campaign_id", "adset_id", "ad_id")},
        day,
        contract.clock,
        before_request=reserve,
        transport=transport,
    )
    with contract.sessions.begin() as s:
        row = s.scalar(
            select(ActionRequest)
            .where(ActionRequest.id == contract.request_id)
            .with_for_update()
        )
        contract._require_wire_budget(s)
        c = dict(row.provenance["controlled"])
        if (
            c.get("claim_id") != claim
            or c.get("validation_gets") != 3
            or c.get("http_started")
        ):
            raise WriteDisabled("EXPERIMENTAL_REVALIDATION_CHANGED")
        c["experimental_revalidation"] = {
            "claim_id": claim,
            "checked_at": contract.clock().isoformat(),
            "baseline_sha256": fingerprint(baseline.model_dump()),
        }
        row.provenance = {**row.provenance, "controlled": c}
        s.add(
            ActionLog(
                id=str(uuid4()),
                request_id=row.id,
                event="experimental_prepost_read_verified",
                created_at=contract.clock(),
                details={
                    "claim_id": claim,
                    "baseline": baseline.model_dump(),
                    "provider_namespace_confirmed": False,
                },
            )
        )
