"use client";
// Thin typed wrapper around the SAKSI Rust core compiled to WebAssembly.
import init, * as core from "../wasm-pkg/saksi_core.js";

export type Header = { n: number; t: number; limbs: number; length: number; sid: number; epoch: number };
export type WShare = { i: number; y: string[]; tags: [number, string][] };
export type WKey = { alpha: string[]; beta: string };
export type WRing = { j: number; keys: [number, WKey][] };
export type Bundle = { header: Header; shares: WShare[]; rings: WRing[] };
export type Outcome = {
  ok: boolean;
  secret_hex?: string;
  accepted: number[];
  rejected: number[];
  located: number[];
  votes: [number, number][];
  mode: string;
  reason: string;
};

let ready: Promise<void> | null = null;
export function loadSaksi(): Promise<void> {
  if (!ready) ready = init({ module_or_path: "/wasm/saksi_core_bg.wasm" }).then(() => undefined);
  return ready;
}

export const deal = (secret: Uint8Array, n: number, t: number): Bundle =>
  JSON.parse(core.saksi_deal(secret, n, t));
export const refresh = (b: Bundle): Bundle => JSON.parse(core.saksi_refresh(JSON.stringify(b)));
export const reconstruct = (b: Bundle): Outcome => JSON.parse(core.saksi_reconstruct(JSON.stringify(b)));
export const reconstructKeyless = (b: Bundle): Outcome =>
  JSON.parse(core.saksi_reconstruct_keyless(JSON.stringify(b)));
export const plainShamir = (b: Bundle): string => core.plain_shamir(JSON.stringify(b));
export const witnessMatrix = (b: Bundle): [number, number, boolean][] =>
  JSON.parse(core.saksi_witness_matrix(JSON.stringify(b)));

// ---------------------------------------------------------------- corruption helpers (attack lab)

const P = (1n << 127n) - 1n;
const toHex = (x: bigint) => x.toString(16).padStart(32, "0");
const fromHex = (h: string) => BigInt("0x" + h);

function randField(): bigint {
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  let x = 0n;
  for (const v of b) x = (x << 8n) | BigInt(v);
  x &= P;
  return x === P ? 0n : x;
}

export const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

export function bitflip(s: WShare): WShare {
  const c = clone(s);
  const v = fromHex(c.y[0]) ^ (1n << 77n);
  c.y[0] = toHex(v % P);
  return c;
}

export function forge(s: WShare): WShare {
  const c = clone(s);
  c.y = c.y.map(() => toHex(randField()));
  return c;
}

/** Tompa-Woll style: shift every limb by +1 so plain Lagrange output moves predictably. */
export function shift(s: WShare): WShare {
  const c = clone(s);
  c.y = c.y.map((h) => toHex((fromHex(h) + 1n) % P));
  return c;
}

export function lyingRing(r: WRing): WRing {
  const c = clone(r);
  c.keys = c.keys.map(([i, k]) => [i, { alpha: k.alpha.map(() => toHex(randField())), beta: toHex(randField()) }]);
  return c;
}

export async function fingerprint(bytes: Uint8Array | string): Promise<string> {
  const data = typeof bytes === "string" ? hexToBytes(bytes) : bytes;
  const d = await crypto.subtle.digest("SHA-256", data as BufferSource);
  return Array.from(new Uint8Array(d).slice(0, 6), (b) => b.toString(16).padStart(2, "0")).join("");
}

export function hexToBytes(h: string): Uint8Array {
  const out = new Uint8Array(h.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(h.slice(2 * i, 2 * i + 2), 16);
  return out;
}

// ---------------------------------------------------------------- custodians

export type CustodianState = "honest" | "offline" | "tampered" | "forged" | "replay" | "colluding";

export const STATES: { id: CustodianState; label: string; hint: string }[] = [
  { id: "honest", label: "Honest", hint: "Submits its real share and keys" },
  { id: "offline", label: "Offline", hint: "Does not answer" },
  { id: "tampered", label: "Bit flip", hint: "One bit of its share flipped in storage" },
  { id: "forged", label: "Forged", hint: "Submits a made-up share" },
  { id: "replay", label: "Replay", hint: "Submits its share from the previous epoch" },
  { id: "colluding", label: "Lying", hint: "Forged share and false keys to vouch for allies" },
];

/** Assemble what reaches the reconstructor in the two-round reveal. */
export function assemble(current: Bundle, previous: Bundle | null, states: CustodianState[]): Bundle {
  const shares: WShare[] = [];
  const rings: WRing[] = [];
  current.shares.forEach((s, k) => {
    const st = states[k] ?? "honest";
    if (st === "offline") return;
    if (st === "tampered") shares.push(bitflip(s));
    else if (st === "forged" || st === "colluding") shares.push(forge(s));
    else if (st === "replay" && previous) shares.push(clone(previous.shares[k]));
    else shares.push(clone(s));
  });
  current.rings.forEach((r, k) => {
    const st = states[k] ?? "honest";
    if (st === "offline") return;
    rings.push(st === "colluding" ? lyingRing(r) : clone(r));
  });
  return { header: current.header, shares, rings };
}
