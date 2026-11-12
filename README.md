# SAKSI: witness-validated secret sharing

*Saksi* means "witness" in Malay.

SAKSI splits a master key into *n* shares over the Mersenne prime field GF(2¹²⁷ − 1). Any *t* shares rebuild the key, and any *t* − 1 shares reveal nothing. Every share carries one-time **witness tags** that the other custodians check during a **two-round reveal**. A forged, tampered, replayed or substituted share is therefore rejected and its owner named. A Reed–Solomon **syndrome check** on the accepted shares gives a second, independent line of defence. If either check fails beyond what can be corrected, SAKSI releases nothing (fail closed).

There is no block cipher, hash function or computational assumption anywhere in the key path. Every guarantee is information-theoretic, so it holds against any adversary, including a quantum one.

Entry for the *Mathematics for Systems Security* hackathon (cryptographic track).

| | |
|---|---|
| Paper (13 pages, proofs and experiments) | [`paper/saksi.pdf`](paper/saksi.pdf) |
| Live demo (WASM core + AI agent) | https://saksi-gamma.vercel.app |
| Video | https://youtu.be/GXIt0Ia1Kog |

## What it guarantees

For *n* custodians, threshold *t*, and up to *c* ≤ ⌊(*n* − 1)/2⌋ corrupted custodians:

* **Perfect secrecy:** any *t* − 1 custodians, including the tags and keys they hold, learn nothing about the key (Theorem 1).
* **Unforgeable witnesses:** a modified share passes one honest witness with probability exactly 1/*p* = 2⁻¹²⁷ (Theorem 2).
* **Robustness and identification:** honest shares are always accepted. A modified share is accepted with probability ≤ 2ⁿ/*p*, and every rejected custodian is named (Theorem 3).
* **Keyless correction:** Reed–Solomon (Gao) decoding corrects ⌊(*m* − *t*)/2⌋ bad shares without any keys (Theorem 4).
* **Refresh:** shares can be re-randomised every epoch. A share stolen in an earlier epoch is rejected afterwards (Proposition 6).

## Measured, not claimed

All of these numbers are produced by [`attacks/harness.py`](attacks/harness.py) and [`core/src/bin/saksi.rs`](core/src/bin/saksi.rs). The raw output is in [`attacks/results/`](attacks/results).

| Experiment | Result |
|---|---|
| E1 Exhaustive secrecy, toy fields *p* = 31, 101, 13 | identical view distribution for every secret; 0 bits leaked |
| E2 χ² uniformity, 100,000 sharings of a fixed secret | all p-values > 0.01; biased-coefficient control leaks 0.0056 bits |
| E3 Z3 collusion with *t* − 1 shares | SAKSI: 31/31 candidates remain (0 bits); Mignotte control: 7.15 bits leaked |
| E4 Witness forgery vs field size, 200,000 tries per field | measured rate tracks 1/*p* |
| E5 Active attacks (bit flip, replacement, Tompa–Woll, substitution, two liars, replay, bad dealer) | plain Shamir fooled 81.9–100% of the time; SAKSI wrong key 0.0%, cheater named 100% |
| E6 The same attacks against the Rust binary | 150/150 correct, 0 wrong keys |
| E7 Fuzzing the Rust parser, 2,000 malformed bundles | 0 crashes, 0 wrong keys |
| Timing (dudect, 10⁶ samples) | every core operation \|t\| < 4.5; both deliberately leaky controls detected |

The paper also shows where SAKSI stops. With 3 of 5 custodians colluding, which is beyond the honest-majority bound, a well-formed wrong key gets through. That is expected, and the experiment shows the bound is tight.

## Repository layout

```
core/      Rust core: constant-time GF(2^127-1), scheme, Gao decoder, CLI, WebAssembly build
ref/       Python reference implementation (the specification and test oracle)
attacks/   attack harness, Python<->Rust cross-check, results
paper/     LaTeX source, figures, and the compiled PDF
web/       Next.js demo: split, custodians, two-round reveal, agent, attack lab
docs/      Devpost write-up and rendered equations
```

## Run it

```bash
# Rust core: tests, CLI, benchmarks, timing study
cd core && cargo test --release
cargo run --release -- deal --n 5 --t 3 --text "my master key" > /tmp/bundle.json
cargo run --release -- reconstruct /tmp/bundle.json
cargo run --release -- timing --samples 1000000

# Python reference and the attack harness
cd ref && python3 -m pytest -q
cd .. && python3 attacks/cross_check.py && python3 attacks/harness.py

# Paper
cd paper && latexmk -pdf saksi.tex

# Web demo (needs the WASM build in web/wasm-pkg, already committed)
cd web && npm install && npm run build && npm start
```

Rebuild the WASM yourself:

```bash
cd core
cargo build --release --lib --target wasm32-unknown-unknown --no-default-features --features wasm
wasm-bindgen --target web --out-dir ../web/wasm-pkg target/wasm32-unknown-unknown/release/saksi_core.wasm
cp ../web/wasm-pkg/saksi_core_bg.wasm ../web/public/wasm/
```

Demo environment variables (all optional):
* `GEMINI_API_KEY`, `GEMINI_MODEL`: the agent's LLM.
* `GROQ_API_KEY`: fallback provider.
* `SERVICE_SECRET`: the mock ledger's credential check.

Without an LLM key, the demo answers with a clearly labelled scripted planner. The credential path is the real one either way.

## Limitations

* The dealer is trusted for its epoch.
* Key material grows as Θ(*n*²) per share.
* Robustness needs an honest majority.
* The combiner must enforce the two-round order.
* The key exists in memory for the instant it is used.
* The Python reference is not constant time.
* Measurements were taken on a cloud VM.

All of this is discussed in §10 of the paper.

## Licence

MIT. See [LICENSE](LICENSE).
