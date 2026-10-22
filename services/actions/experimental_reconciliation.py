"""Local late-observation review; never certifies an API outcome or pause ownership."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select

from services.providers.contracts import WriteDisabled
from services.storage.models import ActionExecution, ActionLog, ActionRequest

EVENT = "pilot_prior_pause_locally_reviewed"
MANUAL = "pilot_late_manual_target_confirmed"


def _previous(session, prior, *, actor_id, workspace, entity_id):
    if (
        not prior
        or prior.workspace_id != workspace
        or prior.initiator_id != actor_id
        or prior.entity_id != entity_id
        or prior.action != "PAUSE_AD"
        or not prior.provenance.get("experimental")
    ):
        raise WriteDisabled("EXPERIMENTAL_PREVIOUS_PAUSE_REQUIRED")
    control = prior.provenance.get("controlled") or {}
    execution = session.scalar(
        select(ActionExecution).where(ActionExecution.request_id == prior.id)
    )
    manual = session.scalars(
        select(ActionLog)
        .where(
            ActionLog.request_id == prior.id,
            ActionLog.event.in_((MANUAL, "pilot_manual_status_mismatch_reported")),
        )
        .order_by(ActionLog.created_at.desc(), ActionLog.id.desc())
    ).first()
    proof = manual.details if manual else {}
    captured = prior.provenance["captured"]
    if (
        control.get("mode") != "LIVE_SINGLE_OPERATION"
        or control.get("attempts") != 1
        or control.get("wire_spent") is not True
        or not control.get("http_started")
        or not execution
        or execution.outcome != "live_unknown"
        or execution.error_code != "MANUAL_READBACK_DEADLINE"
        or not execution.completed_at
        or not manual
        or manual.event != MANUAL
        or proof.get("actor_id") != actor_id
        or proof.get("configured_status") != "PAUSED"
        or proof.get("matches_target") is not True
        or proof.get("late_observation") is not True
        or proof.get("ad_id") != captured["meta_ad_id"]
        or proof.get("adset_id") != captured["hierarchy"][0]
        or proof.get("campaign_id") != captured["hierarchy"][1]
        or proof.get("source") != "USER_REPLY_AFTER_ID_CLARIFICATION"
        or proof.get("authoritative_api") is not False
        or proof.get("creates_pause_ownership") is not False
    ):
        raise WriteDisabled("EXPERIMENTAL_LATE_PAUSE_REVIEW_REQUIRED")
    return control, execution, manual


def review_previous_pause(engine, actor, body, baseline) -> dict:
    """Release only a late-observed, spent PAUSE while retaining its UNKNOWN execution."""
    from services.actions.manual import snapshot
    from services.actions.pilot_contract import fingerprint
    from services.storage.models import AdAccount, Entity

    with engine.sessions.begin() as session:
        prior = engine._locked_manual_row(
            session, actor, body.previous_pause_request_id
        )
        control, execution, manual = _previous(
            session,
            prior,
            actor_id=actor["id"],
            workspace=actor["workspace"],
            entity_id=body.entity_id,
        )
        if engine.clock() < datetime.fromisoformat(control["expires_at"]):
            raise WriteDisabled("EXPERIMENTAL_PREVIOUS_WINDOW_OPEN")
        entity = session.get(Entity, body.entity_id)
        current = snapshot(session, entity, session.get(AdAccount, entity.account_id))
        if (
            baseline.ad_id != current["meta_ad_id"]
            or baseline.account_id != current["meta_account_id"]
            or [baseline.adset_id, baseline.campaign_id] != current["hierarchy"]
            or prior.provenance["captured"]["hierarchy"] != current["hierarchy"]
            or prior.provenance["captured"]["meta_account_id"]
            != current["meta_account_id"]
        ):
            raise WriteDisabled("EXPERIMENTAL_PREVIOUS_IDENTITY_CHANGED")
        baseline.fresh(engine.clock())
        if prior.status == "MANUALLY_REVIEWED":
            reference = control.get("late_local_review")
            require_previous_pause(session, prior, reference)
            return reference
        if prior.status != "unknown":
            raise WriteDisabled("EXPERIMENTAL_PREVIOUS_STATE_CHANGED")
        proof = {
            "request_id": prior.id,
            "actor_id": actor["id"],
            "entity_id": body.entity_id,
            "manual_evidence_id": manual.id,
            "manual_evidence_sha256": fingerprint(manual.details),
            "baseline": baseline.model_dump(),
            "execution_outcome": execution.outcome,
            "execution_error_code": execution.error_code,
            "authoritative_api": False,
            "creates_pause_ownership": False,
            "reason": "LATE_MANUAL_AND_FRESH_READ_MATCH",
        }
        eid = str(uuid4())
        session.add(
            ActionLog(
                id=eid,
                request_id=prior.id,
                event=EVENT,
                created_at=engine.clock(),
                details=proof,
            )
        )
        reference = {
            "request_id": prior.id,
            "evidence_id": eid,
            "evidence_sha256": fingerprint(proof),
        }
        prior.provenance = {
            **prior.provenance,
            "controlled": {**control, "late_local_review": reference},
        }
        prior.status = "MANUALLY_REVIEWED"
        prior.revision += 1
        # Keep OUTCOME_UNKNOWN, original deadline error/outcome, spent wire and all historical logs.
        return reference


def require_previous_pause(session, row, reference) -> None:
    """Recheck pinned local resolution at each future ENABLE contract boundary."""
    from services.actions.pilot_contract import fingerprint

    if not isinstance(reference, dict) or set(reference) != {
        "request_id",
        "evidence_id",
        "evidence_sha256",
    }:
        raise WriteDisabled("EXPERIMENTAL_PREVIOUS_REVIEW_CHANGED")
    prior = session.get(ActionRequest, reference["request_id"])
    _control, _execution, manual = _previous(
        session,
        prior,
        actor_id=row.initiator_id,
        workspace=row.workspace_id,
        entity_id=row.entity_id,
    )
    proof = session.get(ActionLog, reference["evidence_id"])
    if (
        prior.status != "MANUALLY_REVIEWED"
        or not proof
        or proof.event != EVENT
        or proof.request_id != prior.id
        or fingerprint(proof.details) != reference["evidence_sha256"]
        or proof.details.get("manual_evidence_id") != manual.id
        or proof.details.get("manual_evidence_sha256") != fingerprint(manual.details)
        or (prior.provenance.get("controlled") or {}).get("late_local_review")
        != reference
    ):
        raise WriteDisabled("EXPERIMENTAL_PREVIOUS_REVIEW_CHANGED")


def review_ad_enable_for_group(engine, actor, request_id, baseline) -> None:
    """Locally close only the spent, manually observed child ENABLE; API UNKNOWN stays."""
    from services.actions.pilot_contract import fingerprint
    from services.storage.models import Ad, Entity

    with engine.sessions.begin() as session:
        row = engine._locked_manual_row(session, actor, request_id)
        control = row.provenance.get("controlled") or {}
        execution = session.scalar(
            select(ActionExecution).where(ActionExecution.request_id == row.id)
        )
        child = session.get(Ad, row.entity_id)
        group = session.get(Entity, child.adset_id) if child else None
        if (
            row.action != "ENABLE_AD"
            or row.initiator_id != actor["id"]
            or not row.provenance.get("experimental")
            or not group
            or group.external_id != baseline.adset_id
            or row.provenance["captured"]["meta_account_id"] != baseline.account_id
            or row.provenance["captured"]["hierarchy"][1] != baseline.campaign_id
            or not any(
                c.id == row.provenance["captured"]["meta_ad_id"]
                and c.status == "ACTIVE"
                for c in baseline.children
            )
            or control.get("mode") != "LIVE_SINGLE_OPERATION"
            or control.get("attempts") != 1
            or control.get("wire_spent") is not True
            or not execution
            or execution.outcome != "live_unknown"
            or execution.error_code != "MANUAL_READBACK_DEADLINE"
            or engine.clock() < datetime.fromisoformat(control["expires_at"])
        ):
            raise WriteDisabled("EXPERIMENTAL_CHILD_ENABLE_REVIEW_REQUIRED")
        proofs = []
        for event in (
            "pilot_manual_enable_target_confirmed",
            "pilot_manual_enable_parents_confirmed",
            "pilot_manual_effective_status_confirmed",
        ):
            log = session.scalars(
                select(ActionLog)
                .where(ActionLog.request_id == row.id, ActionLog.event == event)
                .order_by(ActionLog.created_at.desc())
            ).first()
            if (
                not log
                or log.details.get("actor_id") != actor["id"]
                or log.details.get("ad_id") != row.provenance["captured"]["meta_ad_id"]
                or log.details.get("configured_status") != "ACTIVE"
            ):
                raise WriteDisabled("EXPERIMENTAL_CHILD_MANUAL_REVIEW_REQUIRED")
            if event != "pilot_manual_enable_target_confirmed" and (
                log.details.get("campaign_status") != "PAUSED"
                or log.details.get("adset_status") != "PAUSED"
            ):
                raise WriteDisabled("EXPERIMENTAL_CHILD_MANUAL_REVIEW_REQUIRED")
            if (
                event == "pilot_manual_effective_status_confirmed"
                and log.details.get("effective_status") != "ADSET_PAUSED"
            ):
                raise WriteDisabled("EXPERIMENTAL_CHILD_MANUAL_REVIEW_REQUIRED")
            proofs.append({"id": log.id, "sha256": fingerprint(log.details)})
        baseline.fresh(engine.clock())
        if (
            row.status == "MANUALLY_REVIEWED"
            and control.get("adset_pilot_local_review") == proofs
        ):
            return
        if row.status != "unknown":
            raise WriteDisabled("EXPERIMENTAL_CHILD_REVIEW_STATE_CHANGED")
        row.provenance = {
            **row.provenance,
            "controlled": {**control, "adset_pilot_local_review": proofs},
        }
        row.status = "MANUALLY_REVIEWED"
        row.revision += 1
        session.add(
            ActionLog(
                id=str(uuid4()),
                request_id=row.id,
                event="pilot_ad_enable_locally_reviewed_for_group",
                created_at=engine.clock(),
                details={
                    "actor_id": actor["id"],
                    "baseline": baseline.model_dump(),
                    "manual_evidence": proofs,
                    "authoritative_api": False,
                    "creates_pause_ownership": False,
                    "execution_outcome_preserved": "live_unknown",
                },
            )
        )


SPENT_ADSET_REVIEW = "ACKNOWLEDGE_SPENT_ADSET_ENABLE_UNKNOWN_NO_RESEND"


def review_spent_adset_enable(
    engine, actor, request_id: str, revision: int, *, acknowledgement: str | None = None
) -> dict:
    """Preview or explicitly acknowledge a late-reviewed spent group ENABLE.

    Only the local request is closed. The execution remains UNKNOWN; its attempt,
    wire claim, original response/audit and absence of pause ownership are retained.
    """
    from services.actions.manual import snapshot
    from services.storage.models import AdAccount, Entity
    from services.sync.engine import aware

    with engine.sessions.begin() as session:
        row = engine._locked_manual_row(session, actor, request_id)
        control = row.provenance.get("controlled") or {}
        marker = control.get("spent_adset_local_review")
        if (
            acknowledgement == SPENT_ADSET_REVIEW
            and marker
            == {
                "actor_id": actor["id"],
                "revision": revision,
                "statement": SPENT_ADSET_REVIEW,
            }
            and row.status == "MANUALLY_REVIEWED"
        ):
            return {
                "request_id": row.id,
                "revision": row.revision,
                "status": row.status,
                "applied": True,
                "idempotent": True,
            }
        execution = session.scalar(
            select(ActionExecution).where(ActionExecution.request_id == row.id)
        )
        ack = session.scalar(
            select(ActionLog.id)
            .where(
                ActionLog.request_id == row.id,
                ActionLog.event == "controlled_live_acknowledged",
            )
            .limit(1)
        )
        manual = control.get("manual_readback") or {}
        captured = row.provenance.get("captured") or {}
        entity = session.get(Entity, row.entity_id)
        account = session.get(AdAccount, entity.account_id) if entity else None
        try:
            expires = datetime.fromisoformat(control["expires_at"])
            observed = datetime.fromisoformat(manual["observed_at"])
        except (KeyError, TypeError, ValueError):
            raise WriteDisabled("SPENT_ADSET_REVIEW_EVIDENCE_REQUIRED") from None
        if (
            row.revision != revision
            or row.status != "unknown"
            or row.action != "ENABLE_ADSET"
            or not row.provenance.get("experimental")
            or not entity
            or entity.kind != "adset"
            or not account
            or account.workspace_id != actor["workspace"]
            or account.provider != "metricflow"
            or control.get("mode") != "LIVE_SINGLE_OPERATION"
            or control.get("response_mode") != "SYNC_200"
            or control.get("attempts") != 1
            or control.get("wire_spent") is not True
            or control.get("http_started") is not True
            or control.get("job_id") is not None
            or not execution
            or execution.outcome != "live_unknown"
            or execution.error_code not in (None, "MANUAL_READBACK_DEADLINE")
            or not execution.completed_at
            or not ack
            or expires.tzinfo is None
            or observed.tzinfo is None
            or engine.clock() <= expires
            or observed <= expires
            or observed < aware(execution.completed_at)
            or manual.get("actor_id") != actor["id"]
            or manual.get("entity_id") != entity.external_id
            or manual.get("account_id") != account.external_id
            or manual.get("configured_status") != "ACTIVE"
            or manual.get("authoritative_api") is not False
            or manual.get("creates_pause_ownership") is not False
        ):
            raise WriteDisabled("SPENT_ADSET_REVIEW_EVIDENCE_REQUIRED")
        current = snapshot(session, entity, account)
        if any(
            current.get(k) != captured.get(k)
            for k in (
                "entity_id",
                "entity_level",
                "meta_ad_id",
                "account_id",
                "meta_account_id",
                "hierarchy",
                "provider",
                "routing",
            )
        ):
            raise WriteDisabled("SPENT_ADSET_REVIEW_IDENTITY_CHANGED")
        result = {
            "request_id": row.id,
            "revision": row.revision,
            "operation": row.action,
            "account_id": account.external_id,
            "entity_id": entity.external_id,
            "status": row.status,
            "proposed_status": "MANUALLY_REVIEWED",
            "execution_outcome_preserved": execution.outcome,
            "creates_pause_ownership": False,
            "provider_requests": 0,
            "required_acknowledgement": SPENT_ADSET_REVIEW,
            "applied": False,
        }
        if acknowledgement is None:
            return result
        if acknowledgement != SPENT_ADSET_REVIEW:
            raise WriteDisabled("SPENT_ADSET_REVIEW_ACKNOWLEDGEMENT_REQUIRED")
        row.provenance = {
            **row.provenance,
            "controlled": {
                **control,
                "spent_adset_local_review": {
                    "actor_id": actor["id"],
                    "revision": revision,
                    "statement": SPENT_ADSET_REVIEW,
                },
            },
        }
        row.status = "MANUALLY_REVIEWED"
        row.revision += 1
        session.add(
            ActionLog(
                id=str(uuid4()),
                request_id=row.id,
                event="pilot_spent_adset_outcome_locally_reviewed",
                created_at=engine.clock(),
                details={
                    "actor_id": actor["id"],
                    "previous_revision": revision,
                    "statement": SPENT_ADSET_REVIEW,
                    "authoritative_api": False,
                    "creates_pause_ownership": False,
                    "execution_outcome_preserved": "live_unknown",
                    "no_resend": True,
                },
            )
        )
        return {
            **result,
            "revision": row.revision,
            "status": row.status,
            "applied": True,
        }
