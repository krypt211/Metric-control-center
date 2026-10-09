"""One source per canonical account and entire requested window, never sum providers."""
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select
from services.providers.models import ProviderConnection,ProviderAccountMapping,ProviderRoutingSetting,ProviderWindow,ProviderSwitchEvent
from services.storage.models import AdAccount,DailyMetric,Entity
from services.sync.engine import utc_now,aware
from services.providers.matching import hierarchy_hash
STALE_SECONDS=1800

def windows_for(session,account,start,end,*,revision=None):
    rows=session.scalars(select(ProviderWindow).where(ProviderWindow.account_id==account.id,ProviderWindow.complete.is_(True),
        ProviderWindow.start_day<=end,ProviderWindow.end_day>=start).order_by(ProviderWindow.imported_at.desc())).all()
    if revision is not None:rows=[r for r in rows if r.credential_revision==revision]
    selected=[];day=start
    while day<=end:
        covers=[r for r in rows if r.start_day<=day<=r.end_day]
        if not covers:return []
        r=covers[0]
        if r not in selected:selected.append(r)
        day+=timedelta(days=1)
    return selected

class DataSourceRouter:
    def __init__(self,session,workspace,now=None):self.session=session;self.workspace=workspace;self.now=now or utc_now()
    def resolve(self,start,end,*,provider_override=None):
        s=self.session
        accounts=s.scalars(select(AdAccount).where(AdAccount.workspace_id==self.workspace)).all()
        mappings={m.account_id:m for m in s.scalars(select(ProviderAccountMapping).where(ProviderAccountMapping.workspace_id==self.workspace))}
        connections={c.provider:c for c in s.scalars(select(ProviderConnection).where(ProviderConnection.workspace_id==self.workspace))}
        families={}
        for a in accounts:
            m=mappings.get(a.id);families.setdefault(m.canonical_id if m else a.id,[]).append(a)
        default=s.get(ProviderRoutingSetting,(self.workspace,"workspace"))
        resolved={}
        def connection_ok(a):
            c=connections.get(a.provider)
            return (c.enabled and c.status in ("healthy","partial")) if c else a.provider=="metricflow"
        def fresh(a,windows):
            c=connections.get(a.provider)
            return bool(windows and all((self.now-aware(w.imported_at)).total_seconds()<=STALE_SECONDS and
                (not c or w.credential_revision==c.revision) for w in windows))
        def compatible(primary,fallback,pw,fw):
            if not primary or not fallback or not pw or not fw:return False,"INCOMPLETE_WINDOW"
            pm,fm=mappings.get(primary.id),mappings.get(fallback.id)
            if not pm or not fm or not pm.meta_account_id or pm.meta_account_id!=fm.meta_account_id:return False,"ACCOUNT_UNCONFIRMED"
            if (primary.currency,primary.timezone)!=(fallback.currency,fallback.timezone):return False,"CURRENCY_TIMEZONE_MISMATCH"
            attrs=[w.attribution for w in pw+fw]
            if any(not a for a in attrs) or any(a!=attrs[0] for a in attrs):return False,"ATTRIBUTION_UNCONFIRMED"
            # Hash current delivered object/parent IDs for this exact interval,
            # rather than comparing catalogs with different irrelevant objects.
            ph=hierarchy_hash(s,primary.id,start,end);fh=hierarchy_hash(s,fallback.id,start,end)
            if ph is None or ph!=fh:return False,"ENTITY_HIERARCHY_MISMATCH"
            return True,None
        for canonical,members in families.items():
            setting=s.get(ProviderRoutingSetting,(self.workspace,canonical)) or default
            primary_name=provider_override or (setting.primary_provider if setting else "metricflow")
            fallback_name=None if provider_override else setting.fallback_provider if setting else None
            primary=next((a for a in members if a.provider==primary_name),None)
            fallback=next((a for a in members if a.provider==fallback_name),None)
            pc=connections.get(primary.provider) if primary else None
            fc=connections.get(fallback.provider) if fallback else None
            pw=windows_for(s,primary,start,end,revision=pc.revision if pc else None) if primary else []
            fw=windows_for(s,fallback,start,end,revision=fc.revision if fc else None) if fallback else []
            # Legacy verified MetricFlow facts remain readable before the first
            # provider coverage run, explicitly marked according to timestamps.
            primary_fresh=fresh(primary,pw) if primary else False
            if primary and not pw and primary.provider=="metricflow":
                observed=s.scalar(select(DailyMetric.observed_at).join(Entity).where(Entity.account_id==primary.id,
                    DailyMetric.day>=start,DailyMetric.day<=end).order_by(DailyMetric.observed_at).limit(1))
                primary_fresh=bool(observed and (self.now-aware(observed)).total_seconds()<=STALE_SECONDS)
            chosen=primary;mode="primary";reason=None;stale=True
            if primary and connection_ok(primary) and primary_fresh:stale=False
            else:
                ok,reason=compatible(primary,fallback,pw,fw)
                if ok and fallback and connection_ok(fallback) and fresh(fallback,fw):
                    chosen=fallback;mode="fallback";stale=False;reason="READ_FALLBACK"
                else:
                    reason=reason or "PROVIDER_UNAVAILABLE"
                    if chosen is None:
                        # Last known snapshot is evidence, not a healthy fallback.
                        chosen=max(members,key=lambda a:aware(a.observed_at)) if members else None
                    mode="stale"
            at=None
            cw=pw if chosen==primary else fw if chosen==fallback else windows_for(s,chosen,start,end) if chosen else []
            if cw:at=min(aware(w.imported_at) for w in cw).isoformat()
            elif chosen:at=aware(chosen.observed_at).isoformat()
            resolved[canonical]={"canonical_id":canonical,"account_id":chosen.id if chosen else None,
                "provider":chosen.provider if chosen else None,"primary":primary_name,"fallback":fallback_name,
                "mode":mode,"stale":stale,"reason":reason,"updated_at":at,
                "connection":connections[chosen.provider].status if chosen and chosen.provider in connections else "unverified",
                "provider_account_id":chosen.external_id if chosen else None}
            if chosen:
                from services.providers.presentation import period_evidence
                connection=connections.get(chosen.provider)
                evidence=period_evidence(s,chosen,start,end,self.now,connection.revision if connection else None)
                resolved[canonical].update(evidence)
                if not evidence["facts_readable"]:
                    resolved[canonical].update(stale=True,mode="stale",reason="INCOMPLETE_WINDOW")
            if not provider_override:
                last=s.scalar(select(ProviderSwitchEvent).where(ProviderSwitchEvent.workspace_id==self.workspace,
                    ProviderSwitchEvent.canonical_id==canonical,ProviderSwitchEvent.period_start==start,
                    ProviderSwitchEvent.period_end==end).order_by(ProviderSwitchEvent.created_at.desc()).limit(1))
                state_reason=reason or "PRIMARY"
                if mode=="fallback" or (last and (last.active_provider!=resolved[canonical]["provider"] or last.reason!=state_reason)):
                    if not last or last.active_provider!=resolved[canonical]["provider"] or last.reason!=state_reason:
                        s.add(ProviderSwitchEvent(id=str(uuid4()),workspace_id=self.workspace,canonical_id=canonical,
                            previous_provider=last.active_provider if last else primary_name,
                            active_provider=resolved[canonical]["provider"],reason=state_reason,
                            period_start=start,period_end=end,created_at=self.now))
        return resolved
