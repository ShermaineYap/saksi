// Mock "internal service" whose bearer credential the agent must use without ever showing it
// to the LLM. Credentials are stateless: token = nonce(16) || HMAC-SHA256(secret, nonce)[0..16].
// (HMAC here belongs to the mock service, not to SAKSI; SAKSI never encrypts with it.)
import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

const secret = () => process.env.SERVICE_SECRET || "saksi-demo-service-secret-not-for-production";

const b64u = (b: Buffer) => b.toString("base64url");

export function mintToken(): string {
  const nonce = randomBytes(16);
  const mac = createHmac("sha256", secret()).update(nonce).digest().subarray(0, 16);
  return "kunci_" + b64u(Buffer.concat([nonce, mac]));
}

export function checkToken(token: string | null): boolean {
  if (!token || !token.startsWith("kunci_")) return false;
  let raw: Buffer;
  try {
    raw = Buffer.from(token.slice(6), "base64url");
  } catch {
    return false;
  }
  if (raw.length !== 32) return false;
  const expect = createHmac("sha256", secret()).update(raw.subarray(0, 16)).digest().subarray(0, 16);
  return timingSafeEqual(expect, raw.subarray(16));
}

// Fictional SME: Kedai Runcit Maju Sdn Bhd (all data invented for the demo).
type Inv = { no: string; customer: string; amount_rm: number; issued: string; due: string; status: "paid" | "unpaid" };
const INVOICES: Record<string, Inv[]> = {
  "2026-10": [
    { no: "KRM-2610-001", customer: "Restoran Selera Kampung", amount_rm: 4820.5, issued: "2026-10-02", due: "2026-10-16", status: "paid" },
    { no: "KRM-2610-002", customer: "Kafe Daun Pandan", amount_rm: 1260.0, issued: "2026-10-05", due: "2026-10-19", status: "unpaid" },
    { no: "KRM-2610-003", customer: "Pasar Mini Sri Murni", amount_rm: 9315.75, issued: "2026-10-09", due: "2026-10-23", status: "paid" },
    { no: "KRM-2610-004", customer: "Kantin SK Taman Melati", amount_rm: 2190.4, issued: "2026-10-14", due: "2026-10-28", status: "unpaid" },
    { no: "KRM-2610-005", customer: "Hotel Seri Tanjung", amount_rm: 15480.0, issued: "2026-10-20", due: "2026-11-19", status: "unpaid" },
    { no: "KRM-2610-006", customer: "Restoran Selera Kampung", amount_rm: 3975.2, issued: "2026-10-27", due: "2026-11-10", status: "paid" },
  ],
  "2026-09": [
    { no: "KRM-2609-001", customer: "Pasar Mini Sri Murni", amount_rm: 8640.0, issued: "2026-09-03", due: "2026-09-17", status: "paid" },
    { no: "KRM-2609-002", customer: "Hotel Seri Tanjung", amount_rm: 12950.0, issued: "2026-09-18", due: "2026-10-18", status: "paid" },
    { no: "KRM-2609-003", customer: "Kafe Daun Pandan", amount_rm: 1105.3, issued: "2026-09-22", due: "2026-10-06", status: "paid" },
  ],
};
const TODAY = "2026-11-12";

export function serve(endpoint: string, month?: string | null) {
  const m = month && INVOICES[month] ? month : "2026-10";
  switch (endpoint) {
    case "health":
      return { service: "ledger.kedai-runcit-maju (demo)", status: "ok", as_of: TODAY };
    case "invoices": {
      const list = INVOICES[m];
      const total = list.reduce((a, b) => a + b.amount_rm, 0);
      return { month: m, count: list.length, total_rm: Math.round(total * 100) / 100, invoices: list };
    }
    case "overdue": {
      const all = Object.values(INVOICES).flat();
      const od = all.filter((i) => i.status === "unpaid" && i.due < TODAY);
      return { as_of: TODAY, count: od.length, total_rm: Math.round(od.reduce((a, b) => a + b.amount_rm, 0) * 100) / 100,
        overdue: od.map((i) => ({ ...i, days_overdue: Math.round((Date.parse(TODAY) - Date.parse(i.due)) / 864e5) })) };
    }
    case "payroll_summary":
      return { month: m, headcount: 7, gross_rm: 21840.0, epf_employer_rm: 2850.7, socso_employer_rm: 382.5,
        note: "aggregates only; individual salaries are not exposed by this endpoint" };
    default:
      return null;
  }
}
