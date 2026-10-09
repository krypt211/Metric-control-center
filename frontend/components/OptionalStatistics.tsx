"use client";
import {useEffect,useState} from "react";
import StatisticsGrid from "./StatisticsGrid";
function period(preset:string):[string,string]{
 const zone=process.env.NEXT_PUBLIC_REPORTING_TIMEZONE??"Europe/Moscow";
 const parts=new Intl.DateTimeFormat("en-CA",{timeZone:zone,year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(new Date());
 const get=(key:string)=>parts.find(p=>p.type===key)!.value;
 const day=new Date(get("year")+"-"+get("month")+"-"+get("day")+"T12:00:00Z");
 const shift=(n:number)=>new Date(day.getTime()-n*86400000).toISOString().slice(0,10);
 return preset==="yesterday"?[shift(1),shift(1)]:[shift(Number(preset)-1),shift(0)];
}
export default function OptionalStatistics({kind,refreshKey=0}:{kind:"tracker"|"creative";refreshKey?:number}){
 const [dates,setDates]=useState<[string,string]>(["",""]),[preset,setPreset]=useState("1"),[account,setAccount]=useState(""),[scope,setScope]=useState("account");
 const [accounts,setAccounts]=useState<{id:string;name:string}[]>([]),[error,setError]=useState("");
 useEffect(()=>{
 setDates(period("1"));const controller=new AbortController();
 void fetch("/api/stats/filters",{signal:controller.signal}).then(r=>{if(!r.ok)throw new Error();return r.json();}).then(d=>setAccounts(d.options.account)).catch(()=>{if(!controller.signal.aborted)setError("Не удалось загрузить кабинеты");});
 return()=>controller.abort();
 },[]);
 const query=new URLSearchParams({kind,scope,start:dates[0],end:dates[1]});if(account)query.set("account",account);
 return <section className="group">
 <div className="filterbar">
 {kind==="tracker"&&<label>Уровень<select value={scope} onChange={e=>setScope(e.target.value)}><option value="account">Кабинет / день</option><option value="ad">Объявление / период</option></select></label>}
 <label>Период<select value={preset} onChange={e=>{setPreset(e.target.value);if(e.target.value!=="custom")setDates(period(e.target.value));}}>
 {[["1","Сегодня"],["yesterday","Вчера"],["3","3 дня"],["7","7 дней"],["14","14 дней"],["30","30 дней"],["custom","Произвольный"]].map(([v,n])=><option key={v} value={v}>{n}</option>)}
 </select></label>
 <label>С<input type="date" value={dates[0]} onChange={e=>{setPreset("custom");setDates([e.target.value,dates[1]]);}}/></label>
 <label>По<input type="date" value={dates[1]} onChange={e=>{setPreset("custom");setDates([dates[0],e.target.value]);}}/></label>
 <label>Кабинет<select value={account} onChange={e=>setAccount(e.target.value)}><option value="">Все кабинеты</option>{accounts.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
 </div>
 <p className="notice">{kind==="tracker"?"Счётчики трекера: кабинет / день или объявление / период. Конверсии и наблюдаемые конверсии отделены. Валюта трекера не подтверждена: выручка, прибыль и ROI пока недоступны.":"Креативы сгруппированы по ключу MetricFlow за точный выбранный период. Денежные результаты трекера пока недоступны."}</p>
 {error&&<div className="notice error" role="alert">{error}</div>}
 <StatisticsGrid key={kind} scope={kind} endpoint="/api/stats/optional" query={query.toString()} refreshKey={refreshKey}/>
 </section>;
}
