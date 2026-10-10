"""Concurrency acceptance in the isolated restored database only."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select

from services.actions.engine import ActionEngine, ActionPolicy
from services.actions.manual_schema import ManualDraftInput
from services.providers.models import ProviderAccountMapping, ProviderConnection
from services.storage.database import make_engine, sessions
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    Ad,
    AdAccount,
    AdSet,
    Campaign,
    Entity,
    EntityCurrentState,
    User,
)
from services.sync.engine import utc_now


def run() -> dict:
    if not os.environ.get("POSTGRES_DB", "").startswith("mcc_phase4_"):
        raise RuntimeError("ISOLATED_RESTORE_REQUIRED")
    db = make_engine()
    factory = sessions(db)
    now = utc_now()
    workspace = "manual-test-" + uuid4().hex
    ids = {key: str(uuid4()) for key in ("actor", "account", "campaign", "adset", "ad")}
    actor = {"id": ids["actor"], "workspace": workspace, "role": "admin"}
    try:
        with factory.begin() as s:
            s.add(
                User(
                    id=ids["actor"],
                    workspace_id=workspace,
                    email=workspace,
                    role="admin",
                )
            )
            s.add(
                AdAccount(
                    id=ids["account"],
                    workspace_id=workspace,
                    provider="metricflow",
                    external_id="act_999000",
                    currency="USD",
                    timezone="Europe/Moscow",
                    observed_at=now,
                )
            )
            s.flush()
            for key, external in (
                ("campaign", "999001"),
                ("adset", "999002"),
                ("ad", "999003"),
            ):
                s.add(
                    Entity(
                        id=ids[key],
                        account_id=ids["account"],
                        kind=key,
                        external_id=external,
                        name="Isolated acceptance",
                    )
                )
            s.flush()
            s.add(Campaign(entity_id=ids["campaign"]))
            s.flush()
            s.add(AdSet(entity_id=ids["adset"], campaign_id=ids["campaign"]))
            s.flush()
            s.add(Ad(entity_id=ids["ad"], adset_id=ids["adset"]))
            s.add(
                EntityCurrentState(
                    entity_id=ids["ad"], status="ACTIVE", observed_at=now, raw={}
                )
            )
            s.add(
                ProviderAccountMapping(
                    account_id=ids["account"],
                    workspace_id=workspace,
                    canonical_id=ids["account"],
                    meta_account_id="act_999000",
                    proof="isolated_mock",
                    updated_at=now,
                )
            )
            s.add(
                ProviderConnection(
                    workspace_id=workspace,
                    provider="metricflow",
                    enabled=True,
                    status="healthy",
                    revision=1,
                    config={},
                    permissions={},
                    capabilities={},
                    quota={},
                    updated_at=now,
                )
            )
        engine = ActionEngine(factory, ActionPolicy())
        command = ManualDraftInput(
            entity_id=ids["ad"],
            account_id=ids["account"],
            meta_ad_id="999003",
            provider="metricflow",
            operation="PAUSE_AD",
            expected_status="ACTIVE",
            reason="Isolated concurrency acceptance",
        )

        def prepare(key):
            try:
                return engine.prepare_manual(actor, command, key)
            except HTTPException as error:
                return {"error": error.detail}

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(prepare, ["same-key"] * 8))
        assert len({r["id"] for r in results}) == 1
        row = results[0]
        with ThreadPoolExecutor(max_workers=8) as pool:
            conflicts = list(pool.map(prepare, [f"other-{i}" for i in range(8)]))
        assert all(r == {"error": "PENDING_ACTION_CONFLICT"} for r in conflicts)
        row = engine.transition_manual(actor, row["id"], "preflight", row["revision"])
        assert row["preflight"]["local_allowed"]

        def confirm(_):
            try:
                return engine.transition_manual(
                    actor, row["id"], "confirm", row["revision"]
                )
            except HTTPException as error:
                return {"error": error.detail}

        with ThreadPoolExecutor(max_workers=8) as pool:
            confirmations = list(pool.map(confirm, range(8)))
        assert sum(r.get("status") == "CONFIRMED" for r in confirmations) == 1
        confirmed = next(r for r in confirmations if r.get("status") == "CONFIRMED")
        result = engine.transition_manual(
            actor, row["id"], "simulate", confirmed["revision"]
        )
        assert result["status"] == "SIMULATED"
        with factory() as s:
            assert s.get(EntityCurrentState, ids["ad"]).status == "ACTIVE"
            assert (
                s.scalar(
                    select(func.count())
                    .select_from(ActionExecution)
                    .join(ActionRequest)
                    .where(ActionRequest.workspace_id == workspace)
                )
                == 0
            )
        return {
            "postgres_manual": "PASS",
            "same_key_threads": 8,
            "conflicting_threads": 8,
            "confirmation_threads": 8,
            "provider_http": 0,
        }
    finally:
        with factory.begin() as s:
            requests = select(ActionRequest.id).where(
                ActionRequest.workspace_id == workspace
            )
            for model in (ActionLog, ActionExecution):
                s.execute(delete(model).where(model.request_id.in_(requests)))
            s.execute(
                delete(ActionRequest).where(ActionRequest.workspace_id == workspace)
            )
            s.execute(
                delete(EntityCurrentState).where(
                    EntityCurrentState.entity_id == ids["ad"]
                )
            )
            for model, key in ((Ad, "ad"), (AdSet, "adset"), (Campaign, "campaign")):
                s.execute(delete(model).where(model.entity_id == ids[key]))
            s.execute(delete(Entity).where(Entity.account_id == ids["account"]))
            s.execute(
                delete(ProviderAccountMapping).where(
                    ProviderAccountMapping.workspace_id == workspace
                )
            )
            s.execute(
                delete(ProviderConnection).where(
                    ProviderConnection.workspace_id == workspace
                )
            )
            s.execute(delete(AdAccount).where(AdAccount.id == ids["account"]))
            s.execute(delete(User).where(User.id == ids["actor"]))
        db.dispose()
