//! JSON wire format shared by the Rust core, the WASM build and the Python reference.
//! Field elements are 32-hex-digit strings; untrusted input is validated (canonical
//! field elements only, bounded sizes) before it reaches the scheme.

use crate::field::Fe;
use crate::scheme::{Header, KeyRing, Share, WitnessKey};
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Clone)]
pub struct WShare {
    pub i: u16,
    pub y: Vec<String>,
    pub tags: Vec<(u16, String)>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct WKey {
    pub alpha: Vec<String>,
    pub beta: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct WRing {
    pub j: u16,
    pub keys: Vec<(u16, WKey)>,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct Bundle {
    pub header: Header,
    pub shares: Vec<WShare>,
    #[serde(default)]
    pub rings: Vec<WRing>,
}

const MAX: usize = 4096;

fn fe(s: &str) -> Result<Fe, String> {
    Fe::from_hex(s).ok_or_else(|| format!("not a canonical field element: {s:.40}"))
}

pub fn share_from(w: &WShare) -> Result<Share, String> {
    if w.y.len() > MAX || w.tags.len() > MAX {
        return Err("share too large".into());
    }
    Ok(Share {
        i: w.i,
        y: w.y.iter().map(|s| fe(s)).collect::<Result<_, _>>()?,
        tags: w.tags.iter().map(|(j, s)| Ok((*j, fe(s)?))).collect::<Result<_, String>>()?,
    })
}

pub fn ring_from(w: &WRing) -> Result<KeyRing, String> {
    if w.keys.len() > MAX {
        return Err("ring too large".into());
    }
    Ok(KeyRing {
        j: w.j,
        keys: w
            .keys
            .iter()
            .map(|(i, k)| {
                if k.alpha.len() > MAX {
                    return Err("key too large".to_string());
                }
                Ok((*i, WitnessKey {
                    alpha: k.alpha.iter().map(|s| fe(s)).collect::<Result<_, _>>()?,
                    beta: fe(&k.beta)?,
                }))
            })
            .collect::<Result<_, String>>()?,
    })
}

pub fn share_to(s: &Share) -> WShare {
    WShare {
        i: s.i,
        y: s.y.iter().map(|f| f.to_hex()).collect(),
        tags: s.tags.iter().map(|(j, t)| (*j, t.to_hex())).collect(),
    }
}

pub fn ring_to(r: &KeyRing) -> WRing {
    WRing {
        j: r.j,
        keys: r
            .keys
            .iter()
            .map(|(i, k)| (*i, WKey { alpha: k.alpha.iter().map(|f| f.to_hex()).collect(), beta: k.beta.to_hex() }))
            .collect(),
    }
}

pub fn bundle(h: &Header, shares: &[Share], rings: &[KeyRing]) -> Bundle {
    Bundle { header: h.clone(), shares: shares.iter().map(share_to).collect(), rings: rings.iter().map(ring_to).collect() }
}

/// Parse a bundle; malformed individual shares are dropped (and reported) rather than
/// aborting, so one corrupted custodian cannot cause a denial of service.
pub fn unbundle(b: &Bundle) -> (Vec<Share>, Vec<KeyRing>, Vec<String>) {
    let mut errs = vec![];
    let shares = b
        .shares
        .iter()
        .filter_map(|w| share_from(w).map_err(|e| errs.push(format!("share {}: {e}", w.i))).ok())
        .collect();
    let rings = b
        .rings
        .iter()
        .filter_map(|w| ring_from(w).map_err(|e| errs.push(format!("ring {}: {e}", w.j))).ok())
        .collect();
    (shares, rings, errs)
}
