import {NextRequest,NextResponse} from "next/server";
import {backendProxy} from "@/lib/proxy";
type Context={params:Promise<{path:string[]}>};
async function proxy(request:NextRequest,context:Context) {
  const path=(await context.params).path.join("/");
  if(!["csrf","login","logout","me"].includes(path))return NextResponse.json({detail:"NOT_FOUND"},{status:404});
  return backendProxy(request,"/api/auth/"+path);
}
export const GET=proxy;
export const POST=proxy;
