//! # SAKSI — witness-validated secret sharing
//!
//! (t, n) secret sharing of a master key over GF(2^127 - 1) with perfect secrecy and two
//! independent, unconditional validation layers: one-time affine "witness" tags
//! (forgery probability 1/p per tag) and Reed-Solomon syndrome decoding.
//! No block cipher, hash function or computational assumption is used anywhere.

pub mod field;
pub mod poly;
pub mod scheme;
pub mod wire;

#[cfg(feature = "wasm")]
mod wasm;

pub use field::{Fe, P};
pub use scheme::{deal, reconstruct, reconstruct_keyless, refresh, Header, KeyRing, Outcome, Share};
