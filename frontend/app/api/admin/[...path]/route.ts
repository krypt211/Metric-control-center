import {NextRequest,NextResponse} from "next/server";
import {backendProxy} from "@/lib/proxy";
type Context={params:Promise<{path:string[]}>};
async function proxy(request:NextRequest,context:Context) {
  const path=(await context.params).path.join("/");
  if(!/^(?:status|users(?:\/[a-f0-9-]{36})?|providers(?:\/(?:diagnostics|mapping|routing(?:\/[a-f0-9-]{36})?|(?:meta|metricflow)\/(?:credentials|check|sync|disconnect)))?)$/.test(path))return NextResponse.json({detail:"NOT_FOUND"},{status:404});
  return backendProxy(request,"/api/admin/"+path);
}
export const GET=proxy;
export const POST=proxy;
export const PATCH=proxy;

export const PUT=proxy;
export const DELETE=proxy;
