"use client";
import {useEffect,useState} from "react";
import {integrationRead,integrationWrite,type WriteState} from "../lib/integrations";
const statuses:Record<string,string>={NOT_CONFIGURED:"Не настроен",STORED_UNVERIFIED:"Сохранён, не проверен",SCOPES_VERIFIED:"WRITE scope подтверждён",PERMISSIONS_PARTIAL:"Недостаточно scopes",PERMISSIONS_UNVERIFIED:"Разрешения не подтверждены",INVALID_CREDENTIAL:"Ключ недействителен",PROVIDER_UNAVAILABLE:"Провайдер недоступен"};
export default function MetricFlowWriteSettings(){
 const [state,setState]=useState<WriteState|null>(null),[token,setToken]=useState(""),[busy,setBusy]=useState(false),[error,setError]=useState("");
 useEffect(()=>{void integrationRead<WriteState>("/metricflow/write-credentials").then(setState).catch(e=>setError(e.message));},[]);
 async function act(operation:string){
  if(!state)return;
  if((operation==="replace"||operation==="delete")&&!window.confirm(operation==="replace"?"Заменить только WRITE-ключ? READ останется прежним.":"Удалить только локальный WRITE-ключ? На стороне MetricFlow ключ не отзывается."))return;
  setBusy(true);setError("");
  try{const result=await integrationWrite<WriteState>("/metricflow/write-credentials/"+operation,{revision:state.revision,...(["save","replace"].includes(operation)?{token}:{}),confirm:operation==="replace"||operation==="delete"});setState({...state,...result});}
  catch(e){setError(e instanceof Error?e.message:"Операция не выполнена.");}
  finally{setToken("");setBusy(false);}
 }
 const editable=!!state?.can_manage&&state.management_available&&!busy;
 return <section className="group" aria-label="Ключ управления рекламой WRITE"><h3>Ключ управления рекламой (WRITE)</h3>
 <p>Назначение: будущее управление рекламой. Отдельный ключ не заменяет READ API.</p>
 {error&&<p role="alert">{error}</p>}
 {!state?<p>Загрузка состояния…</p>:<>
 <dl className="provider-details"><dt>Ключ</dt><dd>{statuses[state.status]??state.status}</dd><dt>Обозначение</dt><dd>{state.fingerprint?"•••• · "+state.fingerprint:"Не сохранён"}</dd>
 <dt>Credential revision</dt><dd>{state.revision}</dd><dt>Последняя проверка</dt><dd>{state.checked_at?new Date(state.checked_at).toLocaleString("ru-RU"):"Не выполнялась"}</dd>
 <dt>entities:write</dt><dd>{state.scope_verified?"Подтверждён":state.checked_at&&state.scopes.length?"Отсутствует":"Не проверен"}</dd><dt>Подписка</dt><dd>{state.access_state??"Не проверена"}</dd>
 <dt>Права на конкретный AD</dt><dd>Не подтверждены</dd><dt>LIVE управление</dt><dd>BLOCKED</dd></dl>
 {state.scope_verified&&<p className="notice">WRITE scope подтверждён. Реальное управление пока заблокировано до подтверждения контракта и разрешений на объекты.</p>}
 {state.status==="PERMISSIONS_PARTIAL"&&!state.scope_verified&&<p>У ключа отсутствует entities:write.</p>}
 {!state.can_manage&&<p>Управление ключами доступно только ADMIN.</p>}
 {!state.management_available&&<p>Изолированный сервис provisioning не настроен. READ API продолжает работать.</p>}
 <form className="filterbar provider-credentials" onSubmit={e=>{e.preventDefault();void act(state.configured?"replace":"save");}}>
 <label>MetricFlow WRITE key<input type="password" value={token} disabled={!editable} onChange={e=>setToken(e.target.value)} autoComplete="off" spellCheck={false} minLength={8} maxLength={4096} required/></label>
 <button disabled={!editable||!token}>{state.configured?"Заменить ключ":"Сохранить ключ"}</button></form>
 <div className="filterbar"><button disabled={!editable||!state.configured} onClick={()=>void act("check")}>Проверить подключение WRITE</button>
 <button disabled={!editable||!state.configured} onClick={()=>void act("delete")}>Удалить локальный ключ</button></div>
 <p>Проверка выполняет только GET /me. Сохранение не включает action-worker. Удаление из MCC не отзывает ключ у MetricFlow.</p>
 <p>LIVE блокеры: неподтверждённый WRITE-контракт и права на объект.</p>
 </>}
 </section>;
}
