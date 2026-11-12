"""Cross-implementation check: Python deals -> Rust reconstructs, Rust deals -> Python reconstructs.

Usage: python3 attacks/cross_check.py [rounds]
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ref"))
from saksi_ref.scheme import deal, reconstruct  # noqa: E402
from saksi_ref.wire import from_bundle, to_bundle  # noqa: E402

BIN = ROOT / "core" / "target" / "release" / "saksi"


def main(rounds: int = 25):
    ok = 0
    for k in range(rounds):
        n, t = [(3, 2), (5, 3), (7, 4)][k % 3]
        secret = os.urandom(1 + k * 7)
        # Python -> Rust
        h, s, r = deal(secret, n, t)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(to_bundle(h, s, r), f)
        out = json.loads(subprocess.check_output([str(BIN), "reconstruct", f.name]))
        os.unlink(f.name)
        assert out["ok"] and out["secret_hex"] == secret.hex(), out
        # Rust -> Python
        b = json.loads(subprocess.check_output([str(BIN), "deal", "--n", str(n), "--t", str(t), "--hex", secret.hex()]))
        h2, s2, r2 = from_bundle(b)
        res = reconstruct(h2, s2, r2)
        assert res.secret == secret, res
        ok += 1
    print(json.dumps({"cross_check_rounds": ok, "status": "pass"}))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 25)
