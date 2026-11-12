"""JSON wire format identical to core/src/wire.rs (field elements as 32 hex digits)."""
from __future__ import annotations

from .scheme import Header, KeyRing, Share


def h(x: int) -> str:
    return f"{x:032x}"


def to_bundle(header: Header, shares: list[Share], rings: list[KeyRing] | None = None) -> dict:
    return {
        "header": {"n": header.n, "t": header.t, "limbs": header.limbs, "length": header.length,
                   "sid": header.sid, "epoch": header.epoch},
        "shares": [{"i": s.i, "y": [h(v) for v in s.y], "tags": [[j, h(t)] for j, t in sorted(s.tags.items())]}
                   for s in shares],
        "rings": [{"j": r.j, "keys": [[i, {"alpha": [h(a) for a in k[0]], "beta": h(k[1])}]
                                      for i, k in sorted(r.keys.items())]} for r in (rings or [])],
    }


def from_bundle(b: dict):
    hd = b["header"]
    header = Header(hd["n"], hd["t"], hd["limbs"], hd["length"], hd["sid"], hd["epoch"])
    shares = [Share(s["i"], [int(v, 16) for v in s["y"]], {j: int(t, 16) for j, t in s["tags"]})
              for s in b["shares"]]
    rings = [KeyRing(r["j"], {i: ([int(a, 16) for a in k["alpha"]], int(k["beta"], 16)) for i, k in r["keys"]})
             for r in b.get("rings", [])]
    return header, shares, rings
