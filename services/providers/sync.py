"""Independent GET jobs. Failures cannot publish partially paginated account windows."""
import os
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import delete,select,update,or_
from services.providers.manager import ProviderManager,ensure
from services.providers.models import ProviderConnection,ProviderWindow
from services.providers.contracts import ProviderError
from services.providers.credentials import load
from services.providers.matching import confirm_accounts,hierarchy_hash
from services.storage.models import AdAccount,DailyMetric,Entity,SyncRun,SyncLease,RawSnapshot
from services.storage.repository import save_row,upsert,insert_for,identity
from services.sync.engine import SyncEngine,utc_now,aware
from services.sync.schema import InsightSchema

def assert_revision(session,workspace,provider,revision):
    c=session.scalar(select(ProviderConnection).where(ProviderConnection.workspace_id==workspace,
        ProviderConnection.provider==provider).with_for_update())
    if not c or not c.enabled or c.revision!=revision:raise ProviderError("CONNECTION_CHANGED")

class MetaSync:
    def __init__(self,manager):self.manager=manager;self.factory=manager.factory;self.workspace=manager.workspace
    async def run(self,job,start,end):
        if start>end or (end-start).days>31:raise ProviderError("SYNC_WINDOW_TOO_LARGE")
        with self.factory.begin() as s:
            ensure(s,self.workspace);c=s.get(ProviderConnection,(self.workspace,"meta"))
            if not c.enabled:return {"status":"disabled"}
            revision=c.revision
        owner=str(uuid4());run_id=str(uuid4());lease_key=self.workspace+":meta:insights";now=utc_now()
        with self.factory.begin() as s:
            s.execute(insert_for(s,SyncLease.__table__).values(key=lease_key,owner=owner,expires_at=now+timedelta(seconds=180)).on_conflict_do_nothing(index_elements=["key"]))
            changed=s.execute(update(SyncLease).where(SyncLease.key==lease_key,or_(SyncLease.owner==owner,SyncLease.expires_at<=now)).values(owner=owner,expires_at=now+timedelta(seconds=180)))
            if changed.rowcount!=1:return {"status":"skipped_overlap"}
            s.add(SyncRun(id=run_id,workspace_id=self.workspace,provider="meta",job=job,status="running",start_day=start,end_day=end,started_at=now,pages=0,rows=0,requests=0))
        client=None;errors=[];count=0
        async def reserve():
            with self.factory.begin() as s:
                assert_revision(s,self.workspace,"meta",revision)
                changed=s.execute(update(SyncLease).where(SyncLease.key==lease_key,SyncLease.owner==owner,
                    SyncLease.expires_at>utc_now()).values(expires_at=utc_now()+timedelta(seconds=180)))
                if changed.rowcount!=1:raise ProviderError("SYNC_LEASE_LOST")
            self.manager.reserve("meta",run_id)
        def fence(s):
            assert_revision(s,self.workspace,"meta",revision)
            lease=s.scalar(select(SyncLease).where(SyncLease.key==lease_key).with_for_update())
            if not lease or lease.owner!=owner or aware(lease.expires_at)<=utc_now():raise ProviderError("SYNC_LEASE_LOST")
        try:
            client=self.manager.create("meta",before_request=reserve)
            health=await client.health_check()
            for account in health["accounts"]:
                try:
                    catalog={}
                    for kind,method in (("campaign",client.get_campaigns),("adset",client.get_adsets),("ad",client.get_ads),("creative",client.get_creatives)):
                        catalog[kind]=await method(account["id"],start,end)
                    insights=await client.get_insights(account["id"],start,end)
                    from services.meta.mapper import map_rows,save_catalog
                    rows=map_rows(insights["data"],account,catalog,start,end,insights["attribution"])
                    with self.factory.begin() as s:
                        fence(s);observed=utc_now();aid=save_catalog(s,self.workspace,account,catalog,observed)
                        # Full GET response is the authoritative replacement for
                        # this source/account/window, including disappeared rows.
                        scope=select(Entity.id).where(Entity.account_id==aid,Entity.kind=="ad")
                        s.execute(delete(DailyMetric).where(DailyMetric.entity_id.in_(scope),DailyMetric.source=="meta",
                            DailyMetric.day>=start,DailyMetric.day<=end))
                        for row in rows:save_row(s,self.workspace,"meta",row,observed)
                        # Restore complete current metadata after fact import.
                        save_catalog(s,self.workspace,account,catalog,observed)
                        confirm_accounts(s,self.workspace)
                        upsert(s,ProviderWindow,{"account_id":aid,"start_day":start,"end_day":end,"imported_at":observed,
                            "source_timestamp":None,"attribution":insights["attribution"],"hierarchy_hash":hierarchy_hash(s,aid,start,end),
                            "complete":True,"run_id":run_id,"credential_revision":revision})
                        count+=len(rows)
                except Exception as error:errors.append(self.manager.failure("meta",error,revision))
            with self.factory.begin() as s:
                assert_revision(s,self.workspace,"meta",revision)
                c=s.get(ProviderConnection,(self.workspace,"meta"))
                c.checked_at=utc_now();c.capabilities=client.get_capabilities();c.permissions=health["permissions"];c.quota=client.client.quota
                c.status="partial" if errors else "healthy";c.error_code=errors[0] if errors else None
                if not errors:c.last_success_at=utc_now()
            status="partial" if errors else "succeeded"
        except Exception as error:
            errors.append(self.manager.failure("meta",error,revision));status="failed"
        finally:
            if client:await client.close()
            with self.factory.begin() as s:
                s.execute(update(SyncRun).where(SyncRun.id==run_id).values(status=locals().get("status","failed"),finished_at=utc_now(),rows=count,pages=client.client.successful_calls if client else 0,error_code=errors[0] if errors else None))
                s.execute(delete(SyncLease).where(SyncLease.key==lease_key,SyncLease.owner==owner))
        return {"status":status,"rows":count,"run_id":run_id,"error_code":errors[0] if errors else None}

async def metricflow_sync(manager,job,start,end,schema=None):
    with manager.factory.begin() as s:
        ensure(s,manager.workspace);c=s.get(ProviderConnection,(manager.workspace,"metricflow"))
        if not c.enabled:return {"status":"disabled"}
        revision=c.revision;credential=load(s,manager.workspace,"metricflow")
    schema=schema or InsightSchema.load(os.environ.get("METRICFLOW_SCHEMA_FILE","/config/metricflow-schema.json"))
    def guard(s):assert_revision(s,manager.workspace,"metricflow",revision)
    class FencedMetricFlowSync(SyncEngine):
        def reserve_request(self,owner,run_id):
            with self.sessions() as s:assert_revision(s,self.workspace,"metricflow",revision)
            return super().reserve_request(owner,run_id)
    engine=FencedMetricFlowSync(manager.factory,schema,credential["token"],workspace=manager.workspace,
        daily_budget=int(os.environ.get("SYNC_DAILY_BUDGET","800")),transport=manager.transports.get("metricflow"),publish_guard=guard)
    result=await engine.run(job,start,end)
    if result["status"]=="succeeded":
        with manager.factory.begin() as s:
            guard(s);c=s.get(ProviderConnection,(manager.workspace,"metricflow"))
            c.status="healthy";c.error_code=None;c.last_success_at=utc_now();c.checked_at=utc_now()
            confirm_accounts(s,manager.workspace)
            if schema.kind=="ad" and schema.config.get("endpoint","insights")=="insights":
                from services.sync.schema import field
                raw=s.scalar(select(RawSnapshot).where(RawSnapshot.run_id==result["run_id"]).order_by(RawSnapshot.page).limit(1))
                source_timestamp=None
                if schema.config.get("snapshot_version_path"):
                    for capture in s.scalars(select(RawSnapshot).where(RawSnapshot.run_id==result["run_id"])):
                        try:source_timestamp=field(capture.payload,schema.config["snapshot_version_path"])
                        except ValueError:continue
                        if isinstance(source_timestamp,str):break
                if not isinstance(source_timestamp,str):source_timestamp=None
                for a in s.scalars(select(AdAccount).where(AdAccount.workspace_id==manager.workspace,AdAccount.provider=="metricflow")):
                    upsert(s,ProviderWindow,{"account_id":a.id,"start_day":start,"end_day":end,"imported_at":utc_now(),
                        "source_timestamp":source_timestamp,"attribution":None,"hierarchy_hash":hierarchy_hash(s,a.id,start,end),
                        "complete":True,"run_id":result["run_id"],"credential_revision":revision})
                c.capabilities={"read":{"get_accounts":"verified","get_insights":"verified","get_campaigns":"verified" if schema.config.get("state_catalog") else "unverified","get_adsets":"verified" if schema.config.get("state_catalog") else "unverified"},
                    "write":{k:"disabled" for k in ("pause_entity","enable_entity","set_budget","set_bid")},"implementation":"GET_ONLY"}
    elif result["status"] not in ("skipped_overlap","disabled"):
        manager.failure("metricflow",ProviderError("PROVIDER_READ_FAILED"),revision)
    return result
