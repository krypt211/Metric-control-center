"""Read exact-scope observations without joining them to core financial facts."""
from sqlalchemy import select
from services.storage.models import AdAccount, ReadStatistic
from services.analytics.dashboard import _ratio
from services.analytics.scopes import finance, creative_tracker_counts
def optional_statistics(session,workspace,start,end,kind,account=None,scope="account",*,sort_key=None,sort_direction="asc",offset=0,limit=None):
    if start>end or kind not in ("tracker","creative") or scope not in ("account","ad"):raise ValueError("Invalid optional query")
    from services.providers.router import DataSourceRouter
    from services.providers.matching import identity_maps
    routes=DataSourceRouter(session,workspace).resolve(start,end)
    amap,_=identity_maps(session,workspace)
    selected=[r["account_id"] for r in routes.values() if r["account_id"]]
    query=select(ReadStatistic,AdAccount).join(AdAccount,ReadStatistic.account_id==AdAccount.id).where(
        AdAccount.workspace_id==workspace,AdAccount.id.in_(selected),ReadStatistic.kind==kind)
    if account:query=query.where(AdAccount.id.in_([aid for aid in selected if account in (aid,amap.get(aid,aid))]))
    if kind=="creative" or scope=="ad":
        query=query.where(ReadStatistic.start_day==start,ReadStatistic.end_day==end)
    else:
        query=query.where(ReadStatistic.start_day>=start,ReadStatistic.end_day<=end)
    if kind=="tracker":
        query=query.where(ReadStatistic.scope_key=="account" if scope=="account" else ReadStatistic.scope_key!="account")
    rows=[]
    for observation,acct in session.execute(query):
        p=observation.payload
        if kind=="creative":
            m=p["metrics"]; money=m["spend"]
            rows.append({"id":observation.id,"account_id":amap.get(acct.id,acct.id),"account_name":acct.name or acct.external_id,
                "name":p.get("name") or "Creative "+observation.scope_key[:12],"creative_key":p["creative_key"],
                "creative_type":p.get("creative_type"),"thumbnail_url":p.get("thumbnail_url"),
                "ads_count":len(p["ad_ids"]),"currency":observation.currency,"timezone":observation.timezone,
                "start":str(start),"end":str(end),"scope":"account/creative/window",
                **m,"ctr":_ratio(m["clicks"],m["impressions"],100),"cpc":_ratio(money,m["clicks"]),
                "cpm":_ratio(money,m["impressions"],1000), **{"tracker_"+name: creative_tracker_counts(p.get("tracker"))[name] for name in ("clicks","conversions","leads","sales")}, **finance((p.get("tracker") or {}).get("revenue"), money, revenue_currency=None, spend_currency=observation.currency, revenue_scope=None, spend_scope=(acct.id,str(start),str(end)))})
        else:
            rows.append({"id":observation.id,"account_id":amap.get(acct.id,acct.id),"account_name":acct.name or acct.external_id,
                "date":str(observation.start_day) if scope=="account" else str(start)+" - "+str(end),
                "name":p.get("name"),"ad_id":p.get("ad_id"),"scope":"account/tracker/day" if scope=="account" else "ad/tracker/window",
                **p["counts"],"currency":None,"timezone":None,"spend":None, **finance(p["raw"].get("revenue"), p["raw"].get("cost"), revenue_currency=observation.currency, spend_currency=observation.currency, revenue_scope=None, spend_scope=None)})
    if kind=="creative":
        from services.analytics.table import table_data,Filters
        core=table_data(session,workspace,Filters(start,end,account=account),level="creative",limit=1000000)
        selected_meta={r["canonical_id"] for r in routes.values() if r["provider"]=="meta"}
        account_names={amap.get(a.id,a.id):a.name or a.external_id for a in session.scalars(select(AdAccount).where(AdAccount.id.in_(selected)))}
        for item in core["rows"]:
            if item["account_id"] in selected_meta:
                rows.append({**item,"account_name":account_names.get(item["account_id"],item["account_id"]),"creative_key":item["external_id"],"thumbnail_url":item["media_url"],
                    "creative_type":None,"ads_count":None,"start":str(start),"end":str(end),"scope":"meta/account/creative/window"})
    rows.sort(key=lambda r:(r["account_name"],r.get("date",""),r.get("id","")))
    total=len(rows)
    if sort_key:
        from services.preferences.registry import sort_rows
        rows=sort_rows(rows,sort_key,sort_direction,"tracker" if kind=="tracker" else "creative")
    rows=rows[offset:offset+limit] if limit is not None else rows[offset:]
    return {"next_offset":offset+limit if limit is not None and total>offset+limit else None,"kind":kind,"start":str(start),"end":str(end),"rows":rows,"total":total,
        "scope":scope,"status":"ready" if rows else "not_loaded",
        "financial_status":"unverified_currency_and_scope",
        "note":"Tracker money and timezone are not proven. Creative metrics are exact-window observations; they are not historical Meta creative IDs."}
