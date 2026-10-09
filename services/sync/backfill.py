"""Resumable core backfill; every window uses the proven atomic insight engine."""
import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from sqlalchemy import select
from services.metricflow.secrets import read_key_file
from services.storage.database import make_engine, sessions
from services.storage.models import ApiQuota, SyncRun
from services.sync.engine import SyncEngine, aware
from services.sync.schema import InsightSchema, SchemaError

def windows(start, end, chunk_days=3):
    if start > end or not 1 <= chunk_days <= 7:
        raise ValueError("Invalid backfill window/chunk")
    while start <= end:
        stop = min(start + timedelta(days=chunk_days-1), end)
        yield start, stop
        start = stop + timedelta(days=1)

class Backfill:
    def __init__(self, sync, *, chunk_days=3):
        if sync.schema.kind != "ad" or sync.schema.config.get("endpoint","insights") != "insights":
            raise SchemaError("Backfill requires the verified ad/day core schema")
        self.sync, self.chunk_days = sync, chunk_days
        digest = hashlib.sha256(json.dumps(sync.schema.config,sort_keys=True).encode()).hexdigest()[:16]
        self.job = "backfill_" + digest

    def completed(self, start, end):
        with self.sync.sessions() as session:
            return session.scalar(select(SyncRun.id).where(
                SyncRun.workspace_id == self.sync.workspace, SyncRun.provider == "metricflow",
                SyncRun.job == self.job, SyncRun.start_day == start, SyncRun.end_day == end,
                SyncRun.status == "succeeded").limit(1))

    def plan(self, start, end):
        work=list(windows(start,end,self.chunk_days))
        pending=[(a,b) for a,b in work if not self.completed(a,b)]
        now=self.sync.clock()
        with self.sync.sessions() as session:
            quota=session.get(ApiQuota,(self.sync.workspace,"metricflow",now.date()))
            used=quota.requests if quota else 0
            blocked=session.scalar(select(ApiQuota).where(
                ApiQuota.workspace_id==self.sync.workspace,ApiQuota.provider=="metricflow",
                ApiQuota.blocked_until>now).limit(1)) is not None
        return {"start":str(start),"end":str(end),"days":(end-start).days+1,
                "windows":len(work),"pending_windows":len(pending),"completed_windows":len(work)-len(pending),
                "daily_budget":self.sync.daily_budget,"daily_used":used,
                "daily_remaining":max(0,self.sync.daily_budget-used),"provider_blocked":blocked,
                # Includes request retries (at most three attempts per page).
                "max_attempts_per_window":self.sync.max_pages*3,
                "hard_max_pending_attempts":len(pending)*self.sync.max_pages*3,
                "budget_policy":"pause between windows; never raise daily budget"}

    async def run(self, start, end, *, replay=False, progress=None):
        results=[]; requests=0; covered=0
        for a,b in windows(start,end,self.chunk_days):
            if not replay and self.completed(a,b):
                item={"start":str(a),"end":str(b),"status":"already_complete"}
            else:
                plan=self.plan(a,b)
                # Leave enough room for one fully bounded window, including retries.
                if plan["provider_blocked"] or plan["daily_remaining"] < plan["max_attempts_per_window"]:
                    return {"status":"paused_quota","days_completed":covered,"requests":requests,"windows":results}
                outcome=await self.sync.run(self.job,a,b)
                item={"start":str(a),"end":str(b),**outcome}
                if outcome.get("run_id"):
                    with self.sync.sessions() as session:
                        run=session.get(SyncRun,outcome["run_id"])
                        requests+=run.requests
                if progress:progress(item)
                results.append(item)
                if outcome["status"]!="succeeded":
                    return {"status":"paused","days_completed":covered,"requests":requests,"windows":results}
            covered+=(b-a).days+1
            if item["status"]=="already_complete":
                results.append(item)
                if progress:progress(item)
        return {"status":"succeeded","days_completed":covered,"requests":requests,"windows":results}

def main():
    parser=argparse.ArgumentParser(description="Controlled READ-only core historical backfill")
    parser.add_argument("--start",required=True,type=date.fromisoformat)
    parser.add_argument("--end",required=True,type=date.fromisoformat)
    parser.add_argument("--chunk-days",type=int,default=3)
    parser.add_argument("--max-pages",type=int,default=32)
    parser.add_argument("--execute",action="store_true")
    parser.add_argument("--replay",action="store_true")
    args=parser.parse_args()
    if os.environ.get("ACTIONS_ENABLED","false").lower()!="false" or os.environ.get("SYNC_ENABLED","false").lower()!="true":
        raise SystemExit("READ-only sync must be enabled; actions must be disabled")
    engine=make_engine()
    try:
        sync=SyncEngine(sessions(engine),InsightSchema.load(os.environ["METRICFLOW_SCHEMA_FILE"]),
             read_key_file(os.environ["METRICFLOW_READ_KEY_FILE"]),workspace=os.environ.get("WORKSPACE_ID","default"),
             daily_budget=int(os.environ.get("SYNC_DAILY_BUDGET","800")),max_pages=args.max_pages)
        backfill=Backfill(sync,chunk_days=args.chunk_days)
        plan=backfill.plan(args.start,args.end)
        print(json.dumps({"plan":plan}),flush=True)
        if args.execute:
            result=asyncio.run(backfill.run(args.start,args.end,replay=args.replay,
                progress=lambda r:print(json.dumps({"window":r}),flush=True)))
            print(json.dumps({"result":result}),flush=True)
            return 0 if result["status"]=="succeeded" else 23 if result["status"]=="paused_quota" else 22
        return 0
    finally:engine.dispose()

if __name__=="__main__":raise SystemExit(main())
