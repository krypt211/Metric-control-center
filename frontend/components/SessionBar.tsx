"use client";
import {useEffect,useState} from "react";
import {flushColumnPreferences,serializeAuthenticatedWrite} from "../lib/use-column-preferences";
export default function SessionBar(){
 const [user,setUser]=useState<{login:string;role:string}|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
 useEffect(()=>{void fetch("/api/auth/me",{cache:"no-store"}).then(async r=>{if(r.status===401){window.location.assign("/login");return;}if(r.ok)setUser((await r.json()).user);});},[]);
 async function logout(){
 setBusy(true);
 try{
 try{await flushColumnPreferences();}catch{if(!window.confirm("Настройки колонок не сохранены. Всё равно выйти?"))return;}
 const r=await serializeAuthenticatedWrite(async()=>{const response=await fetch("/api/auth/csrf",{cache:"no-store"});if(!response.ok)throw new Error();
 return fetch("/api/auth/logout",{method:"POST",headers:{"X-CSRF-Token":(await response.json()).csrf_token}});});
 if(r.ok||r.status===401)window.location.assign("/login");else throw new Error();
 }catch{setError("Не удалось завершить сессию. Повторите выход.");}finally{setBusy(false);}
 }
 return <span className="sessionbar">{user?.login}<a href="/manual-control">Управление рекламой</a><a href="/recommendations">Центр рекомендаций</a><a href="/rules">Правила рекламы</a><a href="/economics">Экономика рекламы</a>{user?.role==="admin"&&<a href="/settings/connections">{"API \u0438 \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f"}</a>}{user?.role==="admin"&&<a href="/admin">Администрирование</a>}<button disabled={busy} onClick={()=>void logout()}>{busy?"Выход…":"Выйти"}</button>{error&&<span role="alert">{error}</span>}</span>;
}
