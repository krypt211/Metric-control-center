"use client";
import {useCallback,useEffect,useState} from "react";
import {economicRange,levelNames,type Level} from "../lib/economics";
import {readEconomics} from "../lib/economics-api";
import EconomicProfiles from "./EconomicProfiles";
import EconomicSettings,{type Settings} from "./EconomicSettings";
import EconomicsTable from "./EconomicsTable";
export default function Economics() {
 const [settings,setSettings]=useState<Settings|null>(null),[error,setError]=useState(""),[refresh,setRefresh]=useState(0);
 const [level,setLevel]=useState<Level>("account"),[dates,setDates]=useState<[string,string]>(["",""]),[preset,setPreset]=useState("closed7"),[profile,setProfile]=useState("");
 const [filters,setFilters]=useState({account:"",campaign:"",adset:"",ad:"",offer:"",geo:""}),[tab,setTab]=useState("stats");
 const load=useCallback(async()=>{setSettings(await readEconomics<Settings>("settings"));},[]);
 useEffect(()=>{setDates(economicRange("closed7"));const abort=new AbortController();void readEconomics<Settings>("settings",abort.signal).then(setSettings).catch(e=>{if(!abort.signal.aborted)setError(e.message);});return()=>abort.abort();},[]);
 useEffect(()=>{if(preset==="custom")return;const update=()=>{const next=economicRange(preset);setDates(old=>old[0]===next[0]&&old[1]===next[1]?old:next);};const timer=setInterval(update,60000);window.addEventListener("focus",update);return()=>{clearInterval(timer);window.removeEventListener("focus",update);};},[preset]);
 async function changed(id?:string){await load();if(id)setProfile(id);else setProfile("");setRefresh(v=>v+1);}
 const validProfile=settings?.profiles.find(p=>p.id===profile&&!p.deleted);
 const query=new URLSearchParams({start:dates[0],end:dates[1],...(validProfile?{profile_id:profile}:{}),...Object.fromEntries(Object.entries(filters).filter(([,v])=>v))}).toString();
 return <div className="economics-surface">
 <p className="notice">Рекламные действия отключены. Здесь сохраняются только экономические настройки и ручные подтверждения.</p>
 {error&&<p className="notice error" role="alert">{error}</p>}{!settings?<p role="status">Загрузка профилей…</p>:<>
 <nav className="tabs" aria-label="Раздел экономики">{[["stats","Финансовая статистика"],["profiles","Профили"],["approval","Апрув и назначения"]].map(([id,name])=><button key={id} className={tab===id?"active":""} onClick={()=>setTab(id)}>{name}</button>)}</nav>
 {!settings.can_edit&&<p className="notice">Доступен просмотр. Для редактирования оператору необходимо разрешение администратора.</p>}
 {tab==="stats"&&<>
 <div className="filters"><label>Период экономики<select value={preset} onChange={e=>{setPreset(e.target.value);if(e.target.value!=="custom")setDates(economicRange(e.target.value));}}><option value="closed7">7 завершённых дней</option><option value="1">Сегодня</option><option value="yesterday">Вчера</option>{[3,7,14,30].map(n=><option key={n} value={n}>Последние {n} дней (включая сегодня)</option>)}<option value="custom">Свой период</option></select></label><label>Дата начала<input aria-label="Дата начала" type="date" value={dates[0]} max={dates[1]} onChange={e=>{setPreset("custom");setDates([e.target.value,dates[1]]);}}/></label><label>Дата окончания<input aria-label="Дата окончания" type="date" value={dates[1]} min={dates[0]} onChange={e=>{setPreset("custom");setDates([dates[0],e.target.value]);}}/></label><label>Профиль оценки<select value={profile} onChange={e=>setProfile(e.target.value)}><option value="">По назначениям</option>{settings.profiles.filter(p=>!p.deleted).map(p=><option key={p.id} value={p.id}>{p.name} · {p.geo||"все GEO"} · {p.currency}</option>)}</select></label>
 {(["account","offer","geo"] as const).map(key=><label key={key}>{{account:"Кабинет",offer:"Оффер",geo:"GEO"}[key]}<select value={filters[key]} onChange={e=>setFilters(f=>({...f,[key]:e.target.value,...(key==="account"?{campaign:"",adset:"",ad:""}:{})}))}><option value="">Все</option>{(settings.options.options[key]??[]).map(o=><option key={o.id} value={o.id}>{o.name}</option>)}</select></label>)}<button onClick={()=>setRefresh(v=>v+1)}>Обновить оценку</button></div>
 <p className="table-note">Даты выбираются по Москве; статистика каждого кабинета учитывает его локальные календарные дни, обе границы включены. По умолчанию — семь завершённых дней.</p>
 <nav className="tabs" aria-label="Уровень экономики">{(["account","campaign","adset","ad"] as Level[]).map(l=><button key={l} className={l===level?"active":""} onClick={()=>{setLevel(l);setFilters(f=>({...f,...Object.fromEntries((["account","campaign","adset","ad"] as Level[]).slice((["account","campaign","adset","ad"] as Level[]).indexOf(l)).map(k=>[k,""]))}));}}>{levelNames[l]}</button>)}</nav>
 <EconomicsTable key={level} level={level} query={query} refresh={refresh} onName={row=>{const levels:Level[]=["account","campaign","adset","ad"],i=levels.indexOf(level);setFilters(f=>({...f,[level]:String(row.id),...Object.fromEntries(levels.slice(i+1).map(k=>[k,""]))}));if(i<3)setLevel(levels[i+1]);}}/>
 </>}
 {tab==="profiles"&&<EconomicProfiles profiles={settings.profiles} canEdit={settings.can_edit} changed={changed}/>}
 {tab==="approval"&&<EconomicSettings data={settings} dates={dates} changed={()=>changed()}/>}
 </>}
 </>;
}