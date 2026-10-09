"use client";
import {useEffect,useRef,useState} from "react";
import {initialBundle,type Bundle,type ColumnConfig,type Preset} from "./column-model";
import type {TableScope} from "./metric-registry";
const base="/api/preferences/columns";
const flushers=new Set<()=>Promise<unknown>>();
const pending=new Set<Promise<unknown>>();
// CSRF rotates on GET: serialize token acquisition with its write across all scopes.
let transportQueue:Promise<unknown>=Promise.resolve();
export async function flushColumnPreferences(){await Promise.all([...Array.from(flushers,fn=>fn()),...pending]);}
export function useColumnPreferences(scope:TableScope){
  const [bundle,setBundle]=useState(()=>initialBundle(scope));
  const [config,setConfig]=useState(bundle.preference.config);
  const [ready,setReady]=useState(false);const [busy,setBusy]=useState(false);
  const [status,setStatus]=useState("Загрузка настроек…");const [error,setError]=useState("");
  const current=useRef({bundle,config,serial:0,needsSave:false,ready:false});
  const mounted=useRef(true);const queue=useRef(Promise.resolve());const timer=useRef<ReturnType<typeof setTimeout>|null>(null);
  function update(result:Bundle,retain=false){
    current.current.bundle=result;
    if(!retain){current.current.config=result.preference.config;current.current.needsSave=false;if(mounted.current)setConfig(result.preference.config);}
    if(mounted.current)setBundle(result);
  }
  async function request(path:string,method:string,body?:unknown):Promise<Bundle>{
    const operation=transportQueue.then(async()=>{
    const csrf=await fetch("/api/auth/csrf",{cache:"no-store"});
    if(!csrf.ok)throw new Error("Сессия истекла или сервер недоступен. Повторите вход.");
    const token=(await csrf.json()).csrf_token;
    const response=await fetch(base+path,{method,cache:"no-store",keepalive:true,headers:{"Content-Type":"application/json","X-CSRF-Token":token},...(body===undefined?{}:{body:JSON.stringify(body)})});
    if(!response.ok)throw new Error(response.status===409?"Настройки изменены в другой вкладке. Загрузите серверные настройки перед сохранением.":response.status===401?"Сессия истекла. Повторите вход.":response.status===422?"Проверьте название, колонки и допустимую ширину.":"Не удалось сохранить настройки.");
    return response.json() as Promise<Bundle>;
    });
    transportQueue=operation.catch(()=>{});return operation;
  }
  function enqueue<T>(fn:()=>Promise<T>):Promise<T>{
    const task=queue.current.then(fn);queue.current=task.then(()=>{},()=>{});return task;
  }
  function persist(){
    const task=enqueue(async()=>{
      const state=current.current;if(!state.ready||!state.needsSave)return;
      const serial=state.serial;const snapshot=state.config;
      if(mounted.current)setStatus("Сохранение рабочего вида…");
      const result=await request("/"+scope+"/view","PUT",{active_id:state.bundle.preference.active_id,config:snapshot,version:state.bundle.preference.version});
      const retain=serial!==current.current.serial;
      update(result,retain);
      if(!retain)current.current.needsSave=false;
      if(mounted.current){setStatus(retain?"Есть новые изменения…":"Рабочий вид сохранён");setError("");}
    }).catch(e=>{if(mounted.current){setError(e.message);setStatus("Не сохранено");}throw e;});
    pending.add(task);task.then(()=>pending.delete(task),()=>pending.delete(task));return task;
  }
  function change(fn:(c:ColumnConfig)=>ColumnConfig,defer=false){
    if(!current.current.ready||busy)return;
    const next=fn(current.current.config);current.current.config=next;current.current.serial++;current.current.needsSave=true;setConfig(next);setStatus("Есть изменения…");
    if(timer.current)clearTimeout(timer.current);
    if(!defer)timer.current=setTimeout(()=>{void persist().catch(()=>{});},450);
  }
  async function reload(){
    if(current.current.needsSave&&!window.confirm("Локальные изменения будут заменены серверными. Продолжить?"))return;
    if(timer.current)clearTimeout(timer.current);
    try{
      await queue.current;
      const r=await fetch(base+"/"+scope,{cache:"no-store"});if(!r.ok)throw new Error("Не удалось загрузить настройки колонок.");
      const result=await r.json();update(result);current.current.ready=true;setReady(true);setError("");setStatus("Настройки загружены");
    }catch(e){setError(e instanceof Error?e.message:"Настройки недоступны");}
  }
  useEffect(()=>{
    mounted.current=true;const controller=new AbortController();
    const flush=async()=>{if(timer.current)clearTimeout(timer.current);await persist();await queue.current;};flushers.add(flush);
    void Promise.allSettled([...pending]).then(()=>fetch(base+"/"+scope,{cache:"no-store",signal:controller.signal})).then(async r=>{if(!r.ok)throw new Error("Не удалось загрузить настройки колонок.");return r.json();})
      .then((result:Bundle)=>{if(controller.signal.aborted)return;update(result);current.current.ready=true;setReady(true);setStatus("Настройки загружены");})
      .catch(e=>{if(!controller.signal.aborted)setError(e.message);});
    return()=>{flushers.delete(flush);mounted.current=false;controller.abort();if(timer.current)clearTimeout(timer.current);void persist().catch(()=>{});};
    // The grid is keyed by scope, so each mounted hook owns a separate serialized queue.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[scope]);
  async function act(fn:(state:typeof current.current)=>Promise<Bundle>){
    setBusy(true);setError("");
    try{if(timer.current)clearTimeout(timer.current);await persist();const result=await enqueue(()=>fn(current.current));update(result);setStatus("Сохранено");}
    catch(e){setError(e instanceof Error?e.message:"Не удалось сохранить настройки");}
    finally{setBusy(false);}
  }
  const active=bundle.presets.find(p=>p.id===bundle.preference.active_id)??bundle.presets[0];
  const modified=JSON.stringify(config)!==JSON.stringify(active.config);
  function activate(id:string){
    if(id!==bundle.preference.active_id&&modified&&!window.confirm("Рабочий вид сохранён, но набор изменён. Переключить без сохранения изменений в набор?"))return;
    void act(s=>request("/"+scope+"/activate","POST",{preset_id:id,version:s.bundle.preference.version}));
  }
  function create(name:string){void act(s=>request("","POST",{scope,name,config:s.config,preference_version:s.bundle.preference.version}));}
  function save(name=active.name){
    if(active.system){const label=window.prompt("Сохранить как мой набор",name==="Базовые"?"Мой набор":name+" — мой");if(label?.trim())create(label.trim());return;}
    void act(s=>request("/presets/"+active.id,"PUT",{name,config:s.config,version:s.bundle.presets.find(p=>p.id===active.id)!.version,preference_version:s.bundle.preference.version}));
  }
  function duplicate(preset:Preset){
    const label=window.prompt("Название копии",preset.name+" — копия");if(!label?.trim())return;
    void act(s=>request("","POST",{scope,name:label.trim(),config:preset.id===s.bundle.preference.active_id?s.config:preset.config,preference_version:s.bundle.preference.version}));
  }
  function remove(){
    if(active.system||!window.confirm("Удалить набор «"+active.name+"»?"))return;
    void act(s=>request("/presets/"+active.id+"?version="+s.bundle.presets.find(p=>p.id===active.id)!.version+"&preference_version="+s.bundle.preference.version,"DELETE"));
  }
  function makeDefault(){void act(s=>request("/"+scope+"/default","PUT",{preset_id:s.bundle.preference.active_id,version:s.bundle.preference.version}));}
  return {bundle,config,active,ready,busy,status,error,modified,change,persist,reload,activate,create,save,duplicate,remove,makeDefault};
}
export type ColumnController=ReturnType<typeof useColumnPreferences>;
