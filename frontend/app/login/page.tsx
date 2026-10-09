"use client";
import {useState} from "react";
import {loginError} from "@/lib/login-error";
export default function LoginPage() {
  const [login,setLogin]=useState("");const [password,setPassword]=useState("");
  const [error,setError]=useState("");const [busy,setBusy]=useState(false);
  async function submit(event:React.FormEvent) {
    event.preventDefault();setBusy(true);setError("");
    try {
      const csrf=await fetch("/api/auth/csrf",{cache:"no-store"});
      if(!csrf.ok){setError(loginError(csrf.status,undefined,csrf.headers.get("retry-after")));return;}
      const token=(await csrf.json()).csrf_token;
      const response=await fetch("/api/auth/login",{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":token},
        body:JSON.stringify({login,password})});
      if(!response.ok){
        const body=await response.json().catch(()=>({}));
        setError(loginError(response.status,body.detail,response.headers.get("retry-after")));return;
      }
      window.location.assign("/");
    } catch {setError("Сервер временно недоступен. Попробуйте позже.");}
    finally{setPassword("");setBusy(false);}
  }
  return <main><section className="group"><h1>Вход в Metric Control Center</h1><form onSubmit={submit} className="loginform">
    <label>Логин или email<input name="username" autoComplete="username" value={login} onChange={e=>setLogin(e.target.value)} required maxLength={320}/></label>
    <label>Пароль<input name="password" type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required maxLength={256}/></label>
    {error&&<p role="alert" className="notice error">{error}</p>}
    <button disabled={busy}>{busy?"Вход…":"Войти"}</button>
  </form></section></main>;
}
