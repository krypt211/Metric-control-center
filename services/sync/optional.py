"""GET-only optional refresh; preserve account/day and exact creative-window scopes."""
import argparse
from copy import copy
import asyncio
from datetime import date
import hashlib
import json
import os
from uuid import uuid4
from sqlalchemy import delete, select, update
from services.analytics.scopes import creative_window, tracker_days, tracker_ad_windows
from services.metricflow.errors import RateLimitExceeded
from services.metricflow.reader import MetricFlowConnector
from services.metricflow.secrets import read_key_file
from services.storage.database import make_engine, sessions
from services.storage.models import AdAccount, ReadStatistic, SyncLease, SyncRun
from services.storage.repository import identity, upsert
from services.sync.engine import SyncEngine, QuotaExhausted, LeaseLost, aware
from services.sync.schema import InsightSchema, SchemaError

class OptionalSync:
    def __init__(self,sync):
        self.sync=copy(sync)
        self.sync.lease_key=f"{sync.workspace}:metricflow:optional"
    async def run(self,start,end):
        if start>end:raise ValueError("Invalid window")
        s=self.sync; owner=str(uuid4());run_id=str(uuid4());now=s.clock()
        if not s.claim(owner):return {"status":"skipped_overlap"}
        with s.sessions.begin() as session:
            session.add(SyncRun(id=run_id,workspace_id=s.workspace,provider="metricflow",job="optional_read",
                status="running",start_day=start,end_day=end,started_at=now,requests=0,pages=0,rows=0))
        rows=0;errors=[]
        try:
            with s.sessions() as session:
                accounts=session.scalars(select(AdAccount).where(AdAccount.workspace_id==s.workspace,AdAccount.provider=="metricflow")).all()
            if not accounts:raise SchemaError("Core account catalog must be synchronized first")
            async def reserve():s.reserve_request(owner,run_id)
            async with MetricFlowConnector(s._read_key,transport=s.transport,before_request=reserve,retry_delay=s.retry_delay) as c:
                for account in accounts:
                    for kind in ("tracker","creative"):
                        try:
                            if kind=="tracker":
                                body=await c.get_tracker_stats(account.external_id,start,end)
                                items=tracker_days(body,start,end)
                            else:
                                ads=await c.get_ads(account.external_id,start,end)
                                creatives=await c.get_creatives(account.external_id,start,end)
                                items=creative_window(ads,creatives,start,end,account.currency)
                                ad_tracker=tracker_ad_windows(ads,start,end)
                            # Validation of the entire endpoint completes before publishing any of its rows.
                            with s.sessions.begin() as session:
                                lease=session.scalar(select(SyncLease).where(SyncLease.key==s.lease_key).with_for_update())
                                if not lease or lease.owner!=owner or aware(lease.expires_at)<=s.clock():raise LeaseLost()
                                if kind=="creative":
                                    # Replace an exact-window catalog so disappeared groups do not linger.
                                    session.execute(delete(ReadStatistic).where(ReadStatistic.account_id==account.id,
                                        ReadStatistic.kind==kind,ReadStatistic.start_day==start,ReadStatistic.end_day==end))
                                for item in items:
                                    a=b=date.fromisoformat(item["date"]) if kind=="tracker" else start
                                    if kind=="creative":b=end
                                    key="account" if kind=="tracker" else hashlib.sha256(item["creative_key"].encode()).hexdigest()
                                    upsert(session,ReadStatistic,dict(id=identity(account.id,kind,key,str(a),str(b)),
                                        account_id=account.id,kind=kind,scope_key=key,start_day=a,end_day=b,
                                        # Monetary/tracker timezone attribution remains unverified.
                                        currency=None if kind=="tracker" else account.currency,
                                        timezone=None if kind=="tracker" else account.timezone,
                                        observed_at=now,payload=item))
                                if kind=="creative":
                                    session.execute(delete(ReadStatistic).where(ReadStatistic.account_id==account.id,
                                        ReadStatistic.kind=="tracker",ReadStatistic.scope_key!="account",
                                        ReadStatistic.start_day==start,ReadStatistic.end_day==end))
                                    for item in ad_tracker:
                                        key="ad_"+hashlib.sha256(item["ad_id"].encode()).hexdigest()[:61]
                                        upsert(session,ReadStatistic,dict(id=identity(account.id,"tracker",key,str(start),str(end)),
                                            account_id=account.id,kind="tracker",scope_key=key,start_day=start,end_day=end,
                                            currency=None,timezone=None,observed_at=now,payload=item))
                            rows+=len(items)+(len(ad_tracker) if kind=="creative" else 0)
                        except (QuotaExhausted,RateLimitExceeded,LeaseLost):raise
                        except Exception as error:
                            errors.append({"account_ref":hashlib.sha256(account.external_id.encode()).hexdigest()[:12],
                                           "kind":kind,"error_code":type(error).__name__})
            status="partial" if errors else "succeeded"
        except Exception as error:
            if isinstance(error,RateLimitExceeded):s.block_quota(error.retry_after_seconds)
            status="skipped_quota" if isinstance(error,QuotaExhausted) else "failed"
            errors.append({"error_code":type(error).__name__})
        finally:
            with s.sessions.begin() as session:
                session.execute(update(SyncRun).where(SyncRun.id==run_id).values(
                    status=status,finished_at=s.clock(),rows=rows,error_code=errors[-1]["error_code"] if errors else None))
                session.execute(delete(SyncLease).where(SyncLease.key==s.lease_key,SyncLease.owner==owner))
        with s.sessions() as session:requests=session.get(SyncRun,run_id).requests
        return {"status":status,"run_id":run_id,"rows":rows,"requests":requests,"errors":errors}

def main():
    p=argparse.ArgumentParser(description="Refresh proven optional READ scopes")
    p.add_argument("--start",required=True,type=date.fromisoformat);p.add_argument("--end",required=True,type=date.fromisoformat)
    a=p.parse_args()
    if os.environ.get("ACTIONS_ENABLED","false").lower()!="false" or os.environ.get("SYNC_ENABLED","false").lower()!="true":
        raise SystemExit("READ sync must be enabled and actions disabled")
    db=make_engine()
    try:
        s=SyncEngine(sessions(db),InsightSchema.load(os.environ["METRICFLOW_SCHEMA_FILE"]),
            read_key_file(os.environ["METRICFLOW_READ_KEY_FILE"]),workspace=os.environ.get("WORKSPACE_ID","default"),
            daily_budget=int(os.environ.get("SYNC_DAILY_BUDGET","800")))
        r=asyncio.run(OptionalSync(s).run(a.start,a.end));print(json.dumps(r))
        return 0 if r["status"]=="succeeded" else 23 if r["status"]=="skipped_quota" else 22
    finally:db.dispose()
if __name__=="__main__":raise SystemExit(main())
