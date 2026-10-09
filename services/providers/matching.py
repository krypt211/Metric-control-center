"""Canonical identities are proven by numeric Meta IDs, never by names."""
import hashlib,json,re
from sqlalchemy import select
from services.storage.models import AdAccount,Entity,Ad,AdSet
from services.storage.repository import upsert
from services.providers.models import ProviderAccountMapping
from services.sync.engine import utc_now

def confirm_accounts(session,workspace):
    accounts=session.scalars(select(AdAccount).where(AdAccount.workspace_id==workspace).order_by(AdAccount.provider.desc(),AdAccount.id)).all()
    by_meta={}
    for a in accounts:
        old=session.get(ProviderAccountMapping,a.id)
        if old:
            if old.meta_account_id:by_meta.setdefault(old.meta_account_id,old.canonical_id)
    for a in accounts:
        if session.get(ProviderAccountMapping,a.id):continue
        proven=a.external_id if a.provider in ("metricflow","meta") and re.fullmatch(r"act_[0-9]+",a.external_id) else None
        canonical=by_meta.setdefault(proven,a.id) if proven else a.id
        upsert(session,ProviderAccountMapping,{"account_id":a.id,"workspace_id":workspace,"canonical_id":canonical,
            "meta_account_id":proven,"proof":"catalog_meta_id" if proven else "unconfirmed","confirmed_by":None,"updated_at":utc_now()})
    session.flush()

def hierarchy_hash(session,account_id,start=None,end=None):
    from services.storage.models import DailyMetric
    entities={r.id:r for r in session.scalars(select(Entity).where(Entity.account_id==account_id))}
    adsets={r.entity_id:r for r in session.scalars(select(AdSet).where(AdSet.entity_id.in_(entities)))}
    ads=session.scalars(select(Ad).where(Ad.entity_id.in_(entities))).all()
    if start is not None:
        delivered=set(session.scalars(select(DailyMetric.entity_id).where(DailyMetric.entity_id.in_(entities),DailyMetric.day>=start,DailyMetric.day<=end)))
        ads=[a for a in ads if a.entity_id in delivered]
    links=[]
    for ad in ads:
        aset=adsets.get(ad.adset_id)
        campaign=entities.get(aset.campaign_id) if aset else None
        if not aset or not campaign:return None
        links.append((entities[ad.entity_id].external_id,entities[ad.adset_id].external_id,campaign.external_id))
    return hashlib.sha256(json.dumps(sorted(links)).encode()).hexdigest()

def identity_maps(session,workspace):
    """Stable IDs from the canonical account + verified object hierarchy."""
    accounts={a.id:a for a in session.scalars(select(AdAccount).where(AdAccount.workspace_id==workspace))}
    mappings={m.account_id:m for m in session.scalars(select(ProviderAccountMapping).where(ProviderAccountMapping.workspace_id==workspace))}
    entities={e.id:e for e in session.scalars(select(Entity).where(Entity.account_id.in_(accounts)))}
    adsets={r.entity_id:r for r in session.scalars(select(AdSet).where(AdSet.entity_id.in_(entities)))}
    ads={r.entity_id:r for r in session.scalars(select(Ad).where(Ad.entity_id.in_(entities)))}
    def signature(e):
        if e.kind=="adset":
            parent=adsets.get(e.id);p=entities.get(parent.campaign_id) if parent else None
            return (e.kind,e.external_id,p.external_id) if p else (e.kind,e.external_id,e.id)
        if e.kind=="ad":
            ad=ads.get(e.id);aset=adsets.get(ad.adset_id) if ad else None;p=entities.get(aset.campaign_id) if aset else None
            return (e.kind,e.external_id,entities[ad.adset_id].external_id,p.external_id) if p else (e.kind,e.external_id,e.id)
        return (e.kind,e.external_id)
    originals={(e.account_id,signature(e)):e.id for e in entities.values()}
    translated={}
    for e in entities.values():
        mapping=mappings.get(e.account_id);canonical=mapping.canonical_id if mapping else e.account_id
        translated[e.id]=originals.get((canonical,signature(e)),e.id)
    return {aid:mappings[aid].canonical_id if aid in mappings else aid for aid in accounts},translated
