"""Require exact scope and currency before mixing provider monetary observations."""
from decimal import Decimal
from services.sync.schema import SchemaError, decimal_value, page_items

COMPLETE={"mode":"none","total_path":"meta.total","require_null_paths":["meta.limit","meta.offset"]}
BASE=("spend","impressions","clicks","leads","purchases","conversions")

def complete_window(payload,start,end):
    rows,cursor=page_items(payload,"data",COMPLETE)
    meta=payload["meta"]
    if meta.get("date_range")!={"from":str(start),"to":str(end)} or not meta.get("data_updated_at"):
        raise SchemaError("Optional endpoint window/version is not explicit")
    if cursor or meta.get("failed_accounts"):
        raise SchemaError("Optional endpoint is incomplete")
    return rows,meta

def finance(revenue,spend,*,revenue_currency,spend_currency,revenue_scope,spend_scope):
    if (not revenue_currency or revenue_currency!=spend_currency or
        revenue_scope is None or revenue_scope!=spend_scope or revenue is None or spend is None):
        return {"revenue":None,"profit":None,"roi":None}
    revenue=decimal_value(revenue);spend=decimal_value(spend)
    profit=revenue-spend
    return {"revenue":str(revenue),"profit":str(profit),
            "roi":str(profit/spend*100) if spend else None}

def creative_tracker_counts(raw):
    if raw is not None and not isinstance(raw,dict):
        raise SchemaError("Creative tracker must be an object or null")
    return {name:decimal_value((raw or {}).get(name),count=True)
            for name in ("clicks","conversions","leads","sales")}

def creative_window(ads_payload,creative_payload,start,end,currency):
    ads,am=complete_window(ads_payload,start,end)
    creatives,cm=complete_window(creative_payload,start,end)
    if am["data_updated_at"]!=cm["data_updated_at"]:
        raise SchemaError("Creative and ads snapshots have different versions")
    by_key={};ids=set()
    for ad in ads:
        if not isinstance(ad.get("id"),str) or not ad["id"].isascii() or not ad["id"].isdigit() or ad["id"] in ids:
            raise SchemaError("Invalid/duplicate ad identity")
        ids.add(ad["id"])
        if ad.get("currency")!=currency:raise SchemaError("Ad currency differs from its account")
        key=ad.get("creative_key")
        if key is not None:
            if not isinstance(key,str) or not key:raise SchemaError("Invalid opaque creative key")
            by_key.setdefault(key,[]).append(ad)
    keys=set();result=[]
    for item in creatives:
        key=item.get("creative_key")
        if not isinstance(key,str) or not key or key in keys or key not in by_key:
            raise SchemaError("Creative identity/linkage is not proven")
        keys.add(key);linked=by_key[key]
        metrics={}
        for name in BASE:
            count=name!="spend"
            actual=decimal_value(item.get(name),count=count)
            values=[decimal_value(a.get(name),count=count) for a in linked]
            if actual is None or any(v is None for v in values) or actual!=sum(values):
                raise SchemaError("Creative totals differ from linked ads")
            metrics["sales" if name=="purchases" else name]=str(actual) if name=="spend" else actual
        # Exact-window attribution only. Never apply current creative metadata to historical ad/day facts.
        result.append({"creative_key":key,"creative_type":item.get("creative_type"),
            "thumbnail_url":item.get("thumbnail_url"),"name":item.get("title") or item.get("body"),
            "ad_ids":[a["id"] for a in linked],"metrics":metrics,
            "tracker":item.get("tracker"),"tracker_counts":creative_tracker_counts(item.get("tracker")),"currency":currency,"version":cm["data_updated_at"]})
    return result

def tracker_days(payload,start,end):
    rows,meta=complete_window(payload,start,end);days=set();result=[]
    from datetime import date
    for item in rows:
        try:day=date.fromisoformat(item["date"])
        except (KeyError,TypeError,ValueError):raise SchemaError("Missing tracker day") from None
        if not start<=day<=end or day in days:raise SchemaError("Duplicate/out-of-window tracker day")
        days.add(day)
        counts={name:decimal_value(item.get(name),count=True) for name in
            ("clicks","unique_clicks","conversions","leads","sales","regs","deposits")}
        # Source monetary values are retained in raw only when currency/timezone is unproven.
        result.append({"date":str(day),"counts":counts,
            "currency":meta.get("currency"),"timezone":meta.get("timezone"),
            "raw":item,"version":meta["data_updated_at"]})
    return result

def breakdown_identity(payload,start,end,dimension):
    rows,meta=complete_window(payload,start,end)
    if meta.get("breakdown")!=dimension:
        raise SchemaError("Provider does not identify the requested breakdown dimension")
    # Without this field, age-like values must not be relabeled as country/device/etc.
    return rows,meta

def tracker_ad_windows(payload,start,end):
    ads,meta=complete_window(payload,start,end)
    result=[];ids=set()
    for ad in ads:
        eid=ad.get("id")
        if not isinstance(eid,str) or not eid.isascii() or not eid.isdigit() or eid in ids:
            raise SchemaError("Invalid tracker ad identity")
        ids.add(eid)
        tracker=ad.get("tracker")
        if tracker is None:continue
        if not isinstance(tracker,dict):raise SchemaError("Tracker must be an object or null")
        counts={name:decimal_value(tracker.get("t_"+name),count=True) for name in
            ("clicks","unique_clicks","conversions","conversions_raw","leads","sales","regs","deposits")}
        # The view is a sparse observation catalog; an absent ad is never treated as known zero.
        if not any(v for v in counts.values()):
            continue
        result.append({"scope":"ad/window","ad_id":eid,"name":ad.get("name"),"counts":counts,
            "raw":tracker,"version":meta["data_updated_at"]})
    return result

