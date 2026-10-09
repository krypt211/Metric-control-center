import {NextRequest} from "next/server";
import {backendProxy} from "@/lib/proxy";
export async function PUT(request:NextRequest){return backendProxy(request,"/api/recommendations/settings");}
