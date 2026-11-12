import { callGemini, callGroq, type Content } from "@/lib/agentServer";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Best-effort per-instance rate limit so the free LLM quota survives judging.
const hits = new Map<string, number[]>();
function limited(ip: string): boolean {
  const now = Date.now();
  const arr = (hits.get(ip) || []).filter((t) => now - t < 10 * 60_000);
  arr.push(now);
  hits.set(ip, arr);
  return arr.length > 40;
}

export async function POST(req: Request) {
  const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "local";
  if (limited(ip)) return Response.json({ error: "rate limited: try again in a few minutes", mode: "demo" }, { status: 429 });
  let body: { contents?: Content[]; provider?: string };
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "bad json" }, { status: 400 });
  }
  const contents = (body.contents || []).slice(-24);
  if (!contents.length || JSON.stringify(contents).length > 60_000) {
    return Response.json({ error: "empty or oversized conversation" }, { status: 400 });
  }
  const order = body.provider === "groq" ? [callGroq, callGemini] : [callGemini, callGroq];
  const errors: string[] = [];
  for (const fn of order) {
    try {
      const { content, model } = await fn(contents);
      return Response.json({ content, model, provider: fn === callGemini ? "gemini" : "groq", fallback_errors: errors });
    } catch (e) {
      const m = (e as Error).message;
      if (!m.startsWith("no-")) errors.push(m);
    }
  }
  return Response.json({ mode: "demo", error: errors.length ? errors.join(" | ") : "no LLM key configured" }, { status: 503 });
}
