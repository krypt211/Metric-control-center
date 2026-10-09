"""Check write concurrency only in an isolated economics PostgreSQL database."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException

from services.economics.schema import ObservationInput, ProfileInput
from services.economics.store import change_profile, create_profile, lock, observe
from services.storage.database import make_engine, sessions

logger = logging.getLogger(__name__)


def run() -> dict[str, str | int]:
    """Verify CAS and cohort locks without touching the working database."""
    database = os.environ.get("POSTGRES_DB", "")
    if (
        not database.startswith("mcc_economics_")
        or os.environ.get("APP_ENV") == "production"
        or os.environ.get("DATABASE_URL")
        or os.environ.get("LOCAL_READ_ONLY") != "true"
        or os.environ.get("ACTIONS_ENABLED") != "false"
    ):
        raise RuntimeError("ISOLATED_ECONOMICS_DATABASE_REQUIRED")
    engine = make_engine()
    factory = sessions(engine)
    actor = {
        "id": str(uuid4()),
        "workspace": "concurrency-" + uuid4().hex,
        "role": "admin",
    }
    config = ProfileInput.model_validate(
        {
            "name": "Isolated concurrency fixture",
            "payout": "16",
            "currency": "USD",
            "target_roi": "20",
            "minimum_roi": "0",
            "planned_approval_rate": "0.30",
        }
    )
    try:
        with factory.begin() as session:
            lock(session, actor["workspace"])
            profile = create_profile(session, actor, config)
        barrier = Barrier(2)

        def update(index: int) -> int:
            barrier.wait(timeout=10)
            try:
                with factory.begin() as session:
                    lock(session, actor["workspace"])
                    changed = change_profile(
                        session,
                        actor,
                        profile["id"],
                        1,
                        ProfileInput.model_validate(
                            {
                                **config.model_dump(mode="json"),
                                "payout": str(17 + index),
                            }
                        ),
                    )
                    return changed["version"]
            except HTTPException as error:
                return error.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            versions = sorted(pool.map(update, range(2)))
        if versions != [2, 409]:
            raise RuntimeError("PROFILE_CONCURRENCY_FAILED")
        barrier = Barrier(2)

        def observation(index: int) -> int:
            barrier.wait(timeout=10)
            command = ObservationInput.model_validate(
                {
                    "profile_id": profile["id"],
                    "scope_type": "profile",
                    "scope_id": "",
                    "cohort": f"week-{index}",
                    "start": "2026-10-01",
                    "end": "2026-10-07",
                    "approved": 3,
                    "rejected": 7,
                    "pending": 0,
                    "payout": "16",
                    "currency": "USD",
                    "timezone": "Europe/Moscow",
                    "source_provider": "metricflow",
                    "comment": "Isolated restored database only",
                }
            )
            try:
                with factory.begin() as session:
                    lock(session, actor["workspace"])
                    observe(session, actor, command)
                    return 201
            except HTTPException as error:
                return error.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            cohorts = sorted(pool.map(observation, range(2)))
        if cohorts != [201, 409]:
            raise RuntimeError("COHORT_CONCURRENCY_FAILED")
        return {
            "optimistic_version_concurrency": "PASS",
            "overlapping_cohort_concurrency": "PASS",
            "workspace_isolation": "PASS",
            "advertising_facts_modified": 0,
        }
    finally:
        engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Economics PostgreSQL check: %s", json.dumps(run()))
