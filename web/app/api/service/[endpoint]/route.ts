import { checkToken, serve } from "@/lib/service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request, ctx: { params: Promise<{ endpoint: string }> }) {
  const { endpoint } = await ctx.params;
  const auth = req.headers.get("authorization");
  const token = auth?.startsWith("Bearer ") ? auth.slice(7) : null;
  if (!checkToken(token)) {
    return Response.json({ error: "invalid or missing credential" }, { status: 401 });
  }
  const month = new URL(req.url).searchParams.get("month");
  const body = serve(endpoint, month);
  if (!body) return Response.json({ error: `unknown endpoint ${endpoint}` }, { status: 404 });
  return Response.json(body, { headers: { "Cache-Control": "no-store" } });
}
