"""Durable READ jobs with independent provider quotas and revision fencing."""
import asyncio,os
from datetime import timedelta,datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select,update
from workers.ingestion import app,factory,window
from services.providers.manager import ProviderManager,ensure
from services.providers.contracts import ProviderError
from services.meta.pilot import enabled as pilot_mode
from services.providers.models import ProviderConnection,ProviderJob
from services.providers.sync import MetaSync,metricflow_sync
from services.sync.engine import utc_now
def manager():return ProviderManager(factory(),os.environ.get("WORKSPACE_ID","default"))
def enabled():
    return os.environ.get("SYNC_ENABLED","false")=="true" and os.environ.get("ACTIONS_ENABLED","false")=="false" and os.environ.get("LOCAL_READ_ONLY","false")=="true"
@app.task(name="providers.meta",ignore_result=True,bind=True)
def meta_sync(self,job="today"):
    if not enabled():return {"status":"disabled"}
    if pilot_mode():return {"status":"pilot_scheduler_held"}
    m=manager()
    with m.factory.begin() as s:
        ensure(s,m.workspace)
        if not s.get(ProviderConnection,(m.workspace,"meta")).enabled:return {"status":"disabled"}
    deadline=datetime.fromisoformat(self.request.expires) if isinstance(self.request.expires,str) else self.request.expires
    published=deadline-timedelta(seconds={"today":540,"yesterday":3300,"last7":82800}[job]) if deadline else utc_now()
    day=published.astimezone(ZoneInfo(os.environ.get("SYNC_TIMEZONE","Europe/Moscow"))).date()
    before,after={"today":(1,1),"yesterday":(2,0),"last7":(7,1)}[job]
    start,end=day-timedelta(days=before),day+timedelta(days=after)
    from services.meta.jobs import enqueue
    with m.factory.begin() as s:
        queued,created=enqueue(s,m.workspace,job,start,end,published_at=published,message_deadline=deadline)
    return {"status":"queued" if created else "deduplicated","job_id":queued.id}

@app.task(name="providers.job",ignore_result=True)
def run_job(job_id):
    if not enabled():return {"status":"disabled"}
    m=manager()
    with m.factory() as s:
        existing=s.get(ProviderJob,job_id)
        is_meta=bool(existing and existing.workspace_id==m.workspace and existing.provider=="meta")
    if is_meta:return run_meta_job(m,job_id)
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
        s.execute(update(ProviderJob).where(ProviderJob.workspace_id==m.workspace,ProviderJob.provider=="metricflow",ProviderJob.status=="running",ProviderJob.started_at<utc_now()-timedelta(minutes=30)).values(status="queued"))
        from services.meta.jobs import maintain
        maintain(s,m.workspace)
        jobs=[]
        for p in ("meta","metricflow"):
            if p=="meta":
                from services.meta.jobs import in_cooldown
                if in_cooldown(s,m.workspace):continue
            if s.scalar(select(ProviderJob.id).where(ProviderJob.workspace_id==m.workspace,ProviderJob.provider==p,ProviderJob.status=="running",*([ProviderJob.purpose=="pilot"] if p=="meta" and pilot_mode() else [])).limit(1)):continue
            j=s.scalar(select(ProviderJob.id).where(ProviderJob.workspace_id==m.workspace,ProviderJob.provider==p,ProviderJob.status=="queued",*([ProviderJob.expires_at.is_not(None)]+([ProviderJob.purpose=="pilot"] if pilot_mode() else []) if p=="meta" else [])).order_by(ProviderJob.created_at).limit(1))
            if j:jobs.append(j)
    for j in jobs:run_job.apply_async(args=[j],expires=55)
    return {"dispatched":len(jobs)}
def run_meta_job(m,job_id):
    with m.factory() as s:
        candidate=s.get(ProviderJob,job_id)
        if pilot_mode() and candidate and candidate.purpose!="pilot":return {"status":"pilot_existing_job_held"}
        if candidate and candidate.purpose=="pilot" and not pilot_mode():return {"status":"pilot_mode_required"}
    from services.meta.jobs import claim,checkpoint,complete,fence
    with m.factory.begin() as s:
        owner=claim(s,m.workspace,job_id)
        if not owner:return {"status":"not_claimable"}
        j=s.get(ProviderJob,job_id);purpose,start,end=j.purpose,j.start_day,j.end_day;accounts=j.account_scope;pilot_id=(j.request_params or {}).get("pilot_session_id")
    # A fresh manager avoids mutating shared READ managers/other tasks.
    runner=ProviderManager(m.factory,m.workspace,transports=m.transports)
    runner.job_guard=lambda:checkpoint(m.factory,m.workspace,job_id,owner)
    runner.job_fence=lambda session:fence(session,m.workspace,job_id,owner)
    runner.job_source="provider_job:"+job_id
    runner.job_accounts=accounts or None
    try:
        runner.job_guard()
        if purpose=="pilot":
            from services.meta.pilot import run
            runner.pilot_id=pilot_id
            result=asyncio.run(run(runner,pilot_id))
        else:result=asyncio.run(runner.health_check("meta") if purpose=="health" else MetaSync(runner).run(purpose,start,end))
        status="succeeded" if result["status"] in ("healthy","succeeded") else "queued" if result["status"]=="skipped_overlap" else "failed"
        reason=result.get("error_code") or (None if status=="succeeded" else "READ_INCOMPLETE")
    except ProviderError as error:status="failed";reason=error.code
    finally:
        with m.factory.begin() as s:
            complete(s,m.workspace,job_id,owner,locals().get("status","failed"),locals().get("reason","READ_WORKER_FAILED"))
            final=s.get(ProviderJob,job_id);result={"status":final.status,"error_code":final.error_code}
            if purpose=="pilot":
                from services.meta.pilot_models import MetaPilotSession
                pilot=s.get(MetaPilotSession,pilot_id)
                if pilot and pilot.status in ("QUEUED","RUNNING"):
                    pilot.status="STOPPED";pilot.reason=final.error_code or "META_PILOT_STOPPED";pilot.finished_at=utc_now()
    return result
