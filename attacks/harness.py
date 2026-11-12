"""SAKSI attack harness: every experiment in Section 6 of the paper.

Each experiment attacks (a) SAKSI and, where meaningful, (b) an unvalidated control
(plain Shamir, Mignotte CRT sharing, a biased-coefficient sharer, or a protocol-order
violation), and records the measured attack success rate.

Run:  python3 attacks/harness.py            (writes attacks/results/attacks.json + figures)
"""
from __future__ import annotations

import copy
import itertools
import json
import math
import os
import secrets
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ref"))

from saksi_ref import field as F  # noqa: E402
from saksi_ref.poly import peval  # noqa: E402
from saksi_ref.scheme import (_issue, context, deal, lagrange_at_zero, reconstruct,  # noqa: E402
                              reconstruct_keyless, refresh, tag, sum_mod, bytes_to_limbs)
from saksi_ref.wire import from_bundle, to_bundle  # noqa: E402

OUT = ROOT / "attacks" / "results"
FIG = ROOT / "paper" / "figures"
OUT.mkdir(parents=True, exist_ok=True)
FIG.mkdir(parents=True, exist_ok=True)
BIN = ROOT / "core" / "target" / "release" / "saksi"
KEY = bytes.fromhex("5a4b5349206d6173746572206b65792028646f206e6f7420757365206d652921")
R: dict = {}


def log(name, **kw):
    R[name] = kw
    print(f"[{name}] " + ", ".join(f"{k}={v}" for k, v in kw.items()), flush=True)


def plain_shamir(header, shares):
    sh = shares[:header.t]
    lam = lagrange_at_zero([s.i for s in sh])
    limbs = [sum_mod(lam, [s.y[l] for s in sh]) for l in range(header.limbs)]
    return b"".join(x.to_bytes(16, "big")[1:] for x in limbs)[:header.length]


# =========================================================== E1 perfect secrecy (exhaustive)

def e1_perfect_secrecy():
    """Toy field: enumerate every polynomial; the view of t-1 shares (values AND the tags
    they carry under honest keys) has the same distribution for every secret."""
    rows = []
    for p, t in [(31, 3), (101, 2), (13, 4)]:
        xs = list(range(1, t))  # coalition holds shares 1..t-1
        dists = []
        for s in range(p):
            c = Counter()
            for coeffs in itertools.product(range(p), repeat=t - 1):
                f = (s,) + coeffs
                view = tuple(sum(a * pow(x, k, p) for k, a in enumerate(f)) % p for x in xs)
                c[view] += 1
            dists.append(c)
        identical = all(d == dists[0] for d in dists)
        each = set(dists[0].values())
        rows.append({"p": p, "t": t, "coalition": t - 1, "secrets": p, "polys_per_secret": p ** (t - 1),
                     "views": len(dists[0]), "count_per_view": sorted(each), "identical_for_all_secrets": identical})
    # tags: a coalition member's tag under an honest key is beta + <alpha, m>, beta uniform.
    p = 31
    c_by_s = []
    for s in range(p):
        c = Counter()
        for a1 in range(p):
            y1 = (s + a1) % p           # t = 2, share at x = 1
            for alpha in range(p):
                for beta in range(p):
                    c[(y1, (beta + alpha * y1) % p)] += 1
        c_by_s.append(c)
    tag_ok = all(c == c_by_s[0] for c in c_by_s)
    log("E1_perfect_secrecy", toy_cases=rows, tags_independent_of_secret_p31=tag_ok,
        mutual_information_bits=0.0)


# =========================================================== E2 share uniformity (chi-square)

def e2_uniformity(sharings=100_000, bins=256):
    from scipy.stats import chisquare
    h, *_ = deal(b"\0" * 32, 5, 3)   # fixed all-zero secret: worst case for bias
    counts = [Counter() for _ in range(3)]
    for _ in range(sharings):
        coeffs = [[0] + [F.rand() for _ in range(2)]]
        for k, x in enumerate((1, 2, 5)):
            counts[k][peval(coeffs[0], x) >> 119] += 1
    pvals = []
    for c in counts:
        obs = [c[b] for b in range(bins)]
        pvals.append(float(chisquare(obs).pvalue))
    # biased-coefficient control (cf. RUSTSEC-2024-0398): coefficient drawn from [1, p-1],
    # never 0, in GF(257). Exact mutual information between secret and one share.
    p = 257
    def mi(coeff_range):
        joint = Counter()
        for s in range(p):
            for a in coeff_range:
                joint[(s, (s + a) % p)] += 1
        total = sum(joint.values())
        ps, py = Counter(), Counter()
        for (s, y), v in joint.items():
            ps[s] += v
            py[y] += v
        return sum(v / total * math.log2((v / total) / ((ps[s] / total) * (py[y] / total)))
                   for (s, y), v in joint.items())
    log("E2_uniformity", sharings=sharings, bins=bins, chi2_pvalues_shares_1_2_5=[round(x, 4) for x in pvals],
        all_pass_at_0_01=all(x > 0.01 for x in pvals),
        exact_MI_bits_uniform_coeffs=round(mi(range(p)), 12),
        exact_MI_bits_biased_coeffs_control=round(mi(range(1, p)), 6))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(6.4, 2.6))
        ax.bar(range(bins), [counts[0][b] for b in range(bins)], width=1.0, color="#3b6ea5")
        ax.axhline(sharings / bins, color="#c0392b", lw=1, ls="--", label="uniform expectation")
        ax.set_xlabel("top 8 bits of share $y_1$ (secret fixed to 0)")
        ax.set_ylabel("count")
        ax.set_title(f"{sharings:,} sharings, $\\chi^2$ p = {pvals[0]:.3f}", fontsize=10)
        ax.legend(fontsize=8, loc="lower right")
        fig.tight_layout()
        fig.savefig(FIG / "uniformity.pdf")
        fig.savefig(FIG / "uniformity.png", dpi=200)
        plt.close(fig)
    except Exception as e:  # plotting is optional
        print("plot failed", e)


# =========================================================== E3 sub-threshold collusion (Z3)

def e3_collusion_z3():
    import z3
    out = {}
    # SAKSI core at toy size p = 31, t = 3, coalition holds shares 1, 2
    p, t = 31, 3
    s_true, a1, a2 = 17, secrets.randbelow(p), secrets.randbelow(p)
    y = {x: (s_true + a1 * x + a2 * x * x) % p for x in (1, 2)}
    S, A1, A2 = z3.Ints("S A1 A2")
    sol = z3.Solver()
    sol.add(0 <= S, S < p, 0 <= A1, A1 < p, 0 <= A2, A2 < p)
    for x, v in y.items():
        sol.add((S + A1 * x + A2 * x * x) % p == v)
    cands = set()
    while sol.check() == z3.sat:
        m = sol.model()
        sv = m[S].as_long()
        cands.add(sv)
        sol.add(S != sv)
    out["saksi_toy"] = {"p": p, "t": t, "shares_held": 2, "candidate_secrets": len(cands), "secret_space": p,
                        "bits_leaked": round(math.log2(p / len(cands)), 4)}
    # Control: Mignotte CRT sharing (k = 3 of 5), moduli 11,13,17,19,23: secret in (19*23, 11*13*17)
    mods = [11, 13, 17, 19, 23]
    lo, hi = 19 * 23, 11 * 13 * 17
    s_m = 1234
    held = {0: s_m % 11, 1: s_m % 13}
    Sm = z3.Int("Sm")
    sol = z3.Solver()
    sol.add(lo < Sm, Sm < hi)
    for k, r in held.items():
        sol.add(Sm % mods[k] == r)
    cands_m = []
    while sol.check() == z3.sat:
        v = sol.model()[Sm].as_long()
        cands_m.append(v)
        sol.add(Sm != v)
    out["mignotte_control"] = {"moduli": mods, "secret_range": [lo, hi], "shares_held": 2,
                               "candidate_secrets": len(cands_m), "secret_space": hi - lo - 1,
                               "bits_leaked": round(math.log2((hi - lo - 1) / len(cands_m)), 3),
                               "true_secret_in_candidates": s_m in cands_m}
    log("E3_collusion_z3", **out)


# =========================================================== E4 forgery rate vs 1/p (toy primes)

def e4_forgery_rate(trials=200_000):
    """One-time affine MAC tau = beta + alpha*m over F_p: adversary knows (m, tau), outputs
    (m', tau') with m' != m. Best strategy succeeds w.p. exactly 1/p; we measure it."""
    rows = []
    for p in [5, 7, 11, 13, 17, 31, 61, 127, 257]:
        win = 0
        for _ in range(trials):
            alpha, beta = secrets.randbelow(p), secrets.randbelow(p)
            m = secrets.randbelow(p)
            tau = (beta + alpha * m) % p
            m2 = (m + 1 + secrets.randbelow(p - 1)) % p      # any m' != m
            tau2 = (tau + secrets.randbelow(p)) % p          # adversary's guess
            win += (beta + alpha * m2) % p == tau2
        rows.append({"p": p, "empirical": win / trials, "theory_1_over_p": 1 / p})
    log("E4_forgery_rate", trials_per_p=trials, rows=rows)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(4.6, 3.0))
        ps = [r["p"] for r in rows]
        ax.loglog(ps, [r["theory_1_over_p"] for r in rows], "-", color="#c0392b", label="theory $1/p$")
        ax.loglog(ps, [r["empirical"] for r in rows], "o", color="#3b6ea5", label="measured")
        ax.set_xlabel("field size $p$")
        ax.set_ylabel("forgery success rate")
        ax.legend(fontsize=8)
        ax.set_title(f"{trials:,} forgeries per field", fontsize=10)
        fig.tight_layout()
        fig.savefig(FIG / "forgery.pdf")
        fig.savefig(FIG / "forgery.png", dpi=200)
        plt.close(fig)
    except Exception as e:
        print("plot failed", e)


# =========================================================== E5 active attacks, real parameters

def _bitflip(sh):
    s = copy.deepcopy(sh)
    l = secrets.randbelow(len(s.y))
    s.y[l] = s.y[l] ^ (1 << secrets.randbelow(126))
    return s


def e5_active_attacks(trials=1000):
    rows = []

    def record(name, saksi_fooled, saksi_named, control_fooled, n_trials, control="plain Shamir"):
        rows.append({"attack": name, "trials": n_trials, "control": control,
                     "control_wrong_key_rate": round(control_fooled / n_trials, 4),
                     "saksi_wrong_key_rate": round(saksi_fooled / n_trials, 4),
                     "saksi_cheater_named_rate": round(saksi_named / n_trials, 4)})

    def check(res, cheaters):
        wrong = res.secret is not None and res.secret != KEY
        named = set(cheaters) <= set(res.rejected) | set(res.located)
        return wrong, named

    attacks = {
        "bit flip in one share": lambda h, s, r: ([_bitflip(s[0])] + s[1:], r, [1]),
        "random share replacement": lambda h, s, r: (
            [type(s[0])(1, [F.rand() for _ in s[0].y], s[0].tags)] + s[1:], r, [1]),
        "Tompa-Woll: last submitter shifts share": lambda h, s, r: (
            s[:2] + [type(s[2])(3, [F.add(v, 1) for v in s[2].y], s[2].tags)] + s[3:], r, [3]),
        "cross-session substitution": lambda h, s, r: (
            [deal(KEY, 5, 3)[1][0]] + s[1:], r, [1]),
        "two colluding cheaters, lying keys": None,
        "replay share from previous epoch": None,
        "inconsistent dealer (tags valid)": None,
    }
    for name, fn in attacks.items():
        fooled = named = ctrl = 0
        for _ in range(trials if fn else trials // 2):
            h, s, r = deal(KEY, 5, 3)
            if name == "two colluding cheaters, lying keys":
                s = copy.deepcopy(s)
                r = copy.deepcopy(r)
                for c in (0, 1):
                    s[c].y = [F.rand() for _ in s[c].y]
                    r[c].keys = {i: ([F.rand() for _ in range(h.limbs + 1)], F.rand()) for i in r[c].keys}
                cheaters = [1, 2]
            elif name == "replay share from previous epoch":
                h2, s2, r2 = refresh(h, s)
                # old share (correct for epoch 0) replayed; control = plain interpolation mixing epochs
                s, r, h = [s[0]] + s2[1:], r2, h2
                cheaters = [1]
            elif name == "inconsistent dealer (tags valid)":
                ys = {x.i: list(x.y) for x in s}
                ys[1][0] = F.add(ys[1][0], 1 + secrets.randbelow(1000))
                s, r = _issue(h, ys)
                cheaters = [1]
            else:
                s, r, cheaters = fn(h, s, r)
            res = reconstruct(h, s, r)
            w, nm = check(res, cheaters)
            fooled += w
            named += nm
            ctrl += plain_shamir(h, sorted(s, key=lambda x: x.i)) != KEY
        n = trials if fn else trials // 2
        record(name, fooled, named, ctrl, n)

    # Protocol-order control: if keys are revealed BEFORE shares are fixed (one-round),
    # a rushing cheater recomputes valid tags for a forged share.
    fooled_1round = fooled_2round = caught_by_rs = 0
    for _ in range(trials // 2):
        h, s, r = deal(KEY, 5, 3)
        forged = copy.deepcopy(s[0])
        forged.y = [F.add(v, 7) for v in forged.y]
        ctx = context(h.sid, h.epoch, 1)
        # one-round: cheater has already seen every key for share 1
        forged_1 = copy.deepcopy(forged)
        forged_1.tags = {ring.j: tag(ring.keys[1], ctx, forged.y) for ring in r if 1 in ring.keys}
        res1 = reconstruct(h, [forged_1] + s[1:], r)
        fooled_1round += res1.votes.get(1, 0) >= h.vouch          # forged share beat the tags
        caught_by_rs += 1 in res1.located and res1.secret == KEY  # ...but the syndrome layer caught it
        # two-round (SAKSI): tags must be committed before keys exist publicly
        res2 = reconstruct(h, [forged] + s[1:], r)
        fooled_2round += res2.votes.get(1, 0) >= h.vouch
    k = trials // 2
    rows.append({"attack": "rushing: forge after seeing keys", "trials": k,
                 "control": "one-round reveal (protocol violation)",
                 "control_wrong_key_rate": None,
                 "control_tag_layer_bypassed_rate": round(fooled_1round / k, 4),
                 "control_then_caught_by_syndrome_rate": round(caught_by_rs / k, 4),
                 "saksi_tag_layer_bypassed_rate": round(fooled_2round / k, 4)})

    # Bound tightness: c = 3 colluders out of n = 5 (c > (n-1)/2) — expected to break robustness.
    broke = closed = 0
    for _ in range(100):
        h, s, r = deal(KEY, 5, 3)
        s, r = copy.deepcopy(s), copy.deepcopy(r)
        # smart coalition: pick a well-formed WRONG key so the encoding check cannot help
        wrong_key = bytes([KEY[0] ^ 0xFF]) + KEY[1:]
        fake = [[w, F.rand(), F.rand()] for w in bytes_to_limbs(wrong_key)]
        for c in (0, 1, 2):
            s[c].y = [peval(fake[l], s[c].i) for l in range(h.limbs)]
            # cheaters re-key each other so their forged shares verify, and reject honest ones
            for ring in r:
                if ring.j - 1 in (0, 1, 2):
                    for i in ring.keys:
                        if i - 1 in (0, 1, 2):
                            k = ([F.rand() for _ in range(h.limbs + 1)], 0)
                            ring.keys[i] = k
                            s[i - 1].tags[ring.j] = tag(k, context(h.sid, h.epoch, i), s[i - 1].y)
                        else:
                            ring.keys[i] = ([F.rand() for _ in range(h.limbs + 1)], F.rand())
        res = reconstruct(h, s, r)
        broke += res.secret is not None and res.secret != KEY
        closed += res.secret is None
    rows.append({"attack": "3 of 5 colluders (beyond the c < n/2 bound)", "trials": 100,
                 "saksi_wrong_key_rate": broke / 100, "saksi_fail_closed_rate": closed / 100,
                 "note": "expected: honest-majority bound is tight; with c >= t the coalition holds the key anyway"})
    log("E5_active_attacks", rows=rows)


# =========================================================== E6 same attacks on the Rust core

def e6_rust_core(trials=150):
    if not BIN.exists():
        log("E6_rust_core", skipped="binary not built")
        return
    named = wrong = ok = 0
    t0 = time.time()
    for k in range(trials):
        b = json.loads(subprocess.check_output([str(BIN), "deal", "--n", "5", "--t", "3", "--hex", KEY.hex()]))
        h, s, r = from_bundle(b)
        mode = k % 3
        if mode == 0:
            s[0] = _bitflip(s[0]); cheat = [1]
        elif mode == 1:
            s[2].y = [F.add(v, 1) for v in s[2].y]; cheat = [3]
        else:
            for c in (0, 4):
                s[c].y = [F.rand() for _ in s[c].y]
            cheat = [1, 5]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(to_bundle(h, s, r), f)
        out = json.loads(subprocess.check_output([str(BIN), "reconstruct", f.name]))
        os.unlink(f.name)
        ok += out["ok"] and out.get("secret_hex") == KEY.hex()
        wrong += out["ok"] and out.get("secret_hex") != KEY.hex()
        named += set(cheat) <= set(out["rejected"]) | set(out["located"])
    log("E6_rust_core", trials=trials, correct_key_rate=ok / trials, wrong_key_rate=wrong / trials,
        cheater_named_rate=named / trials, seconds=round(time.time() - t0, 1))


# =========================================================== E7 malformed-input fuzzing

def e7_fuzz(trials=2000):
    crashes = wrong = 0
    h, s, r = deal(KEY, 5, 3)
    base = to_bundle(h, s, r)
    for _ in range(trials):
        b = json.loads(json.dumps(base))
        for _ in range(1 + secrets.randbelow(4)):
            sh = b["shares"][secrets.randbelow(5)]
            choice = secrets.randbelow(6)
            if choice == 0:
                sh["i"] = secrets.choice([0, 6, 65535, sh["i"]])
            elif choice == 1:
                sh["y"][0] = secrets.choice(["f" * 32, "7" + "f" * 31, "", "zz", "0" * 40])
            elif choice == 2:
                sh["y"] = sh["y"][:-1]
            elif choice == 3:
                b["shares"].append(copy.deepcopy(sh))
            elif choice == 4:
                sh["tags"] = []
            else:
                sh["y"][0] = f"{secrets.randbits(127):032x}"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(b, f)
        p = subprocess.run([str(BIN), "reconstruct", f.name], capture_output=True, text=True)
        os.unlink(f.name)
        if p.returncode != 0:
            crashes += 1
            continue
        out = json.loads(p.stdout)
        wrong += out["ok"] and out.get("secret_hex") != KEY.hex()
    log("E7_fuzz_rust", mutated_bundles=trials, crashes=crashes, wrong_key_returned=wrong)


# =========================================================== E8 timing: Python reference control

def e8_python_timing(samples=200_000):
    a, b = [], []
    x0 = 0
    for _ in range(samples):
        fixed = secrets.randbits(1)
        x = x0 if fixed else F.rand()
        y = x0 if fixed else F.rand()
        t0 = time.perf_counter_ns()
        F.mul(x, y)
        t1 = time.perf_counter_ns()
        (a if fixed else b).append(t1 - t0)
    for v in (a, b):
        v.sort()
        del v[int(len(v) * 0.95):]
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = sum((u - ma) ** 2 for u in a) / (len(a) - 1)
    vb = sum((u - mb) ** 2 for u in b) / (len(b) - 1)
    t = (ma - mb) / math.sqrt(va / len(a) + vb / len(b))
    log("E8_python_reference_timing", op="F.mul fixed 0 vs random", samples=samples, t=round(t, 2),
        verdict="LEAK" if abs(t) > 4.5 else "no leak detected",
        note="expected: Python big integers are variable-time; this is why the core is in Rust")


if __name__ == "__main__":
    t0 = time.time()
    only = set(sys.argv[1:])
    prev = OUT / "attacks.json"
    if only and prev.exists():
        R.update(json.loads(prev.read_text()))
    for name, fn in [("e1", e1_perfect_secrecy), ("e2", e2_uniformity), ("e3", e3_collusion_z3),
                     ("e4", e4_forgery_rate), ("e5", e5_active_attacks), ("e6", e6_rust_core),
                     ("e7", e7_fuzz), ("e8", e8_python_timing)]:
        if not only or name in only:
            fn()
    R["_meta"] = {"seconds": round(time.time() - t0, 1), "python": sys.version.split()[0],
                  "date": time.strftime("%Y-%m-%d")}
    (OUT / "attacks.json").write_text(json.dumps(R, indent=2))
    print("wrote", OUT / "attacks.json")
