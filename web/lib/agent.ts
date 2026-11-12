"use client";
// Client-side agent loop. The LLM runs behind /api/agent; tools run HERE, in the browser.
// The credential exists only inside `useCredential`, for the duration of one fetch.

import type { Content, Part } from "./agentServer";
import { reconstruct, type Bundle, type Outcome } from "./saksi";

export type LedgerEntry =
  | { kind: "llm"; at: number; provider: string; model: string; bytes: number; keyWindowsFound: number }
  | { kind: "tool"; at: number; endpoint: string; outcome: Outcome; keyAliveMs: number; status: number | null };

export type AgentEvent =
  | { type: "assistant"; text: string; provider: string; model: string }
  | { type: "tool"; endpoint: string; month?: string; ok: boolean; summary: string }
  | { type: "notice"; text: string };

export type Deps = {
  getRevealBundle: () => Bundle | null;           // what the custodians submit right now
  leakWindows: LeakIndex;                         // fingerprints of every 8-char window of the credential
  onLedger: (e: LedgerEntry) => void;
  onEvent: (e: AgentEvent) => void;
};

async function sha(s: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(d), (b) => b.toString(16).padStart(2, "0")).join("");
}

// 32-bit FNV-1a: a fast synchronous prefilter; SHA-256 confirms any candidate.
function fnv(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h;
}

export type LeakIndex = { fast: Set<number>; strong: Set<string> };

export async function windowsOf(secret: string): Promise<LeakIndex> {
  const fast = new Set<number>(), strong = new Set<string>();
  for (let i = 0; i + 8 <= secret.length; i++) {
    const w = secret.slice(i, i + 8);
    fast.add(fnv(w));
    strong.add(await sha(w));
  }
  return { fast, strong };
}

async function countLeaks(payload: string, idx: LeakIndex): Promise<number> {
  let found = 0;
  for (let i = 0; i + 8 <= payload.length; i++) {
    const w = payload.slice(i, i + 8);
    if (idx.fast.has(fnv(w)) && idx.strong.has(await sha(w))) found++;
  }
  return found;
}

function hexToUtf8(h: string): string {
  const b = new Uint8Array(h.length / 2);
  for (let i = 0; i < b.length; i++) b[i] = parseInt(h.slice(2 * i, 2 * i + 2), 16);
  return new TextDecoder().decode(b);
}

/** Reassemble the credential with SAKSI, make ONE request, drop the credential. */
async function useCredential(deps: Deps, endpoint: string, month?: string) {
  const bundle = deps.getRevealBundle();
  if (!bundle) return { ok: false, body: { error: "no credential has been split yet" } };
  const t0 = performance.now();
  const outcome = reconstruct(bundle);
  if (!outcome.ok || !outcome.secret_hex) {
    deps.onLedger({ kind: "tool", at: Date.now(), endpoint, outcome, keyAliveMs: 0, status: null });
    return { ok: false, body: { error: "credential unavailable: SAKSI failed closed", reason: outcome.reason,
      rejected_custodians: outcome.rejected } };
  }
  let token: string | null = hexToUtf8(outcome.secret_hex);
  outcome.secret_hex = undefined;
  const url = `/api/service/${endpoint}${month ? `?month=${encodeURIComponent(month)}` : ""}`;
  const req = fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  token = null; // the request has the header; drop our reference immediately
  const alive = performance.now() - t0;
  const r = await req;
  deps.onLedger({ kind: "tool", at: Date.now(), endpoint, outcome, keyAliveMs: alive, status: r.status });
  const body = await r.json().catch(() => ({ error: "bad response" }));
  const result = { ok: r.ok, body: { ...body } as Record<string, unknown> };
  if (outcome.rejected.length || outcome.located.length)
    result.body._saksi = { rejected_custodians: outcome.rejected, located_by_decoding: outcome.located };
  return result;
}

async function step(contents: Content[], deps: Deps): Promise<{ content: Content; provider: string; model: string } | null> {
  const payload = JSON.stringify({ contents });
  const leaks = deps.leakWindows.strong.size ? await countLeaks(payload, deps.leakWindows) : 0;
  const r = await fetch("/api/agent", { method: "POST", headers: { "Content-Type": "application/json" }, body: payload });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    deps.onLedger({ kind: "llm", at: Date.now(), provider: "none", model: "-", bytes: payload.length, keyWindowsFound: leaks });
    if (j.mode === "demo") return null;
    throw new Error(j.error || `agent error ${r.status}`);
  }
  deps.onLedger({ kind: "llm", at: Date.now(), provider: j.provider, model: j.model, bytes: payload.length, keyWindowsFound: leaks });
  return j;
}

export async function ask(question: string, history: Content[], deps: Deps): Promise<Content[]> {
  const contents: Content[] = [...history, { role: "user", parts: [{ text: question }] }];
  for (let round = 0; round < 5; round++) {
    const res = await step(contents, deps);
    if (!res) return scripted(question, contents, deps);
    contents.push(res.content);
    const calls = res.content.parts.filter((p) => p.functionCall);
    const text = res.content.parts.map((p) => p.text).filter(Boolean).join("\n").trim();
    if (text) deps.onEvent({ type: "assistant", text, provider: res.provider, model: res.model });
    if (!calls.length) return contents;
    const responses: Part[] = [];
    for (const c of calls) {
      const args = (c.functionCall!.args || {}) as { endpoint?: string; month?: string };
      const ep = args.endpoint || "health";
      const out = await useCredential(deps, ep, args.month);
      deps.onEvent({ type: "tool", endpoint: ep, month: args.month, ok: out.ok, summary: summarize(out.body) });
      const id = (c.functionCall as { id?: string }).id;
      responses.push({ functionResponse: { name: c.functionCall!.name, response: out.body, ...(id ? { id } : {}) } });
    }
    contents.push({ role: "user", parts: responses });
  }
  deps.onEvent({ type: "notice", text: "Stopped after 5 model turns." });
  return contents;
}

function summarize(b: Record<string, unknown>): string {
  if (b.error) return String(b.error);
  if ("count" in b && "total_rm" in b) return `${b.count} records, RM ${Number(b.total_rm).toLocaleString("en-MY", { minimumFractionDigits: 2 })}`;
  if ("status" in b) return `status ${b.status}`;
  if ("gross_rm" in b) return `gross RM ${Number(b.gross_rm).toLocaleString("en-MY")}`;
  return "ok";
}

/** Fallback when no LLM key is configured: a fixed keyword planner, clearly labelled. */
async function scripted(question: string, contents: Content[], deps: Deps): Promise<Content[]> {
  const q = question.toLowerCase();
  const ep = /overdue|tertunggak|lewat|late|owe/.test(q) ? "overdue" : /payroll|gaji|salary|epf/.test(q) ? "payroll_summary"
    : /invoice|invois|sales|jualan|total/.test(q) ? "invoices" : "health";
  const month = /sep|september/.test(q) ? "2026-09" : "2026-10";
  deps.onEvent({ type: "notice", text: "No LLM key is configured on this deployment, so a scripted planner is answering. The credential path below is the real one." });
  const out = await useCredential(deps, ep, month);
  deps.onEvent({ type: "tool", endpoint: ep, month, ok: out.ok, summary: summarize(out.body) });
  const text = out.ok ? `Scripted answer from ${ep}: ${summarize(out.body)}.` : `I could not use the ledger: ${String(out.body.error)}.`;
  deps.onEvent({ type: "assistant", text, provider: "scripted", model: "keyword planner" });
  return [...contents, { role: "model", parts: [{ text }] }];
}
