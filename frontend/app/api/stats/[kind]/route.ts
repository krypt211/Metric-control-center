import {NextRequest,NextResponse} from "next/server";
import {backendProxy} from "@/lib/proxy";
export async function GET(request:NextRequest,context:{params:Promise<{kind:string}>}) {
  const {kind}=await context.params;
  if(!["table","filters","summary","optional","sources"].includes(kind))return NextResponse.json({detail:"NOT_FOUND"},{status:404});
  return backendProxy(request,"/api/stats/"+kind);
}
