import { NextRequest, NextResponse } from "next/server";
import { operatorHeaders } from "@/lib/operator";

type Context = {params: Promise<{path: string[]}>};
async function proxy(request: NextRequest, context: Context) {
  const path = (await context.params).path.join("/");
  const allowed = /^(?:settings|analyses|profiles|messages|automation(?:\/events)?|decisions(?:\/[a-f0-9-]{36}(?:\/resolve)?)?)$/;
  if (!allowed.test(path)) return NextResponse.json({detail: "Раздел не найден"}, {status: 404});
  if (request.method !== "GET" && request.headers.get("origin") && request.headers.get("origin") !== request.nextUrl.origin) return NextResponse.json({detail: "Запрос из другого источника запрещён"}, {status: 403});
  try {
    const url = new URL(`/api/ai/${path}`, process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000");
    const response = await fetch(url, {method: request.method, headers: {...await operatorHeaders(),
      "Idempotency-Key": request.headers.get("Idempotency-Key") ?? ""}, cache: "no-store",
      ...(request.method !== "GET" ? {body: JSON.stringify(await request.json())} : {}), signal: AbortSignal.timeout(30_000)});
    return NextResponse.json(await response.json(), {status: response.status});
  } catch {return NextResponse.json({detail: "Ответ не получен. Обновите журнал AI перед повтором."}, {status: 503});}
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
