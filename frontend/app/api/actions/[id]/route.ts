import {NextRequest,NextResponse} from "next/server";
import {backendProxy} from "@/lib/proxy";
export async function GET(request:NextRequest,context:{params:Promise<{id:string}>}) {
  const {id}=await context.params;
  if(!/^[a-f0-9-]{36}$/.test(id))return NextResponse.json({detail:"NOT_FOUND"},{status:404});
  return backendProxy(request,"/api/actions/"+id);
}
