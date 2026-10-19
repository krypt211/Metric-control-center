"""One-attempt MOCK_ONLY acceptance in a private restored PostgreSQL schema."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import func, select, text

from services.actions.capabilities import ActionCapabilityRegistry
from services.actions.engine import ActionEngine, ActionPolicy
from services.actions.manual_schema import ManualDraftInput
from services.actions.pilot import (
    EVIDENCE_EVENT,
    PilotAuthorizationInput,
    PilotReadbackInput,
    authorize_pilot,
    execute_pilot,
    record_manual_readback,
)
from services.actions.safety import ActionSafetyGate
from services.actions.write_credentials import WriteCredentialVault
from services.providers.integration_models import WriteCredentialState
from services.providers.models import (
    ProviderAccountMapping,
    ProviderConnection,
    ProviderRoutingSetting,
)
from services.storage.database import database_url, make_engine, sessions
from services.storage.models import (
    ActionExecution,
    ActionLog,
    ActionRequest,
    Ad,
    AdAccount,
    AdSet,
    Base,
    Campaign,
    Entity,
    EntityCurrentState,
    User,
)

# Synthetic fixtures only; this script does not depend on pytest in runtime images.
NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)
WORKSPACE = "write-rehearsal-postgres"
ACTOR = {"id": "admin", "workspace": WORKSPACE, "role": "admin"}
TOKEN = "mfk_fixture_encrypted_postgres_write"


def seed_rehearsal(sf, vault, now):
    with sf.begin() as s:
        s.add(
            User(
                id="admin",
                workspace_id=WORKSPACE,
                email="fixture@invalid",
                role="admin",
            )
        )
        s.add(
            AdAccount(
                id="account",
                workspace_id=WORKSPACE,
                provider="metricflow",
                external_id="act_100",
                name="Synthetic account",
                currency="USD",
                timezone="Europe/Moscow",
                observed_at=now,
            )
        )
        s.flush()
        for key, kind, external in (
            ("campaign", "campaign", "1001"),
            ("adset", "adset", "1002"),
            ("ad", "ad", "1003"),
        ):
            s.add(
                Entity(
                    id=key,
                    account_id="account",
                    kind=kind,
                    external_id=external,
                    name=key,
                )
            )
        s.flush()
        s.add(Campaign(entity_id="campaign"))
        s.flush()
        s.add(AdSet(entity_id="adset", campaign_id="campaign"))
        s.flush()
        s.add(Ad(entity_id="ad", adset_id="adset"))
        s.add(
            EntityCurrentState(entity_id="ad", status="ACTIVE", observed_at=now, raw={})
        )
        s.add(
            ProviderAccountMapping(
                account_id="account",
                workspace_id=WORKSPACE,
                canonical_id="account",
                meta_account_id="act_100",
                proof="catalog_meta_id",
                updated_at=now,
            )
        )
        s.add(
            ProviderConnection(
                workspace_id=WORKSPACE,
                provider="metricflow",
                enabled=True,
                credential_source="server",
                revision=1,
                config={},
                status="healthy",
                permissions={"read": True},
                capabilities={},
                quota={},
                updated_at=now,
            )
        )
        s.add(
            ProviderRoutingSetting(
                workspace_id=WORKSPACE,
                scope="workspace",
                primary_provider="metricflow",
                action_provider="disabled",
                updated_at=now,
            )
        )
        s.add(
            WriteCredentialState(
                workspace_id=WORKSPACE,
                revision=1,
                encrypted=vault.seal(WORKSPACE, TOKEN, 1).decode(),
                status="SCOPES_VERIFIED",
                scopes=["entities:write"],
                access_state="active_paid",
                checked_at=now,
            )
        )


def prepared(engine, entity_id="ad", external_id="1003"):
    command = ManualDraftInput(
        entity_id=entity_id,
        account_id="account",
        meta_ad_id=external_id,
        provider="metricflow",
        operation="PAUSE_AD",
        expected_status="ACTIVE",
        reason="Synthetic rehearsal",
    )
    draft = engine.prepare_manual(ACTOR, command, "mock-controlled-" + entity_id)
    checked = engine.transition_manual(
        ACTOR, draft["id"], "preflight", draft["revision"]
    )
    confirmed = engine.transition_manual(
        ACTOR, checked["id"], "confirm", checked["revision"]
    )
    return engine.prepare_rehearsal(
        ACTOR, confirmed["id"], confirmed["revision"], 1, NOW + timedelta(minutes=5)
    )


def verify_runtime_source():
    """Refuse installed stale packages instead of candidate source overlays."""
    for name, module in (
        ("engine", ActionEngine.__module__),
        ("pilot", authorize_pilot.__module__),
    ):
        expected = Path(__file__).resolve().parents[1] / f"services/actions/{name}.py"
        loaded = Path(sys.modules[module].__file__)
        if (
            hashlib.sha256(expected.read_bytes()).digest()
            != hashlib.sha256(loaded.read_bytes()).digest()
        ):
            raise RuntimeError("CANDIDATE_SOURCE_MISMATCH")


def fixture():
    """Refuse the working database before opening a connection."""
    if not (database_url().database or "").startswith("mcc_integrations_"):
        raise RuntimeError("ISOLATED_DATABASE_REQUIRED")
    verify_runtime_source()
    schema = os.environ["REHEARSAL_SCHEMA"]
    if (
        not schema.startswith("controlled_rehearsal_")
        or not schema.replace("_", "").isalnum()
    ):
        raise RuntimeError("PRIVATE_SCHEMA_REQUIRED")
    db = make_engine(database_url().set(query={"options": "-csearch_path=" + schema}))
    sf = sessions(db)
    vault = WriteCredentialVault(
        Path("/tmp/unused-rehearsal-namespace"), os.environ["REHEARSAL_CIPHER"].encode()
    )
    return db, sf, vault


def child(mode, request_id, revision):
    db, sf, vault = fixture()
    now = NOW + timedelta(seconds=121) if mode == "recover" else NOW
    engine = ActionEngine(sf, ActionPolicy(enabled=True), clock=lambda: now)

    def respond(request):
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer " + TOKEN
        assert json.loads(request.content) == {"level": "ad"}
        assert dict(request.url.params) == {"async": "true"}
        external = request.url.path.split("/")[-2]
        assert external in {"1003", "1004"}
        with sf.begin() as s:
            s.add(
                ActionLog(
                    id=str(uuid4()),
                    request_id=request_id,
                    event="mock_physical_http",
                    created_at=NOW,
                    details={"mode": "MOCK_ONLY"},
                )
            )
        if mode == "crash":
            os._exit(17)  # Durable claim + physical mock attempt survive abrupt death.
        return httpx.Response(
            202,
            json={
                "success": True,
                "entity_id": external,
                "message": "mock only",
                "job_id": 41,
            },
        )

    if mode == "recover":
        engine.verify_pending()
    with (
        patch.dict(os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}),
        patch.object(ActionSafetyGate, "require_verified_contract"),
    ):
        result = asyncio.run(
            engine.execute_rehearsal(
                ACTOR,
                request_id,
                int(revision),
                vault=vault,
                transport=httpx.MockTransport(respond),
            )
        )
    db.dispose()
    print(json.dumps({"claimed": result is not None}))


def _post_deadline_case(sf, vault, scenario, index):
    calls = []
    entity_id, external_id = "ad_" + scenario, str(1000 + index)
    with sf.begin() as session:
        session.add(
            Entity(
                id=entity_id,
                account_id="account",
                kind="ad",
                external_id=external_id,
                name="Synthetic " + scenario,
            )
        )
        session.flush()
        session.add(Ad(entity_id=entity_id, adset_id="adset"))
        session.add(
            EntityCurrentState(
                entity_id=entity_id, status="ACTIVE", observed_at=NOW, raw={}
            )
        )
    clock = [NOW]
    engine = ActionEngine(sf, ActionPolicy(enabled=True), clock=lambda: clock[0])
    permit = prepared(engine, entity_id=entity_id, external_id=external_id)

    async def respond(request):
        assert request.method == "POST"
        assert request.url.path == f"/api/v1/entities/{external_id}/pause"
        calls.append(scenario)
        if scenario == "timeout":
            await asyncio.Event().wait()
        clock[0] += (
            timedelta(minutes=6) if scenario == "deadline" else timedelta(seconds=121)
        )
        if scenario == "recovery":
            engine.verify_pending()
        return httpx.Response(
            202,
            json={
                "success": True,
                "entity_id": external_id,
                "message": "synthetic",
                "job_id": 40 + index,
            },
        )

    async def execute():
        async with asyncio.timeout(10):
            return await engine.execute_rehearsal(
                ACTOR,
                permit["id"],
                permit["revision"],
                vault=vault,
                transport=httpx.MockTransport(respond),
            )

    with (
        patch.dict(os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}),
        patch.object(ActionSafetyGate, "require_verified_contract"),
        patch("services.actions.engine.CONTROLLED_POST_TIMEOUT_SECONDS", 0.5),
    ):
        assert asyncio.run(execute()) == permit["id"]
        with sf() as session:
            row = session.get(ActionRequest, permit["id"])
            control = row.provenance["controlled"]
            assert row.status == "unknown" and control["attempts"] == 1
            assert control["observation"]["state"] == "UNARMED"
            assert control["job_id"] == (None if scenario == "timeout" else 40 + index)
        assert asyncio.run(execute()) is None
    assert len(calls) == 1
    return len(calls)


def post_deadline_cases(sf, vault):
    """Exercise late ACK/recovery/timeout using only a restored fixture schema."""
    attempts = sum(
        _post_deadline_case(sf, vault, scenario, index)
        for index, scenario in enumerate(("deadline", "recovery", "timeout"), start=5)
    )
    return {
        "cases": 3,
        "physical_mock_attempts": attempts,
        "late_ack": "UNKNOWN_WITH_JOB_ID",
        "recovery": "NOT_REOPENED",
        "timeout": "UNKNOWN_NO_RESEND",
    }


def synchronous_cases(sf, vault):
    """All six documented synchronous operations; no production namespace/transport."""
    total = 0
    for index, (level, operation) in enumerate(
        (level, operation)
        for level in ("campaign", "adset", "ad")
        for operation in ("PAUSE", "ENABLE")
    ):
        entity_id, external = f"sync-{index}", str(1080 + index)
        baseline = "ACTIVE" if operation == "PAUSE" else "PAUSED"
        with sf.begin() as session:
            session.add(
                Entity(
                    id=entity_id,
                    account_id="account",
                    kind=level,
                    external_id=external,
                    name="Synthetic sync entity",
                )
            )
            session.flush()
            if level == "campaign":
                session.add(Campaign(entity_id=entity_id))
            elif level == "adset":
                session.add(AdSet(entity_id=entity_id, campaign_id="campaign"))
            else:
                session.add(Ad(entity_id=entity_id, adset_id="adset"))
            session.add(
                EntityCurrentState(
                    entity_id=entity_id,
                    status=baseline,
                    observed_at=NOW,
                    raw={},
                )
            )
        clock = [NOW]
        engine = ActionEngine(
            sf, ActionPolicy(enabled=True), clock=lambda clock=clock: clock[0]
        )
        row = engine.prepare_manual(
            ACTOR,
            ManualDraftInput(
                entity_id=entity_id,
                entity_level=level,
                meta_ad_id=external,
                account_id="account",
                provider="metricflow",
                operation=f"{operation}_{level.upper()}",
                expected_status=baseline,
                reason="Isolated synchronous contract acceptance",
            ),
            f"sync-{index}",
        )
        for event in ("preflight", "confirm"):
            row = engine.transition_manual(ACTOR, row["id"], event, row["revision"])
        permit = engine.prepare_rehearsal(
            ACTOR,
            row["id"],
            row["revision"],
            1,
            NOW + timedelta(minutes=5),
            asynchronous=False,
        )
        calls = []

        def respond(
            request,
            *,
            expected_id=external,
            expected_level=level,
            expected_operation=operation,
            calls=calls,
        ):
            calls.append(request)
            assert request.method == "POST"
            assert (
                request.url.path
                == f"/api/v1/entities/{expected_id}/{expected_operation.lower()}"
            )
            assert not request.url.params
            assert json.loads(request.content) == {"level": expected_level}
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "entity_id": expected_id,
                    "message": "synthetic sync",
                },
            )

        async def execute(engine=engine, permit=permit, respond=respond):
            return await engine.execute_rehearsal(
                ACTOR,
                permit["id"],
                permit["revision"],
                vault=vault,
                transport=httpx.MockTransport(respond),
            )

        with (
            patch.dict(
                os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}
            ),
            patch.object(ActionSafetyGate, "require_verified_contract"),
        ):
            assert asyncio.run(execute()) == permit["id"]
            assert asyncio.run(execute()) is None
        with sf() as session:
            stored = session.get(ActionRequest, permit["id"])
            assert stored.status == "verifying"
            control = stored.provenance["controlled"]
            assert control["state"] == "SYNC_ACKNOWLEDGED_NEEDS_MANUAL_READBACK"
            assert control["job_id"] is None and control["attempts"] == 1
            assert control["observation"]["state"] == "NOT_APPLICABLE"
        clock[0] += timedelta(minutes=6)
        assert engine.verify_pending() == 0
        with sf() as session:
            assert session.get(ActionRequest, permit["id"]).status == "unknown"
        assert len(calls) == 1
        total += len(calls)
    return {
        "cases": 6,
        "physical_mock_attempts": total,
        "resend": "NONE",
        "job_gets": 0,
        "verified_ownership": 0,
    }


@contextmanager
def synthetic_pilot_gates():
    """Fixture evidence only; never change the working registry or flags."""
    original = ActionCapabilityRegistry.inspect

    def verified(*args):
        return {
            **original(*args),
            "write_permission": True,
            "operations": {"PAUSE_AD": "VERIFIED", "ENABLE_AD": "VERIFIED"},
        }

    with (
        patch.dict(os.environ, {"ACTIONS_ENABLED": "true", "LOCAL_READ_ONLY": "false"}),
        patch.object(ActionSafetyGate, "require_verified_contract"),
        patch.object(ActionCapabilityRegistry, "inspect", side_effect=verified),
    ):
        yield


def production_child(mode, request_id, revision):
    db, sf, vault = fixture()
    clock = NOW + timedelta(seconds=121) if mode == "pilot-recover" else NOW
    engine = ActionEngine(sf, ActionPolicy(enabled=True), clock=lambda: clock)

    def respond(request):
        assert request.method == "POST" and not request.url.params
        assert json.loads(request.content) == {"level": "ad"}
        external = request.url.path.split("/")[-2]
        assert external in ("1101", "1102")
        with sf.begin() as session:
            session.add(
                ActionLog(
                    id=str(uuid4()),
                    request_id=request_id,
                    created_at=NOW,
                    event="pilot_mock_physical_http",
                    details={"transport": "MOCK_ONLY"},
                )
            )
        if mode == "pilot-crash":
            os._exit(17)
        return httpx.Response(
            200, json={"success": True, "entity_id": external, "message": "fixture"}
        )

    if mode == "pilot-recover":
        engine.verify_pending()
    with synthetic_pilot_gates():
        result = asyncio.run(
            execute_pilot(
                engine,
                ACTOR,
                request_id,
                int(revision),
                vault=vault,
                transport=httpx.MockTransport(respond),
            )
        )
    db.dispose()
    print(json.dumps({"claimed": result is not None}))


def seed_pilot(sf, vault, index):
    entity_id, external = f"pilot-ad-{index}", str(1100 + index)
    with sf.begin() as session:
        session.add(
            Entity(
                id=entity_id,
                account_id="account",
                kind="ad",
                external_id=external,
                name="Synthetic pilot AD",
            )
        )
        session.flush()
        session.add(Ad(entity_id=entity_id, adset_id="adset"))
        session.add(
            EntityCurrentState(
                entity_id=entity_id, status="ACTIVE", observed_at=NOW, raw={}
            )
        )
    engine = ActionEngine(sf, ActionPolicy(enabled=True), clock=lambda: NOW)
    row = engine.prepare_manual(
        ACTOR,
        ManualDraftInput(
            entity_id=entity_id,
            entity_level="ad",
            meta_ad_id=external,
            account_id="account",
            provider="metricflow",
            operation="PAUSE_AD",
            expected_status="ACTIVE",
            reason="Isolated production-shaped pilot fixture",
        ),
        f"pilot-{index}",
    )
    for event in ("preflight", "confirm"):
        row = engine.transition_manual(ACTOR, row["id"], event, row["revision"])
    with sf.begin() as session:
        session.add(
            ActionLog(
                id=str(uuid4()),
                request_id=row["id"],
                event=EVIDENCE_EVENT,
                created_at=NOW,
                details={
                    "actor_id": ACTOR["id"],
                    "account_id": "act_100",
                    "entity_id": external,
                    "operation": "PAUSE_AD",
                    "credential_revision": 1,
                    "read_revision": 1,
                    "entity_id_namespace": "PROVIDER_AD_ID",
                    "configured_status": "ACTIVE",
                    "effective_status": "ACTIVE",
                    "permission": "MANAGE_CAMPAIGNS",
                    "permission_source": "MANUAL_META_ACCESS_REVIEW",
                    "profile_id": 123,
                    "namespace_source": "synthetic fixture only",
                },
            )
        )
    with synthetic_pilot_gates():
        return authorize_pilot(
            engine,
            ACTOR,
            row["id"],
            PilotAuthorizationInput(
                revision=row["revision"],
                credential_revision=1,
                account_id="act_100",
                entity_id=external,
                operation="PAUSE_AD",
                expected_status="ACTIVE",
                statement="AUTHORIZE_ONE_METRICFLOW_AD_STATUS_POST",
            ),
        )


def production_cases(sf, vault):
    permit = seed_pilot(sf, vault, 1)
    args = [
        sys.executable,
        __file__,
        "pilot-send",
        permit["id"],
        str(permit["revision"]),
    ]
    children = [
        subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(8)
    ]
    claims = []
    for process in children:
        out, _err = process.communicate(timeout=120)
        if process.returncode:
            raise RuntimeError("PILOT_MOCK_RACE_CHILD_FAILED")
        claims.append(json.loads(out)["claimed"])
    assert sum(claims) == 1
    again = subprocess.run(args, capture_output=True, timeout=120, check=False)
    assert again.returncode == 0 and not json.loads(again.stdout)["claimed"]
    with sf() as session:
        saved = session.get(ActionRequest, permit["id"])
        assert saved.status == "verifying"
        revision = saved.revision
    engine = ActionEngine(
        sf, ActionPolicy(enabled=True), clock=lambda: NOW + timedelta(seconds=10)
    )
    result = record_manual_readback(
        engine,
        ACTOR,
        permit["id"],
        PilotReadbackInput(
            revision=revision,
            account_id="act_100",
            entity_id="1101",
            configured_status="PAUSED",
            effective_status="PAUSED",
            observed_at=(NOW + timedelta(seconds=10)).isoformat(),
            statement="RECORD_MANUAL_META_READBACK",
        ),
    )
    assert result["status"] == "MANUALLY_REVIEWED" and not result["authoritative_api"]
    second = seed_pilot(sf, vault, 2)
    crashed = subprocess.run(
        [
            sys.executable,
            __file__,
            "pilot-crash",
            second["id"],
            str(second["revision"]),
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert crashed.returncode == 17
    recovered = subprocess.run(
        [
            sys.executable,
            __file__,
            "pilot-recover",
            second["id"],
            str(second["revision"]),
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert recovered.returncode == 0 and not json.loads(recovered.stdout)["claimed"]
    with sf() as session:
        assert session.get(ActionRequest, second["id"]).status == "unknown"
        assert (
            session.scalar(
                select(func.count())
                .select_from(ActionLog)
                .where(ActionLog.event == "pilot_mock_physical_http")
            )
            == 2
        )
    return {
        "concurrent_processes": 8,
        "race_claims": 1,
        "physical_mock_attempts": 2,
        "restart": "NO_RESEND",
        "crash_recovery": "UNKNOWN_NO_RESEND",
        "manual_record": "RECORDED_WITHOUT_API_AUTHORITY",
    }


def main():
    if not (database_url().database or "").startswith("mcc_integrations_"):
        raise RuntimeError("ISOLATED_DATABASE_REQUIRED")
    verify_runtime_source()
    admin = make_engine()
    schema = "controlled_rehearsal_" + uuid4().hex
    with admin.begin() as c:
        assert (
            c.scalar(text("SELECT version_num FROM alembic_version"))
            == "0016_smart_control"
        )
        c.execute(text("CREATE SCHEMA " + schema))
    os.environ["REHEARSAL_SCHEMA"] = schema
    os.environ["REHEARSAL_CIPHER"] = Fernet.generate_key().decode()
    db, sf, vault = fixture()
    Base.metadata.create_all(db)
    seed_rehearsal(sf, vault, NOW)
    engine = ActionEngine(sf, ActionPolicy(enabled=True), clock=lambda: NOW)
    permit = prepared(engine)
    args = [sys.executable, __file__, "send", permit["id"], str(permit["revision"])]
    children = [
        subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(8)
    ]
    results = []
    for p in children:
        out, _err = p.communicate(timeout=120)
        if p.returncode:
            raise RuntimeError("MOCK_RACE_CHILD_FAILED")
        results.append(json.loads(out))
    assert sum(v["claimed"] for v in results) == 1
    repeated = subprocess.run(args, capture_output=True, timeout=120, check=False)
    assert repeated.returncode == 0 and not json.loads(repeated.stdout)["claimed"]
    with sf() as s:
        first = s.get(ActionRequest, permit["id"])
        assert first.status == "verifying"
        assert first.provenance["controlled"]["job_id"] == 41
        assert first.provenance["controlled"]["attempts"] == 1
    with sf.begin() as s:
        s.add(
            Entity(
                id="ad2",
                account_id="account",
                kind="ad",
                external_id="1004",
                name="Synthetic second AD",
            )
        )
        s.flush()
        s.add(Ad(entity_id="ad2", adset_id="adset"))
        s.add(
            EntityCurrentState(
                entity_id="ad2", status="ACTIVE", observed_at=NOW, raw={}
            )
        )
    second = prepared(engine, entity_id="ad2", external_id="1004")
    crash = subprocess.run(
        [sys.executable, __file__, "crash", second["id"], str(second["revision"])],
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert crash.returncode == 17
    recovered = subprocess.run(
        [sys.executable, __file__, "recover", second["id"], str(second["revision"])],
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert recovered.returncode == 0 and not json.loads(recovered.stdout)["claimed"]
    with sf() as s:
        assert s.scalar(select(func.count()).select_from(ActionExecution)) == 2
        assert (
            s.scalar(
                select(func.count())
                .select_from(ActionLog)
                .where(ActionLog.event == "mock_physical_http")
            )
            == 2
        )
        assert (
            s.scalar(
                select(func.count())
                .select_from(ActionLog)
                .where(ActionLog.event == "verified")
            )
            == 0
        )
        second_row = s.get(ActionRequest, second["id"])
        assert second_row.status == "unknown"
        assert second_row.provenance["controlled"]["attempts"] == 1
        assert second_row.provenance["controlled"]["job_id"] is None
    deadlines = post_deadline_cases(sf, vault)
    synchronous = synchronous_cases(sf, vault)
    production = production_cases(sf, vault)
    print(
        json.dumps(
            {
                "database": database_url().database,
                "schema": schema,
                "concurrent_processes": 8,
                "race_claims": 1,
                "race_physical_mock_attempts": 1,
                "job_id_persisted": 41,
                "restart": "NO_RESEND",
                "abrupt_exit": 17,
                "crash_recovery": "UNKNOWN_NO_RESEND",
                "total_physical_mock_attempts": 2
                + deadlines["physical_mock_attempts"]
                + synchronous["physical_mock_attempts"]
                + production["physical_mock_attempts"],
                "post_deadline_cases": deadlines,
                "synchronous_cases": synchronous,
                "production_shaped_mock_cases": production,
                "live_provider_requests": 0,
                "advertising_write_requests": 0,
                "result": "PASS",
            }
        )
    )
    db.dispose()
    admin.dispose()


if __name__ == "__main__":
    if len(sys.argv) == 4:
        if sys.argv[1].startswith("pilot-"):
            production_child(*sys.argv[1:])
        else:
            child(*sys.argv[1:])
    else:
        main()
