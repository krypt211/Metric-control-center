"use client";
import {useEffect,useState} from "react";
import {integrationRead,integrationWrite} from "../lib/integrations";
type PilotSession={id:string;account_id:string;start:string;end:string;max_attempts:number;used_attempts:number;timeout_seconds:number;status:string;reason:string|null;deadline:string|null};
type State={mode:boolean;scheduler:string;credentials_present:boolean;graph_version:string|null;access_tier:string|null;cooldown_until:string|null;minimum_attempts:number;live_approval_required:boolean;session:PilotSession|null};
export default function MetaReadPilot(){
 const [state,setState]=useState<State|null>(null),[account,setAccount]=useState(""),[start,setStart]=useState(""),[end,setEnd]=useState(""),[maximum,setMaximum]=useState(20),[duration,setDuration]=useState(600),[busy,setBusy]=useState(false),[error,setError]=useState("");
 async function load(){try{setState(await integrationRead<State>("/meta/pilot"));}catch(e){setError((e as Error).message);}}
 useEffect(()=>{void load();},[]);
 async function save(){setBusy(true);setError("");try{await integrationWrite("/meta/pilot",{account_id:account,start,end,max_attempts:maximum,timeout_seconds:duration});await load();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 async function cancel(){if(!state?.session)return;setBusy(true);try{await integrationWrite("/meta/pilot/"+state.session.id+"/cancel",{});await load();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <section className="group" aria-label="Тестовое READ-подключение"><h3>Тестовое READ-подключение</h3>
 <p>Подготовка не включает Meta LIVE. Сохранённая конфигурация не разрешает тест. Только один кабинет, 1–3 дня, до 20 физических HTTP attempts с учётом страниц и повторов.</p>
 {error&&<p role="alert">{error}</p>}
 {state&&<dl className="provider-details"><dt>Пилотный режим</dt><dd>{state.mode?"Подготовка · периодическая Meta sync остановлена":"Не настроен на сервере"}</dd><dt>Credentials</dt><dd>{state.credentials_present?"Сохранены зашифрованно":"Не добавлены"}</dd><dt>Graph API</dt><dd>{state.graph_version??"Не подтверждена"}</dd><dt>Access Tier</dt><dd>{state.access_tier??"Неизвестен"}</dd><dt>Cooldown до</dt><dd>{state.cooldown_until??"Нет подтверждённого cooldown"}</dd><dt>Выбранный аккаунт</dt><dd>{state.session?.account_id??"Не выбран"}</dd><dt>Выбранный период</dt><dd>{state.session?state.session.start+" — "+state.session.end:"Не выбран"}</dd><dt>HTTP использовано / максимум</dt><dd>{state.session?state.session.used_attempts+" / "+state.session.max_attempts:"0 / 20"}</dd><dt>Статус теста</dt><dd>{state.session?.status??"NOT_CONFIGURED"}</dd><dt>Причина остановки / ошибка Meta</dt><dd>{state.session?.reason??"Нет"}</dd></dl>}
 <label>Кабинет пилота (act_ID)<input value={account} onChange={e=>setAccount(e.target.value)} maxLength={68}/></label>
 <label>Пилот: начало периода<input type="date" value={start} onChange={e=>setStart(e.target.value)}/></label>
 <label>Пилот: конец периода<input type="date" value={end} onChange={e=>setEnd(e.target.value)}/></label>
 <label>Максимум HTTP attempts<input type="number" min={1} max={20} value={maximum} onChange={e=>setMaximum(Number(e.target.value))}/></label>
 <label>Лимит времени пилота, секунд<input type="number" min={30} max={900} value={duration} onChange={e=>setDuration(Number(e.target.value))}/></label>
 <button disabled={busy||!state?.mode} onClick={()=>void save()}>Сохранить подготовку READ-теста</button>
 <button disabled={busy} onClick={()=>void load()}>Обновить статус READ-теста</button>
 <button disabled={busy||!state?.session||!["PREPARED","QUEUED","RUNNING"].includes(state.session.status)} onClick={()=>void cancel()}>Отменить READ-тест</button>
 <p>Запуск разрешается отдельно для ID сессии оператором сервера. Стандартный scheduler не включается после завершения. Минимум без pagination/retries — 8 GET; фактическая нагрузка и Access Tier заранее неизвестны.</p>
 </section>;
}
