//! WebAssembly bindings (built with `--features wasm`). JSON in, JSON out.

use crate::scheme;
use crate::wire::{bundle, unbundle, Bundle};
use wasm_bindgen::prelude::*;

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn outcome_json(mut o: scheme::Outcome, errs: Vec<String>) -> String {
    if let Some(s) = o.secret.take() {
        o.secret_hex = Some(hex(&s));
    }
    if !errs.is_empty() {
        o.reason = format!("{} | input: {}", o.reason, errs.join("; "));
    }
    serde_json::to_string(&o).unwrap()
}

/// Split `secret` (raw bytes, e.g. UTF-8) into n shares with threshold t.
#[wasm_bindgen]
pub fn saksi_deal(secret: &[u8], n: u16, t: u16) -> Result<String, JsError> {
    let (h, s, r) = scheme::deal(secret, n, t, 0).map_err(|e| JsError::new(&format!("{e:?}")))?;
    Ok(serde_json::to_string(&bundle(&h, &s, &r)).unwrap())
}

#[wasm_bindgen]
pub fn saksi_reconstruct(bundle_json: &str) -> Result<String, JsError> {
    let b: Bundle = serde_json::from_str(bundle_json).map_err(|e| JsError::new(&e.to_string()))?;
    let (s, r, errs) = unbundle(&b);
    Ok(outcome_json(scheme::reconstruct(&b.header, &s, &r), errs))
}

#[wasm_bindgen]
pub fn saksi_reconstruct_keyless(bundle_json: &str) -> Result<String, JsError> {
    let b: Bundle = serde_json::from_str(bundle_json).map_err(|e| JsError::new(&e.to_string()))?;
    let (s, _, errs) = unbundle(&b);
    Ok(outcome_json(scheme::reconstruct_keyless(&b.header, &s), errs))
}

#[wasm_bindgen]
pub fn saksi_refresh(bundle_json: &str) -> Result<String, JsError> {
    let b: Bundle = serde_json::from_str(bundle_json).map_err(|e| JsError::new(&e.to_string()))?;
    let (s, _, _) = unbundle(&b);
    let (h, s2, r2) = scheme::refresh(&b.header, &s);
    Ok(serde_json::to_string(&bundle(&h, &s2, &r2)).unwrap())
}

/// Unvalidated Lagrange interpolation over the first t shares (attack-lab control only).
#[wasm_bindgen]
pub fn plain_shamir(bundle_json: &str) -> Result<String, JsError> {
    let b: Bundle = serde_json::from_str(bundle_json).map_err(|e| JsError::new(&e.to_string()))?;
    let (s, _, _) = unbundle(&b);
    Ok(scheme::plain_shamir(&b.header, &s).map(|x| hex(&x)).unwrap_or_default())
}

/// [[j, i, ok], ...] — which custodian's key confirmed which share's tag.
#[wasm_bindgen]
pub fn saksi_witness_matrix(bundle_json: &str) -> Result<String, JsError> {
    let b: Bundle = serde_json::from_str(bundle_json).map_err(|e| JsError::new(&e.to_string()))?;
    let (s, r, _) = unbundle(&b);
    Ok(serde_json::to_string(&scheme::witness_matrix(&b.header, &s, &r)).unwrap())
}
