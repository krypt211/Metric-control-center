import { NextRequest, NextResponse } from "next/server";
import { headers } from "next/headers";

export async function sessionHeaders(): Promise<Record<string,string>> {
  const incoming=await headers();
  const result:Record<string,string>={"Content-Type":"application/json"};
  for(const name of ["cookie","origin","x-csrf-token","x-real-ip","idempotency-key"]) {
    const value=incoming.get(name); if(value) result[name]=value;
  }
  // Authorization and actor/workspace headers are never trusted or manufactured.
  return result;
}
export async function backendProxy(request:NextRequest,path:string) {
  try {
    const url=new URL(path,process.env.BACKEND_INTERNAL_URL??"http://127.0.0.1:8000");
    url.search=request.nextUrl.search;
    const response=await fetch(url,{method:request.method,headers:await sessionHeaders(),cache:"no-store",
      signal:AbortSignal.timeout(15_000),...(!["GET","HEAD"].includes(request.method)?{body:await request.text()}:{})});
    const body=response.status>=500?{detail:"SERVICE_UNAVAILABLE"}:await response.json();
    const outgoing=NextResponse.json(body,{status:response.status,headers:{"Cache-Control":"no-store"}});
    for(const value of response.headers.getSetCookie()) outgoing.headers.append("Set-Cookie",value);
    for(const key of ["x-request-id","retry-after"]) {
      const value=response.headers.get(key); if(value) outgoing.headers.set(key,value);
    }
    return outgoing;
  } catch { return NextResponse.json({detail:"SERVICE_UNAVAILABLE"},{status:503}); }
}
