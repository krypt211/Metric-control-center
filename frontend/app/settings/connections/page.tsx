"use client";
import {useCallback,useEffect,useState} from "react";
import SessionBar from "@/components/SessionBar";
import ProviderCapabilities from "@/components/ProviderCapabilities";
type Provider="meta"|"metricflow";
type Connection={provider:Provider;enabled:boolean;status:string;routing_ready:boolean;last_check:string|null;last_success_sync:string|null;account_count:number;error_code:string|null;permissions:{read?:boolean;write_permission?:boolean;write_enabled?:boolean;expires_at?:number;data_access_expires_at?:number};capabilities:Record<string,unknown>;quota:Record<string,unknown>;local_quota:{used:number;limit?:number;blocked_until:string|null};provider_quota?:{used:number|null;limit:number|null;remaining:number|null;checked_at:string|null};app_id?:string;graph_version?:string};
type Route={scope:string;primary_provider:Provider;fallback_provider:Provider|null;action_provider:"disabled"};
type Mapping={account_id:string;canonical_id:string;meta_account_id:string|null;proof:string;provider:Provider;name:string|null;provider_account_id:string};
type Data={connections:Connection[];routing:Route[];mappings:Mapping[];credentials_ui_enabled:boolean;events:{at:string;canonical_id:string;from:string|null;to:string|null;reason:string}[];jobs:{id:string;provider:string;kind:string;status:string;start:string;end:string;error_code:string|null}[]};
const names={meta:"Meta Marketing API",metricflow:"MetricFlow API"};
const statuses:Record<string,string>={healthy:"Подключён",disconnected:"Не подключён",unverified:"Ожидает проверки",error:"Ошибка",partial:"Частичная синхронизация"};
const errors:Record<string,string>={ADMIN_REQUIRED:"Требуется роль ADMIN.",LAST_WORKING_SOURCE_WARNING:"Это последний рабочий источник. Подтвердите отключение.",PRIMARY_SYNC_REQUIRED:"Сначала синхронизируйте данные выбранного источника.",PRIMARY_MUST_BE_VERIFIED:"Сначала проверьте подключение основного источника.",PROVIDER_JOB_IN_PROGRESS:"Задание уже выполняется. Дождитесь завершения.",PROVIDER_DISABLED:"Подключение отключено.",META_TOKEN_INVALID:"Meta отклонила токен или его App ID.",META_TOKEN_EXPIRED:"Срок действия Meta-токена истёк.",META_ADS_READ_REQUIRED:"Meta не подтвердила разрешение ads_read.",META_PERMISSION_DENIED:"Meta не разрешает чтение этих рекламных данных.",META_RATE_LIMIT:"Достигнут лимит Meta API. Синхронизация возобновится позже.",CREDENTIALS_INVALID_OR_ENCRYPTION_UNAVAILABLE:"Проверьте формат credentials и настройку шифрования на сервере.",META_ID_MISMATCH:"Подтверждённые Meta Account IDs различаются. Объединение запрещено.",CSRF_ORIGIN:"Сессия или адрес приложения изменились. Повторите вход.",CSRF_INVALID:"Сессия устарела. Повторите вход."};
const when=(value:string|null)=>value?new Date(value).toLocaleString("ru-RU"):"Ещё не выполнялась";
function RoutingForm({data,scope,onSave,onReset}:{data:Data;scope:string;onSave:(route:Route)=>Promise<void>;onReset?:()=>Promise<void>}){
 const own=data.routing.find(r=>r.scope===scope),base=own??data.routing.find(r=>r.scope==="workspace")!;
 const [primary,setPrimary]=useState<Provider>(base.primary_provider),[fallback,setFallback]=useState<Provider|null>(base.fallback_provider),[saving,setSaving]=useState(false);
 useEffect(()=>{setPrimary(base.primary_provider);setFallback(base.fallback_provider);},[base.primary_provider,base.fallback_provider]);
 return <form className="filterbar" onSubmit={e=>{e.preventDefault();setSaving(true);void onSave({scope,primary_provider:primary,fallback_provider:fallback,action_provider:"disabled"}).finally(()=>setSaving(false)).catch(()=>{});}}>
 <label>Основной источник<select value={primary} onChange={e=>{const p=e.target.value as Provider;setPrimary(p);if(fallback===p)setFallback(null);}}>{data.connections.map(c=><option key={c.provider} value={c.provider} disabled={!c.routing_ready}>{names[c.provider]}{c.status!=="healthy"?" · не проверен":""}</option>)}</select></label>
 <label>Резервный источник<select value={fallback??""} onChange={e=>setFallback((e.target.value||null) as Provider|null)}><option value="">Отключён</option>{data.connections.filter(c=>c.provider!==primary).map(c=><option key={c.provider} value={c.provider}>{names[c.provider]}</option>)}</select></label>
 <button disabled={saving}>Сохранить источники</button>{onReset&&own&&<button type="button" disabled={saving} onClick={()=>void onReset()}>Использовать общие настройки</button>}
 <span>Управление рекламой: отключено</span></form>;
}
function CredentialForm({provider,enabled,onSave}:{provider:Provider;enabled:boolean;onSave:(body:object)=>Promise<void>}){
 const [token,setToken]=useState(""),[app,setApp]=useState(""),[secret,setSecret]=useState(""),[version,setVersion]=useState("v26.0"),[saving,setSaving]=useState(false);
 return <form className="filterbar provider-credentials" onSubmit={e=>{e.preventDefault();setSaving(true);const body={token,...(provider==="meta"?{app_id:app,app_secret:secret,graph_version:version}:{})};void onSave(body).then(()=>{setToken("");setSecret("");}).finally(()=>setSaving(false)).catch(()=>{});}}>
 {provider==="meta"&&<><label>Meta App ID<input value={app} onChange={e=>setApp(e.target.value)} required pattern="[0-9]+" maxLength={64} autoComplete="off"/></label>
 <label>Meta App Secret<input type="password" value={secret} onChange={e=>setSecret(e.target.value)} required minLength={16} maxLength={256} autoComplete="new-password"/></label>
 <label>Graph API version<input value={version} onChange={e=>setVersion(e.target.value)} required pattern="v[0-9]+\.0" maxLength={8}/></label></>}
 <label>{provider==="meta"?"Meta access token":"MetricFlow READ key"}<input type="password" value={token} onChange={e=>setToken(e.target.value)} required maxLength={4096} autoComplete="new-password" spellCheck={false}/></label>
 <button disabled={!enabled||saving}>{saving?"Сохраняем…":"Подключить / заменить credentials"}</button>
 </form>;
}
export default function ConnectionsPage(){
 const [data,setData]=useState<Data|null>(null),[error,setError]=useState(""),[message,setMessage]=useState(""),[scope,setScope]=useState("workspace"),[busy,setBusy]=useState(false);
 const [start,setStart]=useState(""),[end,setEnd]=useState(""),[diagnostics,setDiagnostics]=useState<{routes:unknown[];comparison:Record<string,{id:string;name:string;spend:string|null;currency:string;timezone:string;source_mode:string}[]>;differences:{canonical_id:string;metricflow_spend:string;meta_spend:string;spend_delta:string|null;currency_timezone_compatible:boolean;attribution_compatible:string}[];meta_entity_state:unknown[]}|null>(null);
 const [mappingFrom,setMappingFrom]=useState(""),[mappingTo,setMappingTo]=useState("");
 const load=useCallback(async()=>{
   const response=await fetch("/api/admin/providers",{cache:"no-store"});const payload=await response.json();
   if(response.status===401){window.location.assign("/login");return;}
   if(!response.ok)throw new Error(errors[payload.detail]??"Не удалось загрузить подключения.");
   setData(payload);
 },[]);
 useEffect(()=>{const now=new Date();const last=now.toISOString().slice(0,10);setEnd(last);setStart(new Date(now.getTime()-6*86400000).toISOString().slice(0,10));void load().catch(e=>setError(e.message));},[load]);
 useEffect(()=>{if(!data?.jobs.some(j=>["queued","running"].includes(j.status)))return;const timer=setInterval(()=>void load().catch(e=>setError(e.message)),10000);return()=>clearInterval(timer);},[data,load]);
 async function mutate(path:string,method:string,body?:object){
   setBusy(true);setError("");setMessage("");
   try{
     const csrf=await fetch("/api/auth/csrf",{cache:"no-store"});if(!csrf.ok)throw new Error("Повторите вход.");
     const r=await fetch("/api/admin/providers"+path,{method,headers:{"Content-Type":"application/json","X-CSRF-Token":(await csrf.json()).csrf_token},...(body?{body:JSON.stringify(body)}:{})});
     const result=await r.json();if(!r.ok)throw new Error(errors[result.detail]??"Изменение не сохранено. "+(result.detail??""));
     setMessage(result.status==="queued"?"READ-задание поставлено в очередь. Статус обновляется автоматически.":"Настройки сохранены.");await load();
   }catch(e){setError(e instanceof Error?e.message:"Сервис недоступен.");throw e;}finally{setBusy(false);}
 }
 async function attempt(path:string,method:string,body?:object){try{await mutate(path,method,body);}catch{/* Error is displayed without secret inputs. */}}
 async function compare(){
   if(!start||!end)return;
   setBusy(true);setError("");
   try{const r=await fetch("/api/admin/providers/diagnostics?"+new URLSearchParams({start,end}),{cache:"no-store"});if(!r.ok)throw new Error();setDiagnostics(await r.json());}
   catch{setError("Не удалось сравнить источники. Проверьте период.");}finally{setBusy(false);}
 }
 return <main><header className="topbar"><a href="/">К статистике</a><SessionBar/></header><h1>Настройки · API и подключения</h1>
 <p className="subtitle">Подключения и источники статистики. Все рекламные действия отключены.</p>
 {error&&<p className="notice error" role="alert">{error}</p>}{message&&<p className="notice" role="status">{message}</p>}
 {!data?<p>Загрузка подключений…</p>:<>
 {!data.credentials_ui_enabled&&<p className="notice">Ввод токенов временно недоступен: на сервере не настроен отдельный ключ шифрования. Существующий MetricFlow READ key продолжает использовать server-side .secrets.</p>}
 <div className="provider-cards">{data.connections.map(c=>{
 const running=data.jobs.some(j=>j.provider===c.provider&&["queued","running"].includes(j.status));
 return <section className="group" key={c.provider}><h2>{names[c.provider]}</h2><p><strong>{statuses[c.status]??c.status}</strong> · {c.account_count} аккаунтов</p>
 <dl className="provider-details"><dt>Последняя проверка</dt><dd>{when(c.last_check)}</dd><dt>Успешная синхронизация</dt><dd>{when(c.last_success_sync)}</dd><dt>READ</dt><dd>{c.permissions.read?"Подтверждён":"Не подтверждён"}</dd><dt>WRITE</dt><dd>Отключён{c.permissions.write_permission?" · ads_management присутствует":""}</dd><dt>Локальная квота, запросов сегодня</dt><dd>{c.local_quota.used}{c.local_quota.blocked_until?" · пауза до "+when(c.local_quota.blocked_until):""}</dd>
 {c.provider==="meta"&&<><dt>App ID / API version</dt><dd>{c.app_id??"—"} / {c.graph_version??"v26.0"}</dd><dt>Токен действителен до</dt><dd>{c.permissions.expires_at?when(new Date(c.permissions.expires_at*1000).toISOString()):"Срок не сообщён"}</dd><dt>Доступ к данным до</dt><dd>{c.permissions.data_access_expires_at?when(new Date(c.permissions.data_access_expires_at*1000).toISOString()):"Срок не сообщён"}</dd><dt>OAuth</dt><dd>Не настроен · первоначальное подключение токеном</dd></>}
 </dl>{c.error_code&&<p className="notice error">{errors[c.error_code]??"READ-проверка не прошла: "+c.error_code}</p>}
 <div className="filterbar"><button disabled={!c.enabled||busy||running} onClick={()=>void attempt("/"+c.provider+"/check","POST")}>Проверить соединение</button>
 <button disabled={!c.enabled||busy||running||!start||!end} onClick={()=>void attempt("/"+c.provider+"/sync","POST",{start,end})}>Синхронизировать выбранный период</button>
 <button disabled={!c.routing_ready||busy} onClick={()=>void attempt("/routing","PUT",{scope:"workspace",primary_provider:c.provider,fallback_provider:null,action_provider:"disabled"})}>Выбрать основным</button>
 <button disabled={!c.enabled||busy} onClick={()=>{const another=data.connections.some(x=>x.provider!==c.provider&&x.enabled&&x.status==="healthy");if(window.confirm(another?"Отключить "+names[c.provider]+"? Снимок статистики сохранится.":"Это последний рабочий источник. Новая статистика перестанет поступать, панель покажет STALE. Отключить?"))void attempt("/"+c.provider+"/disconnect","POST",{acknowledge_last_source:!another,forget_credentials:false});}}>Отключить</button>
 <button disabled={c.enabled||busy} onClick={()=>{if(window.confirm("Удалить сохранённые credentials этого отключённого подключения? Для полного отзыва токена используйте настройки Meta / MetricFlow."))void attempt("/"+c.provider+"/disconnect","POST",{acknowledge_last_source:true,forget_credentials:true});}}>Удалить сохранённые credentials</button></div>
 <details><summary>Подключить или обновить credentials</summary><CredentialForm provider={c.provider} enabled={data.credentials_ui_enabled&&!busy} onSave={body=>mutate("/"+c.provider+"/credentials","POST",body)}/></details>

 </section>;})}</div>
 <ProviderCapabilities connections={data.connections}/>
 <section className="group"><h2>Источники статистики и маршрутизация по аккаунтам</h2><p>Резерв применяется только к подтверждённому аккаунту при совпадении валюты, часового пояса, атрибуции и полноты периода. При несовместимости сохраняется снимок с пометкой STALE.</p>
 <label>Настройка для<select value={scope} onChange={e=>setScope(e.target.value)}><option value="workspace">Все аккаунты · общие настройки</option>{Array.from(new Map(data.mappings.map(m=>[m.canonical_id,m])).values()).map(m=><option key={m.canonical_id} value={m.canonical_id}>{m.name??m.provider_account_id} · {m.meta_account_id??"не сопоставлен"}</option>)}</select></label>
 <RoutingForm key={scope} data={data} scope={scope} onSave={r=>attempt("/routing","PUT",r)} onReset={scope!=="workspace"?()=>attempt("/routing/"+scope,"DELETE"):undefined}/>
 <details><summary>Сопоставление аккаунтов</summary><div className="tablewrap"><table><thead><tr><th>Провайдер</th><th>Аккаунт</th><th>Meta Account ID</th><th>Доказательство</th><th>Общая идентичность</th></tr></thead><tbody>{data.mappings.map(m=><tr key={m.account_id}><td>{names[m.provider]}</td><td>{m.name} · {m.provider_account_id}</td><td>{m.meta_account_id??"Не подтверждён"}</td><td>{m.proof}</td><td>{m.canonical_id}</td></tr>)}</tbody></table></div>
 <form className="filterbar" onSubmit={e=>{e.preventDefault();if(window.confirm("Подтвердить ручное сопоставление? Это не подтверждает атрибуцию и не разрешает WRITE."))void attempt("/mapping","POST",{account_id:mappingFrom,target_account_id:mappingTo,confirm:true});}}><label>Источник<select value={mappingFrom} onChange={e=>setMappingFrom(e.target.value)} required><option value="">Выберите аккаунт</option>{data.mappings.map(m=><option key={m.account_id} value={m.account_id}>{names[m.provider]} · {m.provider_account_id}</option>)}</select></label><label>Сопоставить с<select value={mappingTo} onChange={e=>setMappingTo(e.target.value)} required><option value="">Выберите аккаунт</option>{data.mappings.filter(m=>m.provider!==data.mappings.find(x=>x.account_id===mappingFrom)?.provider).map(m=><option key={m.account_id} value={m.account_id}>{names[m.provider]} · {m.provider_account_id}</option>)}</select></label><button disabled={busy}>Подтвердить сопоставление</button></form></details>
 </section>
 <section className="group"><h2>Диагностика API и сравнение источников</h2><div className="filterbar"><label>С<input type="date" value={start} onChange={e=>setStart(e.target.value)}/></label><label>По<input type="date" value={end} onChange={e=>setEnd(e.target.value)}/></label><button disabled={busy} onClick={()=>void compare()}>Сравнить источники</button><button disabled={busy} onClick={()=>void load().catch(e=>setError(e.message))}>Обновить подключения</button></div>
 {diagnostics&&<><p>Расхождения показаны без автоматической корректировки. Неизвестная атрибуция не считается совпадением.</p><div className="tablewrap"><table><thead><tr><th>Аккаунт</th><th>MetricFlow spend</th><th>Meta spend</th><th>Разница Meta − MetricFlow</th><th>Совместимость валюты / timezone</th></tr></thead><tbody>{diagnostics.differences.map(d=><tr key={d.canonical_id}><td>{d.canonical_id}</td><td>{d.metricflow_spend??"—"}</td><td>{d.meta_spend??"—"}</td><td>{d.spend_delta??"Не сопоставимо"}</td><td>{d.currency_timezone_compatible?"Да":"Нет"}</td></tr>)}</tbody></table></div>
 {Object.entries(diagnostics.comparison).map(([provider,rows])=><div key={provider}><h3>{names[provider as Provider]}</h3>{rows.length?<div className="tablewrap"><table><thead><tr><th>Аккаунт</th><th>Spend</th><th>Валюта</th><th>Часовой пояс</th><th>Источник</th></tr></thead><tbody>{rows.map(r=><tr key={r.id}><td>{r.name}</td><td>{r.spend??"—"}</td><td>{r.currency}</td><td>{r.timezone}</td><td>{r.source_mode}</td></tr>)}</tbody></table></div>:<p>Данных этого источника за выбранный период нет.</p>}</div>)}
 <details><summary>Маршрутизация и состояние объектов Meta</summary><p>Бюджеты и ставки ниже сохранены в исходных единицах Meta. Масштаб валюты не подтверждён; нормализованные значения не подставляются.</p><pre>{JSON.stringify({routes:diagnostics.routes,meta_entity_state:diagnostics.meta_entity_state},null,2)}</pre></details></>}
 </section>
 <section className="group"><h2>READ-задания</h2><div className="tablewrap"><table><thead><tr><th>Источник</th><th>Задание</th><th>Период</th><th>Статус</th><th>Ошибка</th></tr></thead><tbody>{data.jobs.map(j=><tr key={j.id}><td>{names[j.provider as Provider]??"Неизвестный источник"}</td><td>{j.kind==="health"?"Проверка подключения":"Синхронизация"}</td><td>{j.start} — {j.end}</td><td>{{queued:"В очереди",running:"Выполняется",succeeded:"Успешно",failed:"Ошибка",partial:"Частично",skipped_overlap:"Уже выполняется",skipped_quota:"Лимит запросов",disabled:"Отключено"}[j.status]??"Неизвестно"}</td><td>{errors[j.error_code??""]??j.error_code??"—"}</td></tr>)}</tbody></table></div></section>
 <section className="group"><h2>История переключений</h2><div className="tablewrap"><table><thead><tr><th>Дата</th><th>Аккаунт</th><th>Из</th><th>В</th><th>Причина</th></tr></thead><tbody>{data.events.map((e,i)=><tr key={i}><td>{when(e.at)}</td><td>{e.canonical_id}</td><td>{e.from??"—"}</td><td>{e.to??"—"}</td><td>{e.reason}</td></tr>)}</tbody></table></div></section>
 </>}</main>;
}
