//! Constant-time arithmetic in the Mersenne prime field F_p, p = 2^127 - 1.
//!
//! Every operation on secret values is branch-free and free of secret-indexed memory
//! access: reductions use the identity 2^127 = 1 (mod p) followed by a masked conditional
//! subtraction, multiplication uses four fixed 64x64 -> 128-bit products, and inversion
//! is a fixed-length square-and-multiply chain (exponent p - 2 is public) with masked
//! selection, so its instruction trace is identical for every input.

use core::hint::black_box;
use zeroize::Zeroize;

/// The field modulus, the Mersenne prime 2^127 - 1.
pub const P: u128 = (1u128 << 127) - 1;

/// A field element in canonical form (0 <= value < p).
#[derive(Clone, Copy, Default, Debug, Zeroize)]
pub struct Fe(pub(crate) u128);

/// All-ones mask if `bit == 1`, zero if `bit == 0`.
#[inline(always)]
fn mask(bit: u128) -> u128 {
    0u128.wrapping_sub(black_box(bit) & 1)
}

/// Map any x < 2^128 to its canonical representative mod p without branching.
#[inline(always)]
fn freeze(x: u128) -> u128 {
    let x = (x & P) + (x >> 127); // <= p + 1
    let (d, borrow) = x.overflowing_sub(P);
    let keep = mask(borrow as u128); // all ones iff x < p
    (x & keep) | (d & !keep)
}

impl Fe {
    pub const ZERO: Fe = Fe(0);
    pub const ONE: Fe = Fe(1);

    /// Reduce an arbitrary u128 into the field.
    #[inline]
    pub fn from_u128(x: u128) -> Fe {
        Fe(freeze(x))
    }

    /// Construct from a value that must already be canonical; `None` otherwise.
    /// Used to validate untrusted input (shares, tags, keys).
    pub fn from_canonical(x: u128) -> Option<Fe> {
        if x < P { Some(Fe(x)) } else { None }
    }

    #[inline]
    pub fn value(self) -> u128 {
        self.0
    }

    #[inline]
    pub fn add(self, o: Fe) -> Fe {
        Fe(freeze(self.0 + o.0))
    }

    #[inline]
    pub fn sub(self, o: Fe) -> Fe {
        Fe(freeze(self.0 + (P - o.0)))
    }

    #[inline]
    pub fn neg(self) -> Fe {
        Fe(freeze(P - self.0))
    }

    /// Full 127x127 -> 254-bit product via four 64x64 multiplies, then 2^128 = 2 (mod p).
    #[inline]
    pub fn mul(self, o: Fe) -> Fe {
        let (a0, a1) = (self.0 as u64 as u128, self.0 >> 64);
        let (b0, b1) = (o.0 as u64 as u128, o.0 >> 64);
        let p00 = a0 * b0;
        let p01 = a0 * b1; // < 2^127
        let p10 = a1 * b0; // < 2^127
        let p11 = a1 * b1; // < 2^126
        let mid = p01 + p10; // < 2^128
        let (lo, c) = p00.overflowing_add(mid << 64);
        let hi = p11 + (mid >> 64) + (c as u128); // < 2^126
        // x = hi * 2^128 + lo  ==  2*hi + (lo mod 2^127) + (lo >> 127)   (mod p)
        let r = (hi << 1) + (lo & P) + (lo >> 127); // <= 2^128 - 2
        Fe(freeze(r))
    }

    #[inline]
    pub fn square(self) -> Fe {
        self.mul(self)
    }

    /// Inverse by Fermat: a^(p-2). Fixed 127-step ladder; always multiplies and selects
    /// with a mask, so timing does not depend on `self`. Returns 0 for 0.
    pub fn inv(self) -> Fe {
        const E: u128 = P - 2;
        let mut r = Fe::ONE;
        let mut i = 127;
        while i > 0 {
            i -= 1;
            r = r.square();
            let t = r.mul(self);
            r = Fe::select(((E >> i) & 1) == 1, t, r);
        }
        r
    }

    /// Constant-time select: `a` if `c` else `b`.
    #[inline(always)]
    pub fn select(c: bool, a: Fe, b: Fe) -> Fe {
        let m = mask(c as u128);
        Fe((a.0 & m) | (b.0 & !m))
    }

    /// Constant-time equality.
    #[inline]
    pub fn ct_eq(self, o: Fe) -> bool {
        let x = black_box(self.0 ^ o.0);
        ((x | x.wrapping_neg()) >> 127) == 0
    }

    #[inline]
    pub fn ct_is_zero(self) -> bool {
        self.ct_eq(Fe::ZERO)
    }

    /// Uniform element from the OS CSPRNG (getrandom). Rejection only on the single
    /// value 2^127 - 1 (probability 2^-127); the loop condition depends on fresh
    /// randomness, never on secrets.
    pub fn random() -> Fe {
        loop {
            let mut buf = [0u8; 16];
            getrandom::getrandom(&mut buf).expect("OS randomness unavailable");
            let x = u128::from_be_bytes(buf) & P;
            buf.zeroize();
            if x != P {
                return Fe(x);
            }
        }
    }

    pub fn to_hex(self) -> String {
        format!("{:032x}", self.0)
    }

    pub fn from_hex(s: &str) -> Option<Fe> {
        if s.is_empty() || s.len() > 32 {
            return None;
        }
        u128::from_str_radix(s, 16).ok().and_then(Fe::from_canonical)
    }
}

/// Lagrange coefficients at x = 0 for distinct public points `xs`.
pub fn lagrange_at_zero(xs: &[Fe]) -> Vec<Fe> {
    xs.iter()
        .enumerate()
        .map(|(i, &xi)| {
            let mut num = Fe::ONE;
            let mut den = Fe::ONE;
            for (j, &xj) in xs.iter().enumerate() {
                if i != j {
                    num = num.mul(xj);
                    den = den.mul(xj.sub(xi));
                }
            }
            num.mul(den.inv())
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    fn big_mul(a: u128, b: u128) -> u128 {
        // reference via u128 limbs and schoolbook mod p with repeated folding
        let mut acc: u128 = 0;
        let mut x = a;
        let mut y = b;
        while y > 0 {
            if y & 1 == 1 {
                acc = (acc + x) % P;
            }
            x = (x << 1) % P;
            y >>= 1;
        }
        acc
    }

    #[test]
    fn edges() {
        assert_eq!(Fe::from_u128(P).0, 0);
        assert_eq!(Fe::from_u128(u128::MAX).0, 1);
        let m1 = Fe(P - 1);
        assert_eq!(m1.mul(m1).0, 1);
        assert_eq!(m1.add(Fe::ONE).0, 0);
        assert_eq!(Fe::ZERO.sub(Fe::ONE).0, P - 1);
        assert_eq!(Fe::ZERO.neg().0, 0);
        assert_eq!(Fe::ZERO.inv().0, 0);
        assert!(Fe(5).ct_eq(Fe(5)) && !Fe(5).ct_eq(Fe(6)));
    }

    proptest! {
        #[test]
        fn mul_matches_reference(a in 0..P, b in 0..P) {
            prop_assert_eq!(Fe(a).mul(Fe(b)).0, big_mul(a, b));
        }
        #[test]
        fn inverse(a in 1..P) {
            prop_assert_eq!(Fe(a).mul(Fe(a).inv()).0, 1);
        }
        #[test]
        fn add_sub(a in 0..P, b in 0..P) {
            prop_assert_eq!(Fe(a).add(Fe(b)).sub(Fe(b)).0, a);
            prop_assert_eq!(Fe(a).add(Fe(b)).0, ((a % P) + (b % P)) % P);
        }
    }
}
