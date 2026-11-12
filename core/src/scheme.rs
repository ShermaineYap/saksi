//! The SAKSI scheme: Share, Witness, two-round Reveal, Syndrome check, Reconstruct.
//! Mirrors `ref/saksi_ref/scheme.py` exactly; cross-checked by `tests/cross.rs`.

use crate::field::{lagrange_at_zero, Fe};
use crate::poly::{eval, gao_decode};
use serde::{Deserialize, Serialize};
use zeroize::{Zeroize, ZeroizeOnDrop};

pub const LIMB_BYTES: usize = 15;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct Header {
    pub n: u16,
    pub t: u16,
    pub limbs: u16,
    pub length: u32,
    pub sid: u64,
    pub epoch: u32,
}

impl Header {
    /// Confirmations a share needs from *other* key holders: floor((n - 1) / 2).
    pub fn vouch(&self) -> usize {
        (self.n as usize - 1) / 2
    }
}

/// Share i: limb values and the tags tau_{j,i} that verifier j can check.
#[derive(Clone, Debug, Zeroize, ZeroizeOnDrop)]
pub struct Share {
    pub i: u16,
    pub y: Vec<Fe>,
    pub tags: Vec<(u16, Fe)>,
}

/// One-time witness key (alpha_0..alpha_L, beta).
#[derive(Clone, Debug, Zeroize, ZeroizeOnDrop)]
pub struct WitnessKey {
    pub alpha: Vec<Fe>,
    pub beta: Fe,
}

/// Key ring of holder j: keys used to check every other share i.
#[derive(Clone, Debug, Zeroize, ZeroizeOnDrop)]
pub struct KeyRing {
    pub j: u16,
    pub keys: Vec<(u16, WitnessKey)>,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Outcome {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub secret_hex: Option<String>,
    pub accepted: Vec<u16>,
    pub rejected: Vec<u16>,
    pub located: Vec<u16>,
    pub votes: Vec<(u16, usize)>,
    pub mode: String,
    pub reason: String,
    #[serde(skip)]
    pub secret: Option<Vec<u8>>,
}

#[derive(Debug, PartialEq, Eq)]
pub enum Error {
    BadParams,
    EmptySecret,
}

pub fn bytes_to_limbs(data: &[u8]) -> Vec<Fe> {
    data.chunks(LIMB_BYTES)
        .map(|c| {
            let mut buf = [0u8; 16];
            buf[1..1 + c.len()].copy_from_slice(c);
            let v = u128::from_be_bytes(buf);
            buf.zeroize();
            Fe::from_u128(v)
        })
        .collect()
}

/// Inverse of `bytes_to_limbs`. `None` if a limb exceeds the 120-bit encoding range or the
/// zero padding is non-zero: an honest reconstruction never yields that, so it proves
/// corruption and the caller fails closed.
pub fn limbs_to_bytes(limbs: &[Fe], length: usize) -> Option<Vec<u8>> {
    let mut out = Vec::with_capacity(limbs.len() * LIMB_BYTES);
    let mut bad = 0u128;
    for l in limbs {
        bad |= l.value() >> (8 * LIMB_BYTES);
        out.extend_from_slice(&l.value().to_be_bytes()[1..]);
    }
    let pad = out[length.min(out.len())..].iter().fold(0u8, |a, b| a | b);
    out.truncate(length);
    if bad != 0 || pad != 0 {
        out.zeroize();
        return None;
    }
    Some(out)
}

fn finish(mut out: Outcome, limbs: &[Fe], h: &Header) -> Outcome {
    match limbs_to_bytes(limbs, h.length as usize) {
        Some(b) => {
            out.ok = true;
            out.secret = Some(b);
        }
        None => {
            out.ok = false;
            out.mode = "fail-closed".into();
            out.reason = "reconstructed value outside the key encoding (corruption)".into();
        }
    }
    out
}

/// Public per-share context bound into every tag: session id | epoch << 64 | index << 96.
pub fn context(h: &Header, i: u16) -> Fe {
    Fe::from_u128((h.sid as u128) | ((h.epoch as u128) << 64) | ((i as u128) << 96))
}

/// tau = beta + alpha_0 * ctx + sum_l alpha_{l+1} * y_l
pub fn tag(key: &WitnessKey, ctx: Fe, y: &[Fe]) -> Fe {
    let mut acc = key.beta.add(key.alpha[0].mul(ctx));
    for (a, m) in key.alpha[1..].iter().zip(y) {
        acc = acc.add(a.mul(*m));
    }
    acc
}

fn fresh_key(limbs: usize) -> WitnessKey {
    WitnessKey { alpha: (0..=limbs).map(|_| Fe::random()).collect(), beta: Fe::random() }
}

fn issue(h: &Header, ys: Vec<(u16, Vec<Fe>)>) -> (Vec<Share>, Vec<KeyRing>) {
    let mut shares: Vec<Share> =
        ys.iter().map(|(i, y)| Share { i: *i, y: y.clone(), tags: vec![] }).collect();
    let mut rings: Vec<KeyRing> = ys.iter().map(|(j, _)| KeyRing { j: *j, keys: vec![] }).collect();
    for ring in rings.iter_mut() {
        for sh in shares.iter_mut() {
            if sh.i == ring.j {
                continue;
            }
            let k = fresh_key(h.limbs as usize);
            sh.tags.push((ring.j, tag(&k, context(h, sh.i), &sh.y)));
            ring.keys.push((sh.i, k));
        }
    }
    (shares, rings)
}

/// Split `secret` into n shares with threshold t.
pub fn deal(secret: &[u8], n: u16, t: u16, epoch: u32) -> Result<(Header, Vec<Share>, Vec<KeyRing>), Error> {
    if !(2 <= t && t <= n && n >= 3) {
        return Err(Error::BadParams);
    }
    if secret.is_empty() {
        return Err(Error::EmptySecret);
    }
    let mut s = bytes_to_limbs(secret);
    let mut sid = [0u8; 8];
    getrandom::getrandom(&mut sid).expect("OS randomness unavailable");
    let h = Header {
        n,
        t,
        limbs: s.len() as u16,
        length: secret.len() as u32,
        sid: u64::from_be_bytes(sid) & ((1u64 << 53) - 1), // 53 bits: exact in JSON/JavaScript numbers
        epoch,
    };
    let mut coeffs: Vec<Vec<Fe>> = s
        .iter()
        .map(|&sl| {
            let mut c = vec![sl];
            c.extend((1..t).map(|_| Fe::random()));
            c
        })
        .collect();
    let ys: Vec<(u16, Vec<Fe>)> = (1..=n)
        .map(|i| (i, coeffs.iter().map(|c| eval(c, Fe::from_u128(i as u128))).collect()))
        .collect();
    coeffs.zeroize();
    s.zeroize();
    let (shares, rings) = issue(&h, ys);
    Ok((h, shares, rings))
}

/// Proactive refresh: add a fresh sharing of zero, re-issue keys and tags under epoch + 1.
pub fn refresh(h: &Header, shares: &[Share]) -> (Header, Vec<Share>, Vec<KeyRing>) {
    let nh = Header { epoch: h.epoch + 1, ..h.clone() };
    let mut zero: Vec<Vec<Fe>> = (0..h.limbs)
        .map(|_| {
            let mut c = vec![Fe::ZERO];
            c.extend((1..h.t).map(|_| Fe::random()));
            c
        })
        .collect();
    let ys = shares
        .iter()
        .map(|sh| {
            let x = Fe::from_u128(sh.i as u128);
            (sh.i, sh.y.iter().zip(&zero).map(|(y, z)| y.add(eval(z, x))).collect())
        })
        .collect();
    zero.zeroize();
    let (s, r) = issue(&nh, ys);
    (nh, s, r)
}

fn well_formed(h: &Header, sh: &Share) -> bool {
    sh.i >= 1 && sh.i <= h.n && sh.y.len() == h.limbs as usize
}

/// Parity-check syndrome of the GRS code: S_k = sum_i v_i x_i^k y_i, k < m - t.
pub fn syndrome(xs: &[Fe], ys: &[Fe], t: usize) -> Vec<Fe> {
    let m = xs.len();
    let v: Vec<Fe> = xs
        .iter()
        .enumerate()
        .map(|(i, &xi)| {
            let mut d = Fe::ONE;
            for (j, &xj) in xs.iter().enumerate() {
                if i != j {
                    d = d.mul(xi.sub(xj));
                }
            }
            d.inv()
        })
        .collect();
    (0..m.saturating_sub(t))
        .map(|k| {
            let mut acc = Fe::ZERO;
            for ((&x, &vi), &y) in xs.iter().zip(&v).zip(ys) {
                let mut xp = Fe::ONE;
                for _ in 0..k {
                    xp = xp.mul(x);
                }
                acc = acc.add(vi.mul(xp).mul(y));
            }
            acc
        })
        .collect()
}

/// Count, for each share, how many other holders' keys confirm its tag.
/// Tag comparison is constant time; the count itself is public (it names cheaters).
pub fn votes(h: &Header, shares: &[&Share], rings: &[KeyRing]) -> Vec<(u16, usize)> {
    shares
        .iter()
        .map(|sh| {
            let ctx = context(h, sh.i);
            let mut c = 0usize;
            for ring in rings {
                if ring.j == sh.i {
                    continue;
                }
                let key = ring.keys.iter().find(|(i, _)| *i == sh.i).map(|(_, k)| k);
                let tg = sh.tags.iter().find(|(j, _)| *j == ring.j).map(|(_, t)| *t);
                if let (Some(k), Some(tg)) = (key, tg) {
                    if k.alpha.len() == h.limbs as usize + 1 {
                        c += tag(k, ctx, &sh.y).ct_eq(tg) as usize;
                    }
                }
            }
            (sh.i, c)
        })
        .collect()
}

fn decode_all(h: &Header, xs_idx: &[u16], shares: &[&Share]) -> Option<(Vec<Fe>, Vec<u16>)> {
    let xs: Vec<Fe> = xs_idx.iter().map(|&i| Fe::from_u128(i as u128)).collect();
    let mut limbs = vec![];
    let mut located = std::collections::BTreeSet::new();
    for l in 0..h.limbs as usize {
        let ys: Vec<Fe> = shares.iter().map(|s| s.y[l]).collect();
        let (f, errs) = gao_decode(&xs, &ys, h.t as usize)?;
        limbs.push(f.first().copied().unwrap_or(Fe::ZERO));
        located.extend(errs.into_iter().map(|e| xs_idx[e]));
    }
    Some((limbs, located.into_iter().collect()))
}

/// Two-round reconstruction. `round1` (shares + tags) must be fixed before `round2` (keys).
pub fn reconstruct(h: &Header, round1: &[Share], round2: &[KeyRing]) -> Outcome {
    let mut out = Outcome::default();
    let rings: Vec<KeyRing> = round2.iter().filter(|r| r.j >= 1 && r.j <= h.n).cloned().collect();
    let mut cands: std::collections::BTreeMap<u16, Vec<&Share>> = Default::default();
    for sh in round1 {
        if well_formed(h, sh) {
            cands.entry(sh.i).or_default().push(sh);
        } else {
            out.rejected.push(sh.i);
        }
    }
    // Several submissions under one index (a cheater racing an honest custodian): keep the
    // candidate with the most witness confirmations, so the honest share survives.
    let shares: Vec<&Share> = cands
        .into_values()
        .map(|lst| {
            if lst.len() == 1 {
                lst[0]
            } else {
                let mut best = lst[0];
                let mut best_v = 0usize;
                for c in lst {
                    let v = votes(h, &[c], &rings)[0].1;
                    if v > best_v {
                        best = c;
                        best_v = v;
                    }
                }
                best
            }
        })
        .collect();
    out.votes = votes(h, &shares, &rings);
    let acc: Vec<&Share> = shares
        .iter()
        .zip(&out.votes)
        .filter(|(_, (_, v))| *v >= h.vouch())
        .map(|(s, _)| *s)
        .collect();
    out.rejected
        .extend(out.votes.iter().filter(|(_, v)| *v < h.vouch()).map(|(i, _)| *i));
    out.rejected.sort();
    let t = h.t as usize;
    if acc.len() < t {
        out.mode = "fail-closed".into();
        out.reason = format!("only {} valid shares, need {}", acc.len(), t);
        return out;
    }
    let idx: Vec<u16> = acc.iter().map(|s| s.i).collect();
    let xs: Vec<Fe> = idx.iter().map(|&i| Fe::from_u128(i as u128)).collect();
    let clean = (0..h.limbs as usize).all(|l| {
        let ys: Vec<Fe> = acc.iter().map(|s| s.y[l]).collect();
        syndrome(&xs, &ys, t).iter().all(|s| s.ct_is_zero())
    });
    let mut limbs;
    if clean {
        let lam = lagrange_at_zero(&xs[..t]);
        limbs = (0..h.limbs as usize)
            .map(|l| {
                let mut a = Fe::ZERO;
                for (li, s) in lam.iter().zip(&acc[..t]) {
                    a = a.add(li.mul(s.y[l]));
                }
                a
            })
            .collect::<Vec<Fe>>();
        out.accepted = idx;
        out.mode = "witness-verified, syndrome-clean".into();
    } else {
        match decode_all(h, &idx, &acc) {
            None => {
                out.mode = "fail-closed".into();
                out.reason = "syndrome non-zero and decoding failed".into();
                return out;
            }
            Some((l, located)) => {
                out.accepted = idx.iter().copied().filter(|i| !located.contains(i)).collect();
                out.located = located;
                if out.accepted.len() < t {
                    out.mode = "fail-closed".into();
                    out.reason = "too few consistent shares after decoding".into();
                    return out;
                }
                limbs = l;
                out.mode = "witness-verified, syndrome-corrected".into();
            }
        }
    }
    let out = finish(out, &limbs, h);
    limbs.zeroize();
    out
}

/// Independent second mechanism: no keys, Reed-Solomon decoding over all shares.
pub fn reconstruct_keyless(h: &Header, round1: &[Share]) -> Outcome {
    let mut out = Outcome::default();
    let mut shares: Vec<&Share> = round1.iter().filter(|s| well_formed(h, s)).collect();
    shares.sort_by_key(|s| s.i);
    shares.dedup_by_key(|s| s.i);
    if shares.len() < h.t as usize {
        out.mode = "fail-closed".into();
        out.reason = "fewer than t shares".into();
        return out;
    }
    let idx: Vec<u16> = shares.iter().map(|s| s.i).collect();
    match decode_all(h, &idx, &shares) {
        None => {
            out.mode = "fail-closed".into();
            out.reason = "decoding failed (too many bad shares)".into();
        }
        Some((mut limbs, located)) => {
            out.accepted = idx.iter().copied().filter(|i| !located.contains(i)).collect();
            out.located = located;
            out.mode = "keyless Reed-Solomon".into();
            let o = finish(out, &limbs, h);
            limbs.zeroize();
            return o;
        }
    }
    out
}

/// Plain Shamir (no validation) — used only as the control in the attack lab.
pub fn plain_shamir(h: &Header, round1: &[Share]) -> Option<Vec<u8>> {
    let sh: Vec<&Share> = round1.iter().filter(|s| well_formed(h, s)).take(h.t as usize).collect();
    if sh.len() < h.t as usize {
        return None;
    }
    let xs: Vec<Fe> = sh.iter().map(|s| Fe::from_u128(s.i as u128)).collect();
    let lam = lagrange_at_zero(&xs);
    let limbs: Vec<Fe> = (0..h.limbs as usize)
        .map(|l| {
            let mut a = Fe::ZERO;
            for (li, s) in lam.iter().zip(&sh) {
                a = a.add(li.mul(s.y[l]));
            }
            a
        })
        .collect();
    // control: report whatever interpolation yields, even if out of range
    let mut v = Vec::new();
    for l in &limbs {
        v.extend_from_slice(&l.value().to_be_bytes()[1..]);
    }
    v.truncate(h.length as usize);
    Some(v)
}

/// Per-pair witness results for display: (verifier j, share i, tag confirmed?).
/// Cells where j has no key for i, or i carries no tag for j, are omitted.
pub fn witness_matrix(h: &Header, round1: &[Share], round2: &[KeyRing]) -> Vec<(u16, u16, bool)> {
    let mut out = vec![];
    for sh in round1.iter().filter(|s| well_formed(h, s)) {
        let ctx = context(h, sh.i);
        for ring in round2 {
            if ring.j == sh.i {
                continue;
            }
            let key = ring.keys.iter().find(|(i, _)| *i == sh.i).map(|(_, k)| k);
            let tg = sh.tags.iter().find(|(j, _)| *j == ring.j).map(|(_, t)| *t);
            if let (Some(k), Some(tg)) = (key, tg) {
                if k.alpha.len() == h.limbs as usize + 1 {
                    out.push((ring.j, sh.i, tag(k, ctx, &sh.y).ct_eq(tg)));
                }
            }
        }
    }
    out
}

/// Syndrome of the accepted shares for each limb, as booleans "all zero?" (display only).
pub fn syndrome_clean(h: &Header, round1: &[Share], accepted: &[u16]) -> Vec<bool> {
    let acc: Vec<&Share> = accepted.iter().filter_map(|i| round1.iter().find(|s| s.i == *i)).collect();
    let xs: Vec<Fe> = acc.iter().map(|s| Fe::from_u128(s.i as u128)).collect();
    (0..h.limbs as usize)
        .map(|l| {
            let ys: Vec<Fe> = acc.iter().map(|s| s.y[l]).collect();
            syndrome(&xs, &ys, h.t as usize).iter().all(|s| s.ct_is_zero())
        })
        .collect()
}
