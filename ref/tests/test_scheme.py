import copy
import itertools
import os
import random as _testrng  # test-only shuffling, never used for key material

import pytest

from saksi_ref import field as F
from saksi_ref import poly
from saksi_ref.scheme import (deal, reconstruct, reconstruct_keyless, refresh, syndrome,
                              bytes_to_limbs, limbs_to_bytes)

KEY = bytes.fromhex("00112233445566778899aabbccddeeff0123456789abcdeffedcba9876543210")


def test_field_basics():
    for _ in range(200):
        a, b = F.rand(), F.rand_nonzero()
        assert F.mul(a, F.inv(b)) * 1 == F.mul(a, F.inv(b))
        assert F.mul(F.mul(a, F.inv(b)), b) == a
        assert F.add(F.sub(a, b), b) == a
        assert F.mul(a, b) == (a * b) % F.P
    assert F.reduce(F.P) == 0 and F.reduce(2 * F.P) == 0


def test_encoding_roundtrip_utf8():
    for msg in [b"x", KEY, "kunci rahsia 密钥 \U0001F511".encode(), os.urandom(100)]:
        assert limbs_to_bytes(bytes_to_limbs(msg), len(msg)) == msg


@pytest.mark.parametrize("n,t", [(3, 2), (5, 3), (7, 4), (9, 5)])
def test_any_t_subset_reconstructs(n, t):
    h, shares, rings = deal(KEY, n, t)
    for subset in itertools.combinations(range(n), t):
        r = reconstruct(h, [shares[i] for i in subset], rings)
        assert r.secret == KEY, (subset, r)
    r = reconstruct(h, shares, rings)
    assert r.secret == KEY and r.rejected == [] and r.mode.startswith("witness")


def test_fail_closed_below_threshold():
    h, shares, rings = deal(KEY, 5, 3)
    r = reconstruct(h, shares[:2], rings)
    assert r.secret is None and r.mode == "fail-closed"


def test_forged_share_is_named():
    h, shares, rings = deal(KEY, 5, 3)
    bad = copy.deepcopy(shares)
    bad[1].y[0] = F.add(bad[1].y[0], 1)
    r = reconstruct(h, bad, rings)
    assert r.secret == KEY and r.rejected == [2]


def test_two_cheaters_n5():
    h, shares, rings = deal(KEY, 5, 3)
    bad = copy.deepcopy(shares)
    bad[0].y = [F.rand() for _ in bad[0].y]
    bad[4].y[1] = F.rand()
    # cheaters also lie with their keys: publish random keys to try to vouch for each other
    rings2 = copy.deepcopy(rings)
    for j in (0, 4):
        for i in list(rings2[j].keys):
            rings2[j].keys[i] = ([F.rand() for _ in range(h.limbs + 1)], F.rand())
    r = reconstruct(h, bad, rings2)
    assert r.secret == KEY and set(r.rejected) == {1, 5}


def test_tompa_woll_last_submitter():
    """Cheater submits last with a share shifted so others would reconstruct garbage."""
    h, shares, rings = deal(KEY, 5, 3)
    bad = copy.deepcopy(shares[:3])
    # choose delta so Lagrange output changes by a chosen amount; tags were fixed in round 1
    bad[2].y = [F.add(v, 12345) for v in bad[2].y]
    r = reconstruct(h, bad + shares[3:], rings)
    assert r.secret == KEY and 3 in r.rejected


def test_replay_after_refresh_rejected():
    h, shares, rings = deal(KEY, 5, 3)
    h2, s2, r2 = refresh(h, shares)
    assert all(a.y != b.y for a, b in zip(shares, s2))
    mixed = [shares[0]] + s2[1:]         # attacker replays an epoch-0 share
    r = reconstruct(h2, mixed, r2)
    assert r.secret == KEY and r.rejected == [1]
    assert reconstruct(h2, s2, r2).secret == KEY


def test_bad_dealer_detected_by_syndrome():
    """Dealer hands out an inconsistent share but tags it honestly: syndrome catches it."""
    from saksi_ref.scheme import _issue
    h, shares, _ = deal(KEY, 5, 3)
    ys = {s.i: list(s.y) for s in shares}
    ys[4][0] = F.add(ys[4][0], 99)
    s2, r2 = _issue(h, ys)
    r = reconstruct(h, s2, r2)
    assert r.secret == KEY and r.located == [4] and "corrected" in r.mode


def test_keyless_reed_solomon():
    h, shares, _ = deal(KEY, 7, 3)
    bad = copy.deepcopy(shares)
    bad[2].y = [F.rand() for _ in bad[2].y]
    bad[5].y = [F.rand() for _ in bad[5].y]
    r = reconstruct_keyless(h, bad)
    assert r.secret == KEY and r.located == [3, 6]


def test_syndrome_zero_iff_consistent():
    h, shares, _ = deal(b"k", 6, 3)
    xs = [s.i for s in shares]
    ys = [s.y[0] for s in shares]
    assert not any(syndrome(xs, ys, 3))
    ys[2] = F.add(ys[2], 1)
    assert any(syndrome(xs, ys, 3))


def test_gao_random():
    for _ in range(20):
        k, m = 3, 9
        f = [F.rand() for _ in range(k)]
        xs = list(range(1, m + 1))
        ys = [poly.peval(f, x) for x in xs]
        bad = _testrng.sample(range(m), (m - k) // 2)
        for b in bad:
            ys[b] = F.rand()
        g, errs = poly.gao_decode(xs, ys, k)
        assert g == poly.trim(f) and sorted(errs) == sorted(bad)


def test_malformed_inputs():
    h, shares, rings = deal(KEY, 5, 3)
    bad = copy.deepcopy(shares)
    bad[0].y[0] = F.P            # out of field
    bad[1].i = 0                 # forbidden evaluation point
    r = reconstruct(h, bad, rings)
    assert r.secret == KEY and 1 not in r.accepted


def test_no_random_module_in_library():
    import pathlib
    src = pathlib.Path(__file__).parents[1] / "saksi_ref"
    for p in src.glob("*.py"):
        text = p.read_text()
        assert "import random" not in text, p


def test_duplicate_index_race_keeps_honest_share():
    """A cheater submits a forged share under custodian 2's index BEFORE the honest one."""
    h, shares, rings = deal(KEY, 5, 3)
    fake = copy.deepcopy(shares[1])
    fake.y = [F.rand() for _ in fake.y]
    r = reconstruct(h, [fake] + shares, rings)
    assert r.secret == KEY and 2 in r.accepted
    r = reconstruct(h, [fake] + shares[:1] + shares[2:3], rings)  # only 1, 3 and the fake 2
    assert r.secret is None  # fake under index 2 is not accepted; below threshold
