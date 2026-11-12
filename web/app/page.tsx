"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import WitnessMatrix from "@/components/WitnessMatrix";
import AttackLab from "@/components/AttackLab";
import {
  assemble, deal, fingerprint, loadSaksi, plainShamir, reconstruct, reconstructKeyless, refresh,
  STATES, witnessMatrix, type Bundle, type CustodianState, type Outcome,
} from "@/lib/saksi";
import { ask, windowsOf, type AgentEvent, type LeakIndex, type LedgerEntry } from "@/lib/agent";
import type { Content } from "@/lib/agentServer";

const REPO = process.env.NEXT_PUBLIC_REPO_URL || "https://github.com/ShermaineYap/saksi";
const VIDEO = process.env.NEXT_PUBLIC_VIDEO_URL || "";

const CUSTODIANS = [
  ["This browser", "Kept in this device's storage"],
  ["Passkey vault", "Wrapped to the owner's passkey"],
  ["Server escrow", "Recovery share held by the host"],
  ["Aisyah, finance", "Colleague's phone"],
  ["Wei Jie, IT", "Colleague's laptop"],
  ["Rajesh, auditor", "External auditor"],
  ["Mei Ling, director", "Director's phone"],
  ["Farid, operations", "Warehouse terminal"],
  ["Offsite safe", "Printed share in a safe"],
];

type Reveal = { outcome: Outcome; cells: [number, number, boolean][]; present: Set<number>; plain: string; plainFp: string;
  keyless: Outcome; fp: string; run: number };

export default function Page() {
  const [ready, setReady] = useState(false);
  const [err, setErr] = useState("");
  // hero
  const [hero, setHero] = useState<{ cells: [number, number, boolean][]; votes: [number, number][] } | null>(null);
  // split
  const [mode, setMode] = useState<"credential" | "text">("credential");
  const [text, setText] = useState("kata laluan pangkalan data: m@ju-2026!");
  const [n, setN] = useState(5);
  const [t, setT] = useState(3);
  const [cur, setCur] = useState<Bundle | null>(null);
  const [prev, setPrev] = useState<Bundle | null>(null);
  const [fp, setFp] = useState("");
  const [splitNote, setSplitNote] = useState("");
  const windows = useRef<LeakIndex>({ fast: new Set(), strong: new Set() });
  // custodians
  const [states, setStates] = useState<CustodianState[]>(Array(9).fill("honest"));
  // reveal
  const [rev, setRev] = useState<Reveal | null>(null);
  // agent
  const [history, setHistory] = useState<Content[]>([]);
  const [events, setEvents] = useState<(AgentEvent | { type: "user"; text: string })[]>([]);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const chatEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadSaksi()
      .then(() => {
        setReady(true);
        // Hero: a live 3-of-5 sharing where custodian 2 forges its share.
        const b = deal(new TextEncoder().encode("hero-demo-key"), 5, 3);
        const atk = assemble(b, null, ["honest", "forged", "honest", "honest", "honest"]);
        const o = reconstruct(atk);
        setHero({ cells: witnessMatrix(atk), votes: o.votes });
      })
      .catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    const box = chatEnd.current?.parentElement;
    if (box && events.length) box.scrollTop = box.scrollHeight; // scroll the chat box only, never the page
  }, [events]);

  const split = useCallback(async () => {
    setErr("");
    setRev(null);
    let secret: Uint8Array;
    if (mode === "credential") {
      const r = await fetch("/api/service/provision", { method: "POST" });
      const { token } = await r.json();
      windows.current = await windowsOf(token);
      secret = new TextEncoder().encode(token);
      setSplitNote(`A fresh ${token.length}-character ledger credential was issued, split, and its plaintext discarded from this page.`);
    } else {
      secret = new TextEncoder().encode(text);
      windows.current = await windowsOf(text);
      setSplitNote(`Your ${secret.length}-byte secret was split. Its plaintext stays only in the text box.`);
    }
    setFp(await fingerprint(secret));
    const b0 = deal(secret, n, t);
    secret.fill(0);
    const b1 = refresh(b0); // custodians hold epoch-1 shares; epoch-0 shares exist only for the replay attack
    setPrev(b0);
    setCur(b1);
    setStates(Array(9).fill("honest"));
  }, [mode, text, n, t]);

  const revealBundle = useCallback(() => (cur ? assemble(cur, prev, states.slice(0, cur.header.n)) : null), [cur, prev, states]);

  const runReveal = useCallback(async () => {
    const b = revealBundle();
    if (!b) return;
    const outcome = reconstruct(b);
    const plain = plainShamir(b);
    const keyless = reconstructKeyless({ ...b, rings: [] });
    const outFp = outcome.secret_hex ? await fingerprint(outcome.secret_hex) : "";
    const plainFp = plain ? await fingerprint(plain) : "";
    keyless.secret_hex = undefined;
    outcome.secret_hex = undefined;
    setRev({ outcome, cells: witnessMatrix(b), present: new Set(b.shares.map((s) => s.i)), plain: plain ? "yes" : "",
      plainFp, keyless, fp: outFp, run: Date.now() });
  }, [revealBundle]);

  const send = useCallback(async (question: string) => {
    if (!question.trim() || busy) return;
    setBusy(true);
    setQ("");
    setEvents((e) => [...e, { type: "user", text: question }]);
    try {
      const h = await ask(question, history, {
        getRevealBundle: revealBundle,
        leakWindows: windows.current,
        onLedger: (x) => setLedger((l) => [...l, x]),
        onEvent: (x) => setEvents((e) => [...e, x]),
      });
      setHistory(h);
    } catch (e) {
      setEvents((x) => [...x, { type: "notice", text: `Agent error: ${(e as Error).message}` }]);
    } finally {
      setBusy(false);
    }
  }, [busy, history, revealBundle]);

  const leaks = ledger.reduce((a, e) => a + (e.kind === "llm" ? e.keyWindowsFound : 0), 0);
  const llmCalls = ledger.filter((e) => e.kind === "llm") as Extract<LedgerEntry, { kind: "llm" }>[];
  const toolCalls = ledger.filter((e) => e.kind === "tool") as Extract<LedgerEntry, { kind: "tool" }>[];
  const bytes = llmCalls.reduce((a, e) => a + e.bytes, 0);
  const names = useMemo(() => CUSTODIANS.map((c) => c[0]), []);
  const need = cur ? Math.floor((cur.header.n - 1) / 2) : 2;

  return (
    <>
      <div className="wrap">
        <header className="mast">
          <a className="mark" href="#top">SAKSI<small>witness-validated secret sharing</small></a>
          <nav aria-label="Sections">
            <a href="#split">Split</a><a href="#custodians">Custodians</a><a href="#reveal">Reveal</a>
            <a href="#agent">Agent</a><a href="#lab">Attack lab</a><a href="#paper">Paper</a>
          </nav>
        </header>

        <section className="hero" id="top">
          <div>
            <h1>Split a master key five ways. Catch the custodian who lies.</h1>
            <p>
              SAKSI shares a key over the prime field 2<sup>127</sup>−1 so that fewer than <em>t</em> custodians learn
              nothing at all. Every share carries one-time witness tags that the other custodians check, so a
              forged, tampered or replayed share is rejected and its owner named. The probability of slipping a
              forgery past one witness is 2<sup>−127</sup>.
            </p>
            <p>
              Then an AI agent uses the key, and the LLM provider never receives a single byte of it.
            </p>
            <div className="facts">
              <span className="chip">No cipher or hash in the key path</span>
              <span className="chip">Constant-time Rust, run here as WebAssembly</span>
              <span className="chip">Post-quantum by construction</span>
            </div>
          </div>
          <div>
            {hero ? (
              <WitnessMatrix n={5} names={names} cells={hero.cells} votes={hero.votes} need={2}
                present={new Set([1, 2, 3, 4, 5])} animateKey="hero"
                title="Live: custodian 2 submits a forged share"
                sub="Each row is a share; each column is a custodian checking it with its own one-time key. Share 2 needs 2 confirmations and gets none." />
            ) : (
              <div className="matrix"><p className="sub">{err ? `Could not load the WebAssembly core: ${err}` : "Loading the Rust core…"}</p></div>
            )}
          </div>
        </section>

        {/* ------------------------------------------------ 1 split */}
        <section className="step" id="split">
          <div className="num">1</div>
          <div>
            <h2>Split the secret</h2>
            <p className="lede">
              The dealer encodes the secret as field elements, multiplies by a Vandermonde matrix to make <em>n</em>{" "}
              shares, and issues every custodian one-time keys to witness everyone else&apos;s share.
            </p>
            <div className="two">
              <div className="panel">
                <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
                  <legend className="field" style={{ fontWeight: 600, marginBottom: 6 }}>What to split</legend>
                  <div className="row">
                    <label className="row small"><input type="radio" name="m" checked={mode === "credential"} onChange={() => setMode("credential")} /> A fresh ledger credential, used by the agent in step 4</label>
                    <label className="row small"><input type="radio" name="m" checked={mode === "text"} onChange={() => setMode("text")} /> My own text</label>
                  </div>
                </fieldset>
                {mode === "text" && (
                  <div style={{ marginTop: 10 }}>
                    <label className="field" htmlFor="sec">Secret (UTF-8)</label>
                    <input id="sec" type="text" value={text} onChange={(e) => setText(e.target.value)} maxLength={400} />
                  </div>
                )}
                <div className="range"><label htmlFor="n">Custodians</label>
                  <input id="n" type="range" min={3} max={9} value={n} onChange={(e) => { const v = +e.target.value; setN(v); if (t > v) setT(v); }} /><b>{n}</b></div>
                <div className="range"><label htmlFor="t">Threshold</label>
                  <input id="t" type="range" min={2} max={n} value={t} onChange={(e) => setT(+e.target.value)} /><b>{t}</b></div>
                <p className="muted small">Any {t} custodians can rebuild the secret; any {t - 1} learn nothing. Up to {Math.floor((n - 1) / 2)} lying custodians are identified.</p>
                <button className="btn" onClick={split} disabled={!ready}>Split into {n} shares</button>
              </div>
              <div className="panel">
                <h3>Shares issued</h3>
                {!cur ? <p className="muted">No shares yet. Split a secret to see what each custodian receives.</p> : (
                  <>
                    <p className="small">{splitNote}</p>
                    <dl className="kv">
                      <dt>Session</dt><dd className="hex">{cur.header.sid.toString(16)}</dd>
                      <dt>Epoch</dt><dd>{cur.header.epoch} (refreshed once, so a stale epoch-0 share exists for the replay test)</dd>
                      <dt>Fingerprint</dt><dd className="hex">{fp}</dd>
                    </dl>
                    <div style={{ marginTop: 12 }}>
                      {cur.shares.map((s) => (
                        <div key={s.i} className="small" style={{ padding: "6px 0", borderTop: "1px solid var(--rule)" }}>
                          <b>{s.i}. {CUSTODIANS[s.i - 1][0]}</b> · {s.y.length} field elements, {s.tags.length} witness tags, {cur.rings[s.i - 1].keys.length} witness keys
                          <div className="hex">y = {s.y[0].slice(0, 20)}…</div>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </section>

        {/* ------------------------------------------------ 2 custodians */}
        <section className="step" id="custodians">
          <div className="num">2</div>
          <div>
            <h2>Decide who misbehaves</h2>
            <p className="lede">
              In this demo every custodian is simulated in your browser, so you can make any of them lie. SAKSI
              names up to {Math.floor(((cur?.header.n ?? n) - 1) / 2)} liars at once and refuses to output anything when fewer than {cur?.header.t ?? t} honest shares remain.
            </p>
            <div className="panel">
              {Array.from({ length: cur?.header.n ?? n }, (_, k) => (
                <div className="cust" key={k}>
                  <div className="idx">{k + 1}</div>
                  <div><span className="name">{CUSTODIANS[k][0]}</span> <span className="where">· {CUSTODIANS[k][1]}</span></div>
                  <div className="seg" role="group" aria-label={`Behaviour of custodian ${k + 1}`}>
                    {STATES.map((s) => (
                      <button key={s.id} title={s.hint} aria-pressed={states[k] === s.id} className={s.id === "honest" || s.id === "offline" ? "" : "bad"}
                        onClick={() => setStates((st) => st.map((x, i) => (i === k ? s.id : x)))}>{s.label}</button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ------------------------------------------------ 3 reveal */}
        <section className="step" id="reveal">
          <div className="num">3</div>
          <div>
            <h2>Run the two-round reveal</h2>
            <p className="lede">
              Round 1: custodians submit shares and tags. Round 2, only after that: they publish their witness keys.
              A share is accepted with {need} confirmations from other custodians. The accepted shares must then
              pass a Reed–Solomon syndrome check before Lagrange interpolation rebuilds the key.
            </p>
            <button className="btn" onClick={runReveal} disabled={!cur}>Run the two-round reveal</button>
            {!cur && <span className="muted small" style={{ marginLeft: 12 }}>Split a secret first.</span>}
            {rev && cur && (
              <div className="two" style={{ marginTop: 20 }}>
                <WitnessMatrix n={cur.header.n} names={names} cells={rev.cells} votes={rev.outcome.votes} need={need}
                  present={rev.present} animateKey={rev.run} title="Witness matrix" sub="Rows: share being checked. Columns: the custodian whose key checks it." />
                <div>
                  <div className={`verdict ${rev.outcome.ok ? "good" : "bad"}`}>
                    <strong>{rev.outcome.ok ? (rev.fp === fp ? "Key rebuilt correctly" : "Key rebuilt") : "Refused: no key released"}</strong>
                    {rev.outcome.ok ? `Fingerprint ${rev.fp} matches the secret you split.` : rev.outcome.reason}
                    <dl className="kv">
                      <dt>Path</dt><dd>{rev.outcome.mode}</dd>
                      <dt>Accepted</dt><dd>{rev.outcome.accepted.join(", ") || "none"}</dd>
                      <dt>Named cheaters</dt><dd>{[...rev.outcome.rejected, ...rev.outcome.located].map((i) => `${i} (${CUSTODIANS[i - 1]?.[0] ?? "?"})`).join(", ") || "none"}</dd>
                    </dl>
                  </div>
                  <div className="compare">
                    <div><b>Plain Shamir, same shares</b>
                      {rev.plainFp ? (rev.plainFp === fp ? <><span className="tick">✓</span> correct key</> : <><span className="cross">✗</span> silently wrong key ({rev.plainFp})</>) : "not enough shares"}
                      <div className="muted small">No validation: interpolates whatever the first {cur.header.t} custodians send.</div>
                    </div>
                    <div><b>Keyless decoding, same shares</b>
                      {rev.keyless.ok ? <><span className="tick">✓</span> recovered; located {rev.keyless.located.join(", ") || "no errors"}</> : <><span className="cross">✗</span> {rev.keyless.reason}</>}
                      <div className="muted small">Independent second check: Reed–Solomon decoding, no keys at all.</div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* ------------------------------------------------ 4 agent */}
        <section className="step" id="agent">
          <div className="num">4</div>
          <div>
            <h2>Let the agent use the key</h2>
            <p className="lede">
              Kunci is an operations agent for a fictional Malaysian wholesaler. The LLM plans and calls{" "}
              <code>fetch_ledger</code>. That tool runs in your browser: SAKSI rebuilds the credential from the custodians as
              you configured them, makes one request, and drops it. The LLM only ever sees the tool&apos;s result.
            </p>
            {!cur || mode !== "credential" ? (
              <p className="muted">Split a <b>ledger credential</b> in step 1 first. The agent needs it to reach the ledger.</p>
            ) : null}
            <div className="two">
              <div className="panel">
                <div className="chat" aria-live="polite">
                  {events.length === 0 && <p className="muted">Ask about invoices, overdue payments or payroll totals. Then make two custodians lie and ask again.</p>}
                  {events.map((e, k) =>
                    e.type === "user" ? <div key={k} className="msg user">{e.text}</div>
                    : e.type === "assistant" ? <div key={k} className="msg bot"><span className="who">Kunci · {e.provider} {e.model}</span>{e.text}</div>
                    : e.type === "tool" ? <div key={k} className={`msg tool ${e.ok ? "" : "fail"}`}>fetch_ledger({e.endpoint}{e.month ? `, ${e.month}` : ""}) → {e.ok ? "" : "refused: "}{e.summary}</div>
                    : <div key={k} className="msg note">{e.text}</div>)}
                  <div ref={chatEnd} />
                </div>
                <div className="suggest">
                  {["Which customers are overdue, and by how much?", "Berapa jumlah invois bulan Oktober?", "Summarise payroll for October."].map((s) => (
                    <button key={s} onClick={() => send(s)} disabled={busy || !cur || mode !== "credential"}>{s}</button>
                  ))}
                </div>
                <form className="composer" onSubmit={(e) => { e.preventDefault(); send(q); }}>
                  <input type="text" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask Kunci about the ledger" aria-label="Question" />
                  <button className="btn" disabled={busy || !cur || mode !== "credential"}>{busy ? "Working…" : "Ask"}</button>
                </form>
              </div>
              <div className="panel">
                <h3>What left this browser</h3>
                <div className="row" style={{ alignItems: "flex-end", gap: 18 }}>
                  <div><div className={`zero ${leaks ? "bad" : "good"}`}>{leaks}</div><div className="small muted">credential fragments found in LLM traffic</div></div>
                  <div className="small muted">{llmCalls.length} requests to the LLM, {bytes.toLocaleString()} bytes scanned for every 8-character piece of the credential.</div>
                </div>
                <div className="scroll-x" style={{ marginTop: 14 }}>
                  <table className="ledger">
                    <thead><tr><th>Event</th><th>Detail</th></tr></thead>
                    <tbody>
                      {ledger.length === 0 && <tr><td colSpan={2} className="muted">Nothing yet.</td></tr>}
                      {ledger.map((e, k) => e.kind === "llm" ? (
                        <tr key={k}><td>LLM request</td><td>{e.provider === "none" ? "no LLM configured" : `${e.provider} · ${e.model}`}; {e.bytes} bytes; fragments: {e.keyWindowsFound}</td></tr>
                      ) : (
                        <tr key={k}><td>Credential used</td><td>
                          {e.outcome.ok ? <>rebuilt from {e.outcome.accepted.join(", ")}; in memory <span className="live">{e.keyAliveMs.toFixed(1)} ms</span>; ledger HTTP {e.status}</> : <span className="cross">refused: {e.outcome.reason}</span>}
                          {(e.outcome.rejected.length > 0 || e.outcome.located.length > 0) && <> · named: {[...e.outcome.rejected, ...e.outcome.located].join(", ")}</>}
                        </td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="small muted" style={{ marginTop: 12 }}>
                  Custodians reset? The agent always uses the current custodian settings from step 2, so making three of five
                  lie makes the next tool call fail closed.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* ------------------------------------------------ 5 attack lab */}
        <section className="step" id="lab">
          <div className="num">5</div>
          <div>
            <h2>Attack it yourself</h2>
            <p className="lede">
              Each run deals fresh random 32-byte keys in WebAssembly, applies the attack, and compares SAKSI with
              plain Shamir interpolation on exactly the same shares.
            </p>
            <AttackLab ready={ready} />
          </div>
        </section>

        <section className="step" id="paper">
          <div className="num" aria-hidden="true">§</div>
          <div>
            <h2>Paper, proofs and code</h2>
            <p className="lede">
              The paper proves perfect secrecy, a 1/p forgery bound per witness tag and robustness for up to
              ⌊(n−1)/2⌋ liars, and reports every experiment: exhaustive secrecy checks, χ² share uniformity, Z3
              collusion attacks, active attacks on the Rust core, fuzzing, and dudect timing tests.
            </p>
            <div className="row">
              <a className="btn" href="/saksi.pdf">Read the paper (PDF)</a>
              <a className="btn ghost" href={REPO}>Source code</a>
              {VIDEO && <a className="btn ghost" href={VIDEO}>Watch the video</a>}
            </div>
          </div>
        </section>
      </div>
      <footer>
        <div className="wrap row">
          <span>SAKSI is a hackathon research prototype for the Mathematics for Systems Security challenge. MIT licence.</span>
          <span>Saksi means “witness” in Malay.</span>
        </div>
      </footer>
    </>
  );
}
