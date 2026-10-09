"""Validate Meta hierarchy and normalize selected, non-overlapping action metrics."""
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo
from services.meta.provider import account_id,entity_id
from services.providers.contracts import ProviderError
from services.sync.schema import NormalizedRow,ParentRow,decimal_value
from services.storage.models import AdAccount,Entity,Campaign,AdSet,Ad,Creative,EntityCurrentState
from services.storage.repository import identity,upsert
from services.providers.models import ProviderCatalog

def numeric(value,count=False):
    if value is None:return None
    number=decimal_value(value)
    # Meta can return modeled/fractional action counts. Preserve raw precision;
    # the existing integer counters cannot honestly display a rounded result.
    if count and number!=number.to_integral_value():return None
    return decimal_value(value,count=count)
def action(values,kind,count=True):
    if values is None:return None
    if not isinstance(values,list):raise ProviderError("META_INVALID_ACTIONS")
    found=[v.get("value") for v in values if isinstance(v,dict) and v.get("action_type")==kind]
    if len(found)>1:raise ProviderError("META_DUPLICATE_ACTION_TYPE")
    return numeric(found[0],count) if found else None

def account_values(raw):
    aid=account_id(raw.get("id"))
    if account_id(raw.get("account_id"))!=aid:raise ProviderError("META_ACCOUNT_MISMATCH")
    currency=raw.get("currency");zone=raw.get("timezone_name")
    if not isinstance(currency,str) or not __import__("re").fullmatch("[A-Z]{3}",currency):raise ProviderError("META_CURRENCY_UNKNOWN")
    try:ZoneInfo(zone)
    except (ValueError,TypeError,KeyError):raise ProviderError("META_TIMEZONE_UNKNOWN") from None
    return {"account_id":aid,"account_name":raw.get("name"),"currency":currency,"timezone":zone}

def hierarchy(catalog):
    campaigns={entity_id(r["id"]):r for r in catalog["campaign"]}
    adsets={entity_id(r["id"]):r for r in catalog["adset"]}
    ads={entity_id(r["id"]):r for r in catalog["ad"]}
    creatives={entity_id(r["id"]):r for r in catalog["creative"]}
    if any(len(group)!=len(catalog[kind]) for kind,group in (("campaign",campaigns),("adset",adsets),("ad",ads),("creative",creatives))):raise ProviderError("META_DUPLICATE_ENTITY")
    for aset in adsets.values():
        if entity_id(aset.get("campaign_id")) not in campaigns:raise ProviderError("META_PARENT_MISMATCH")
    for ad in ads.values():
        sid=entity_id(ad.get("adset_id"));cid=entity_id(ad.get("campaign_id"))
        if sid not in adsets or cid not in campaigns or entity_id(adsets[sid].get("campaign_id"))!=cid:raise ProviderError("META_PARENT_MISMATCH")
        creative=(ad.get("creative") or {}).get("id")
        if creative and entity_id(creative) not in creatives:raise ProviderError("META_CREATIVE_MISMATCH")
    return campaigns,adsets,ads,creatives

def map_rows(raws,account,catalog,start,end,attribution):
    values=account_values(account);campaigns,adsets,ads,creatives=hierarchy(catalog);result=[];seen=set()
    for r in raws:
        aid=account_id(r.get("account_id"));eid=entity_id(r.get("ad_id"))
        cid=entity_id(r.get("campaign_id"));sid=entity_id(r.get("adset_id"))
        if aid!=values["account_id"] or r.get("account_currency")!=values["currency"] or eid not in ads or cid not in campaigns or sid not in adsets or entity_id(ads[eid]["adset_id"])!=sid or entity_id(ads[eid]["campaign_id"])!=cid:raise ProviderError("META_INSIGHT_ID_MISMATCH")
        try:day=date.fromisoformat(r["date_start"])
        except (ValueError,TypeError,KeyError):raise ProviderError("META_DATE_INVALID") from None
        if r.get("date_stop")!=str(day) or not start<=day<=end or (eid,day) in seen:raise ProviderError("META_WINDOW_MISMATCH")
        seen.add((eid,day))
        metrics={k:numeric(r.get(k),k in ("impressions","clicks","reach")) for k in ("spend","impressions","clicks","reach","frequency")}
        metrics.update(leads=action(r.get("actions"),attribution["lead_action_type"]),
            sales=action(r.get("actions"),attribution["purchase_action_type"]),conversions=None,
            revenue=action(r.get("action_values"),attribution["purchase_action_type"],False))
        creative=(ads[eid].get("creative") or {}).get("id")
        c=creatives.get(str(creative),{})
        raw={**r,"_provider":{"provider":"meta","account_id":aid,"attribution":attribution,"source_timestamp":None}}
        raw["inline_link_clicks"]=numeric(r.get("inline_link_clicks"),True)
        raw["video_starts"]=action(r.get("video_play_actions"),"video_view")
        raw["video_p100_views"]=action(r.get("video_p100_watched_actions"),"video_view")
        raw["landing_page_views"]=action(r.get("actions"),"landing_page_view")
        raw["registrations"]=action(r.get("actions"),"complete_registration")
        result.append(NormalizedRow(aid,values["account_name"],values["currency"],values["timezone"],
            eid,ads[eid].get("name"),"ad",day,metrics,None,None,None,
            {"status":ads[eid].get("effective_status") or ads[eid].get("status")},
            [ParentRow("campaign",cid,campaigns[cid].get("name"),{"status":campaigns[cid].get("effective_status")}),
             ParentRow("adset",sid,adsets[sid].get("name"),{"status":adsets[sid].get("effective_status")})],
            str(creative) if creative else None,c.get("name"),c.get("thumbnail_url"),{},None,raw))
    return result

def save_catalog(session,workspace,account,catalog,now):
    values=account_values(account);aid=identity(workspace,"meta",values["account_id"])
    upsert(session,AdAccount,{"id":aid,"workspace_id":workspace,"provider":"meta","external_id":values["account_id"],
        "name":values["account_name"],"currency":values["currency"],"timezone":values["timezone"],"observed_at":now,
        "labels":{"status":str(account.get("account_status"))}})
    # Validate the full catalog even if an account has no delivered ads.
    hierarchy(catalog)
    for kind in ("campaign","adset","creative","ad"):
        for raw in catalog[kind]:
            if account_id(raw.get("account_id"))!=values["account_id"]:raise ProviderError("META_ENTITY_ACCOUNT_MISMATCH")
            eid=entity_id(raw["id"]);key=identity(aid,kind,eid)
            upsert(session,Entity,{"id":key,"account_id":aid,"kind":kind,"external_id":eid,"name":raw.get("name")})
            links={}
            if kind=="adset":links["campaign_id"]=identity(aid,"campaign",entity_id(raw["campaign_id"]))
            if kind=="ad":
                links["adset_id"]=identity(aid,"adset",entity_id(raw["adset_id"]))
                creative=(raw.get("creative") or {}).get("id")
                links["creative_id"]=identity(aid,"creative",entity_id(creative)) if creative else None
            if kind=="creative":links["media_url"]=raw.get("thumbnail_url")
            upsert(session,{"campaign":Campaign,"adset":AdSet,"ad":Ad,"creative":Creative}[kind],{"entity_id":key,**links})
            upsert(session,ProviderCatalog,{"account_id":aid,"kind":kind,"external_id":eid,"observed_at":now,"payload":raw})
            if kind!="creative":
                # Values retain their exact provider units. Do not guess budget
                # scale or treat daily/lifetime budgets as interchangeable.
                upsert(session,EntityCurrentState,{"entity_id":key,"status":raw.get("effective_status") or raw.get("status"),
                    "budget":None,"bid":None,"observed_at":now,"raw":{**raw,"budget_units":"meta_minor_units_unverified"}})
    return aid
