import {NextRequest,NextResponse} from "next/server";
import {backendProxy} from "@/lib/proxy";
type Context={params:Promise<{path?:string[]}>};
async function proxy(request:NextRequest,context:Context){
 const path=(await context.params).path??[];const suffix=path.length?"/"+path.join("/"):"";
 if(!/^(|\/(account|campaign|adset|ad|creative|tracker|eco_account|eco_campaign|eco_adset|eco_ad)(\/(view|activate|default))?|\/presets\/[a-f0-9-]{36})$/.test(suffix))return NextResponse.json({detail:"NOT_FOUND"},{status:404});
 return backendProxy(request,"/api/preferences/columns"+suffix);
}
export const GET=proxy;export const POST=proxy;export const PUT=proxy;export const DELETE=proxy;
