"use client";
export type Source={canonical_id:string;provider:string|null;provider_account_id?:string|null;mode:string;stale:boolean;updated_at:string|null;connection?:string;reason?:string|null;account_name?:string;timezone?:string;local_date?:string;coverage?:string;sync_status?:string;sync_at?:string|null;window_status?:string;source_timestamp?:string|null;sync_error?:string|null};
const providerName=(p:string|null)=>p==="meta"?"Meta":p==="metricflow"?"MetricFlow":"Не выбран";
const connectionName=(s?:string)=>({healthy:"Подключён",partial:"Частично доступен",error:"Ошибка",disconnected:"Не подключён",unverified:"Не проверен"}[s??""]??"Не проверен");
const syncName=(s?:string)=>({succeeded:"Успешна",failed:"Ошибка",partial:"Частичная",skipped_quota:"Отложена: лимит запросов",skipped_overlap:"Уже выполняется",running:"Выполняется",not_run:"Не выполнена"}[s??""]??"Не выполнена");
const coverageName=(s?:string)=>({available:"Данные получены",no_data:"За выбранный период данные ещё не поступили",not_started:"Выбранная дата ещё не началась в timezone кабинета",not_synced:"Нет подтверждённой синхронизации за выбранный период"}[s??""]??"Наличие данных не подтверждено");
const time=(value:string|null|undefined)=>value?new Date(value).toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit"}):"неизвестно";
export default function SourceSummary({sources}:{sources:Source[]}){
 if(!sources.length)return null;
 const providers=Array.from(new Set(sources.map(s=>s.provider)));
 const updated=sources.map(s=>s.updated_at).filter((x):x is string=>!!x).sort()[0];
 const connected=sources.every(s=>s.connection==="healthy");
 const warning=sources.some(s=>s.stale||s.connection==="error"||s.coverage==="no_data"||s.coverage==="not_synced");
 return <div className="data-sources" aria-label="Источники статистики">
 <p className={warning?"notice":"source-summary"} data-testid="source-summary">Источник: {providers.length===1?providerName(providers[0]):"Несколько источников"} · Обновлено: {time(updated)} · {connected?"Подключён":"Проверьте состояние подключений"}</p>
 <details><summary>Состояние данных по кабинетам</summary><div className="tablewrap"><table><thead><tr><th>Кабинет / источник</th><th>Подключение</th><th>Синхронизация</th><th>Данные периода</th><th>Свежесть</th></tr></thead><tbody>{sources.map(s=><tr key={s.canonical_id}><td>{s.account_name??s.provider_account_id}<small>{providerName(s.provider)} · {s.mode==="fallback"?"Резервный":s.mode==="stale"?"Последний подтверждённый снимок":"Основной"}</small><small>{s.timezone} · дата кабинета {s.local_date}</small></td><td>{connectionName(s.connection)}</td><td>{syncName(s.sync_status)} · {time(s.sync_at)}{s.sync_error&&<small>Код ошибки: {s.sync_error}</small>}</td><td>{coverageName(s.coverage)}</td><td>{s.stale?"Требуют обновления":"Снимок актуален"}<small>Данные источника: {time(s.source_timestamp)}</small></td></tr>)}</tbody></table></div></details>
 </div>;
}