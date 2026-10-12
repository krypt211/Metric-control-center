"use client";
import {useEffect,useId,useRef,useState} from "react";
import {matchesSearch} from "../lib/rule-targets";

export type SearchOption = {id:string;name:string;external_id?:string;[key:string]:unknown};
type Result = {rows:SearchOption[];total:number;next_offset:number|null};
export default function SearchableSelect({label,value,onChange,options,kind,filters="",multiple=false,disabled=false,placeholder="Все",onPick,optionKey}:{
 label:string;value:string|string[];onChange:(value:string|string[])=>void;
 options?:SearchOption[];kind?:string;filters?:string;multiple?:boolean;disabled?:boolean;
 placeholder?:string;optionKey?:(option:SearchOption)=>string;onPick?:(option:SearchOption)=>void;
}) {
 const id=useId(),input=useRef<HTMLInputElement>(null),trigger=useRef<HTMLButtonElement>(null);
 const root=useRef<HTMLDivElement>(null);
 const [alignRight,setAlignRight]=useState(false);
 const [open,setOpen]=useState(false),[q,setQ]=useState(""),[offset,setOffset]=useState(0);
 const [rows,setRows]=useState<SearchOption[]>([]),[total,setTotal]=useState(0),[next,setNext]=useState<number|null>(null);
 const [active,setActive]=useState(0),[busy,setBusy]=useState(false),[error,setError]=useState("");
 const [labels,setLabels]=useState<Record<string,string>>({});
 const selected=Array.isArray(value)?value:value?[value]:[];
 useEffect(()=>{
  if(!open)return;
  input.current?.focus();
  setAlignRight((root.current?.getBoundingClientRect().left??0)+340>window.innerWidth-16);
  function outside(e:MouseEvent){if(!root.current?.contains(e.target as Node))setOpen(false);}
  document.addEventListener("mousedown",outside);
  return()=>document.removeEventListener("mousedown",outside);
 },[open]);
 useEffect(()=>{setOffset(0);setActive(0);},[q,filters]);
 useEffect(()=>{
  if(!open)return;
  const controller=new AbortController();
  if(options&&!kind){
   setBusy(false);
   const found=options.filter(o=>matchesSearch(o.name,o.external_id??o.id,q));
   setRows(found.slice(offset,offset+20));setTotal(found.length);setNext(offset+20<found.length?offset+20:null);
   setLabels(old=>({...old,...Object.fromEntries(options.map(o=>[o.id,o.name]))}));return;
  }
  setRows([]);setBusy(true);
  const timer=setTimeout(()=>{
   setBusy(true);setError("");
   const params=new URLSearchParams(filters);params.set("kind",kind??"account");params.set("q",q);params.set("offset",String(offset));
   void fetch("/api/smart-rules/catalog/search?"+params,{signal:controller.signal,cache:"no-store"})
    .then(async r=>{if(!r.ok)throw new Error("Не удалось загрузить объекты");return await r.json() as Result;})
    .then(data=>{if(controller.signal.aborted)return;setRows(data.rows);setTotal(data.total);setNext(data.next_offset);
     setLabels(old=>({...old,...Object.fromEntries(data.rows.map(o=>[o.id,o.name]))}));setActive(0);})
    .catch(e=>{if(!controller.signal.aborted)setError(e.message);})
    .finally(()=>{if(!controller.signal.aborted)setBusy(false);});
  },250);
  return()=>{clearTimeout(timer);controller.abort();};
 },[open,q,offset,filters,kind,options]);
 useEffect(()=>{if(open)document.getElementById(id+"-"+active)?.scrollIntoView({block:"nearest"});},[open,active,id]);
 function searchTo(query:string){if(query!==q){setRows([]);setBusy(true);setQ(query);}}
 function pick(option:SearchOption){
  onPick?.(option);
  const key=optionKey?.(option)??option.id;
  onChange(multiple?(selected.includes(key)?selected.filter(x=>x!==key):[...selected,key]):key);
  if(!multiple){setOpen(false);trigger.current?.focus();}
 }
 const keyFor=(option:SearchOption)=>optionKey?.(option)??option.id;
 const available=rows;
 return <div className="searchable-select" ref={root}>
  <button type="button" ref={trigger} aria-label={label} aria-haspopup="listbox" aria-expanded={open}
    disabled={disabled} onClick={()=>setOpen(v=>!v)}>{selected.length?(multiple?selected.length+" выбрано":labels[selected[0]]??options?.find(o=>o.id===selected[0])?.name??selected[0]):placeholder} ▾</button>
  {open&&<div className="searchable-popup" style={alignRight?{left:"auto",right:0}:undefined}>
   <input ref={input} role="combobox" aria-label={"Поиск: "+label} aria-controls={id}
    aria-expanded={open} aria-autocomplete="list" aria-activedescendant={available[active]?id+"-"+active:undefined}
    value={q} placeholder="Название или ID" onChange={e=>searchTo(e.target.value)} onKeyDown={e=>{
     if(e.key==="Escape"){e.preventDefault();setOpen(false);trigger.current?.focus();}
     if(e.key==="ArrowDown"||e.key==="ArrowUp"){e.preventDefault();setActive(a=>Math.max(0,Math.min(available.length-1,a+(e.key==="ArrowDown"?1:-1))));}
     if(e.key==="Enter"){e.preventDefault();if(!busy&&available[active])pick(available[active]);}
    }}/>
   <div className="actionbuttons"><button type="button" onClick={()=>{searchTo("");input.current?.focus();}}>Очистить поиск</button>
    <button type="button" onClick={()=>onChange(multiple?[]:"")}>Снять выбор</button></div>
   {busy&&<span role="status">Поиск…</span>}{error&&<span role="alert">{error}</span>}
   <div id={id} role="listbox" aria-label={label+" результаты"} aria-multiselectable={multiple||undefined}>
    {available.map((o,i)=><button type="button" role="option" id={id+"-"+i} key={o.id+":"+String(o.provider??"")}
      aria-selected={selected.includes(keyFor(o))} disabled={busy} className={i===active?"active":""} onMouseMove={()=>setActive(i)}
      onClick={()=>pick(o)}>{selected.includes(keyFor(o))?"☑ ":"☐ "}{o.name}{o.provider?" · "+String(o.provider):""}<small>{o.external_id??o.id}</small></button>)}
   </div>
   {!busy&&!error&&!available.length&&<p>Ничего не найдено</p>}
   <div className="pagination"><span>Найдено: {total}</span>
    <button type="button" disabled={!offset||busy} onClick={()=>setOffset(Math.max(0,offset-20))}>Назад</button>
    <button type="button" disabled={next===null||busy} onClick={()=>next!==null&&setOffset(next)}>Далее</button></div>
  </div>}
 </div>;
}
