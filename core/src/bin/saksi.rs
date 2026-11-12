//! `saksi` command-line tool.
//!
//!   saksi deal --n 5 --t 3 (--hex <HEX> | --text <UTF8>)   > bundle.json
//!   saksi reconstruct bundle.json
//!   saksi keyless bundle.json
//!   saksi refresh bundle.json                               > bundle2.json
//!   saksi timing [--samples N]                              (dudect-style leakage test)
//!   saksi bench                                             (throughput)

use saksi_core::field::Fe;
use saksi_core::scheme;
use saksi_core::wire::{bundle, unbundle, Bundle};
use std::time::Instant;

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn unhex(s: &str) -> Vec<u8> {
    (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i + 2], 16).expect("bad hex")).collect()
}

fn arg(args: &[String], name: &str) -> Option<String> {
    args.iter().position(|a| a == name).and_then(|i| args.get(i + 1).cloned())
}

fn load(path: &str) -> Bundle {
    serde_json::from_str(&std::fs::read_to_string(path).expect("read")).expect("parse bundle")
}

fn print_outcome(mut o: scheme::Outcome, errs: Vec<String>) {
    if let Some(s) = o.secret.take() {
        o.secret_hex = Some(hex(&s));
    }
    if !errs.is_empty() {
        o.reason = format!("{} | input: {}", o.reason, errs.join("; "));
    }
    println!("{}", serde_json::to_string_pretty(&o).unwrap());
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("deal") => {
            let n: u16 = arg(&args, "--n").unwrap_or("5".into()).parse().unwrap();
            let t: u16 = arg(&args, "--t").unwrap_or("3".into()).parse().unwrap();
            let secret = match (arg(&args, "--hex"), arg(&args, "--text")) {
                (Some(h), _) => unhex(&h),
                (_, Some(t)) => t.into_bytes(),
                _ => {
                    let mut k = [0u8; 32];
                    getrandom::getrandom(&mut k).unwrap();
                    k.to_vec()
                }
            };
            let (h, s, r) = scheme::deal(&secret, n, t, 0).expect("bad parameters");
            println!("{}", serde_json::to_string_pretty(&bundle(&h, &s, &r)).unwrap());
        }
        Some("reconstruct") => {
            let b = load(&args[2]);
            let (s, r, e) = unbundle(&b);
            print_outcome(scheme::reconstruct(&b.header, &s, &r), e);
        }
        Some("keyless") => {
            let b = load(&args[2]);
            let (s, _, e) = unbundle(&b);
            print_outcome(scheme::reconstruct_keyless(&b.header, &s), e);
        }
        Some("refresh") => {
            let b = load(&args[2]);
            let (s, _, _) = unbundle(&b);
            let (h, s2, r2) = scheme::refresh(&b.header, &s);
            println!("{}", serde_json::to_string_pretty(&bundle(&h, &s2, &r2)).unwrap());
        }
        Some("timing") => timing(arg(&args, "--samples").map(|s| s.parse().unwrap()).unwrap_or(200_000)),
        Some("bench") => bench(),
        _ => eprintln!("usage: saksi deal|reconstruct|keyless|refresh|timing|bench (see source header)"),
    }
}

// ------------------------------------------------------------------ timing study

#[cfg(target_arch = "x86_64")]
#[inline(always)]
fn cycles() -> u64 {
    unsafe {
        core::arch::x86_64::_mm_lfence();
        let c = core::arch::x86_64::_rdtsc();
        core::arch::x86_64::_mm_lfence();
        c
    }
}
#[cfg(not(target_arch = "x86_64"))]
fn cycles() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos() as u64
}

/// Welch t-statistic after discarding the slowest 5% of each class (dudect cropping).
fn welch(a: &mut Vec<f64>, b: &mut Vec<f64>) -> (f64, f64, f64) {
    for v in [&mut *a, &mut *b] {
        v.sort_by(|x, y| x.partial_cmp(y).unwrap());
        let keep = (v.len() as f64 * 0.95) as usize;
        v.truncate(keep);
    }
    let stats = |v: &Vec<f64>| {
        let m = v.iter().sum::<f64>() / v.len() as f64;
        let var = v.iter().map(|x| (x - m).powi(2)).sum::<f64>() / (v.len() as f64 - 1.0);
        (m, var)
    };
    let (ma, va) = stats(a);
    let (mb, vb) = stats(b);
    ((ma - mb) / (va / a.len() as f64 + vb / b.len() as f64).sqrt(), ma, mb)
}

/// Deliberately leaky inverse (binary extended Euclid, data-dependent loop count):
/// POSITIVE CONTROL showing the test can detect a timing leak. Never used by the scheme.
fn leaky_inv(a: u128) -> u128 {
    let p = saksi_core::P as i128;
    let (mut t, mut nt, mut r, mut nr) = (0i128, 1i128, p, a as i128);
    while nr != 0 {
        let q = r / nr;
        (t, nt) = (nt, t - q * nt);
        (r, nr) = (nr, r - q * nr);
    }
    (if t < 0 { t + p } else { t }) as u128
}

/// Deliberately leaky tag comparison (early-exit byte compare): POSITIVE CONTROL.
fn leaky_eq(a: &[u8; 16], b: &[u8; 16]) -> bool {
    for i in 0..16 {
        if a[i] != b[i] {
            return false;
        }
    }
    true
}

/// dudect methodology: inputs for both classes are generated BEFORE measurement, classes
/// are interleaved in random order, and only the operation under test is timed.
fn run<I, G: FnMut(bool) -> I, F: FnMut(&I)>(name: &str, samples: usize, mut gen: G, mut f: F) -> String {
    let mut coin = vec![0u8; samples];
    getrandom::getrandom(&mut coin).unwrap();
    let classes: Vec<bool> = coin.iter().map(|c| c & 1 == 0).collect();
    let inputs: Vec<I> = classes.iter().map(|&c| gen(c)).collect();
    let (mut a, mut b) = (Vec::with_capacity(samples), Vec::with_capacity(samples));
    for (k, inp) in inputs.iter().enumerate() {
        let c0 = cycles();
        f(inp);
        let c1 = cycles();
        if classes[k] { a.push((c1 - c0) as f64) } else { b.push((c1 - c0) as f64) }
    }
    let (t, ma, mb) = welch(&mut a, &mut b);
    let verdict = if t.abs() < 4.5 { "no leak detected" } else { "LEAK" };
    format!(
        "{{\"op\":\"{name}\",\"samples\":{samples},\"t\":{t:.2},\"mean_fixed\":{ma:.1},\"mean_random\":{mb:.1},\"verdict\":\"{verdict}\"}}"
    )
}

fn timing(samples: usize) {
    let fixed_a = Fe::ZERO;
    let one = Fe::ONE;
    let mut sink = Fe::ZERO;
    let mut results = vec![];

    results.push(run(
        "Fe::mul (fixed 0 vs random)",
        samples,
        |fixed| if fixed { (fixed_a, fixed_a) } else { (Fe::random(), Fe::random()) },
        |(x, y)| sink = sink.add(std::hint::black_box(*x).mul(std::hint::black_box(*y))),
    ));
    results.push(run(
        "Fe::inv (fixed 1 vs random)",
        samples / 4,
        |fixed| if fixed { one } else { Fe::random() },
        |x| sink = sink.add(std::hint::black_box(*x).inv()),
    ));

    // tag verification: valid tag (accept) vs random tag (reject)
    let (h, shares, rings) = scheme::deal(b"timing-study-master-key-32bytes!", 5, 3, 0).unwrap();
    let key = &rings[0].keys[0].1;
    let sh = &shares[1];
    let ctx = scheme::context(&h, sh.i);
    let good = scheme::tag(key, ctx, &sh.y);
    results.push(run(
        "tag verify (valid vs forged tag)",
        samples,
        |fixed| if fixed { good } else { Fe::random() },
        |probe| {
            let ok = scheme::tag(key, ctx, &sh.y).ct_eq(std::hint::black_box(*probe));
            sink = sink.add(Fe::from_u128(ok as u128));
        },
    ));

    // Lagrange combination of t shares: shares of an all-zero key vs a random key
    let zero_secret = [0u8; 32];
    let (_, sz, _) = scheme::deal(&zero_secret, 5, 3, 0).unwrap();
    let lam = saksi_core::field::lagrange_at_zero(&[Fe::ONE, Fe::from_u128(2), Fe::from_u128(3)]);
    results.push(run(
        "Lagrange combine 3 shares (zero key vs random key)",
        samples,
        |fixed| {
            if fixed {
                [sz[0].y[0], sz[1].y[0], sz[2].y[0]]
            } else {
                let (_, s, _) = scheme::deal(&[0x5a; 15], 5, 3, 0).unwrap();
                [s[0].y[0], s[1].y[0], s[2].y[0]]
            }
        },
        |ys| {
            let mut acc = Fe::ZERO;
            for (l, y) in lam.iter().zip(ys) {
                acc = acc.add(l.mul(std::hint::black_box(*y)));
            }
            sink = sink.add(acc);
        },
    ));

    // positive controls (must be flagged, otherwise the test has no power)
    results.push(run(
        "CONTROL leaky Euclid inverse (fixed 1 vs random)",
        samples / 4,
        |fixed| if fixed { 1u128 } else { Fe::random().value() | 1 },
        |x| sink = sink.add(Fe::from_u128(leaky_inv(std::hint::black_box(*x)))),
    ));
    let tb = good.value().to_be_bytes();
    results.push(run(
        "CONTROL leaky early-exit compare (equal vs random)",
        samples,
        |fixed| if fixed { tb } else { Fe::random().value().to_be_bytes() },
        |probe| sink = sink.add(Fe::from_u128(leaky_eq(&tb, std::hint::black_box(probe)) as u128)),
    ));

    println!("[\n  {}\n]", results.join(",\n  "));
    eprintln!("(sink {})", sink.value() & 1);
}

fn bench() {
    let mut x = Fe::random();
    let y = Fe::random();
    let n = 2_000_000;
    let t0 = Instant::now();
    for _ in 0..n {
        x = x.mul(y);
    }
    let mul_ns = t0.elapsed().as_nanos() as f64 / n as f64;
    let t0 = Instant::now();
    for _ in 0..20_000 {
        x = x.add(x.inv());
    }
    let inv_ns = t0.elapsed().as_nanos() as f64 / 20_000.0;
    let key = [7u8; 32];
    let reps = 2000;
    let t0 = Instant::now();
    let mut last = None;
    for _ in 0..reps {
        last = Some(scheme::deal(&key, 5, 3, 0).unwrap());
    }
    let deal_us = t0.elapsed().as_micros() as f64 / reps as f64;
    let (h, s, r) = last.unwrap();
    let t0 = Instant::now();
    for _ in 0..reps {
        assert!(scheme::reconstruct(&h, &s, &r).ok);
    }
    let rec_us = t0.elapsed().as_micros() as f64 / reps as f64;
    let mut bad = s.clone();
    bad[1].y[0] = bad[1].y[0].add(Fe::ONE);
    let t0 = Instant::now();
    for _ in 0..reps {
        assert!(scheme::reconstruct_keyless(&h, &bad).ok);
    }
    let kl_us = t0.elapsed().as_micros() as f64 / reps as f64;
    println!(
        "{{\"mul_ns\":{mul_ns:.1},\"inv_ns\":{inv_ns:.1},\"deal_5_3_32B_us\":{deal_us:.1},\"reconstruct_5_3_us\":{rec_us:.1},\"keyless_decode_5_3_1err_us\":{kl_us:.1},\"sink\":{}}}",
        x.value() & 1
    );
}
