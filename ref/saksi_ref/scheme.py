"""SAKSI: (t, n) secret sharing over F_p with unconditional share validation.

Layers
  1. Share      y = V a           (Vandermonde / Shamir encoding, perfect secrecy)
  2. Witness    tau_ji = beta + <alpha, (ctx_i, y_i)>   (one-time affine MAC, forgery 1/p)
  3. Reveal     round 1 shares+tags, round 2 keys        (defeats rushing / Tompa-Woll)
  4. Syndrome   H y = 0 on accepted shares; Gao decoding localises residual errors
  5. Lagrange   s = sum lambda_i y_i, fail closed if < t valid shares

This is the reference implementation (specification + oracle). It is not constant time.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field as dfield

from . import field as F
from .poly import gao_decode, peval

LIMB_BYTES = 15  # 120-bit limbs < p


# ---------------------------------------------------------------- encoding

def bytes_to_limbs(data: bytes) -> list[int]:
    if not data:
        raise ValueError("secret must be non-empty")
    out = []
    for off in range(0, len(data), LIMB_BYTES):
        chunk = data[off:off + LIMB_BYTES].ljust(LIMB_BYTES, b"\0")
        out.append(int.from_bytes(chunk, "big"))
    return out


def limbs_to_bytes(limbs: list[int], length: int) -> bytes | None:
    """Inverse of bytes_to_limbs. Returns None if a limb is outside the 120-bit encoding
    range or the zero padding is non-zero: an honest reconstruction never produces that,
    so it proves corruption and the caller fails closed."""
    if any(x >> (8 * LIMB_BYTES) for x in limbs):
        return None
    raw = b"".join(int(x).to_bytes(LIMB_BYTES, "big") for x in limbs)
    if any(raw[length:]):
        return None
    return raw[:length]


def context(sid: int, epoch: int, i: int) -> int:
    """Public per-share context bound into every tag: session id, epoch, share index."""
    assert 0 <= sid < 2**64 and 0 <= epoch < 2**32 and 0 < i < 2**16
    return sid | (epoch << 64) | (i << 96)


# ---------------------------------------------------------------- data types

@dataclass(frozen=True)
class Header:
    n: int
    t: int
    limbs: int
    length: int
    sid: int
    epoch: int = 0

    @property
    def vouch(self) -> int:
        """Number of independent key-holder confirmations a share needs: floor((n-1)/2)."""
        return (self.n - 1) // 2


@dataclass
class Share:
    i: int
    y: list[int]
    tags: dict[int, int]  # j -> tau_{j,i}: tag on this share under verifier j's key


@dataclass
class KeyRing:
    j: int
    keys: dict[int, tuple[list[int], int]]  # i -> (alpha vector, beta) used to check share i


@dataclass
class Result:
    secret: bytes | None
    accepted: list[int] = dfield(default_factory=list)
    rejected: list[int] = dfield(default_factory=list)   # failed witness check (named cheaters)
    located: list[int] = dfield(default_factory=list)    # passed tags but located by RS decoding
    votes: dict[int, int] = dfield(default_factory=dict)
    mode: str = ""
    reason: str = ""


# ---------------------------------------------------------------- MAC

def tag(key: tuple[list[int], int], ctx: int, y: list[int]) -> int:
    alpha, beta = key
    msg = [ctx] + list(y)
    acc = beta
    for a, m in zip(alpha, msg):
        acc = F.add(acc, F.mul(a, m))
    return acc


def fresh_key(limbs: int) -> tuple[list[int], int]:
    return [F.rand() for _ in range(limbs + 1)], F.rand()


# ---------------------------------------------------------------- dealing

def _issue(header: Header, ys: dict[int, list[int]]):
    """Issue fresh one-time witness keys and tags for share vectors ys (index -> limbs)."""
    shares = {i: Share(i, ys[i], {}) for i in ys}
    rings = {j: KeyRing(j, {}) for j in ys}
    for j in ys:
        for i in ys:
            if i == j:
                continue
            k = fresh_key(header.limbs)
            rings[j].keys[i] = k
            shares[i].tags[j] = tag(k, context(header.sid, header.epoch, i), ys[i])
    return [shares[i] for i in sorted(shares)], [rings[j] for j in sorted(rings)]


def deal(secret: bytes, n: int, t: int, epoch: int = 0, sid: int | None = None):
    """Split `secret` into n shares; any t reconstruct it, any t-1 learn nothing."""
    if not (2 <= t <= n) or n < 3 or n >= 2**16:
        raise ValueError("need 2 <= t <= n, n >= 3")
    s = bytes_to_limbs(secret)
    header = Header(n=n, t=t, limbs=len(s), length=len(secret),
                    sid=secrets.randbits(53) if sid is None else sid, epoch=epoch)
    # coefficient matrix: column l is (s_l, r_1, ..., r_{t-1})
    coeffs = [[s_l] + [F.rand() for _ in range(t - 1)] for s_l in s]
    ys = {i: [peval(c, i) for c in coeffs] for i in range(1, n + 1)}
    shares, rings = _issue(header, ys)
    return header, shares, rings


def refresh(header: Header, shares: list[Share]):
    """Proactive refresh: add a sharing of 0 and re-issue keys/tags under epoch+1.

    Old shares remain valid for the old epoch only; their tags cannot verify under the
    new keys, so a share stolen before the refresh is rejected after it.
    """
    new = Header(header.n, header.t, header.limbs, header.length, header.sid, header.epoch + 1)
    zero = [[0] + [F.rand() for _ in range(header.t - 1)] for _ in range(header.limbs)]
    ys = {sh.i: [F.add(sh.y[l], peval(zero[l], sh.i)) for l in range(header.limbs)] for sh in shares}
    s2, r2 = _issue(new, ys)
    return new, s2, r2


# ---------------------------------------------------------------- validation

def _well_formed(header: Header, sh: Share) -> bool:
    return (isinstance(sh.i, int) and 1 <= sh.i <= header.n and len(sh.y) == header.limbs
            and all(isinstance(v, int) and 0 <= v < F.P for v in sh.y))


def lagrange_at_zero(xs: list[int]) -> list[int]:
    lam = []
    for i, xi in enumerate(xs):
        num, den = 1, 1
        for j, xj in enumerate(xs):
            if i != j:
                num = F.mul(num, xj)
                den = F.mul(den, F.sub(xj, xi))
        lam.append(F.mul(num, F.inv(den)))
    return lam


def syndrome(xs: list[int], ys: list[int], t: int) -> list[int]:
    """S_k = sum_i v_i x_i^k y_i for k < m - t, with v_i = 1 / prod_{j != i}(x_i - x_j).

    All S_k = 0 iff the points lie on one polynomial of degree < t (parity check of the
    generalised Reed-Solomon code generated by the Vandermonde matrix).
    """
    m = len(xs)
    v = []
    for i, xi in enumerate(xs):
        d = 1
        for j, xj in enumerate(xs):
            if i != j:
                d = F.mul(d, F.sub(xi, xj))
        v.append(F.inv(d))
    out = []
    for k in range(m - t):
        acc = 0
        for xi, vi, yi in zip(xs, v, ys):
            acc = F.add(acc, F.mul(vi, F.mul(F.pow_(xi, k), yi)))
        out.append(acc)
    return out


def verify_votes(header: Header, shares: dict[int, Share], rings: dict[int, KeyRing]):
    votes = {}
    for i, sh in shares.items():
        ctx = context(header.sid, header.epoch, i)
        c = 0
        for j, ring in rings.items():
            if j == i or i not in ring.keys or j not in sh.tags:
                continue
            ok = secrets.compare_digest(
                tag(ring.keys[i], ctx, sh.y).to_bytes(16, "big"),
                int(sh.tags[j] % 2**128).to_bytes(16, "big"))
            c += ok
        votes[i] = c
    return votes


def reconstruct(header: Header, round1: list[Share], round2: list[KeyRing]) -> Result:
    """Two-round reconstruction. Round 1 (shares + tags) must be fixed before round 2 (keys)."""
    res = Result(secret=None)
    cands: dict[int, list[Share]] = {}
    for sh in round1:
        if not _well_formed(header, sh):
            res.rejected.append(getattr(sh, "i", -1))
            continue
        cands.setdefault(sh.i, []).append(sh)
    rings = {r.j: r for r in round2 if 1 <= r.j <= header.n}
    # Several submissions under one index (e.g. a cheater racing an honest custodian):
    # keep the candidate with the most witness confirmations, so the honest share survives.
    shares: dict[int, Share] = {}
    for i, lst in cands.items():
        shares[i] = lst[0] if len(lst) == 1 else max(
            lst, key=lambda c: verify_votes(header, {i: c}, rings)[i])

    res.votes = verify_votes(header, shares, rings)
    acc = sorted(i for i, v in res.votes.items() if v >= header.vouch)
    res.rejected += sorted(i for i, v in res.votes.items() if v < header.vouch)
    if len(acc) < header.t:
        res.mode, res.reason = "fail-closed", f"only {len(acc)} valid shares, need {header.t}"
        return res

    xs = acc
    clean = all(not any(syndrome(xs, [shares[i].y[l] for i in xs], header.t))
                for l in range(header.limbs))
    if clean:
        lam = lagrange_at_zero(xs[:header.t])
        limbs = [sum_mod(lam, [shares[i].y[l] for i in xs[:header.t]]) for l in range(header.limbs)]
        res.accepted, res.mode = acc, "witness-verified, syndrome-clean"
        return _finish(res, limbs, header)

    # Residual inconsistency (bad dealer, or a forgery that beat the tags): decode.
    limbs, located = [], set()
    for l in range(header.limbs):
        f, errs = gao_decode(xs, [shares[i].y[l] for i in xs], header.t)
        if f is None:
            res.mode, res.reason = "fail-closed", "syndrome non-zero and decoding failed"
            return res
        limbs.append(f[0] if f else 0)
        located.update(xs[e] for e in errs)
    res.located = sorted(located)
    res.accepted = [i for i in acc if i not in located]
    if len(res.accepted) < header.t:
        res.mode, res.reason = "fail-closed", "too few consistent shares after decoding"
        return res
    res.mode = "witness-verified, syndrome-corrected"
    return _finish(res, limbs, header)


def reconstruct_keyless(header: Header, round1: list[Share]) -> Result:
    """Second, independent mechanism: no keys at all, Reed-Solomon decoding over all shares."""
    res = Result(secret=None)
    shares = {sh.i: sh for sh in round1 if _well_formed(header, sh)}
    xs = sorted(shares)
    if len(xs) < header.t:
        res.mode, res.reason = "fail-closed", "fewer than t shares"
        return res
    limbs, located = [], set()
    for l in range(header.limbs):
        f, errs = gao_decode(xs, [shares[i].y[l] for i in xs], header.t)
        if f is None:
            res.mode, res.reason = "fail-closed", "decoding failed (too many bad shares)"
            return res
        limbs.append(f[0] if f else 0)
        located.update(xs[e] for e in errs)
    res.located = sorted(located)
    res.accepted = [i for i in xs if i not in located]
    res.mode = "keyless Reed-Solomon"
    return _finish(res, limbs, header)


def _finish(res: Result, limbs: list[int], header: Header) -> Result:
    res.secret = limbs_to_bytes(limbs, header.length)
    if res.secret is None:
        res.mode, res.reason = "fail-closed", "reconstructed value outside the key encoding (corruption)"
    return res


def sum_mod(lam: list[int], ys: list[int]) -> int:
    acc = 0
    for a, b in zip(lam, ys):
        acc = F.add(acc, F.mul(a, b))
    return acc
