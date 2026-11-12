"""Polynomial arithmetic over F_p and Gao's Reed-Solomon decoder.

Polynomials are lists of coefficients, lowest degree first, with no trailing zeros
(the zero polynomial is []).
"""
from __future__ import annotations

from . import field as F


def trim(a: list[int]) -> list[int]:
    a = list(a)
    while a and a[-1] == 0:
        a.pop()
    return a


def deg(a: list[int]) -> int:
    return len(trim(a)) - 1  # deg(0) = -1


def padd(a, b):
    n = max(len(a), len(b))
    return trim([F.add(a[i] if i < len(a) else 0, b[i] if i < len(b) else 0) for i in range(n)])


def psub(a, b):
    n = max(len(a), len(b))
    return trim([F.sub(a[i] if i < len(a) else 0, b[i] if i < len(b) else 0) for i in range(n)])


def pmul(a, b):
    if not a or not b:
        return []
    out = [0] * (len(a) + len(b) - 1)
    for i, ai in enumerate(a):
        if ai == 0:
            continue
        for j, bj in enumerate(b):
            out[i + j] = F.add(out[i + j], F.mul(ai, bj))
    return trim(out)


def pdivmod(a, b):
    a, b = trim(a), trim(b)
    if not b:
        raise ZeroDivisionError("polynomial division by zero")
    q = [0] * max(0, len(a) - len(b) + 1)
    r = list(a)
    inv_lead = F.inv(b[-1])
    while len(r) >= len(b) and r:
        shift = len(r) - len(b)
        coef = F.mul(r[-1], inv_lead)
        q[shift] = coef
        for i, bi in enumerate(b):
            r[shift + i] = F.sub(r[shift + i], F.mul(coef, bi))
        r = trim(r)
    return trim(q), r


def peval(a, x):
    acc = 0
    for c in reversed(a):
        acc = F.add(F.mul(acc, x), c)
    return acc


def interpolate(xs, ys):
    """Lagrange interpolation: the unique polynomial of degree < len(xs) through the points."""
    result = []
    for i, (xi, yi) in enumerate(zip(xs, ys)):
        num = [1]
        den = 1
        for j, xj in enumerate(xs):
            if j == i:
                continue
            num = pmul(num, [F.neg(xj), 1])
            den = F.mul(den, F.sub(xi, xj))
        result = padd(result, [F.mul(c, F.mul(yi, F.inv(den))) for c in num])
    return result


def gao_decode(xs, ys, k):
    """Gao (2002) decoder for Reed-Solomon codes.

    Given m points, find the polynomial f of degree < k that agrees with all but at most
    floor((m - k) / 2) of them. Returns (f, error_indices) or (None, None) on failure.
    """
    m = len(xs)
    if m < k:
        return None, None
    g0 = [1]
    for x in xs:
        g0 = pmul(g0, [F.neg(x), 1])
    g1 = interpolate(xs, ys)
    # Partial extended Euclid on (g0, g1): stop when deg(r) < (m + k) / 2.
    r0, r1 = g0, g1
    v0, v1 = [], [1]
    while deg(r1) >= (m + k) / 2:
        q, r = pdivmod(r0, r1)
        r0, r1 = r1, r
        v0, v1 = v1, psub(v0, pmul(q, v1))
    g, v = r1, v1
    if not v:
        return None, None
    f, rem = pdivmod(g, v)
    if rem or deg(f) >= k:
        return None, None
    errors = [i for i, (x, y) in enumerate(zip(xs, ys)) if peval(f, x) != y]
    if len(errors) > (m - k) // 2:
        return None, None
    return f, errors
