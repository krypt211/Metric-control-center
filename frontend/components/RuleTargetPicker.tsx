"use client";
import {useEffect,useRef,useState} from "react";
import {writeRules} from "../lib/smart-rules";
import SearchableSelect from "./SearchableSelect";
import {catalogTarget,mergeTargets,targetKey,targetSummary,targetTypes,type CatalogObject,type Target} from "../lib/rule-targets";

export default function RuleTargetPicker({value,onChange,disabled=false}:{value:Target[];onChange:(items:Target[])=>void;disabled?:boolean}) {
 const [kind,setKind]=useState<Target["scope_type"]>("CAMPAIGN"),[q,setQ]=useState(""),[offset,setOffset]=useState(0);
 const [accounts,setAccounts]=useState<string[]>([]),[campaigns,setCampaigns]=useState<string[]>([]),[adsets,setAdsets]=useState<string[]>([]);
 const [rows,setRows]=useState<CatalogObject[]>([]),[total,setTotal]=useState(0),[next,setNext]=useState<number|null>(null);
 const [busy,setBusy]=useState(false),[error,setError]=useState(""),[show,setShow]=useState(false),[confirmAll,setConfirmAll]=useState(false);
 const header=useRef<HTMLInputElement>(null),valueRef=useRef(value);
 valueRef.current=value;
 const filters=new URLSearchParams();
 accounts.forEach(v=>filters.append("accounts",v));campaigns.forEach(v=>filters.append("campaigns",v));adsets.forEach(v=>filters.append("adsets",v));
 const context=filters.toString();
 const chosen=new Set(value.map(targetKey)),visibleChosen=rows.filter(r=>chosen.has(targetKey(r)));
 const incompatible=value.filter(t=>(accounts.length&&!accounts.includes(t.account_id))||
  (campaigns.length&&t.scope_type!=="ACCOUNT"&&!(campaigns.includes(t.scope_type==="CAMPAIGN"?t.scope_id:t.campaign_id??"")))||
  (adsets.length&&["AD","ADSET"].includes(t.scope_type)&&!adsets.includes(t.scope_type==="ADSET"?t.scope_id:t.adset_id??"")));
 useEffect(()=>{setOffset(0);setConfirmAll(false);},[q,kind,context]);
 useEffect(()=>{if(header.current)header.current.indeterminate=visibleChosen.length>0&&visibleChosen.length<rows.length;},[visibleChosen.length,rows.length]);
 useEffect(()=>{
  const controller=new AbortController();
  setRows([]);setBusy(true);
  const timer=setTimeout(()=>{
   setBusy(true);setError("");
   const params=new URLSearchParams(context);params.set("kind",kind.toLowerCase());params.set("q",q);params.set("offset",String(offset));
   void fetch("/api/smart-rules/catalog/search?"+params,{signal:controller.signal,cache:"no-store"})
    .then(async r=>{if(!r.ok)throw new Error("Не удалось загрузить каталог");return r.json();})
    .then(data=>{if(!controller.signal.aborted){setRows(data.rows);setTotal(data.total);setNext(data.next_offset);}})
    .catch(e=>{if(!controller.signal.aborted)setError(e.message);})
    .finally(()=>{if(!controller.signal.aborted)setBusy(false);});
  },250);return()=>{clearTimeout(timer);controller.abort();};
 },[kind,q,offset,context]);
 function searchTo(query:string){if(query!==q){setRows([]);setBusy(true);setQ(query);}}
 function chooseKind(level:Target["scope_type"]){if(level!==kind){setRows([]);setBusy(true);setKind(level);}}
 function pageTo(page:number){setRows([]);setBusy(true);setOffset(page);}
 function toggle(row:Target,yes:boolean){
  onChange(yes?mergeTargets(value,[row]):value.filter(t=>targetKey(t)!==targetKey(row)));
 }
 async function allFound(){
  setBusy(true);setError("");
  try{
   const data=await writeRules<{rows:Target[];total:number}>("/catalog/select-all","POST",{kind:kind.toLowerCase(),q,accounts,campaigns,adsets});
   const resolved=data.rows;
   const merged=mergeTargets(valueRef.current,resolved);
   if(merged.length>200)throw new Error("Лимит выбора — 200 объектов.");
   onChange(merged);setConfirmAll(false);
  }catch(e){setError(e instanceof Error?e.message:"Ошибка поиска");}finally{setBusy(false);}
 }
 return <section aria-label="Выбор объектов правила" className="rule-target-picker">
  <h3>Изменить объекты</h3>
  <p>Поиск по названию и ID во всём локальном каталоге. Все слова должны совпасть, порядок не важен.</p>
  <div className="filters">
   <label>Кабинеты<SearchableSelect label="Кабинеты фильтр" kind="account" multiple value={accounts} onChange={v=>setAccounts(v as string[])}/></label>
   <label>Кампании<SearchableSelect label="Кампании фильтр" kind="campaign" filters={new URLSearchParams(accounts.map(v=>["accounts",v])).toString()} multiple value={campaigns} onChange={v=>setCampaigns(v as string[])}/></label>
   <label>Группы<SearchableSelect label="Группы фильтр" kind="adset" filters={new URLSearchParams([...accounts.map(v=>["accounts",v]),...campaigns.map(v=>["campaigns",v])]).toString()} multiple value={adsets} onChange={v=>setAdsets(v as string[])}/></label>
   <label>Объявления<SearchableSelect label="Объявления выбор" kind="ad" filters={context} multiple
    disabled={disabled} value={value.filter(t=>t.scope_type==="AD").map(targetKey)} optionKey={o=>targetKey(o as unknown as CatalogObject)}
    onPick={o=>{const row=o as unknown as CatalogObject;toggle(catalogTarget(row),!chosen.has(targetKey(row)));}} onChange={v=>{if(!(v as string[]).length)onChange(value.filter(t=>t.scope_type!=="AD"));}}/></label>
  </div>
  {!!incompatible.length&&<div role="alert" className="notice">
   {incompatible.length} выбранных объектов вне текущих фильтров. Выбор сохранён.
   <button type="button" onClick={()=>{setAccounts([]);setCampaigns([]);setAdsets([]);}}>Сохранить выбор</button>
   <button type="button" disabled={disabled} onClick={()=>onChange(value.filter(t=>!incompatible.includes(t)))}>Убрать несовместимые</button>
  </div>}
  <nav className="levelnav" aria-label="Уровень выбора">{(Object.keys(targetTypes) as Target["scope_type"][]).map(t=><button type="button" key={t} className={kind===t?"active":""} onClick={()=>chooseKind(t)}>{targetTypes[t]}</button>)}</nav>
  <div className="filterbar"><label>Поиск объектов<input aria-label="Поиск объектов" value={q} onChange={e=>searchTo(e.target.value)} placeholder="Название или ID"/></label><button type="button" onClick={()=>searchTo("")}>Очистить поиск объектов</button><span>Найдено: {total}</span></div>
  {error&&<p role="alert">{error}</p>}{busy&&<p role="status">Поиск объектов…</p>}
  <div className="tablewrap"><table className="target-table"><thead><tr>
   <th><input ref={header} type="checkbox" aria-label="Выбрать текущую страницу" checked={rows.length>0&&visibleChosen.length===rows.length}
    disabled={disabled||busy||!rows.length||mergeTargets(value,rows).length>200||rows.some(r=>!r.hierarchy_verified)} onChange={e=>onChange(e.target.checked?mergeTargets(value,rows):value.filter(t=>!rows.some(r=>targetKey(r)===targetKey(t))))}/></th>
   <th>Название</th><th>ID</th><th>Кабинет · провайдер</th>
  </tr></thead><tbody>{rows.map(r=><tr key={targetKey(r)}>
   <td><input type="checkbox" aria-label={"Выбрать "+r.name+" · "+r.external_id+" · "+r.provider+" · "+r.account_id} checked={chosen.has(targetKey(r))} disabled={disabled||busy||(!chosen.has(targetKey(r))&&value.length>=200)||!r.hierarchy_verified} onChange={e=>toggle(r,e.target.checked)}/></td>
   <td>{r.name}</td><td>{r.external_id}</td><td>{r.account_name} · {r.provider}</td>
  </tr>)}</tbody></table></div>
  {!busy&&!rows.length&&<p>Ничего не найдено</p>}
  <div className="pagination"><span>{offset+1}–{Math.min(offset+20,total)} из {total}</span><button type="button" disabled={!offset||busy} onClick={()=>pageTo(Math.max(0,offset-20))}>Предыдущая страница</button><button type="button" disabled={next===null||busy} onClick={()=>next!==null&&pageTo(next)}>Следующая страница</button>
   <button type="button" disabled={disabled||busy||!total||total>200} onClick={()=>setConfirmAll(true)}>Выбрать все найденные ({total})</button></div>
  {confirmAll&&<div role="dialog" aria-label="Подтверждение полного выбора"><p>Выбрать все {total} найденных объектов? Это отдельный выбор всего результата поиска.</p><button type="button" onClick={()=>void allFound()}>Подтвердить весь результат</button><button type="button" onClick={()=>setConfirmAll(false)}>Отменить полный выбор</button></div>}
  <p role="status">Выбрано: {value.length} · {targetSummary(value)}</p>
  {!!value.length&&<div className="actionbuttons"><button type="button" onClick={()=>setShow(v=>!v)}>Просмотреть выбранное</button><button type="button" disabled={disabled} onClick={()=>onChange([])}>Очистить выбор</button></div>}
  {show&&<ul className="selected-targets">{value.map(t=><li key={targetKey(t)}>{t.name??t.scope_id} · {t.scope_type} · {t.external_id??t.scope_id} · {t.account_name??t.account_id} · {t.provider} · родитель: {t.adset_id??t.campaign_id??t.account_id}
   <button type="button" disabled={disabled} onClick={()=>toggle(t,false)}>Удалить из выбора: {t.name??t.scope_id}</button></li>)}</ul>}
  <p className="card-note">Правило применяется ко всем текущим и новым объявлениям выбранных кампаний, групп и кабинетов. Для AD — только конкретное объявление. Пересечения объединяются без повторной оценки. Изменения сохраняются только явной кнопкой; при перезагрузке несохранённый выбор теряется.</p>
 </section>;
}
