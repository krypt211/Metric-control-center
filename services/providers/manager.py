"""One registry, isolated clients, quotas and safe health metadata."""
import os
from pathlib import Path
from datetime import timedelta
from sqlalchemy import select,update,or_
from services.providers.models import ProviderConnection,ProviderCredential
from services.providers.credentials import load
from services.providers.contracts import ProviderError,ActionProviderRouter
from services.providers.matching import confirm_accounts
from services.storage.models import AdAccount,ApiQuota
from services.storage.repository import identity,upsert,insert_for
from services.sync.engine import utc_now
from services.sync.schema import InsightSchema

PROVIDERS=("metricflow","meta")
def ensure(session,workspace):
    for provider in PROVIDERS:
        if not session.get(ProviderConnection,(workspace,provider)):
            path=os.environ.get("METRICFLOW_READ_KEY_FILE","")
            enabled=provider=="metricflow" and bool(path and Path(path).is_file())
            session.add(ProviderConnection(workspace_id=workspace,provider=provider,enabled=enabled,
                credential_source="server",revision=1,config={},status="unverified" if enabled else "disconnected",
                permissions={},capabilities={},quota={},updated_at=utc_now()))
    session.flush();confirm_accounts(session,workspace)

class ProviderManager:
    def __init__(self,factory,workspace="default",transports=None):
        self.factory=factory;self.workspace=workspace;self.transports=transports or {}
    def reserve(self,provider,run_id=None):
        from services.storage.models import SyncRun
        now=utc_now();limit=int(os.environ.get("SYNC_DAILY_BUDGET" if provider=="metricflow" else "META_DAILY_BUDGET","800" if provider=="metricflow" else "5000"))
        with self.factory.begin() as s:
            if s.scalar(select(ApiQuota).where(ApiQuota.workspace_id==self.workspace,ApiQuota.provider==provider,ApiQuota.blocked_until>now).limit(1)):raise ProviderError("PROVIDER_QUOTA_BLOCKED")
            s.execute(insert_for(s,ApiQuota.__table__).values(workspace_id=self.workspace,provider=provider,utc_day=now.date(),requests=0).on_conflict_do_nothing(index_elements=["workspace_id","provider","utc_day"]))
            changed=s.execute(update(ApiQuota).where(ApiQuota.workspace_id==self.workspace,ApiQuota.provider==provider,ApiQuota.utc_day==now.date(),ApiQuota.requests<limit,or_(ApiQuota.blocked_until.is_(None),ApiQuota.blocked_until<=now)).values(requests=ApiQuota.requests+1))
            if changed.rowcount!=1:raise ProviderError("PROVIDER_QUOTA_EXHAUSTED")
            if run_id:s.execute(update(SyncRun).where(SyncRun.id==run_id).values(requests=SyncRun.requests+1))
    def create(self,provider,*,before_request=None):
        if provider not in PROVIDERS:raise ProviderError("INVALID_PROVIDER")
        with self.factory() as s:
            c=s.get(ProviderConnection,(self.workspace,provider))
            if c and not c.enabled:raise ProviderError("PROVIDER_DISABLED")
            data=load(s,self.workspace,provider)
        async def reserve():
            self.reserve(provider)
        kwargs={"transport":self.transports.get(provider),"before_request":before_request or reserve}
        if provider=="meta":
            from services.meta.provider import MetaMarketingProvider
            return MetaMarketingProvider(data,**kwargs)
        from services.providers.metricflow import MetricFlowProvider
        schema=InsightSchema.load(os.environ.get("METRICFLOW_SCHEMA_FILE","/config/metricflow-schema.json"))
        return MetricFlowProvider(data,schema=schema,**kwargs)
    def failure(self,provider,error,revision=None):
        code=getattr(error,"code",type(error).__name__)
        if code not in {"META_TOKEN_INVALID","META_TOKEN_EXPIRED","META_ADS_READ_REQUIRED","META_PERMISSION_DENIED","META_RATE_LIMIT","META_TIMEOUT","META_UNAVAILABLE","PROVIDER_DISABLED","META_NOT_CONNECTED","CREDENTIAL_UNAVAILABLE","PROVIDER_QUOTA_BLOCKED","PROVIDER_QUOTA_EXHAUSTED","AuthenticationError","PermissionDenied","RateLimitExceeded","QuotaExhausted","SchemaError"}:code="PROVIDER_READ_FAILED"
        now=utc_now()
        with self.factory.begin() as s:
            c=s.get(ProviderConnection,(self.workspace,provider))
            if c and c.enabled and (revision is None or c.revision==revision):
                c.status="error";c.error_code=code;c.checked_at=now
            retry=getattr(error,"retry_after",None) or getattr(error,"retry_after_seconds",None)
            if code in ("META_RATE_LIMIT","RateLimitExceeded"):
                until=now+timedelta(seconds=retry or 900)
                if provider=="metricflow":until=max(until,now.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1))
                s.execute(update(ApiQuota).where(ApiQuota.workspace_id==self.workspace,ApiQuota.provider==provider,ApiQuota.utc_day==now.date()).values(blocked_until=until))
        return code
    async def health_check(self,provider):
        with self.factory.begin() as s:
            ensure(s,self.workspace)
            c=s.get(ProviderConnection,(self.workspace,provider));revision=c.revision
        client=None
        try:
            client=self.create(provider);result=await client.health_check()
            with self.factory.begin() as s:
                c=s.get(ProviderConnection,(self.workspace,provider))
                if not c.enabled or c.revision!=revision:raise ProviderError("CONNECTION_CHANGED")
                for raw in result["accounts"]:
                    if provider=="meta":
                        from services.meta.mapper import account_values
                        values=account_values(raw)
                    else:
                        from services.metricflow.onboarding import account_values
                        values=account_values(raw,client.schema.config["account_catalog"])
                    aid=identity(self.workspace,provider,values["account_id"])
                    upsert(s,AdAccount,{"id":aid,"workspace_id":self.workspace,"provider":provider,"external_id":values["account_id"],
                        "name":values["account_name"],"currency":values["currency"],"timezone":values["timezone"],"observed_at":utc_now()})
                confirm_accounts(s,self.workspace)
                c.status="healthy";c.error_code=None;c.checked_at=utc_now()
                # A health probe is narrower than a successful insights sync.
                verified={k:v for k,v in c.capabilities.get("read",{}).items() if v=="verified"}
                c.permissions=result["permissions"];c.capabilities=result["capabilities"];c.quota=result["quota"]
                if provider=="metricflow" and result["permissions"].get("read"):
                    c.capabilities.setdefault("read",{}).update(verified)
            return {"status":"healthy"}
        except Exception as error:return {"status":"error","error_code":self.failure(provider,error,revision)}
        finally:
            if client:await client.close()
