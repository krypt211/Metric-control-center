"""Explicitly unverified-ID preparation; shares the existing single-use executor."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Literal, Self
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import select

from services.actions.factory import checked_write_state, credential_digest
from services.actions.manual import snapshot
from services.actions.manual_schema import ManualDraftInput
from services.actions.rule_pilot import (
    STATEMENT as RULE_STATEMENT,
)
from services.actions.rule_pilot import (
    RulePilotBinding,
    bind_rule_source,
    require_rule_source,
)
from services.metricflow.errors import MetricFlowError, RateLimitExceeded
from services.metricflow.reader import MetricFlowConnector
from services.providers.contracts import WriteDisabled
from services.providers.manager import ProviderManager
from services.providers.models import ProviderConnection
from services.storage.models import ActionLog, ActionRequest, AdAccount, Entity, User

EVENT = "pilot_experimental_prepared"
REVOKED = "pilot_experimental_revoked"
STATEMENT = "AUTHORIZE_ONE_EXPERIMENTAL_PAUSE_WITH_UNVERIFIED_ID"
ENABLE_STATEMENT = "AUTHORIZE_ONE_EXPERIMENTAL_ENABLE_WITH_UNVERIFIED_ID"
ADSET_STATEMENT = "AUTHORIZE_ONE_EXPERIMENTAL_ENABLE_ADSET_WITH_UNVERIFIED_ID"
ADSET_NAMESPACE = "UNVERIFIED_CANDIDATE_FACEBOOK_ADSET_ID"


def authorization_statement(operation: str) -> str:
    if operation == "PAUSE_AD":
        return STATEMENT
    if operation == "ENABLE_AD":
        return ENABLE_STATEMENT
    if operation == "ENABLE_ADSET":
        return ADSET_STATEMENT
    raise WriteDisabled("EXPERIMENTAL_OPERATION_INVALID")


PREPARE = "PREPARE_EXPERIMENT_ONLY_NO_POST"
NAMESPACE = "UNVERIFIED_CANDIDATE_FACEBOOK_AD_ID"


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class ExperimentalPrepareInput(StrictModel):
    entity_id: str = Field(min_length=1, max_length=36)
    credential_revision: int = Field(ge=1)
    management_confirmed: Literal[True]
    statement: Literal["PREPARE_EXPERIMENT_ONLY_NO_POST"]
    operation: Literal["PAUSE_AD", "ENABLE_AD", "ENABLE_ADSET"] = "PAUSE_AD"
    simulation_id: str | None = Field(default=None, min_length=1, max_length=36)
    previous_pause_request_id: str | None = Field(
        default=None, min_length=1, max_length=36
    )

    previous_ad_request_id: str | None = Field(
        default=None, min_length=1, max_length=36
    )

    @model_validator(mode="after")
    def require_previous_pause(self) -> Self:
        if self.simulation_id and self.operation != "PAUSE_AD":
            raise ValueError("Rule pilot supports only one PAUSE_AD")
        if (self.operation == "ENABLE_AD") != bool(self.previous_pause_request_id):
            raise ValueError(
                "ENABLE requires a previous PAUSE; PAUSE cannot reference one"
            )
        if (self.operation == "ENABLE_ADSET") != bool(self.previous_ad_request_id):
            raise ValueError("ADSET test requires the completed AD test reference")
        return self

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
    ad_status: Literal["ACTIVE", "PAUSED"]
    ad_effective: Literal["ADSET_PAUSED", "PAUSED"]
    source_updated_at: str

    def fresh(self, now: datetime) -> None:
        try:
            at = datetime.fromisoformat(self.source_updated_at)
            if at.tzinfo is None or not -60 <= (now - at).total_seconds() <= 900:
                raise ValueError()
        except (TypeError, ValueError):
            raise WriteDisabled("EXPERIMENTAL_BASELINE_STALE") from None


class ChildAd(StrictModel):
    id: str = Field(pattern=r"^[0-9]{1,128}$")
    status: Literal["ACTIVE", "PAUSED"]


class AdsetBaseline(StrictModel):
    account_id: str = Field(pattern=r"^act_[0-9]{1,128}$")
    campaign_id: str = Field(pattern=r"^[0-9]{1,128}$")
    adset_id: str = Field(pattern=r"^[0-9]{1,128}$")
    campaign_status: Literal["PAUSED"]
    campaign_effective: Literal["PAUSED"]
    adset_status: Literal["PAUSED"]
    adset_effective: Literal["PAUSED"]
    children: list[ChildAd] = Field(min_length=1, max_length=500)
    source_updated_at: str

    def fresh(self, now: datetime) -> None:
        Baseline.fresh(self, now)


def own_status(baseline: Baseline | AdsetBaseline) -> str:
    return (
        baseline.adset_status
        if isinstance(baseline, AdsetBaseline)
        else baseline.ad_status
    )


def own_effective(baseline: Baseline | AdsetBaseline) -> str:
    return (
        baseline.adset_effective
        if isinstance(baseline, AdsetBaseline)
        else baseline.ad_effective
    )


def parent_statuses(baseline: Baseline | AdsetBaseline) -> dict[str, str]:
    result = {"campaign": baseline.campaign_status}
    if isinstance(baseline, Baseline):
        result["adset"] = baseline.adset_status
    return result


class ExperimentalReview(StrictModel):
    provider: Literal["metricflow"] = "metricflow"
    wire_revision: Literal["status-sync-v1"] = "status-sync-v1"
    operation: Literal["PAUSE_AD", "ENABLE_AD", "ENABLE_ADSET"] = "PAUSE_AD"
    entity_id_namespace: Literal[
        "UNVERIFIED_CANDIDATE_FACEBOOK_AD_ID", "UNVERIFIED_CANDIDATE_FACEBOOK_ADSET_ID"
    ] = NAMESPACE
    source_kind: Literal["USER_REQUESTED_EXPERIMENT"] = "USER_REQUESTED_EXPERIMENT"
    preparation_statement: Literal["PREPARE_EXPERIMENT_ONLY_NO_POST"]
    reviewed_by: str
    baseline: Baseline | AdsetBaseline
    previous_pause: dict | None = None
    rule_binding: RulePilotBinding | None = None

    @model_validator(mode="after")
    def validate_operation_baseline(self) -> Self:
        require_operation_baseline(self.baseline, self.operation)
        expected_namespace = (
            ADSET_NAMESPACE if self.operation == "ENABLE_ADSET" else NAMESPACE
        )
        if self.entity_id_namespace != expected_namespace:
            raise ValueError("Namespace does not match level")
        if (self.operation == "ENABLE_AD") != bool(self.previous_pause):
            raise ValueError("Previous PAUSE reference does not match operation")
        return self


def require_operation_baseline(
    baseline: Baseline | AdsetBaseline, operation: str
) -> None:
    if operation == "ENABLE_ADSET":
        if not isinstance(baseline, AdsetBaseline):
            raise WriteDisabled("EXPERIMENTAL_LEVEL_MISMATCH")
        return
    if not isinstance(baseline, Baseline):
        raise WriteDisabled("EXPERIMENTAL_LEVEL_MISMATCH")
    expected = (
        ("ACTIVE", "ADSET_PAUSED") if operation == "PAUSE_AD" else ("PAUSED", "PAUSED")
    )
    if (
        operation not in ("PAUSE_AD", "ENABLE_AD")
        or (baseline.ad_status, baseline.ad_effective) != expected
    ):
        raise WriteDisabled("EXPERIMENTAL_STATUS_OR_SHAPE_CHANGED")


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
) -> Baseline | AdsetBaseline:
    """Exactly three documented GETs, no pagination guessing or retries."""
    payloads = []
    async with MetricFlowConnector(
        token, read_retries=0, before_request=before_request, transport=transport
    ) as client:
        for kind in ("campaigns", "adsets", "ads"):
            payloads.append(
                await getattr(client, "get_" + kind)(identity["account_id"], day, day)
            )
    if "ad_id" not in identity:
        c = selected(payloads[0], identity["campaign_id"])
        group = selected(payloads[1], identity["adset_id"])
        ads = payloads[2]
        # Reuse strict completeness validation without selecting another target.
        if (
            not isinstance(ads, dict)
            or not isinstance(ads.get("data"), list)
            or not ads["data"]
            or not isinstance(ads["data"][0], dict)
        ):
            raise WriteDisabled("EXPERIMENTAL_CHILD_INVENTORY_REQUIRED")
        selected(ads, ads["data"][0].get("id"))
        children = [
            r for r in ads["data"] if r.get("parent_id") == identity["adset_id"]
        ]
        stamps = [v["meta"].get("data_updated_at") for v in payloads]
        if (
            not isinstance(stamps[0], str)
            or len(set(stamps)) != 1
            or group.get("campaign_id") != identity["campaign_id"]
            or group.get("parent_id") != identity["campaign_id"]
            or any(r.get("campaign_id") != identity["campaign_id"] for r in children)
            or len({r.get("id") for r in children}) != len(children)
        ):
            raise WriteDisabled("EXPERIMENTAL_GROUP_SNAPSHOT_CHANGED")
        try:
            baseline = AdsetBaseline.model_validate(
                {
                    **identity,
                    "campaign_status": c.get("status"),
                    "campaign_effective": c.get("effective_status"),
                    "adset_status": group.get("status"),
                    "adset_effective": group.get("effective_status"),
                    "children": [
                        {"id": r.get("id"), "status": r.get("status")}
                        for r in sorted(children, key=lambda r: r.get("id", ""))
                    ],
                    "source_updated_at": stamps[0],
                }
            )
        except ValidationError:
            raise WriteDisabled("EXPERIMENTAL_GROUP_BASELINE_INVALID") from None
        baseline.fresh(now())
        return baseline
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
    if captured.get("entity_level") == "adset":
        return {
            "account_id": captured["meta_account_id"],
            "adset_id": captured["external_id"],
            "campaign_id": captured["hierarchy"][1],
        }
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
        row.action != review.operation
        or row.value is not None
        or review.reviewed_by != row.initiator_id
        or any(getattr(review.baseline, k) != v for k, v in expected.items())
        or evidence.details.get("read_revision") != current["credential_revision"]
    ):
        raise WriteDisabled("EXPERIMENTAL_BINDING_CHANGED")
    require_rule_source(session, row, review.rule_binding, now)
    review.baseline.fresh(now)
    if review.operation == "ENABLE_AD":
        from services.actions.experimental_reconciliation import require_previous_pause

        require_previous_pause(session, row, review.previous_pause)
    return review


def execution_snapshot(session, row, current: dict, now: datetime) -> dict:
    if not row.provenance.get("experimental"):
        return current
    review = review_for(session, row, current, now)
    b = review.baseline
    return {
        **current,
        "status": own_status(b),
        "effective_status": own_effective(b),
        "status_refreshed_at": b.source_updated_at,
        "status_source": "METRICFLOW_CATALOG_STATUS",
        "experimental_parent_statuses": parent_statuses(b),
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
            or entity.kind != ("adset" if body.operation == "ENABLE_ADSET" else "ad")
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
    require_operation_baseline(baseline, body.operation)
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
    previous_pause = None
    if body.operation == "ENABLE_AD":
        from services.actions.experimental_reconciliation import review_previous_pause

        previous_pause = review_previous_pause(engine, actor, body, baseline)
    if body.operation == "ENABLE_ADSET":
        from services.actions.experimental_reconciliation import (
            review_ad_enable_for_group,
        )

        review_ad_enable_for_group(engine, actor, body.previous_ad_request_id, baseline)
    draft = engine.prepare_manual(
        actor,
        ManualDraftInput(
            entity_id=body.entity_id,
            account_id=account_local_id,
            meta_ad_id=current["external_id"],
            entity_level=current["entity_level"],
            provider="metricflow",
            operation=body.operation,
            expected_status=own_status(baseline),
            simulation_id=body.simulation_id,
            reason="Experimental pilot preparation only; WRITE ID is unverified",
        ),
        "experimental-" + str(uuid4()),
    )
    with engine.sessions.begin() as s:
        row = engine._locked_manual_row(s, actor, draft["id"])
        if body.simulation_id and (
            row.status != "DRAFT"
            or row.provenance.get("controlled")
            or row.provenance.get("experimental")
        ):
            raise WriteDisabled("RULE_PILOT_ALREADY_PREPARED")
        eid = str(uuid4())
        review = ExperimentalReview(
            preparation_statement=PREPARE,
            reviewed_by=actor["id"],
            baseline=baseline,
            operation=body.operation,
            entity_id_namespace=ADSET_NAMESPACE
            if body.operation == "ENABLE_ADSET"
            else NAMESPACE,
            previous_pause=previous_pause,
            rule_binding=bind_rule_source(s, row, engine.clock()),
        )
        proof = {
            "actor_id": actor["id"],
            "account_id": baseline.account_id,
            "entity_id": current["external_id"],
            "operation": body.operation,
            "credential_revision": body.credential_revision,
            "read_revision": current["credential_revision"],
            "entity_id_namespace": review.entity_id_namespace,
            "configured_status": own_status(baseline),
            "effective_status": own_effective(baseline),
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
                "status": own_status(baseline),
                "effective_status": own_effective(baseline),
                "status_refreshed_at": baseline.source_updated_at,
                "status_source": "METRICFLOW_CATALOG_STATUS",
                "experimental_parent_statuses": parent_statuses(baseline),
            },
        }
        s.flush()
        return {
            "request_id": row.id,
            "revision": row.revision,
            "status": "PREPARED_NO_POST_AUTHORIZATION",
            "namespace": review.entity_id_namespace,
            "provider_namespace_confirmed": False,
            "baseline": baseline.model_dump(),
            "expires_at": row.provenance["expires_at"],
            "baseline_expires_at": (
                datetime.fromisoformat(baseline.source_updated_at)
                + timedelta(seconds=900)
            ).isoformat(),
            "max_post_attempts": 1,
            "max_prepost_get_attempts": 3,
            "authorization_statement_required": (
                RULE_STATEMENT
                if review.rule_binding
                else authorization_statement(body.operation)
            ),
            "rule_source": row.provenance.get("rule_source"),
            "operation": body.operation,
            "previous_pause": previous_pause,
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
        identity_for(captured),
        day,
        contract.clock,
        before_request=reserve,
        transport=transport,
    )
    require_operation_baseline(baseline, contract.operation)
    if isinstance(baseline, AdsetBaseline) and baseline.children != b.children:
        raise WriteDisabled("EXPERIMENTAL_CHILD_INVENTORY_CHANGED")
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
