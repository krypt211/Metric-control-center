import { NextRequest, NextResponse } from "next/server";
import { backendProxy } from "@/lib/proxy";
type Context = { params: Promise<{ path?: string[] }> };
async function proxy(request: NextRequest, context: Context) {
  const suffix = (await context.params).path?.join("/") ?? "";
  if (
    !/^(settings|grants|ads|from-rule|requests(\/[a-f0-9-]{36}(\/(preflight|confirm|simulate|cancel))?)?)$/.test(
      suffix,
    )
  )
    return NextResponse.json({ detail: "NOT_FOUND" }, { status: 404 });
  return backendProxy(request, "/api/manual-control/" + suffix);
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
