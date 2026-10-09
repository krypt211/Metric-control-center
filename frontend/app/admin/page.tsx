"use client";
import {useEffect,useState} from "react";
import SessionBar from "@/components/SessionBar";
type User={id:string;login:string;role:string;active:boolean;can_login:boolean};
export default function AdminPage() {
  const [users,setUsers]=useState<User[]>([]);const [status,setStatus]=useState<Record<string,unknown>|null>(null);
  const [error,setError]=useState("");const [login,setLogin]=useState("");const [password,setPassword]=useState("");const [role,setRole]=useState("viewer");
  async function load() {
    const [u,s]=await Promise.all([fetch("/api/admin/users",{cache:"no-store"}),fetch("/api/admin/status",{cache:"no-store"})]);
    if(u.status===403){setError("Требуется роль ADMIN.");return;}if(!u.ok||!s.ok){setError("Сервис недоступен.");return;}
    setUsers((await u.json()).users);setStatus(await s.json());
  }
  useEffect(()=>{void load().catch(()=>setError("Сервис недоступен."));},[]);
  async function mutate(path:string,method:string,body:object) {
    const csrf=await fetch("/api/auth/csrf",{cache:"no-store"});if(!csrf.ok)throw new Error();
    const response=await fetch("/api/admin/"+path,{method,headers:{"Content-Type":"application/json","X-CSRF-Token":(await csrf.json()).csrf_token},body:JSON.stringify(body)});
    if(!response.ok){setError(response.status===409?"Нельзя отключить последнего администратора.":"Изменение не сохранено.");return;}
    setError("");await load();
  }
  return <main><header className="topbar"><a href="/">К статистике</a><SessionBar/></header><h1>Администрирование</h1>
    {error&&<p role="alert" className="notice error">{error}</p>}
    <section className="group"><h2>Пользователи</h2><div className="tablewrap"><table><thead><tr><th>Логин</th><th>Роль</th><th>Доступ</th><th/></tr></thead>
    <tbody>{users.map(u=><tr key={u.id}><td>{u.login}</td><td><select value={u.role} onChange={e=>void mutate("users/"+u.id,"PATCH",{role:e.target.value}).catch(()=>setError("Сервис недоступен."))}>{["viewer","operator","admin"].map(r=><option key={r}>{r}</option>)}</select></td>
    <td>{u.active&&u.can_login?"Активен":"Отключён"}</td><td><button onClick={()=>void mutate("users/"+u.id,"PATCH",{active:!u.active}).catch(()=>setError("Сервис недоступен."))}>{u.active?"Отключить":"Включить"}</button></td></tr>)}</tbody></table></div>
    <form className="filterbar" onSubmit={e=>{e.preventDefault();void mutate("users","POST",{login,password,role}).then(()=>setPassword("")).catch(()=>setError("Сервис недоступен."));}}>
      <label>Логин<input value={login} onChange={e=>setLogin(e.target.value)} required autoComplete="off"/></label>
      <label>Пароль<input type="password" value={password} onChange={e=>setPassword(e.target.value)} required minLength={12} maxLength={256} autoComplete="new-password"/></label>
      <label>Роль<select value={role} onChange={e=>setRole(e.target.value)}>{["viewer","operator","admin"].map(r=><option key={r}>{r}</option>)}</select></label><button>Создать пользователя</button>
    </form></section>
    <section className="group"><h2>Состояние системы</h2><button onClick={()=>void load()}>Обновить</button><pre>{status?JSON.stringify(status,null,2):"Загрузка…"}</pre></section>
  </main>;
}
