"use client";
import {useEffect,useState} from "react";
import SourceSummary,{type Source} from "./SourceSummary";
export default function DataSources({start,end,account="",refreshKey=0}:{start:string;end:string;account?:string;refreshKey?:number}){
 const [rows,setRows]=useState<Source[]>([]),[error,setError]=useState("");
 useEffect(()=>{
   if(!start||!end)return;
   const controller=new AbortController();
   void fetch("/api/stats/sources?"+new URLSearchParams({start,end}),{cache:"no-store",signal:controller.signal}).then(async r=>{if(!r.ok)throw new Error();return r.json();})
     .then(d=>{if(!controller.signal.aborted){setRows(d.sources);setError("");}}).catch(()=>{if(!controller.signal.aborted)setError("Статус источников временно недоступен.");});
   return()=>controller.abort();
 },[start,end,refreshKey]);
 return <>{error&&<p className="notice">{error}</p>}<SourceSummary sources={rows.filter(r=>!account||r.canonical_id===account)}/></>;
}