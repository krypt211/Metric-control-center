"""ADMIN provider settings; credentials never leave the server in a response."""
from datetime import date,timedelta
from uuid import uuid4
import os
from fastapi import APIRouter,Request,HTTPException
from pydantic import BaseModel,ConfigDict,Field,SecretStr,StrictBool
from typing import Literal
from sqlalchemy import select,delete,text
from backend.auth import admin,identity,factory,csrf_check
from services.providers.manager import ensure,PROVIDERS
from services.providers.credentials import encrypt,cipher,CredentialError
from services.providers.models import ProviderConnection,ProviderCredential,ProviderRoutingSetting,ProviderAccountMapping,ProviderSwitchEvent,ProviderJob,ProviderWindow
from services.storage.models import AdAccount,SyncRun,EntityCurrentState,Entity,ApiQuota
from services.storage.repository import upsert
from services.sync.engine import utc_now
from services.providers.router import DataSourceRouter
from services.providers.presentation import quota_numbers
from services.analytics.table import Filters,table_data
router=APIRouter()
BASE="/api/admin/providers"
class Strict(BaseModel):model_config=ConfigDict(extra="forbid")
class Credentials(Strict):
    token:SecretStr=Field(min_length=1,max_length=4096)
    app_id:str|None=Field(default=None,max_length=64)
    app_secret:SecretStr|None=Field(default=None,max_length=256)
    graph_version:str=Field(default="v26.0",pattern=r"^v[0-9]{1,3}\.0$")
class Routing(Strict):
    primary_provider:Literal["metricflow","meta"]
    fallback_provider:Literal["metricflow","meta"]|None=None
    action_provider:Literal["disabled"]="disabled"
    scope:str=Field(default="workspace",min_length=1,max_length=36)
class Disconnect(Strict):
    acknowledge_last_source:StrictBool=False
    forget_credentials:StrictBool=False
class Period(Strict):
    start:date
    end:date
class Mapping(Strict):
    account_id:str=Field(min_length=1,max_length=36)
    target_account_id:str=Field(min_length=1,max_length=36)
    confirm:StrictBool=False
def actor(request,mutation=False):
    value=admin(request)
    if mutation:csrf_check(request,value)
    return value
def provider_name(provider):
    if provider not in PROVIDERS:raise HTTPException(404,"PROVIDER_NOT_FOUND")
def lock(session,workspace):
    if session.bind.dialect.name=="postgresql":
        import hashlib
        key=int.from_bytes(hashlib.sha256(("providers:"+workspace).encode()).digest()[:8],"big",signed=True)
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"),{"key":key})
def audit(s,a,canonical,previous,active,reason):
    s.add(ProviderSwitchEvent(id=str(uuid4()),workspace_id=a["workspace"],canonical_id=canonical,
        previous_provider=previous,active_provider=active,reason=reason,created_at=utc_now(),actor_id=a["id"]))
def enqueue(s,a,provider,kind,start,end):
    if s.scalar(select(ProviderJob).where(ProviderJob.workspace_id==a["workspace"],ProviderJob.provider==provider,ProviderJob.status.in_(("queued","running"))).limit(1)):
        raise HTTPException(409,"PROVIDER_JOB_IN_PROGRESS")
    jobs=[]
    for offset in range(0,(end-start).days+1,3 if kind=="sync" else (end-start).days+1):
        first=start+timedelta(days=offset);last=min(end,first+timedelta(days=2)) if kind=="sync" else end
        job=ProviderJob(id=str(uuid4()),workspace_id=a["workspace"],provider=provider,kind=kind,start_day=first,end_day=last,status="queued",created_at=utc_now())
        s.add(job);jobs.append(job.id)
    return {"status":"queued","job_ids":jobs}
def synced_source(s,workspace,connection,scope="workspace"):
    if not connection.last_success_at:return False
    query=select(ProviderWindow.account_id).join(AdAccount,AdAccount.id==ProviderWindow.account_id).where(
        AdAccount.workspace_id==workspace,AdAccount.provider==connection.provider,
        ProviderWindow.complete.is_(True),ProviderWindow.credential_revision==connection.revision)
    if scope!="workspace":
        query=query.join(ProviderAccountMapping,ProviderAccountMapping.account_id==AdAccount.id).where(
            ProviderAccountMapping.workspace_id==workspace,ProviderAccountMapping.canonical_id==scope)
    return s.scalar(query.limit(1)) is not None
@router.get(BASE)
def settings(request:Request):
    a=actor(request)
    with factory().begin() as s:
        ensure(s,a["workspace"]);now=utc_now();cards=[]
        for c in s.scalars(select(ProviderConnection).where(ProviderConnection.workspace_id==a["workspace"])):
            accounts=s.scalars(select(AdAccount).where(AdAccount.workspace_id==a["workspace"],AdAccount.provider==c.provider)).all()
            run=s.scalar(select(SyncRun).where(SyncRun.workspace_id==a["workspace"],SyncRun.provider==c.provider,SyncRun.status=="succeeded").order_by(SyncRun.finished_at.desc()).limit(1))
            quota=s.get(ApiQuota,(a["workspace"],c.provider,now.date()))
            cards.append({"provider":c.provider,"enabled":c.enabled,"status":c.status,"credential_source":c.credential_source,
                "credential_configured":bool(s.get(ProviderCredential,(a["workspace"],c.provider))) or (c.provider=="metricflow" and bool(os.environ.get("METRICFLOW_READ_KEY_FILE"))),
                "last_check":c.checked_at.isoformat() if c.checked_at else None,"last_success_sync":c.last_success_at.isoformat() if c.last_success_at else run.finished_at.isoformat() if run and run.finished_at else None,
                "routing_ready":bool(c.enabled and c.status=="healthy" and synced_source(s,a["workspace"],c)),"account_count":len(accounts),"permissions":c.permissions,"capabilities":c.capabilities,"error_code":c.error_code,"quota":c.quota,
                "provider_quota":{**quota_numbers(c.quota),"checked_at":c.quota.get("checked_at")},
                "local_quota":{"limit":int(os.environ.get("SYNC_DAILY_BUDGET" if c.provider=="metricflow" else "META_DAILY_BUDGET","800" if c.provider=="metricflow" else "5000")),"used":quota.requests if quota else 0,"blocked_until":quota.blocked_until.isoformat() if quota and quota.blocked_until else None},
                "app_id":c.config.get("app_id"),"graph_version":c.config.get("graph_version"),"oauth":"not_configured"})
        routing=[{"scope":r.scope,"primary_provider":r.primary_provider,"fallback_provider":r.fallback_provider,"action_provider":"disabled"} for r in s.scalars(select(ProviderRoutingSetting).where(ProviderRoutingSetting.workspace_id==a["workspace"]))]
        if not any(r["scope"]=="workspace" for r in routing):routing.insert(0,{"scope":"workspace","primary_provider":"metricflow","fallback_provider":None,"action_provider":"disabled"})
        mappings=[{"account_id":m.account_id,"canonical_id":m.canonical_id,"meta_account_id":m.meta_account_id,"proof":m.proof,
            "provider":s.get(AdAccount,m.account_id).provider,"name":s.get(AdAccount,m.account_id).name,"provider_account_id":s.get(AdAccount,m.account_id).external_id}
            for m in s.scalars(select(ProviderAccountMapping).where(ProviderAccountMapping.workspace_id==a["workspace"]))]
        events=s.scalars(select(ProviderSwitchEvent).where(ProviderSwitchEvent.workspace_id==a["workspace"]).order_by(ProviderSwitchEvent.created_at.desc()).limit(100)).all()
        jobs=s.scalars(select(ProviderJob).where(ProviderJob.workspace_id==a["workspace"]).order_by(ProviderJob.created_at.desc()).limit(40)).all()
        try:cipher();credential_ui=True
        except CredentialError:credential_ui=False
        return {"connections":cards,"routing":routing,"mappings":mappings,"credentials_ui_enabled":credential_ui,"action_provider":"disabled","actions_enabled":False,"read_only":True,
            "events":[{"at":e.created_at.isoformat(),"canonical_id":e.canonical_id,"from":e.previous_provider,"to":e.active_provider,"reason":e.reason} for e in events],
            "jobs":[{"id":j.id,"provider":j.provider,"kind":j.kind,"status":j.status,"start":str(j.start_day),"end":str(j.end_day),"error_code":j.error_code} for j in jobs]}
@router.post(BASE+"/{provider}/credentials")
def credentials(provider:str,command:Credentials,request:Request):
    a=actor(request,True);provider_name(provider);data={"token":command.token.get_secret_value()}
    if provider=="meta":data.update(app_id=command.app_id or "",app_secret=command.app_secret.get_secret_value() if command.app_secret else "",graph_version=command.graph_version)
    try:encrypted=encrypt(a["workspace"],provider,data)
    except Exception:raise HTTPException(422,"CREDENTIALS_INVALID_OR_ENCRYPTION_UNAVAILABLE") from None
    with factory().begin() as s:
        lock(s,a["workspace"]);ensure(s,a["workspace"]);c=s.get(ProviderConnection,(a["workspace"],provider))
        c.enabled=True;c.credential_source="encrypted";c.revision+=1;c.status="unverified";c.error_code=None;c.permissions={};c.capabilities={};c.checked_at=None;c.last_success_at=None;c.updated_at=utc_now()
        c.config={"app_id":data["app_id"],"graph_version":data["graph_version"]} if provider=="meta" else {}
        upsert(s,ProviderCredential,{"workspace_id":a["workspace"],"provider":provider,"encrypted":encrypted,"updated_at":utc_now()})
        for j in s.scalars(select(ProviderJob).where(ProviderJob.workspace_id==a["workspace"],ProviderJob.provider==provider,ProviderJob.status.in_(("queued","running")))):
            j.status="cancelled";j.finished_at=utc_now();j.error_code="CREDENTIAL_REPLACED"
        s.flush();audit(s,a,"workspace",None,provider,"CREDENTIAL_REPLACED")
        return enqueue(s,a,provider,"health",utc_now().date(),utc_now().date())
@router.post(BASE+"/{provider}/check")
def check(provider:str,request:Request):
    a=actor(request,True);provider_name(provider)
    with factory().begin() as s:
        lock(s,a["workspace"]);ensure(s,a["workspace"])
        if not s.get(ProviderConnection,(a["workspace"],provider)).enabled:raise HTTPException(409,"PROVIDER_DISABLED")
        return enqueue(s,a,provider,"health",utc_now().date(),utc_now().date())
@router.post(BASE+"/{provider}/sync")
def synchronize(provider:str,command:Period,request:Request):
    a=actor(request,True);provider_name(provider)
    if command.start>command.end or (command.end-command.start).days>90:raise HTTPException(422,"SYNC_WINDOW_MUST_BE_1_TO_91_DAYS")
    with factory().begin() as s:
        lock(s,a["workspace"]);ensure(s,a["workspace"])
        if not s.get(ProviderConnection,(a["workspace"],provider)).enabled:raise HTTPException(409,"PROVIDER_DISABLED")
        return enqueue(s,a,provider,"sync",command.start,command.end)
@router.post(BASE+"/{provider}/disconnect")
def disconnect(provider:str,command:Disconnect,request:Request):
    a=actor(request,True);provider_name(provider)
    with factory().begin() as s:
        lock(s,a["workspace"]);ensure(s,a["workspace"]);c=s.get(ProviderConnection,(a["workspace"],provider))
        other=s.scalar(select(ProviderConnection).where(ProviderConnection.workspace_id==a["workspace"],ProviderConnection.provider!=provider,ProviderConnection.enabled.is_(True),ProviderConnection.status=="healthy").limit(1))
        if c.enabled and not other and not command.acknowledge_last_source:raise HTTPException(409,"LAST_WORKING_SOURCE_WARNING")
        c.enabled=False;c.revision+=1;c.status="disconnected";c.permissions={};c.capabilities={};c.updated_at=utc_now()
        if command.forget_credentials:s.execute(delete(ProviderCredential).where(ProviderCredential.workspace_id==a["workspace"],ProviderCredential.provider==provider))
        for j in s.scalars(select(ProviderJob).where(ProviderJob.workspace_id==a["workspace"],ProviderJob.provider==provider,ProviderJob.status.in_(("queued","running")))):
            j.status="cancelled";j.finished_at=utc_now()
        audit(s,a,"workspace",provider,None,"DISCONNECTED")
        return {"status":"disconnected","remote_revocation":"not_performed","snapshot_retained":True}
@router.put(BASE+"/routing")
def routing(command:Routing,request:Request):
    a=actor(request,True)
    if command.primary_provider==command.fallback_provider:raise HTTPException(422,"PRIMARY_AND_FALLBACK_MUST_DIFFER")
    with factory().begin() as s:
        lock(s,a["workspace"]);ensure(s,a["workspace"])
        if command.scope!="workspace" and not s.scalar(select(ProviderAccountMapping).where(ProviderAccountMapping.workspace_id==a["workspace"],ProviderAccountMapping.canonical_id==command.scope).limit(1)):raise HTTPException(404,"ACCOUNT_NOT_FOUND")
        c=s.get(ProviderConnection,(a["workspace"],command.primary_provider))
        if not c.enabled or c.status!="healthy":raise HTTPException(409,"PRIMARY_MUST_BE_VERIFIED")
        if not synced_source(s,a["workspace"],c,command.scope):raise HTTPException(409,"PRIMARY_SYNC_REQUIRED")
        old=s.get(ProviderRoutingSetting,(a["workspace"],command.scope));audit(s,a,command.scope,old.primary_provider if old else "metricflow",command.primary_provider,"MANUAL_ROUTING")
        upsert(s,ProviderRoutingSetting,{"workspace_id":a["workspace"],"scope":command.scope,"primary_provider":command.primary_provider,"fallback_provider":command.fallback_provider,"action_provider":"disabled","updated_at":utc_now()})
        return {"status":"saved","action_provider":"disabled"}
@router.delete(BASE+"/routing/{scope}")
def remove_override(scope:str,request:Request):
    a=actor(request,True)
    if scope=="workspace":raise HTTPException(422,"WORKSPACE_ROUTING_REQUIRED")
    with factory().begin() as s:
        lock(s,a["workspace"]);s.execute(delete(ProviderRoutingSetting).where(ProviderRoutingSetting.workspace_id==a["workspace"],ProviderRoutingSetting.scope==scope))
        audit(s,a,scope,None,None,"OVERRIDE_REMOVED");return {"status":"saved"}
@router.post(BASE+"/mapping")
def mapping(command:Mapping,request:Request):
    a=actor(request,True)
    if not command.confirm:raise HTTPException(422,"MAPPING_CONFIRMATION_REQUIRED")
    with factory().begin() as s:
        lock(s,a["workspace"]);ensure(s,a["workspace"]);one=s.get(AdAccount,command.account_id);two=s.get(AdAccount,command.target_account_id)
        if not one or not two or one.workspace_id!=a["workspace"] or two.workspace_id!=a["workspace"]:raise HTTPException(404,"ACCOUNT_NOT_FOUND")
        if one.provider==two.provider:raise HTTPException(422,"PROVIDERS_MUST_DIFFER")
        m=s.get(ProviderAccountMapping,one.id);target=s.get(ProviderAccountMapping,two.id)
        if m.meta_account_id and target.meta_account_id and m.meta_account_id!=target.meta_account_id:raise HTTPException(422,"META_ID_MISMATCH")
        old=m.canonical_id
        members=s.scalars(select(ProviderAccountMapping).where(ProviderAccountMapping.workspace_id==a["workspace"],ProviderAccountMapping.canonical_id==old)).all()
        new_members=s.scalars(select(ProviderAccountMapping).where(ProviderAccountMapping.workspace_id==a["workspace"],ProviderAccountMapping.canonical_id==target.canonical_id)).all()
        if old!=target.canonical_id and {s.get(AdAccount,x.account_id).provider for x in members}&{s.get(AdAccount,x.account_id).provider for x in new_members}:raise HTTPException(422,"DUPLICATE_PROVIDER_MAPPING")
        for member in members:member.canonical_id=target.canonical_id;member.proof="admin_confirmed";member.confirmed_by=a["id"];member.updated_at=utc_now()
        audit(s,a,target.canonical_id,one.provider,two.provider,"MANUAL_MAPPING");return {"status":"saved","automatic_failover":"requires_proven_meta_id_and_attribution"}
@router.get(BASE+"/diagnostics")
def diagnostics(request:Request,start:date,end:date):
    a=actor(request)
    if start>end or (end-start).days>90:raise HTTPException(422,"INVALID_PERIOD")
    with factory().begin() as s:
        ensure(s,a["workspace"]);routes=DataSourceRouter(s,a["workspace"]).resolve(start,end);comparison={}
        for provider in PROVIDERS:
            report=table_data(s,a["workspace"],Filters(start,end),provider_override=provider,limit=1000)
            comparison[provider]=[r for r in report["rows"] if r["source_provider"]==provider]
        by_provider={p:{r["id"]:r for r in rows} for p,rows in comparison.items()};differences=[]
        from decimal import Decimal
        for key in sorted(set(by_provider["meta"])&set(by_provider["metricflow"])):
            x,y=by_provider["metricflow"][key],by_provider["meta"][key];same=(x["currency"],x["timezone"])==(y["currency"],y["timezone"])
            delta=str(Decimal(y["spend"])-Decimal(x["spend"])) if same and x["spend"] is not None and y["spend"] is not None else None
            differences.append({"canonical_id":key,"metricflow_spend":x["spend"],"meta_spend":y["spend"],"spend_delta":delta,"currency_timezone_compatible":same,"attribution_compatible":"unverified"})
        states=s.execute(select(Entity,EntityCurrentState).join(EntityCurrentState).join(AdAccount).where(AdAccount.workspace_id==a["workspace"],AdAccount.provider=="meta").limit(100)).all()
        return {"routes":list(routes.values()),"comparison":comparison,"differences":differences,"corrected_automatically":False,
            "meta_entity_state":[{"id":e.external_id,"kind":e.kind,"status":st.status,**{k:st.raw.get(k) for k in ("daily_budget","lifetime_budget","bid_strategy","bid_amount","budget_units","attribution_spec")}} for e,st in states]}
@router.get("/api/stats/sources")
def sources(request:Request,start:date,end:date):
    a=identity(request)
    if start>end or (end-start).days>365:raise HTTPException(422,"INVALID_PERIOD")
    with factory().begin() as s:return {"sources":list(DataSourceRouter(s,a["workspace"]).resolve(start,end).values())}