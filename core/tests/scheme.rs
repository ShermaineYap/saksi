use saksi_core::field::Fe;
use saksi_core::scheme::*;

const KEY: &[u8] = b"\x00\x11\x22\x33\x44\x55\x66\x77\x88\x99\xaa\xbb\xcc\xdd\xee\xff\x01\x23\x45\x67\x89\xab\xcd\xef\xfe\xdc\xba\x98\x76\x54\x32\x10";

fn subsets(n: usize, t: usize) -> Vec<Vec<usize>> {
    (0u32..(1 << n)).filter(|m| m.count_ones() as usize == t)
        .map(|m| (0..n).filter(|i| m >> i & 1 == 1).collect()).collect()
}

#[test]
fn every_threshold_subset_reconstructs() {
    for (n, t) in [(3, 2), (5, 3), (7, 4), (9, 5)] {
        let (h, s, r) = deal(KEY, n, t, 0).unwrap();
        for sub in subsets(n as usize, t as usize) {
            let pick: Vec<Share> = sub.iter().map(|&i| s[i].clone()).collect();
            let o = reconstruct(&h, &pick, &r);
            assert!(o.ok, "{n} {t} {sub:?} {}", o.reason);
            assert_eq!(o.secret.unwrap(), KEY);
        }
    }
}

#[test]
fn below_threshold_fails_closed() {
    let (h, s, r) = deal(KEY, 5, 3, 0).unwrap();
    let o = reconstruct(&h, &s[..2], &r);
    assert!(!o.ok && o.secret.is_none() && o.mode == "fail-closed");
}

#[test]
fn forged_share_is_named_and_ignored() {
    let (h, mut s, r) = deal(KEY, 5, 3, 0).unwrap();
    s[1].y[0] = s[1].y[0].add(Fe::ONE);
    let o = reconstruct(&h, &s, &r);
    assert!(o.ok);
    assert_eq!(o.secret.unwrap(), KEY);
    assert_eq!(o.rejected, vec![2]);
    // the unvalidated control is fooled when the forged share is among the first t
    assert_ne!(plain_shamir(&h, &s).unwrap(), KEY);
}

#[test]
fn colluding_cheaters_with_lying_keys() {
    let (h, mut s, mut r) = deal(KEY, 5, 3, 0).unwrap();
    for l in 0..h.limbs as usize {
        s[0].y[l] = Fe::random();
    }
    s[4].y[1] = Fe::random();
    for j in [0usize, 4] {
        for (_, k) in r[j].keys.iter_mut() {
            k.alpha = (0..=h.limbs).map(|_| Fe::random()).collect();
            k.beta = Fe::random();
        }
    }
    let o = reconstruct(&h, &s, &r);
    assert!(o.ok);
    assert_eq!(o.secret.unwrap(), KEY);
    assert_eq!(o.rejected, vec![1, 5]);
}

#[test]
fn replay_across_epochs_rejected() {
    let (h, s, _) = deal(KEY, 5, 3, 0).unwrap();
    let (h2, mut s2, r2) = refresh(&h, &s);
    s2[0] = s[0].clone();
    let o = reconstruct(&h2, &s2, &r2);
    assert!(o.ok);
    assert_eq!(o.rejected, vec![1]);
    assert_eq!(o.secret.unwrap(), KEY);
}

#[test]
fn keyless_decoding_localises() {
    let (h, mut s, _) = deal(KEY, 7, 3, 0).unwrap();
    for l in 0..h.limbs as usize {
        s[2].y[l] = Fe::random();
        s[5].y[l] = Fe::random();
    }
    let o = reconstruct_keyless(&h, &s);
    assert!(o.ok);
    assert_eq!(o.located, vec![3, 6]);
    assert_eq!(o.secret.unwrap(), KEY);
    // three errors exceed floor((7-3)/2) = 2: must fail closed, never return a wrong key
    s[0].y[0] = Fe::random();
    let o = reconstruct_keyless(&h, &s);
    assert!(!o.ok || o.secret.as_deref() == Some(KEY));
}

#[test]
fn utf8_and_odd_lengths() {
    for msg in ["k", "kunci rahsia 密钥 🔑", &"x".repeat(301)] {
        let (h, s, r) = deal(msg.as_bytes(), 4, 2, 0).unwrap();
        assert_eq!(reconstruct(&h, &s, &r).secret.unwrap(), msg.as_bytes());
    }
}

#[test]
fn rejects_bad_parameters() {
    assert!(deal(KEY, 2, 2, 0).is_err());
    assert!(deal(KEY, 5, 6, 0).is_err());
    assert!(deal(KEY, 5, 1, 0).is_err());
    assert!(deal(b"", 5, 3, 0).is_err());
}

#[test]
fn malformed_shares_do_not_crash() {
    let (h, mut s, r) = deal(KEY, 5, 3, 0).unwrap();
    s[0].i = 0;
    s[1].y.pop();
    s[2].i = 9;
    s.push(s[3].clone()); // duplicate
    let o = reconstruct(&h, &s, &r);
    assert!(!o.ok); // only shares 4 and 5 are well-formed: below threshold
}

#[test]
fn duplicate_index_race_keeps_honest_share() {
    let (h, s, r) = deal(KEY, 5, 3, 0).unwrap();
    let mut fake = s[1].clone();
    for l in 0..h.limbs as usize {
        fake.y[l] = Fe::random();
    }
    let mut sub = vec![fake.clone()];
    sub.extend(s.iter().cloned());
    let o = reconstruct(&h, &sub, &r);
    assert!(o.ok && o.accepted.contains(&2));
    assert_eq!(o.secret.unwrap(), KEY);
    let o = reconstruct(&h, &[fake, s[0].clone(), s[2].clone()], &r);
    assert!(!o.ok);
}
