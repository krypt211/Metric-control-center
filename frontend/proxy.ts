import { NextRequest, NextResponse } from "next/server";

export async function proxy(request:NextRequest) {
  const nonce=Buffer.from(crypto.randomUUID()).toString("base64");
  const csp="default-src 'self'; script-src 'self' 'nonce-"+nonce+"' 'strict-dynamic'; "+
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self'; "+
    "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'";
  const incoming=new Headers(request.headers);
  incoming.set("x-nonce",nonce); incoming.set("Content-Security-Policy",csp);
  let response=NextResponse.next({request:{headers:incoming}});
  if(!request.nextUrl.pathname.startsWith("/api/")&&request.nextUrl.pathname!=="/login") {
    try {
      const auth=await fetch((process.env.BACKEND_INTERNAL_URL??"http://127.0.0.1:8000")+"/api/auth/me",
        {headers:{cookie:request.headers.get("cookie")??"","x-real-ip":request.headers.get("x-real-ip")??""},
          cache:"no-store",signal:AbortSignal.timeout(5_000)});
      if(!auth.ok) response=NextResponse.redirect(new URL("/login",request.url));
    } catch { response=NextResponse.redirect(new URL("/login",request.url)); }
  }
  response.headers.set("Content-Security-Policy",csp);
  response.headers.set("X-Content-Type-Options","nosniff");
  response.headers.set("X-Frame-Options","DENY");
  response.headers.set("Referrer-Policy","no-referrer");
  response.headers.set("Permissions-Policy","camera=(), microphone=(), geolocation=()");
  response.headers.set("Cache-Control","no-store");
  return response;
}
export const config={matcher:["/((?!_next/static|_next/image|favicon.ico).*)"]};
