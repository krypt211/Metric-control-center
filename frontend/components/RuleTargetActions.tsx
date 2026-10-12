"use client";
import {useEffect,useState} from "react";
import {conditionNames,readRules,writeRules,type Rule,type Simulation} from "../lib/smart-rules";
import {targetInput,targetKey,targetSummary,type Target} from "../lib/rule-targets";
import SearchableSelect from "./SearchableSelect";
import RuleTargetPicker from "./RuleTargetPicker";

export default function RuleTargetActions({targets,onChange,onCreate,onSaved,refreshKey}:{targets:Target[];onChange:(targets:Target[])=>void;onCreate?:(targets:Target[])=>void;onSaved?:(rule:Rule)=>void;refreshKey?:string}) {
 const [showPicker,setShowPicker]=useState(false);
 const [rules,setRules]=useState<Rule[]>([]),[canEdit,setCanEdit]=useState(false),[ruleId,setRuleId]=useState("");
 const [mode,setMode]=useState<"add"|"remove"|"simulate"|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(""),[message,setMessage]=useState("");
 const [start,setStart]=useState(""),[end,setEnd]=useState(""),[affected,setAffected]=useState<number|null>(null),[issues,setIssues]=useState<string[]>([]);
 const [result,setResult]=useState<Simulation|null>(null);
 useEffect(()=>{void readRules<{rules:Rule[];can_edit:boolean}>().then(data=>{setRules(data.rules.filter(r=>!r.deleted));setCanEdit(data.can_edit);}).catch(e=>setError(e.message));},[refreshKey]);
 const rule=rules.find(r=>r.id===ruleId),existing=rule?.definition.selection.targets??[];
 const selectedKeys=new Set(targets.map(targetKey));
 const removing=existing.filter(t=>selectedKeys.has(targetKey(t))).length;
 async function preview(next:"add"|"remove"|"simulate"){
  setMode(next);setAffected(null);setIssues([]);setResult(null);
  if(next==="remove"){setAffected(0);return;}
  try{
   const data=await writeRules<{total:number;issues:{reason_code:string}[]}>("/catalog/resolve","POST",{targets:targets.map(targetInput)});
   setAffected(data.total);setIssues(data.issues.map(i=>i.reason_code));
  }catch(e){setError(e instanceof Error?e.message:"Ошибка предварительной проверки");}
 }
 function create(){
  if(onCreate){onCreate(targets);return;}
  sessionStorage.setItem("mcc.rule-target-draft",JSON.stringify(targets.map(targetInput)));
  window.location.assign("/rules");
 }
 async function save(){
  if(!rule)return;
  setBusy(true);setError("");
  try{
   const dated=targets.map(t=>({...targetInput(t),effective_start:start||t.effective_start||null,effective_end:end||t.effective_end||null}));
   if(mode==="simulate"){
    const data=await writeRules<Simulation>("/"+rule.id+"/simulate-selected","POST",{revision:rule.revision,targets:dated});
    setResult(data);setMessage("DRY RUN сохранён в истории. Реклама не изменена.");
   }else{
    const saved=await writeRules<Rule>("/"+rule.id+"/assignments/bulk","POST",{revision:rule.revision,operation:mode,targets:dated});
    setRules(old=>old.map(r=>r.id===saved.id?saved:r));setMessage("Назначения сохранены · версия "+saved.revision);setMode(null);onSaved?.(saved);
   }
  }catch(e){setError(e instanceof Error?e.message:"Не удалось сохранить назначения");}finally{setBusy(false);}
 }
 if(!targets.length)return null;
 return <section className="target-actions" aria-label="Массовые назначения">
  <p>Выбрано: {targets.length} · {targetSummary(targets)}</p>
  {error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
  <div className="actionbuttons"><button type="button" onClick={()=>onChange([])}>Очистить весь выбор</button>
   <button type="button" disabled={!canEdit||busy} onClick={create}>Создать правило для выбранных</button>
   <button type="button" disabled={!canEdit||busy} onClick={()=>void preview("add")}>Назначить правило выбранным</button>
   <button type="button" disabled={!canEdit||busy} onClick={()=>void preview("remove")}>Удалить правило у выбранных</button>
   <button type="button" disabled={!canEdit||busy} onClick={()=>void preview("simulate")}>DRY RUN выбранных</button>
  </div>
  <details onToggle={e=>setShowPicker(e.currentTarget.open)}><summary>Просмотреть и изменить выбранное</summary>{showPicker&&<RuleTargetPicker value={targets} onChange={onChange} disabled={!canEdit||busy}/>}</details>
  {mode&&<div role="dialog" aria-label="Массовое назначение правила" className="group">
   <h3>{mode==="remove"?"Снять назначения":mode==="simulate"?"DRY RUN выбранной области":"Назначить существующее правило"}</h3>
   <SearchableSelect label="Правило для выбранных" value={ruleId} options={rules.map(r=>({id:r.id,name:r.definition.name}))} placeholder="Выберите правило" onChange={v=>setRuleId(v as string)}/>
   <p>{targetSummary(targets)} · потенциально Ads: {affected??"проверка"} · пересечения объединяются.</p>
   {rule&&!rule.definition.selection.target_mode&&!rule.definition.selection.account_ids.length&&!rule.definition.selection.campaign&&!rule.definition.selection.adset&&!rule.definition.selection.ad&&<p className="notice">Это правило пока проверяет все доступные Ads. Сохранение назначений явно заменит общий охват выбранными объектами.</p>}
   <ul className="selected-targets">{targets.map(t=><li key={targetKey(t)}>{t.name??t.scope_id} · {t.scope_type} · {t.external_id??t.scope_id} · {t.account_name??t.account_id} · {t.provider}</li>)}</ul>
   {rule&&<details><summary>Просмотреть условия</summary><p>{rule.definition.name} · {rule.definition.expression.operator}</p><ul>{rule.definition.expression.children.map((c,i)=><li key={i}>{"type" in c?conditionNames[c.type]:c.operator==="AND"?"Все условия":"Любое условие"}</li>)}</ul></details>}
   {mode==="remove"?<p>Будет снято прямых назначений: {removing}. Унаследованные назначения и само правило сохраняются.</p>:<>
    <label>Назначения действуют с<input type="date" value={start} onChange={e=>setStart(e.target.value)}/></label>
    <label>Назначения действуют до<input type="date" value={end} min={start} onChange={e=>setEnd(e.target.value)}/></label>
    <p>Правило применяется ко всем текущим и новым объявлениям выбранных кампаний, групп и кабинетов. Версия правила: актуальная (LATEST). Существующие явные назначения сохраняются.</p>
   </>}
   {!!issues.length&&<p role="alert">Область требует проверки: {issues.join(" · ")}</p>}
   <button type="button" disabled={!rule||busy||affected===null||!!issues.length||(mode==="remove"&&!removing)} onClick={()=>void save()}>{mode==="simulate"?"Запустить DRY RUN":mode==="remove"?"Подтвердить снятие назначений":"Сохранить назначения"}</button>
   <button type="button" disabled={busy} onClick={()=>setMode(null)}>Отменить</button>
   {result&&<div><p>Проверено Ads: {result.total}</p><ul>{result.rows.map((r,i)=><li key={i}>{String(r.name??r.external_id)} · {String(r.status)}</li>)}</ul></div>}
  </div>}
 </section>;
}
