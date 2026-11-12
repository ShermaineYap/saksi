"use client";

import { useState } from "react";
import { assemble, deal, plainShamir, reconstruct, refresh, type Bundle, type CustodianState } from "@/lib/saksi";
import results from "@/data/results.json";

type Row = { name: string; hint: string; build: (b0: Bundle) => { b: Bundle; cheaters: number[] } };

const st = (m: Record<number, CustodianState>): CustodianState[] =>
  [1, 2, 3, 4, 5].map((i) => m[i] ?? "honest");

const ATTACKS: Row[] = [
  { name: "Bit flip", hint: "Custodian 1's stored share has one bit flipped",
    build: (b0) => { const b1 = refresh(b0); return { b: assemble(b1, b0, st({ 1: "tampered" })), cheaters: [1] }; } },
  { name: "Forged share", hint: "Custodian 2 submits random values",
    build: (b0) => { const b1 = refresh(b0); return { b: assemble(b1, b0, st({ 2: "forged" })), cheaters: [2] }; } },
  { name: "Replay", hint: "Custodian 1 submits its share from the previous epoch",
    build: (b0) => { const b1 = refresh(b0); return { b: assemble(b1, b0, st({ 1: "replay" })), cheaters: [1] }; } },
  { name: "Two liars", hint: "Custodians 1 and 3 forge shares and publish false keys",
    build: (b0) => { const b1 = refresh(b0); return { b: assemble(b1, b0, st({ 1: "colluding", 3: "colluding" })), cheaters: [1, 3] }; } },
];

type Res = { trials: number; plainWrong: number; saksiWrong: number; named: number; failClosed: number; ms: number };

const toHex = (u: Uint8Array) => Array.from(u, (x) => x.toString(16).padStart(2, "0")).join("");

export default function AttackLab({ ready }: { ready: boolean }) {
  const [res, setRes] = useState<Record<string, Res>>({});
  const [running, setRunning] = useState<string | null>(null);
  const TRIALS = 200;

  async function run(a: Row) {
    setRunning(a.name);
    const r: Res = { trials: 0, plainWrong: 0, saksiWrong: 0, named: 0, failClosed: 0, ms: 0 };
    const t0 = performance.now();
    for (let k = 0; k < TRIALS; k++) {
      const key = new Uint8Array(32);
      crypto.getRandomValues(key);
      const hex = toHex(key);
      const { b, cheaters } = a.build(deal(key, 5, 3));
      const o = reconstruct(b);
      r.trials++;
      r.plainWrong += plainShamir(b) !== hex ? 1 : 0;
      r.saksiWrong += o.ok && o.secret_hex !== hex ? 1 : 0;
      r.failClosed += o.ok ? 0 : 1;
      const named = new Set([...o.rejected, ...o.located]);
      r.named += cheaters.every((c) => named.has(c)) ? 1 : 0;
      if (k % 25 === 24) { r.ms = performance.now() - t0; setRes((x) => ({ ...x, [a.name]: { ...r } })); await new Promise((z) => setTimeout(z, 0)); }
    }
    r.ms = performance.now() - t0;
    setRes((x) => ({ ...x, [a.name]: r }));
    setRunning(null);
  }

  const pct = (x: number, n: number) => (n ? `${((100 * x) / n).toFixed(1)}%` : "–");
  const e5 = results.e5 as Record<string, unknown>[];

  return (
    <>
      <div className="panel scroll-x">
        <table className="lab-table">
          <thead>
            <tr><th>Attack (3-of-5, {TRIALS} keys)</th><th>Plain Shamir returns a wrong key</th><th>SAKSI returns a wrong key</th><th>SAKSI names the cheater</th><th /></tr>
          </thead>
          <tbody>
            {ATTACKS.map((a) => {
              const r = res[a.name];
              return (
                <tr key={a.name}>
                  <td><b>{a.name}</b><div className="muted small">{a.hint}</div></td>
                  <td>{r ? <><div className="bar ctrl"><i style={{ width: pct(r.plainWrong, r.trials) }} /></div><span className="pct">{pct(r.plainWrong, r.trials)}</span></> : "–"}</td>
                  <td>{r ? <><div className="bar ours"><i style={{ width: pct(r.saksiWrong, r.trials) }} /></div><span className="pct">{pct(r.saksiWrong, r.trials)}</span></> : "–"}</td>
                  <td>{r ? <span className="pct">{pct(r.named, r.trials)}</span> : "–"}</td>
                  <td><button className="btn ghost" disabled={!ready || running !== null} onClick={() => run(a)}>{running === a.name ? `Running ${r?.trials ?? 0}/${TRIALS}` : "Run"}</button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="muted small" style={{ marginTop: 10 }}>
          Plain Shamir can look right by luck when the damage lands in the zero padding of a short final limb; SAKSI
          still rejects those shares.
        </p>
      </div>
      <div className="panel">
        <h3>Full offline study (Python reference and Rust core)</h3>
        <div className="scroll-x">
          <table className="lab-table">
            <thead><tr><th>Attack</th><th>Trials</th><th>Control fooled</th><th>SAKSI wrong key</th></tr></thead>
            <tbody>
              {e5.filter((r) => typeof r.control_wrong_key_rate === "number").map((r) => (
                <tr key={String(r.attack)}><td>{String(r.attack)}</td><td>{String(r.trials)}</td>
                  <td className="pct">{(100 * Number(r.control_wrong_key_rate)).toFixed(1)}%</td>
                  <td className="pct">{(100 * Number(r.saksi_wrong_key_rate)).toFixed(1)}%</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small" style={{ marginTop: 10 }}>
          Rust fuzzing: {results.e7.mutated_bundles.toLocaleString()} malformed bundles, {results.e7.crashes} crashes, {results.e7.wrong_key_returned} wrong keys.
          Timing (dudect, 10⁶ samples): every core operation |t| &lt; 4.5; both deliberately leaky controls flagged.
        </p>
      </div>
    </>
  );
}
