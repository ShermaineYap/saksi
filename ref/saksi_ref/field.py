"""Arithmetic in the Mersenne prime field F_p, p = 2^127 - 1.

Reference implementation: clear and checkable, NOT constant time
(Python integers are variable-time). The Rust core in ../../core is the
constant-time implementation; this module is the specification and test oracle.
"""
from __future__ import annotations

import secrets

P = (1 << 127) - 1          # Mersenne prime M127
BITS = 127


def reduce(x: int) -> int:
    """Reduce a non-negative integer < 2^254 modulo p using 2^127 = 1 (mod p)."""
    x = (x & P) + (x >> 127)
    x = (x & P) + (x >> 127)
    return 0 if x == P else x


def add(a: int, b: int) -> int:
    return reduce(a + b)


def sub(a: int, b: int) -> int:
    return reduce(a + (P - b))


def mul(a: int, b: int) -> int:
    return reduce(a * b)


def neg(a: int) -> int:
    return 0 if a == 0 else P - a


def pow_(a: int, e: int) -> int:
    r = 1
    base = a
    while e:
        if e & 1:
            r = mul(r, base)
        base = mul(base, base)
        e >>= 1
    return r


def inv(a: int) -> int:
    """Multiplicative inverse by Fermat's little theorem: a^(p-2)."""
    if a % P == 0:
        raise ZeroDivisionError("0 has no inverse in F_p")
    return pow_(a, P - 2)


def rand() -> int:
    """Uniform element of F_p from the OS CSPRNG (rejection sampling)."""
    while True:
        x = secrets.randbits(127)
        if x != P:
            return x


def rand_nonzero() -> int:
    while True:
        x = rand()
        if x:
            return x
