"use client";
import {useEffect,useState} from "react";
import type {TableScope} from "../lib/metric-registry";
import {useColumnPreferences} from "../lib/use-column-preferences";
import ColumnManager from "./ColumnManager";
import StatisticsTable,{type StatisticsRow} from "./StatisticsTable";
export default function StatisticsGrid({scope,endpoint,query,refreshKey=0,onName,selection}:{scope:TableScope;endpoint:string;query:string;refreshKey?:number;onName?:(row:StatisticsRow)=>void;selection?:Parameters<typeof StatisticsTable>[0]["selection"]}){
 const columns=useColumnPreferences(scope);
 const [rows,setRows]=useState<StatisticsRow[]>([]),[offset,setOffset]=useState(0),[next,setNext]=useState<number|null>(null),[total,setTotal]=useState(0);
 const [error,setError]=useState(""),[busy,setBusy]=useState(false);
 const sort=columns.config.sorting;
 useEffect(()=>{setOffset(0);},[query,sort?.key,sort?.direction]);
 useEffect(()=>{
 const params=new URLSearchParams(query);if(!params.get("start")||!params.get("end"))return;
 const controller=new AbortController();params.set("offset",String(offset));params.set("limit","100");
 if(sort){params.set("sort_key",sort.key);params.set("sort_direction",sort.direction);}
 setBusy(true);
 void fetch(endpoint+"?"+params,{cache:"no-store",signal:controller.signal}).then(async r=>{
 const data=await r.json();if(r.status===401){window.location.assign("/login");throw new Error("Повторите вход");}
 if(!r.ok)throw new Error("Не удалось загрузить статистику.");return data;
 }).then(data=>{if(controller.signal.aborted)return;setRows(data.rows);setNext(data.next_offset??null);setTotal(data.total);setError("");})
 .catch(e=>{if(!controller.signal.aborted)setError(e.message);}).finally(()=>{if(!controller.signal.aborted)setBusy(false);});
 return()=>controller.abort();
 },[endpoint,query,offset,sort?.key,sort?.direction,refreshKey]);
 return <div className="statistics-grid">
 <ColumnManager scope={scope} controller={columns} rows={rows}/>
 {error&&<p className="notice error" role="alert">{error}</p>}
 {busy&&<p role="status">Загрузка статистики…</p>}
 <StatisticsTable scope={scope} rows={rows} config={columns.config} change={columns.change} commit={()=>void columns.persist().catch(()=>{})} disabled={!columns.ready||columns.busy} onName={onName} selection={selection}/>
 <div className="pagination"><span>{total?(offset+1)+"–"+Math.min(offset+100,total)+" из "+total:"0 строк"}</span><button disabled={offset===0||busy} onClick={()=>setOffset(Math.max(0,offset-100))}>Назад</button><button disabled={next===null||busy} onClick={()=>next!==null&&setOffset(next)}>Далее</button></div>
 </div>;
}
