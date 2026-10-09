import {NextRequest, NextResponse} from "next/server";
import {backendProxy} from "@/lib/proxy";
type Context = {params: Promise<{path: string[]}>};
async function proxy(request: NextRequest, context: Context) {
  const suffix = (await context.params).path.join("/");
  if (!/^(settings|preview|evaluate|evaluations|audit|grants|profiles|assignments|observations|profiles\/[a-f0-9-]{36}(\/(copy|restore))?|assignments\/[a-f0-9-]{36})$/.test(suffix)) {
    return NextResponse.json({detail: "NOT_FOUND"}, {status: 404});
  }
  return backendProxy(request, "/api/economics/" + suffix);
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;