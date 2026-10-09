"""Durable READ jobs with independent provider quotas and revision fencing."""
import asyncio,os
from datetime import timedelta
from sqlalchemy import select,update
from workers.ingestion import app,factory,window
from services.providers.manager import ProviderManager,ensure
from services.providers.models import ProviderConnection,ProviderJob
from services.providers.sync import MetaSync,metricflow_sync
from services.sync.engine import utc_now
def manager():return ProviderManager(factory(),os.environ.get("WORKSPACE_ID","default"))
def enabled():
    return os.environ.get("SYNC_ENABLED","false")=="true" and os.environ.get("ACTIONS_ENABLED","false")=="false" and os.environ.get("LOCAL_READ_ONLY","false")=="true"
@app.task(name="providers.meta",ignore_result=True)
def meta_sync(job="today"):
    if not enabled():return {"status":"disabled"}
    m=manager()
    with m.factory.begin() as s:
        ensure(s,m.workspace)
        if not s.get(ProviderConnection,(m.workspace,"meta")).enabled:return {"status":"disabled"}
    start,end=window(job)
    return asyncio.run(MetaSync(m).run(job,start,end))
@app.task(name="providers.job",ignore_result=True)
def run_job(job_id):
    if not enabled():return {"status":"disabled"}
    m=manager()
    with m.factory.begin() as s:
        claim=s.execute(update(ProviderJob).where(ProviderJob.id==job_id,ProviderJob.workspace_id==m.workspace,ProviderJob.status=="queued").values(status="running",started_at=utc_now(),finished_at=None))
        if claim.rowcount!=1:return {"status":"already_claimed"}
        j=s.get(ProviderJob,job_id);provider,start,end,kind=j.provider,j.start_day,j.end_day,j.kind
    try:
        if kind=="health":result=asyncio.run(m.health_check(provider))
        else:result=asyncio.run(MetaSync(m).run("manual",start,end) if provider=="meta" else metricflow_sync(m,"manual",start,end))
        status="succeeded" if result["status"] in ("healthy","succeeded") else result["status"]
        code=result.get("error_code")
    except Exception as error:status="failed";code=m.failure(provider,error)
    with m.factory.begin() as s:
        s.execute(update(ProviderJob).where(ProviderJob.id==job_id,ProviderJob.status=="running").values(status=status,finished_at=utc_now(),error_code=code))
    return {"status":status,"error_code":code}
@app.task(name="providers.dispatch",ignore_result=True)
def dispatch():
    if not enabled():return {"status":"disabled"}
    m=manager()
    with m.factory.begin() as s:
        s.execute(update(ProviderJob).where(ProviderJob.workspace_id==m.workspace,ProviderJob.status=="running",ProviderJob.started_at<utc_now()-timedelta(minutes=30)).values(status="queued"))
        jobs=[]
        for p in ("meta","metricflow"):
            if s.scalar(select(ProviderJob.id).where(ProviderJob.workspace_id==m.workspace,ProviderJob.provider==p,ProviderJob.status=="running").limit(1)):continue
            j=s.scalar(select(ProviderJob.id).where(ProviderJob.workspace_id==m.workspace,ProviderJob.provider==p,ProviderJob.status=="queued").order_by(ProviderJob.created_at).limit(1))
            if j:jobs.append(j)
    for j in jobs:run_job.apply_async(args=[j],expires=55)
    return {"dispatched":len(jobs)}