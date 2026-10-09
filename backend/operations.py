"""Admin-only status: scoped sync history, persistent quota, expiring service heartbeats."""
from datetime import datetime,timedelta,timezone
import os
from zoneinfo import ZoneInfo
from fastapi import APIRouter,Request
from sqlalchemy import select
from backend.auth import admin,factory,limiter
from backend.health import readiness
from services.storage.models import ApiQuota,SyncRun
router=APIRouter()
@router.get("/api/admin/status")
def status(request:Request):
    actor=admin(request);now=datetime.now(timezone.utc)
    def view(run):
        if not run:return None
        return {"status":run.status,"job":run.job,"started_at":run.started_at.isoformat(),
                "finished_at":run.finished_at.isoformat() if run.finished_at else None,
                "rows":run.rows,"requests":run.requests,"error_code":run.error_code}
    with factory()() as session:
        query=select(SyncRun).where(SyncRun.workspace_id==actor["workspace"],SyncRun.provider=="metricflow",SyncRun.job!="optional_read")
        success=session.scalar(query.where(SyncRun.status=="succeeded").order_by(SyncRun.finished_at.desc()).limit(1))
        failure=session.scalar(query.where(SyncRun.status=="failed").order_by(SyncRun.finished_at.desc()).limit(1))
        quota=session.get(ApiQuota,(actor["workspace"],"metricflow",now.date()))
        q={"used":quota.requests if quota else 0,"local_limit":int(os.environ.get("SYNC_DAILY_BUDGET","800"))}
    local=now.astimezone(ZoneInfo(os.environ.get("SYNC_TIMEZONE","Europe/Moscow")))
    next_sync=local.replace(second=0,microsecond=0)+timedelta(minutes=10-local.minute%10)
    beats={}
    for name in ("worker","scheduler"):
        try:beats[name]="alive" if limiter().get("mcc:heartbeat:"+name) else "unavailable"
        except Exception:beats[name]="unavailable"
    return {"as_of":now.isoformat(),"workspace":actor["workspace"],"mode":"READ ONLY","actions_enabled":False,
        "last_successful_sync":view(success),"last_failed_sync":view(failure),
        "next_scheduled_sync":next_sync.isoformat() if beats["scheduler"]=="alive" else None,
        "schedule_note":"today every 10 minutes; yesterday hourly :03; last7 daily 04:07",
        "metricflow_quota":q,"services":beats,"readiness":readiness(factory()),
        "settings":{"timezone":str(local.tzinfo),"session_ttl_seconds":int(os.environ.get("SESSION_TTL_SECONDS","28800"))}}
