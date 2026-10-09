"use client";
import {serializeAuthenticatedWrite} from "./use-column-preferences";
import {localized} from "./economics";
export async function readEconomics<T>(path: string, signal?: AbortSignal): Promise<T> {
 const response=await fetch("/api/economics/"+path,{cache:"no-store",signal});
 const data=await response.json();
 if(response.status===401){window.location.assign("/login");throw new Error("Повторите вход");}
 if(!response.ok)throw new Error(typeof data.detail==="string"?localized(data.detail):"Проверьте период и фильтры.");
 return data;
}
export function writeEconomics<T>(path: string, method: string, body?: unknown): Promise<T> {
 return serializeAuthenticatedWrite(async()=>{
 const csrf=await fetch("/api/auth/csrf",{cache:"no-store"});
 if(!csrf.ok)throw new Error("Повторите вход");
 const token=(await csrf.json()).csrf_token;
 const response=await fetch("/api/economics/"+path,{method,headers:{"Content-Type":"application/json","X-CSRF-Token":token},...(body===undefined?{}:{body:JSON.stringify(body)})});
 const data=await response.json();
 if(!response.ok)throw new Error(typeof data.detail==="string"?localized(data.detail):"Проверьте заполнение полей: денежные значения вводятся через точку, ROI должен быть больше −100%.");
 return data as T;
 });
}