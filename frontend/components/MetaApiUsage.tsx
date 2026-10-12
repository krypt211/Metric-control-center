"use client";
import SearchableSelect from "./SearchableSelect";
import {useEffect,useState} from "react";
import {integrationRead,integrationWrite} from "../lib/integrations";
type Usage={sync_account_ids:string[];available_accounts:{id:string;name:string}[];enabled:boolean;access_tier:string|null;coverage:string;coverage_since:string|null;minute:number|null;hour:number|null;day:number|null;success:number|null;errors:number|null;retries:number|null;pagination:number|null;incidents:number|null;per_account:Record<string,number>;usage_percent:number|null;cooldown_until:string|null;last_incident:{at:string;code:number|null;subcode:number|null;endpoint:string;run_id:string}|null;last_operation:{id:string;kind:string;requests:number}|null;scheduler_status:string;settings:{request_interval_seconds:number;app_concurrency:number;account_concurrency:number;retry_cap:number;page_size:number;scheduler_minutes:number}};
type Log={timestamp:string;endpoint:string;account_id:string|null;run_id:string;attempt:number;page:number;http_status:number|null;duration_ms:number|null;error_code:number|null;outcome:string;source:string};
type Estimate={classification:string;total_no_retries:number;maximum_with_two_retries:number;minimum_one_page_per_edge:number;scheduled_today_per_day:number;objects_per_account:Record<string,number>;assumptions:string[]};
const n=(v:number|null)=>v===null?"Нет измерений":String(v);
export default function MetaApiUsage(){
 const [usage,setUsage]=useState<Usage|null>(null),[error,setError]=useState(""),[tab,setTab]=useState("usage"),[logs,setLogs]=useState<Log[]>([]),[total,setTotal]=useState(0),[offset,setOffset]=useState(0);
 const [period,setPeriod]=useState("today");
 const [accounts,setAccounts]=useState(1),[days,setDays]=useState(1),[estimate,setEstimate]=useState<Estimate|null>(null),[interval,setInterval]=useState(1);
 const [account,setAccount]=useState(""),[endpoint,setEndpoint]=useState(""),[code,setCode]=useState(""),[run,setRun]=useState(""),[start,setStart]=useState(""),[end,setEnd]=useState("");
 const [selected,setSelected]=useState<string[]>([]);
 const [busy,setBusy]=useState(false);
 async function load(){try{const u=await integrationRead<Usage>("/meta/usage");setUsage(u);setInterval(u.settings.request_interval_seconds);setSelected(u.sync_account_ids);}catch(e){setError((e as Error).message);}}
 useEffect(()=>{void load();},[]);
 async function journal(next=0){
  setBusy(true);setError("");
  try{const p=new URLSearchParams({offset:String(next),limit:"25"});if(account)p.set("account",account);if(endpoint)p.set("endpoint",endpoint);if(code)p.set("error_code",code);if(run)p.set("run_id",run);if(start)p.set("start",new Date(start).toISOString());if(end)p.set("end",new Date(end).toISOString());
   const r=await integrationRead<{rows:Log[];total:number}>("/meta/requests?"+p);setLogs(r.rows);setTotal(r.total);setOffset(next);
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}
 }
 async function forecast(){setBusy(true);setError("");try{setEstimate(await integrationWrite<Estimate>("/meta/estimate",{accounts,days}));}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 async function pacing(){setBusy(true);setError("");try{await integrationWrite("/meta/pacing",{request_interval_seconds:interval,account_ids:selected},"PUT");await load();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <section className="group" aria-label="Использование Meta API"><h3>Использование API — Meta</h3>
 {error&&<p role="alert">{error}</p>}
 <div className="filterbar"><button onClick={()=>{setTab("usage");void load();}}>Использование API</button><button onClick={()=>{setTab("log");void journal();}}>Журнал запросов</button><button onClick={()=>setTab("estimate")}>Прогноз Meta sync</button></div>
 {usage&&tab==="usage"&&<>
 {!usage.enabled&&<p>Meta API не подключён. Доступен расчёт предполагаемых запросов по конфигурации.</p>}
 <dl className="provider-details"><dt>Подключение</dt><dd>{usage.enabled?"Подключено":"Отключено"}</dd><dt>Access Tier</dt><dd>{usage.access_tier??"Неизвестен"}</dd>
 <dt>HTTP за минуту / час / сутки</dt><dd>{n(usage.minute)} / {n(usage.hour)} / {n(usage.day)}</dd>
 <dt>Успешные / ошибки / retries</dt><dd>{n(usage.success)} / {n(usage.errors)} / {n(usage.retries)}</dd><dt>Pagination / rate-limit incidents</dt><dd>{n(usage.pagination)} / {n(usage.incidents)}</dd>
 <dt>Provider utilization</dt><dd>{usage.usage_percent===null?"Не сообщена":usage.usage_percent+"%"} · это процент, не остаток запросов</dd>
 <dt>Cooldown до</dt><dd>{usage.cooldown_until?new Date(usage.cooldown_until).toLocaleString("ru-RU"):"Нет подтверждённого cooldown"}</dd><dt>Scheduler</dt><dd>{usage.scheduler_status}</dd>
 <dt>Последняя операция</dt><dd>{usage.last_operation?usage.last_operation.kind+" · HTTP "+usage.last_operation.requests:"Нет измерений"}</dd><dt>Последний rate-limit incident</dt><dd>{usage.last_incident?usage.last_incident.at+" · "+usage.last_incident.endpoint+" · code "+usage.last_incident.code:"Не измерен"}</dd></dl>
 <p>Покрытие: {usage.coverage_since??"счётчик ещё не записал попыток"}. Исторические счётчики до установки meter не являются точной HTTP telemetry.</p>
 <ul>{Object.entries(usage.per_account).map(([id,count])=><li key={id}>{id}: {count} HTTP attempts за сутки</li>)}</ul>
 <p>Локальные ограничения: один запрос на приложение и аккаунт; до 2 retries; страница 100. Это локальная политика, не гарантированная квота Meta.</p>
 <SearchableSelect label="Аккаунты Meta для синхронизации (до 3)" multiple value={selected} options={usage.available_accounts} onChange={v=>{const ids=v as string[];if(ids.length>3){setError("Выберите до трёх аккаунтов.");return;}setSelected(ids);}}/><p>До первого запуска выберите область. Более трёх аккаунтов за run не синхронизируются.</p>
 <label>Минимальный интервал запросов, секунд<input type="number" value={interval} min={1} max={600} onChange={e=>setInterval(Number(e.target.value))}/></label><button disabled={busy} onClick={()=>void pacing()}>Сохранить локальный интервал</button>
 <p>Scheduler: today каждые 10 минут, yesterday каждый час, 7 дней раз в сутки. Изменение интервала не включает Meta LIVE.</p>
 </>}
 {tab==="log"&&<>
 <div className="filterbar"><label>Canonical account ID<input value={account} onChange={e=>setAccount(e.target.value)} maxLength={36}/></label><label>Endpoint category<input value={endpoint} onChange={e=>setEndpoint(e.target.value)} maxLength={32}/></label><label>Meta error code<input type="number" value={code} onChange={e=>setCode(e.target.value)}/></label><label>Sync run ID<input value={run} onChange={e=>setRun(e.target.value)} maxLength={36}/></label><label>Запросы с<input type="datetime-local" value={start} onChange={e=>setStart(e.target.value)}/></label><label>Запросы до<input type="datetime-local" value={end} onChange={e=>setEnd(e.target.value)}/></label><button disabled={busy} onClick={()=>void journal()}>Применить фильтры журнала</button></div>
 <p>Найдено: {total}</p><div className="table-scroll"><table><thead><tr>{["UTC","Account","Endpoint","Attempt / page","HTTP","ms","Error","Run / source"].map(t=><th key={t}>{t}</th>)}</tr></thead><tbody>{logs.map((r,i)=><tr key={i}><td>{r.timestamp}</td><td>{r.account_id??"Неизвестен"}</td><td>{r.endpoint}</td><td>{r.attempt} / {r.page}</td><td>{r.http_status??"Нет ответа"}</td><td>{r.duration_ms?.toFixed(0)??"—"}</td><td>{r.error_code??r.outcome}</td><td>{r.run_id} / {r.source}</td></tr>)}</tbody></table></div>
 {!total&&<p>Нет записей для этих фильтров; это не доказательство отсутствия прошлой активности.</p>}
 <button disabled={busy||offset===0} onClick={()=>void journal(Math.max(0,offset-25))}>Предыдущие запросы</button><button disabled={busy||offset+25>=total} onClick={()=>void journal(offset+25)}>Следующие запросы</button>
 </>}
 {tab==="estimate"&&<>
 <div className="filterbar"><label>Аккаунтов для прогноза<select value={accounts} onChange={e=>setAccounts(Number(e.target.value))}>{[1,3,10,50].map(a=><option key={a} value={a}>{a}</option>)}</select></label><label>Период прогноза<select value={period} onChange={e=>{setPeriod(e.target.value);setDays(["today","yesterday"].includes(e.target.value)?1:Number(e.target.value));}}><option value="today">Сегодня</option><option value="yesterday">Вчера</option><option value={7}>7 дней</option><option value={30}>30 дней</option></select></label><button disabled={busy} onClick={()=>void forecast()}>Рассчитать без Meta API</button></div>
 {estimate&&<><p>Estimated: {estimate.total_no_retries} HTTP attempts без retries · до {estimate.maximum_with_two_retries} при двух повторах каждого запроса.</p><p>Минимум при одной странице каждого edge: {estimate.minimum_one_page_per_edge}. Today scheduler: {estimate.scheduled_today_per_day}/сутки по этим предположениям.</p><p>Источник: {estimate.classification}. Это прогноз, фактических запросов не выполнено.</p><ul>{estimate.assumptions.map(a=><li key={a}>{({"100 rows/page; one Insights row per AD/day assumed, actual pages unknown":"Запрошено до 100 строк на страницу; строки AD/day и фактическая pagination неизвестны.","four catalogs and one AD-level Insights query per account; no per-AD Insights calls":"Четыре каталога и один account Insights запрос уровня AD; отдельных запросов по каждому AD нет.","fields, attribution and timezone unchanged; no breakdowns/batch/async jobs":"Поля, атрибуция и timezone сохраняются; breakdowns, batch и async jobs не используются.","Insights local pacing weight 2 is not a provider complexity score":"Вес Insights 2 используется только для локального pacing, не как квота Meta.","auth reads the full account roster; account selection does not constrain that roster":"Проверка доступа получает полный список аккаунтов; выбранная область ограничивает последующую статистику.","today every 10 minutes, yesterday hourly, seven-day reconciliation daily":"Today: каждые 10 минут; yesterday: каждый час; 7 дней: ежедневно."} as Record<string,string>)[a]??a}</li>)}</ul></>}
 </>}
 </section>;
}
