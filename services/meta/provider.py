"""Meta-specific catalogs/Insights. No assumption of MetricFlow response formats."""
from datetime import date
import json,re
from services.meta.client import MetaClient
from services.providers.contracts import DisabledWriteContract,ProviderError

def account_id(value):
    value=str(value)
    if value.startswith("act_"):value=value[4:]
    if not re.fullmatch(r"[0-9]{1,64}",value):raise ProviderError("INVALID_META_ACCOUNT_ID")
    return "act_"+value
def entity_id(value):
    value=str(value)
    if not re.fullmatch(r"[0-9]{1,128}",value):raise ProviderError("INVALID_META_ENTITY_ID")
    return value

class MetaMarketingProvider(DisabledWriteContract):
    name="meta"
    FIELDS={
        "campaign":"id,name,account_id,status,effective_status,daily_budget,lifetime_budget,bid_strategy,updated_time",
        "adset":"id,name,account_id,campaign_id,status,effective_status,daily_budget,lifetime_budget,bid_strategy,bid_amount,attribution_spec,updated_time",
        "ad":"id,name,account_id,campaign_id,adset_id,status,effective_status,creative{id,name,thumbnail_url},updated_time",
        "creative":"id,name,account_id,thumbnail_url,object_story_spec"
    }
    def __init__(self,credentials,**kwargs):
        self.client=MetaClient(credentials,**kwargs);self.verified=set();self.permissions={}
    async def close(self):await self.client.close()
    async def get_accounts(self):
        rows=await self.client.edge("me/adaccounts",{"fields":"id,account_id,name,account_status,currency,timezone_name"})
        seen=set()
        for r in rows:
            aid=account_id(r["id"])
            if aid in seen or account_id(r.get("account_id"))!=aid:raise ProviderError("META_ACCOUNT_MISMATCH")
            seen.add(aid)
        self.verified.add("get_accounts");return rows
    async def _catalog(self,account,kind):
        aid=account_id(account);edge={"campaign":"campaigns","adset":"adsets","ad":"ads","creative":"adcreatives"}[kind]
        rows=await self.client.edge(aid+"/"+edge,{"fields":self.FIELDS[kind]})
        seen=set()
        for r in rows:
            eid=entity_id(r.get("id"))
            if eid in seen or account_id(r.get("account_id"))!=aid:raise ProviderError("META_ENTITY_ACCOUNT_MISMATCH")
            seen.add(eid)
        self.verified.add("get_creatives" if kind=="creative" else "get_"+edge);return rows
    async def get_campaigns(self,account,start,end):return await self._catalog(account,"campaign")
    async def get_adsets(self,account,start,end):return await self._catalog(account,"adset")
    async def get_ads(self,account,start,end):return await self._catalog(account,"ad")
    async def get_creatives(self,account,start,end):return await self._catalog(account,"creative")
    async def get_insights(self,account,start,end,level="ad"):
        if level not in ("account","campaign","adset","ad") or not isinstance(start,date) or not isinstance(end,date) or start>end:raise ProviderError("INVALID_META_WINDOW")
        fields="account_id,account_name,account_currency,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,date_start,date_stop,spend,impressions,clicks,reach,frequency,actions,action_values,inline_link_clicks,unique_clicks,unique_inline_link_clicks,video_play_actions,video_p100_watched_actions"
        attribution={"action_attribution_windows":["7d_click","1d_view"],"action_report_time":"impression","use_unified_attribution_setting":False,"conversion_basis":"advertising","lead_action_type":"lead","purchase_action_type":"purchase"}
        rows=await self.client.edge(account_id(account)+"/insights",{"fields":fields,"level":level,
            "time_range":json.dumps({"since":str(start),"until":str(end)}),"time_increment":1,
            "action_attribution_windows":json.dumps(attribution["action_attribution_windows"]),
            "action_report_time":"impression","use_unified_attribution_setting":"false"})
        self.verified.add("get_insights")
        return {"data":rows,"attribution":attribution,"source_timestamp":None,"complete":True}
    async def get_entity_state(self,account,kind,entity):
        if kind not in ("campaign","adset","ad"):raise ProviderError("META_STATE_UNSUPPORTED")
        row=await self.client.get(entity_id(entity),{"fields":self.FIELDS[kind]})
        if account_id(row.get("account_id"))!=account_id(account):raise ProviderError("META_ENTITY_ACCOUNT_MISMATCH")
        self.verified.add("get_entity_state");return row
    def get_capabilities(self):
        reads=("get_accounts","get_campaigns","get_adsets","get_ads","get_creatives","get_insights","get_entity_state")
        return {"read":{k:("verified" if k in self.verified else "unverified") for k in reads},
            "write":{k:"disabled" for k in ("pause_entity","enable_entity","set_budget","set_bid")},
            "implementation":"GET_ONLY","verification":"runtime","budget_units":"provider_minor_units"}
    async def health_check(self):
        self.permissions=await self.client.verify_token()
        accounts=await self.get_accounts()
        return {"status":"healthy","permissions":self.permissions,"accounts":accounts,"quota":self.client.quota,"capabilities":self.get_capabilities()}
