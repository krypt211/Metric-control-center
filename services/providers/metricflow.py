"""Adapter around the unchanged, verified MetricFlow Connector and schema."""
from datetime import UTC, date, datetime
from services.metricflow.reader import MetricFlowConnector
from services.metricflow.onboarding import list_mapping
from services.metricflow.probe import scope_check,usage_summary
from services.sync.schema import page_items
from services.providers.contracts import DisabledWriteContract,ProviderError

class MetricFlowProvider(DisabledWriteContract):
    name="metricflow"
    def __init__(self,credentials,*,schema,transport=None,before_request=None,retry_delay=0.5,**kwargs):
        self.connector=MetricFlowConnector(credentials["token"],transport=transport,before_request=before_request,retry_delay=retry_delay)
        self.schema=schema;self.verified=set();self.quota={}
    async def close(self):await self.connector.close()
    async def _collect(self,method,*args,params=None):
        query=dict(params or {});rows=[];seen=set()
        for _ in range(100):
            body=await method(*args,params=query)
            path,_,pagination=list_mapping(body)
            page,cursor=page_items(body,path,pagination);rows.extend(page)
            if len(rows)>200000:raise ProviderError("METRICFLOW_ROW_CAP")
            if cursor is None:return rows
            if cursor in seen:raise ProviderError("METRICFLOW_CURSOR_LOOP")
            seen.add(cursor);query[pagination["cursor_parameter"]]=cursor
        raise ProviderError("METRICFLOW_PAGE_CAP")
    async def get_accounts(self):
        rows=await self._collect(self.connector.get_accounts);self.verified.add("get_accounts");return rows
    async def _catalog(self,kind,account,start,end):
        rows=await self._collect(getattr(self.connector,"get_"+kind),account,start,end)
        self.verified.add("get_"+kind);return rows
    async def get_campaigns(self,account,start,end):return await self._catalog("campaigns",account,start,end)
    async def get_adsets(self,account,start,end):return await self._catalog("adsets",account,start,end)
    async def get_ads(self,account,start,end):return await self._catalog("ads",account,start,end)
    async def get_creatives(self,account,start,end):return await self._catalog("creatives",account,start,end)
    async def get_insights(self,account,start,end,level="ad"):
        if not __import__("re").fullmatch(r"act_[0-9]+",account):raise ProviderError("INVALID_PROVIDER_ACCOUNT_ID")
        if level!=self.schema.kind:raise ProviderError("METRICFLOW_LEVEL_NOT_CONFIGURED")
        # The existing cross-account /insights contract remains unchanged.
        from services.sync.schema import field
        query=dict(self.schema.config.get("query",{}));rows=[];seen=set();version=None
        for _ in range(100):
            body=await self.connector.get_insights(start,end,params=query)
            page,cursor=self.schema.page(body)
            ranges=self.schema.config.get("range_paths",{})
            if ranges and (field(body,ranges["start"])!=str(start) or field(body,ranges["end"])!=str(end)):raise ProviderError("METRICFLOW_WINDOW_MISMATCH")
            path=self.schema.config.get("snapshot_version_path")
            if path:
                stamp=field(body,path)
                if not isinstance(stamp,str) or not stamp or (version is not None and stamp!=version):raise ProviderError("METRICFLOW_SNAPSHOT_CHANGED")
                version=stamp
            rows.extend(page)
            if len(rows)>200000:raise ProviderError("METRICFLOW_ROW_CAP")
            if cursor is None:break
            if cursor in seen:raise ProviderError("METRICFLOW_CURSOR_LOOP")
            seen.add(cursor);query[self.schema.pagination["cursor_parameter"]]=cursor
        else:raise ProviderError("METRICFLOW_PAGE_CAP")
        self.verified.add("get_insights")
        return {"data":[r for r in rows if str(self.schema.value(r,"account_id"))==account],"complete":True,"attribution":None,"source_timestamp":version}
    async def get_entity_state(self,account,kind,entity):
        rows=await self._catalog({"campaign":"campaigns","adset":"adsets","ad":"ads"}[kind],account,date.today(),date.today())
        matches=[r for r in rows if r.get("id")==entity]
        if len(matches)!=1:raise ProviderError("METRICFLOW_ENTITY_NOT_FOUND")
        self.verified.add("get_entity_state");return matches[0]
    def get_capabilities(self):
        reads=("get_accounts","get_campaigns","get_adsets","get_ads","get_creatives","get_insights","get_entity_state")
        return {"read":{k:("verified" if k in self.verified else "unverified") for k in reads},
            "write":{k:"disabled" for k in ("pause_entity","enable_entity","set_budget","set_bid")},"implementation":"GET_ONLY"}
    async def health_check(self):
        me=await self.connector.get_me()
        confirmed=scope_check(me)
        self.quota={"summary":usage_summary(await self.connector.get_usage()),"checked_at":datetime.now(UTC).isoformat()}
        accounts=await self.get_accounts()
        return {"status":"healthy","accounts":accounts,"permissions":{"read":confirmed,"write_permission":False,"write_enabled":False},
            "capabilities":self.get_capabilities(),"quota":self.quota}
