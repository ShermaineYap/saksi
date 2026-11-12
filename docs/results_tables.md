| Attack (real parameters, p = 2¹²⁷−1, n = 5, t = 3) | Trials | Plain Shamir returns wrong key | SAKSI returns wrong key | SAKSI names the cheater |
|---|---:|---:|---:|---:|
| bit flip in one share | 1000 | 81.9% | 0.0% | 100.0% |
| random share replacement | 1000 | 100.0% | 0.0% | 100.0% |
| Tompa-Woll: last submitter shifts share | 1000 | 100.0% | 0.0% | 100.0% |
| cross-session substitution | 1000 | 100.0% | 0.0% | 100.0% |
| two colluding cheaters, lying keys | 500 | 100.0% | 0.0% | 100.0% |
| replay share from previous epoch | 500 | 100.0% | 0.0% | 100.0% |
| inconsistent dealer (tags valid) | 500 | 100.0% | 0.0% | 100.0% |

| Operation (Rust core, dudect) | Samples | \|t\| | Verdict (threshold 4.5) |
|---|---:|---:|---|
| Fe::mul (fixed 0 vs random) | 1,000,000 | 0.50 | no leak detected |
| Fe::inv (fixed 1 vs random) | 250,000 | 1.11 | no leak detected |
| tag verify (valid vs forged tag) | 1,000,000 | 0.85 | no leak detected |
| Lagrange combine 3 shares (zero key vs random key) | 1,000,000 | 0.57 | no leak detected |
| CONTROL leaky Euclid inverse (fixed 1 vs random) | 250,000 | 3421.23 | LEAK |
| CONTROL leaky early-exit compare (equal vs random) | 1,000,000 | 192.46 | LEAK |
