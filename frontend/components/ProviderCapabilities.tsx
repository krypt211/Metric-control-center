"use client";
export type ProviderCard={provider:"meta"|"metricflow";enabled:boolean;status:string;capabilities:Record<string,unknown>;local_quota:{used:number;limit?:number;blocked_until:string|null};provider_quota?:{used:number|null;limit:number|null;remaining:number|null;checked_at:string|null};error_code?:string|null;graph_version?:string};
const methods=[['get_accounts','Получение кабинетов'],['get_campaigns','Получение кампаний'],['get_adsets','Получение групп объявлений'],['get_ads','Получение объявлений'],['get_insights','Получение статистики'],['get_creatives','Получение креативов'],['pause_entity','Изменение статуса'],['set_budget','Изменение бюджета'],['set_bid','Изменение ставки']] as const;
export function capabilityStatus(c:ProviderCard|undefined,key:string):string{
 if(['pause_entity','set_budget','set_bid'].includes(key))return 'Отключено';
 if(!c?.enabled||c.status==='disconnected')return 'Нет подключения';
 if(c.status==='error')return 'Ошибка';
 const reads=c.capabilities.read as Record<string,string>|undefined;
 const state=reads?.[key];
 return state==='verified'?'Доступно и проверено':state==='unsupported'?'Не поддерживается':'Реализовано, но не проверено на живом API';
}
export function QuotaPanel({connection:c}:{connection:ProviderCard}){
 const limit=c.local_quota.limit;
 const used=c.local_quota.used;
 const quota=c.provider_quota;
 const name=c.provider==='metricflow'?'MetricFlow':'Meta';
 return <div className="quota-panel" aria-label={'Квота '+name}>
 <p>Запросов к {name} сегодня: {used} / {limit??'Неизвестно'} (локальный лимит)</p>
 {limit!==undefined&&<><progress aria-label={'Использование локального лимита '+name} value={used} max={limit}/><p>Осталось по локальному лимиту: {Math.max(0,limit-used)}</p></>}
 <p>Лимит провайдера: {quota?.used??'Неизвестно'} / {quota?.limit??'Неизвестно'}</p>
 <small>Локальные запросы учитываются по UTC. Использование у провайдера — на момент последней проверки {quota?.checked_at?new Date(quota.checked_at).toLocaleString('ru-RU'):'(неизвестно)'}.</small>
 </div>;
}
export default function ProviderCapabilities({connections}:{connections:ProviderCard[]}){
 const meta=connections.find(c=>c.provider==='meta'),mf=connections.find(c=>c.provider==='metricflow');
 return <section className="group"><details><summary>Доступные возможности и API quota</summary>
 <div className="tablewrap"><table><thead><tr><th>Возможность</th><th>Meta</th><th>MetricFlow</th><th>Статус</th></tr></thead><tbody>{methods.map(([key,label])=><tr key={key}><td>{label}</td><td>{capabilityStatus(meta,key)}</td><td>{capabilityStatus(mf,key)}</td><td>{['pause_entity','set_budget','set_bid'].includes(key)?'Управление рекламой отключено':'Только чтение'}</td></tr>)}</tbody></table></div>
 {connections.map(c=><QuotaPanel key={c.provider} connection={c}/>)}
 </details><details><summary>Технические подробности</summary>{connections.map(c=><div key={c.provider}><h3>{c.provider==='meta'?'Meta':'MetricFlow'}</h3><dl><dt>Версия API</dt><dd>{c.graph_version??'Не указана'}</dd><dt>Код ошибки</dt><dd>{c.error_code??'Нет'}</dd></dl><pre>{JSON.stringify({capabilities:c.capabilities,provider_quota:c.provider_quota},null,2)}</pre></div>)}</details></section>;
}