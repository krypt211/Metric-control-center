"use client";
import {useEffect,useState} from "react";
import {economicRow,localized,type Level} from "../lib/economics";
import {readEconomics} from "../lib/economics-api";
import {useColumnPreferences} from "../lib/use-column-preferences";
import {formatMetric} from "../lib/column-model";
import ColumnManager from "./ColumnManager";
import StatisticsTable from "./StatisticsTable";
import SourceSummary,{type Source} from "./SourceSummary";
type Row=Record<string,unknown>;
type Result={rows:Row[];total:number;next_offset:number|null;sources:Source[];start:string;end:string;as_of:string};
export default function EconomicsTable({level,query,refresh,onName}:{level:Level;query:string;refresh:number;onName:(row:Row)=>void}) {
 const scope=`eco_${level}` as const,columns=useColumnPreferences(scope);
 const [data,setData]=useState<Result|null>(null),[offset,setOffset]=useState(0),[busy,setBusy]=useState(false),[error,setError]=useState(""),[selected,setSelected]=useState("");
 const sort=columns.config.sorting;
 useEffect(()=>setOffset(0),[query,sort?.key,sort?.direction]);
 useEffect(()=>{const controller=new AbortController(),params=new URLSearchParams(query);if(!params.get("start")||!params.get("end"))return;
 params.set("level",level);params.set("offset",String(offset));params.set("limit","100");if(sort){params.set("sort_key",sort.key);params.set("sort_direction",sort.direction);}
 setBusy(true);void readEconomics<Result>("evaluate?"+params,controller.signal).then(d=>{if(controller.signal.aborted)return;setData(d);setError("");}).catch(e=>{if(!controller.signal.aborted)setError(e.message);}).finally(()=>{if(!controller.signal.aborted)setBusy(false);});return()=>controller.abort();
 },[level,query,refresh,offset,sort?.key,sort?.direction]);
 const rows=data?.rows.map(economicRow)??[],card=data?.rows.find(r=>r.id===selected)??data?.rows[0];
 return <section aria-label="Финансовая статистика">
 {data&&<SourceSummary sources={data.sources}/>}{error&&<p className="notice error" role="alert">{error}</p>}{busy&&<p role="status">Расчёт экономики…</p>}
 {card&&<><div className="filters"><label>Карточки объекта<select value={String(card.id)} onChange={e=>setSelected(e.target.value)}>{data?.rows.map((r,i)=><option key={i} value={String(r.id)}>{String(r.name)} · {String(r.currency)}</option>)}</select></label><span>{String(card.profile_name??"Профиль не назначен")} · {localized(card.economics_data_quality)}</span></div>
 <div className="cards" data-testid="economics-cards">{(["actual_cpl","target_cpl","maximum_cpl","estimated_revenue","estimated_roi","actual_revenue","actual_roi"] as const).map(k=><article className="card" key={k}><h3>{{actual_cpl:"Фактический CPL",target_cpl:"Целевой CPL",maximum_cpl:"Максимальный CPL",estimated_revenue:"Прогнозная выручка",estimated_roi:"Прогнозный ROI",actual_revenue:"Подтверждённая выручка",actual_roi:"Подтверждённый ROI"}[k]}</h3><p className="value">{formatMetric(card[k],k,card.currency)}</p><p className="card-note">{k.startsWith("estimated")?"Прогноз · "+localized(card.approval_source):k.startsWith("actual")&&k!=="actual_cpl"?"Только подтверждённая совместимая когорта":k==="actual_cpl"?"По лидам выбранного источника":"Ориентир · "+localized(card.approval_source)}</p></article>)}</div>
 <p className="notice" data-testid="economics-assessment">{localized(card.economics_status)} · Основа оценки: {localized(card.status_basis??"UNKNOWN")} · {localized(card.maturity_status??"UNKNOWN")}<br/>{Array.isArray(card.reason_codes)?card.reason_codes.map(localized).join("; "):""}</p>
 <details><summary>Данные оценки и условия будущих правил</summary><p>Лиды: {String(card.leads??"—")} / минимум {String(card.minimum_leads??"—")}; апрувы: {String(card.approved_sales??"—")} / минимум {String(card.minimum_sales??"—")}; решений: {String(card.processed_decisions??"—")} / минимум {String(card.minimum_processed??"—")}. Допуск к оценке правил: {card.eligible_for_rule_evaluation?"Да":"Нет"}. Выполнение действий отключено.</p><p>Версия профиля: {String(card.profile_version??"—")}. Снимок: {String(card.evaluation_id??"—")} · {card.evaluation_at?new Date(String(card.evaluation_at)).toLocaleString("ru-RU"):"—"}.</p><p>Поздние изменения: {economicRow(card).late_event_changes??"нет зарегистрированных изменений"}.</p></details></>}
 <ColumnManager scope={scope} controller={columns} rows={rows}/>
 <StatisticsTable scope={scope} rows={rows} config={columns.config} change={columns.change} commit={()=>void columns.persist().catch(()=>{})} disabled={!columns.ready||columns.busy} onName={r=>{setSelected(String(r.id));onName(r);}}/>
 <div className="pagination"><span>{data?.total?`${offset+1}–${Math.min(offset+100,data.total)} из ${data.total}`:"0 строк"}</span><button disabled={busy||offset===0} onClick={()=>setOffset(Math.max(0,offset-100))}>Назад</button><button disabled={busy||data?.next_offset==null} onClick={()=>setOffset(data!.next_offset!)}>Далее</button></div>
 <p className="table-note">Валюты не объединяются. Покупки Meta и продажи трекера показаны независимо и не означают апрув. «—» означает отсутствие совместимых данных.</p>
 </section>;
}