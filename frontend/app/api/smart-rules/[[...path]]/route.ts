import { NextRequest, NextResponse } from "next/server";
import { backendProxy } from "@/lib/proxy";
type Context = { params: Promise<{ path?: string[] }> };
async function proxy(request: NextRequest, context: Context) {
  const suffix = (await context.params).path?.join("/") ?? "";
  if (
    !/^(|available-scopes|grants|[a-f0-9-]{36}(\/(copy|restore|simulate|history))?|simulations\/[a-f0-9-]{36})$/.test(
      suffix,
    )
  )
    return NextResponse.json({ detail: "NOT_FOUND" }, { status: 404 });
  return backendProxy(
    request,
    "/api/smart-rules" + (suffix ? "/" + suffix : ""),
  );
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
