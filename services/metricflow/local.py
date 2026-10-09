"""Manual READ-only onboarding and sync, using the existing engine and secrets."""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update

from services.metricflow.errors import MetricFlowError, RateLimitExceeded
from services.metricflow.onboarding import discover
from services.metricflow.probe import check, print_summary, safe_error
from services.metricflow.reader import MetricFlowConnector
from services.metricflow.secrets import read_key_file
from services.storage.database import make_engine, sessions
from services.storage.models import ApiQuota
from services.storage.repository import insert_for
from services.sync.engine import QuotaExhausted, SyncEngine
from services.sync.schema import InsightSchema, SchemaError


class ReadBudget:
    def __init__(self, factory):
        self.factory = factory
        self.workspace = os.environ.get("WORKSPACE_ID", "default")
        self.limit = int(os.environ.get("SYNC_DAILY_BUDGET", "800"))

    async def reserve(self):
        now = datetime.now(timezone.utc)
        with self.factory.begin() as session:
            blocked = session.scalar(select(ApiQuota).where(ApiQuota.workspace_id == self.workspace, ApiQuota.provider == "metricflow", ApiQuota.blocked_until > now).limit(1))
            if blocked:
                raise QuotaExhausted()
            session.execute(insert_for(session, ApiQuota.__table__).values(workspace_id=self.workspace, provider="metricflow", utc_day=now.date(), requests=0).on_conflict_do_nothing(index_elements=["workspace_id", "provider", "utc_day"]))
            changed = session.execute(update(ApiQuota).where(ApiQuota.workspace_id == self.workspace, ApiQuota.provider == "metricflow", ApiQuota.utc_day == now.date(), ApiQuota.requests < self.limit, or_(ApiQuota.blocked_until.is_(None), ApiQuota.blocked_until <= now)).values(requests=ApiQuota.requests+1))
            if changed.rowcount != 1:
                raise QuotaExhausted()

    def block(self, retry_after):
        now = datetime.now(timezone.utc)
        tomorrow = datetime.combine(now.date()+timedelta(days=1), datetime.min.time(), timezone.utc)
        until = max(tomorrow, now+timedelta(seconds=min(retry_after or 0, 604800)))
        with self.factory.begin() as session:
            session.execute(update(ApiQuota).where(ApiQuota.workspace_id == self.workspace, ApiQuota.provider == "metricflow", ApiQuota.utc_day == now.date()).values(blocked_until=until))


async def synchronize(start=None, end=None):
    if os.environ.get("ACTIONS_ENABLED", "false").lower() == "true":
        raise RuntimeError("Refusing sync helper: ACTIONS_ENABLED must be false")
    if os.environ.get("SYNC_ENABLED", "false").lower() != "true":
        raise RuntimeError("SYNC_ENABLED must be true. Run start.bat")
    path = Path(os.environ.get("METRICFLOW_SCHEMA_FILE", "/config/metricflow-schema.json"))
    key = read_key_file(os.environ.get("METRICFLOW_READ_KEY_FILE"))
    engine = make_engine()
    factory = sessions(engine)
    budget = ReadBudget(factory)
    today = datetime.now(timezone.utc).astimezone(ZoneInfo(os.environ.get("SYNC_TIMEZONE", "Europe/Moscow"))).date()
    start, end = start or today-timedelta(days=1), end or today
    if start > end:
        raise ValueError("Invalid sync window")
    print(f"Sync window: {start} through {end} (inclusive)")
    try:
        async with MetricFlowConnector(key, before_request=budget.reserve) as reader:
            checked = await check(reader)
            print_summary(checked)
            if not path.is_file():
                print("Detecting mappings from real READ responses...")
                sample = await reader.get_insights(start, end, params={"level": "ad"})
                config = discover(checked["accounts"], sample)
                # /config is read-only in regular workers. The launcher creates
                # this onboarding container with a writable config mount only.
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
                temporary.replace(path)
                print("READ schema configured from provider fields; no key or response body was saved in config")
        schema = InsightSchema.load(str(path))
        if schema.kind != "ad" or schema.config.get("endpoint", "insights") != "insights":
            raise SchemaError("The dashboard primary schema must use ad-level insights")
        print("Schema validation: STARTED")
        print("Import: STARTED")
        result = await SyncEngine(factory, schema, key, workspace=budget.workspace, daily_budget=budget.limit).run("manual_initial", start, end)
        success = result["status"] == "succeeded"
        print("Last sync: " + ("SUCCESS" if success else "FAILED"))
        if success:
            print("READ schema: VERIFIED")
            print("Pagination: VERIFIED")
            print("Mappings: VERIFIED (CORE)")
            print("Import: SUCCESS")
            for field, label in (("accounts", "Accounts"), ("campaigns", "Campaigns"), ("adsets", "Ad Sets"), ("ads", "Ads"), ("creatives", "Creatives"), ("rows", "Metric rows")):
                print(f"{label} imported: {result[field]}")
            print("Counts refer to distinct entities processed by this run, not cumulative inserts.")
            if result["creatives"] == 0:
                print("Creatives: no creative IDs in this period/schema; preview requires provider metadata")
            print("Dashboard: http://127.0.0.1:3000")
            return 0
        print("Sync error: " + result.get("error_code", result["status"]))
        print("READ schema: FAILED" if result.get("error_code") == "SchemaError" else "Import: FAILED")
        return 23 if result.get("error_code") in ("QuotaExhausted", "RateLimitExceeded") else 21 if result.get("error_code") == "SchemaError" else 22
    except RateLimitExceeded as error:
        budget.block(error.retry_after_seconds)
        raise
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Safe MetricFlow initial READ sync")
    parser.add_argument("command", choices=["sync"])
    from datetime import date
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    args = parser.parse_args()
    if bool(args.start) != bool(args.end) or (args.start and args.start > args.end):
        parser.error("Pass both --start and --end in chronological order")
    print("MCC_APPLICATION_STARTED")
    try:
        raise SystemExit(asyncio.run(synchronize(args.start, args.end)))
    except SchemaError as error:
        print("Last sync: FAILED")
        print("READ schema: NOT VERIFIED")
        print("Schema validation failed; inspect the sanitized live contract and mappings.")
        print("Import: NOT STARTED")
        print("No partial metrics were published. The API response format needs a verified config/metricflow-schema.json; do not copy the synthetic example.")
        raise SystemExit(21) from None
    except Exception as error:
        print(safe_error(error))
        print("Last sync: FAILED")
        code = 23 if type(error).__name__ in ("QuotaExhausted", "RateLimitExceeded") else 20 if isinstance(error, MetricFlowError) else 22
        print({20: "READ API: FAILED", 23: "READ API: QUOTA BLOCKED", 22: "Local import / application: FAILED"}[code])
        print("Import: NOT STARTED")
        raise SystemExit(code) from None


if __name__ == "__main__":
    main()
