import {NextRequest} from "next/server";
import {backendProxy} from "@/lib/proxy";
export async function GET(request:NextRequest){return backendProxy(request,"/api/dashboard/today");}
