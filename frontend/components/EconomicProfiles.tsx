"use client";
import {useEffect,useState} from "react";
import {emptyProfile,percentToRate,rateToPercent,profileCommand,type Profile,localized} from "../lib/economics";
import {readEconomics,writeEconomics} from "../lib/economics-api";
import {formatMetric} from "../lib/column-model";
type Audit={event:string;created_at:string;payload:{after?:Profile;before?:Profile}};
export default function EconomicProfiles({profiles,canEdit,changed}:{profiles:Profile[];canEdit:boolean;changed:(id?:string)=>Promise<void>}) {
 const [draft,setDraft]=useState<Profile>({...emptyProfile}),[percent,setPercent]=useState("30"),[history,setHistory]=useState<Audit[]>([]),[restoreVersion,setRestoreVersion]=useState("1");
 const [preview,setPreview]=useState<Record<string,unknown>|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
 function choose(p:Profile){setDraft({...p});setPercent(rateToPercent(p.planned_approval_rate));setError("");setPreview(null);setRestoreVersion(String(p.version??1));}
 useEffect(()=>{if(!draft.id){setHistory([]);return;}const abort=new AbortController();void readEconomics<{rows:Audit[]}>("audit?resource_id="+draft.id,abort.signal).then(d=>setHistory(d.rows)).catch(e=>{if(!abort.signal.aborted)setError(e.message);});return()=>abort.abort();},[draft.id,draft.version]);
 function set(key:keyof Profile,value:string|number){setDraft(p=>({...p,[key]:value}));setPreview(null);}
 async function act(fn:()=>Promise<void>){setBusy(true);setError("");try{await fn();}catch(e){setError(e instanceof Error?e.message:"Не удалось сохранить");}finally{setBusy(false);}}
 function command(){if(!draft.name.trim())throw new Error("Введите название профиля.");if(!Number.isFinite(Number(draft.target_roi))||!Number.isFinite(Number(draft.minimum_roi))||Number(draft.minimum_roi)<=-100||Number(draft.target_roi)<=-100||Number(draft.target_roi)<Number(draft.minimum_roi))throw new Error("ROI должен быть больше −100%, целевой — не ниже минимального.");return {...profileCommand(draft),planned_approval_rate:percentToRate(percent)};}
 async function save(){await act(async()=>{const result=await writeEconomics<Profile>(draft.id?"profiles/"+draft.id:"profiles",draft.id?"PUT":"POST",{...command(),...(draft.id?{version:draft.version}:{})});choose(result);await changed(result.id);});}
 return <section className="economic-panel" aria-label="Экономические профили">
 <h2>Экономические профили</h2><p>Выплата и проценты задают прогноз. Подтверждённый ROI требует совместимой когорты и подтверждения выручки.</p>
 <div className="filters"><label>Редактируемый профиль<select aria-label="Редактируемый профиль" value={draft.id??""} onChange={e=>choose(profiles.find(p=>p.id===e.target.value)??{...emptyProfile})}><option value="">Новый профиль</option>{profiles.map(p=><option key={p.id} value={p.id}>{p.name}{p.deleted?" (удалён)":""} · v{p.version}</option>)}</select></label><button disabled={!canEdit||busy} onClick={()=>choose({...emptyProfile})}>Новый профиль</button></div>
 <form onSubmit={e=>{e.preventDefault();void save();}}>
 <fieldset disabled={!canEdit||busy||draft.deleted} className="economic-fields">
 <label>Название профиля<input required maxLength={120} value={draft.name} onChange={e=>set("name",e.target.value)}/></label>
 <label>Оффер<input maxLength={128} value={draft.offer} onChange={e=>set("offer",e.target.value)}/></label>
 <label>GEO<input maxLength={2} pattern="[A-Z]{2}|" value={draft.geo} onChange={e=>set("geo",e.target.value.toUpperCase())}/></label>
 <label>Выплата за апрув<input required inputMode="decimal" pattern="[0-9]+(\.[0-9]{1,8})?" value={draft.payout} onChange={e=>set("payout",e.target.value)}/></label>
 <label>Валюта профиля<input required maxLength={3} pattern="[A-Z]{3}" value={draft.currency} onChange={e=>set("currency",e.target.value.toUpperCase())}/></label>
 <label>Целевой ROI, %<input required inputMode="decimal" value={draft.target_roi} onChange={e=>set("target_roi",e.target.value)}/></label>
 <label>Минимальный ROI, %<input required inputMode="decimal" value={draft.minimum_roi} onChange={e=>set("minimum_roi",e.target.value)}/></label>
 <label>Плановый апрув, %<input required inputMode="decimal" value={percent} onChange={e=>{setPercent(e.target.value);setPreview(null);}}/></label>
 <label>Источник лидов<select value={draft.lead_source} onChange={e=>set("lead_source",e.target.value)}><option value="meta">Лиды Meta</option><option value="tracker">Лиды трекера</option></select></label>
 <label>Минимум лидов<input type="number" min={1} max={100000000} required value={draft.minimum_leads} onChange={e=>set("minimum_leads",Number(e.target.value))}/></label>
 <label>Минимум продаж<input type="number" min={0} max={100000000} required value={draft.minimum_sales} onChange={e=>set("minimum_sales",Number(e.target.value))}/></label>
 <label>Порог продаж считается по<select value={draft.sale_threshold_type} onChange={e=>set("sale_threshold_type",e.target.value)}><option value="approved">Подтверждённым апрувам</option><option value="observed">Покупкам Meta (не апрувам)</option><option value="estimated">Прогнозным апрувам</option></select></label>
 <label>Минимум обработанных решений<input type="number" min={1} max={100000000} required value={draft.minimum_processed} onChange={e=>set("minimum_processed",Number(e.target.value))}/></label>
 <label>Созревание, часов<input type="number" min={0} max={8760} required value={draft.maturation_hours} onChange={e=>set("maturation_hours",Number(e.target.value))}/></label>
 <label>Политика апрува<select value={draft.actual_approval_policy} onChange={e=>set("actual_approval_policy",e.target.value)}><option value="planned">Всегда плановый</option><option value="mature_actual">Зрелый ручной при достаточной выборке</option></select></label>
 </fieldset>
 <div className="actionbuttons"><button type="button" disabled={busy||draft.deleted} onClick={()=>void act(async()=>setPreview(await writeEconomics("preview","POST",command())))}>Рассчитать ориентиры</button><button type="submit" disabled={!canEdit||busy||draft.deleted}>Сохранить профиль</button>{draft.id&&!draft.deleted&&<><button type="button" disabled={!canEdit||busy} onClick={()=>void act(async()=>{const p=await writeEconomics<Profile>("profiles/"+draft.id+"/copy","POST",{version:draft.version});choose(p);await changed(p.id);})}>Копировать профиль</button><button type="button" className="danger" disabled={!canEdit||busy} onClick={()=>{if(window.confirm("Удалить профиль? История сохранится."))void act(async()=>{const p=await writeEconomics<Profile>("profiles/"+draft.id,"DELETE",{version:draft.version});choose(p);await changed();});}}>Удалить профиль</button></>}</div>
 </form>
 {preview&&<div className="cards" data-testid="economics-preview">{(["target_cpl","maximum_cpl","target_approved_cps","maximum_approved_cps"] as const).map(k=><article className="card" key={k}><h3>{{target_cpl:"Целевой CPL",maximum_cpl:"Максимальный CPL",target_approved_cps:"Целевой CPS апрува",maximum_approved_cps:"Максимальный CPS апрува"}[k]}</h3><p className="value">{formatMetric(preview[k],k,draft.currency)}</p><p className="card-note">Плановый ориентир · {percent}% апрува</p></article>)}</div>}
 {error&&<p className="notice error" role="alert">{error}</p>}
 {draft.id&&<details><summary>История и восстановление профиля</summary><ul>{history.map((h,i)=><li key={i}>{new Date(h.created_at).toLocaleString("ru-RU")} · {localized(h.event)} · v{h.payload.after?.version??h.payload.before?.version}</li>)}</ul><div className="filters"><label>Версия для восстановления<select value={restoreVersion} onChange={e=>setRestoreVersion(e.target.value)}>{Array.from(new Set(history.map(h=>h.payload.after?.version).filter((v):v is number=>typeof v==="number"))).map(v=><option key={v} value={v}>v{v}</option>)}</select></label><button disabled={!canEdit||busy||!history.length} onClick={()=>void act(async()=>{const p=await writeEconomics<Profile>("profiles/"+draft.id+"/restore","POST",{version:draft.version,restore_version:Number(restoreVersion)});choose(p);await changed(p.id);})}>Восстановить версию</button></div></details>}
 </section>;
}