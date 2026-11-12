//! Polynomials over F_p (lowest degree first) and Gao's Reed-Solomon decoder.
//!
//! Evaluation (used on secret coefficients when dealing) is a fixed Horner loop.
//! Division and the Euclidean algorithm branch on polynomial *degrees*; they are only
//! used on the error-correction path, whose outcome (which shares were bad) is public.

use crate::field::Fe;

pub type Poly = Vec<Fe>;

pub fn trim(mut a: Poly) -> Poly {
    while let Some(last) = a.last() {
        if last.value() == 0 {
            a.pop();
        } else {
            break;
        }
    }
    a
}

pub fn deg(a: &Poly) -> isize {
    let mut d = a.len() as isize - 1;
    while d >= 0 && a[d as usize].value() == 0 {
        d -= 1;
    }
    d
}

pub fn eval(a: &[Fe], x: Fe) -> Fe {
    let mut acc = Fe::ZERO;
    for c in a.iter().rev() {
        acc = acc.mul(x).add(*c);
    }
    acc
}

pub fn add(a: &Poly, b: &Poly) -> Poly {
    let n = a.len().max(b.len());
    trim((0..n)
        .map(|i| a.get(i).copied().unwrap_or_default().add(b.get(i).copied().unwrap_or_default()))
        .collect())
}

pub fn sub(a: &Poly, b: &Poly) -> Poly {
    let n = a.len().max(b.len());
    trim((0..n)
        .map(|i| a.get(i).copied().unwrap_or_default().sub(b.get(i).copied().unwrap_or_default()))
        .collect())
}

pub fn mul(a: &Poly, b: &Poly) -> Poly {
    if a.is_empty() || b.is_empty() {
        return vec![];
    }
    let mut out = vec![Fe::ZERO; a.len() + b.len() - 1];
    for (i, ai) in a.iter().enumerate() {
        for (j, bj) in b.iter().enumerate() {
            out[i + j] = out[i + j].add(ai.mul(*bj));
        }
    }
    trim(out)
}

pub fn divmod(a: &Poly, b: &Poly) -> Option<(Poly, Poly)> {
    let a = trim(a.clone());
    let b = trim(b.clone());
    if b.is_empty() {
        return None;
    }
    let mut r = a.clone();
    let mut q = vec![Fe::ZERO; a.len().saturating_sub(b.len()) + 1];
    let inv_lead = b[b.len() - 1].inv();
    while !r.is_empty() && r.len() >= b.len() {
        let shift = r.len() - b.len();
        let coef = r[r.len() - 1].mul(inv_lead);
        q[shift] = coef;
        for (i, bi) in b.iter().enumerate() {
            r[shift + i] = r[shift + i].sub(coef.mul(*bi));
        }
        r = trim(r);
    }
    Some((trim(q), r))
}

pub fn interpolate(xs: &[Fe], ys: &[Fe]) -> Poly {
    let mut result: Poly = vec![];
    for (i, (&xi, &yi)) in xs.iter().zip(ys).enumerate() {
        let mut num: Poly = vec![Fe::ONE];
        let mut den = Fe::ONE;
        for (j, &xj) in xs.iter().enumerate() {
            if i != j {
                num = mul(&num, &vec![xj.neg(), Fe::ONE]);
                den = den.mul(xi.sub(xj));
            }
        }
        let scale = yi.mul(den.inv());
        let term: Poly = num.iter().map(|c| c.mul(scale)).collect();
        result = add(&result, &term);
    }
    result
}

/// Gao (2002): returns (f, error positions) where deg f < k and f disagrees with at most
/// floor((m - k) / 2) of the m points; `None` if no such f exists (fail closed).
pub fn gao_decode(xs: &[Fe], ys: &[Fe], k: usize) -> Option<(Poly, Vec<usize>)> {
    let m = xs.len();
    if m < k || k == 0 {
        return None;
    }
    let mut g0: Poly = vec![Fe::ONE];
    for &x in xs {
        g0 = mul(&g0, &vec![x.neg(), Fe::ONE]);
    }
    let g1 = interpolate(xs, ys);
    let (mut r0, mut r1) = (g0, g1);
    let (mut v0, mut v1): (Poly, Poly) = (vec![], vec![Fe::ONE]);
    while 2 * deg(&r1) >= (m + k) as isize {
        let (q, r) = divmod(&r0, &r1)?;
        let v2 = sub(&v0, &mul(&q, &v1));
        r0 = r1;
        r1 = r;
        v0 = v1;
        v1 = v2;
    }
    if v1.is_empty() {
        return None;
    }
    let (f, rem) = divmod(&r1, &v1)?;
    if !rem.is_empty() || deg(&f) >= k as isize {
        return None;
    }
    let errors: Vec<usize> = xs
        .iter()
        .zip(ys)
        .enumerate()
        .filter(|(_, (x, y))| !eval(&f, **x).ct_eq(**y))
        .map(|(i, _)| i)
        .collect();
    if errors.len() > (m - k) / 2 {
        return None;
    }
    Some((f, errors))
}
