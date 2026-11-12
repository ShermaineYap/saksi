import { mintToken } from "@/lib/service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Issues a fresh credential. The browser splits it with SAKSI immediately and discards it.
export async function POST() {
  return Response.json({ token: mintToken() }, { headers: { "Cache-Control": "no-store" } });
}
