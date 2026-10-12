export async function integrationRead<T>(path:string):Promise<T>{
 const r=await fetch("/api/admin/providers"+path,{cache:"no-store"});
 if(!r.ok)throw new Error("Не удалось загрузить диагностику подключения.");
 return r.json();
}
export async function integrationWrite<T>(path:string,body:object,method="POST"):Promise<T>{
 const csrf=await fetch("/api/auth/csrf",{cache:"no-store"});
 if(!csrf.ok)throw new Error("Требуется повторный вход.");
 const r=await fetch("/api/admin/providers"+path,{method,headers:{"Content-Type":"application/json","X-CSRF-Token":(await csrf.json()).csrf_token},body:JSON.stringify(body)});
 const data=await r.json();
 if(!r.ok){const labels:Record<string,string>={WRITE_REVISION_CONFLICT:"Ключ изменился. Обновите страницу.",WRITE_ALREADY_STORED:"Для замены требуется подтверждение.",INVALID_INPUT:"Проверьте формат ключа.",CREDENTIAL_MANAGER_UNAVAILABLE:"Изолированный сервис управления ключами недоступен.",ADMIN_REQUIRED:"Только ADMIN может управлять ключом."};throw new Error(labels[data.detail]??"Операция не выполнена. Проверьте подключение и права.");}
 return data;
}
export type WriteState={configured:boolean;revision:number;status:string;fingerprint:string|null;checked_at:string|null;scopes:string[];scope_verified:boolean;access_state:string|null;permissions:string;live_actions:string;can_manage:boolean;management_available:boolean};
