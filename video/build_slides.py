"""Render the video's slides (1920x1080) from HTML using the site's design tokens."""
import json
import subprocess
import sys
from pathlib import Path

V = Path(__file__).parent
S = Path("/home/claude/saksi")
IMG = S / "docs" / "img"
d = json.loads((S / "attacks/results/attacks.json").read_text())
timing = json.loads((S / "attacks/results/timing_rust.json").read_text())
LINKS = json.loads((V / "links.json").read_text()) if (V / "links.json").exists() else {}

CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Schibsted+Grotesk:wght@400;500;600;700;800&display=swap');
*{box-sizing:border-box} html,body{margin:0;width:1920px;height:1080px;overflow:hidden}
body{background:#edf1ea;color:#14304a;font-family:'Schibsted Grotesk',sans-serif;
 background-image:repeating-radial-gradient(circle at 12% -10%,transparent 0 30px,rgba(20,48,74,.04) 30px 31px),
 repeating-radial-gradient(circle at 92% 110%,transparent 0 34px,rgba(30,116,72,.035) 34px 35px)}
.f{position:absolute;inset:70px 110px 170px 110px;display:flex;flex-direction:column}
h1{font-size:76px;line-height:1.02;margin:0 0 26px;font-weight:800;letter-spacing:-.02em;max-width:22ch}
h2{font-size:58px;line-height:1.05;margin:0 0 30px;font-weight:800;letter-spacing:-.015em}
p,li{font-size:32px;line-height:1.4;color:#2f4a60;margin:0 0 14px}
.step{font-size:30px;font-weight:700;color:#5a6a70;margin-bottom:8px}
.sheet{background:#fff;border:2px solid #14304a;border-radius:14px;padding:22px 26px;box-shadow:8px 8px 0 #e2e8df}
.sheet img{display:block;width:100%}
.row{display:flex;gap:40px;align-items:flex-start}
.col{flex:1;min-width:0}
.chip{display:inline-block;border:2px solid #c6d0c6;background:#f7f9f5;border-radius:999px;padding:8px 20px;font-size:26px;margin:0 12px 12px 0}
.stat{background:#f7f9f5;border:2px solid #c6d0c6;border-radius:14px;padding:22px 26px;flex:1}
.stat b{display:block;font-size:66px;line-height:1;font-weight:800}
.stat span{font-size:25px;color:#2f4a60;display:block;margin-top:10px;line-height:1.3}
.good{color:#1e7448}.bad{color:#b8361f}
table{border-collapse:collapse;width:100%;font-size:27px}
th{text-align:left;color:#5a6a70;font-weight:600;border-bottom:3px solid #14304a;padding:10px 12px}
td{border-bottom:1.5px solid #c6d0c6;padding:11px 12px}
td.n{font-family:'IBM Plex Mono',monospace;font-size:26px}
.box{border:2.5px solid #14304a;border-radius:12px;padding:16px 22px;font-size:30px;font-weight:600;background:#f7f9f5;text-align:center}
.arrow{font-size:44px;color:#5a6a70}
"""

def page(body):
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"

e5 = [r for r in d["E5_active_attacks"]["rows"] if isinstance(r.get("control_wrong_key_rate"), (int, float))]
pct = lambda x: f"{100*x:.1f}%"
e3 = d["E3_collusion_z3"]
e2 = d["E2_uniformity"]
e7 = d["E7_fuzz_rust"]
tmax = max(abs(r["t"]) for r in timing if not r["op"].startswith("CONTROL"))
tctl = min(abs(r["t"]) for r in timing if r["op"].startswith("CONTROL"))

slides = {}
slides["s1"] = f"""<div class='f' style='flex-direction:row;gap:70px;align-items:center'>
<div style='flex:1.05'>
 <div style='font-size:150px;font-weight:800;letter-spacing:.05em;line-height:1'>SAKSI</div>
 <p style='font-size:44px;color:#14304a;font-weight:600;margin:24px 0 30px;line-height:1.2'>Witness-validated secret sharing over GF(2<sup>127</sup> − 1)</p>
 <p>Mathematics for Systems Security, cryptographic track</p>
 <p style='color:#5a6a70'>Shermaine Yap Shi Min, Asia Pacific University, Malaysia</p></div>
<div style='flex:1'><img src='{V/'slides/hero_matrix.png'}' style='width:100%'></div></div>"""

slides["s2"] = """<div class='f'><h2>Plain Shamir trusts every share it is given</h2>
<div class='row' style='align-items:center;gap:30px;margin-top:40px'>
 <div style='display:flex;flex-direction:column;gap:22px'>
  <div class='box'>Custodian 1: real share</div><div class='box'>Custodian 2: real share</div>
  <div class='box' style='border-color:#b8361f;color:#b8361f;background:#f4dcd5'>Custodian 3: shifted share</div></div>
 <div class='arrow'>→</div><div class='box' style='padding:30px 34px'>Lagrange<br>interpolation</div><div class='arrow'>→</div>
 <div class='box' style='border-color:#b8361f;color:#b8361f;background:#f4dcd5;padding:30px 34px'>Wrong key.<br>No error.</div></div>
<p style='margin-top:60px;max-width:60ch'>Tompa and Woll (1988): the last custodian to submit can make everyone else rebuild a wrong key while learning the real one.</p></div>"""

slides["s3a"] = f"""<div class='f'><div class='step'>Step 1 of 3</div><h2>Share: a Vandermonde matrix over the Mersenne prime</h2>
<div class='sheet' style='width:1300px'><img src='{IMG/'eq_sharing.png'}'></div>
<p style='margin-top:34px'>Any <i>t</i> shares rebuild the key. Any <i>t</i> − 1 shares are consistent with every possible key equally often: perfect secrecy (Theorem 1).</p></div>"""

slides["s3b"] = f"""<div class='f'><div class='step'>Step 2 of 3</div><h2>Witness: one-time tags, checked in two rounds</h2>
<div class='row'><div class='col'><div class='sheet'><img src='{IMG/'eq_context_tag.png'}'></div>
<div class='sheet' style='margin-top:24px'><img src='{IMG/'eq_vote.png'}'></div></div>
<div style='width:520px'><p><b>Round 1:</b> shares and tags are fixed.</p><p><b>Round 2:</b> only then are the keys published.</p>
<p>A forger passes one witness with probability 1/<i>p</i> = 2<sup>−127</sup> (Theorem 2).</p></div></div></div>"""

slides["s3c"] = f"""<div class='f'><div class='step'>Step 3 of 3</div><h2>Check, then release, or release nothing</h2>
<div class='sheet' style='width:1500px'><img src='{IMG/'flow.png'}'></div>
<div style='margin-top:30px'><span class='chip'>No block cipher</span><span class='chip'>No hash function</span><span class='chip'>No pre-existing encryption algorithm</span><span class='chip'>Unconditional, so post-quantum by construction</span></div></div>"""

slides["s6a"] = f"""<div class='f'><h2>Survives cryptanalysis: passive attacks</h2>
<div class='row' style='gap:28px'>
 <div class='stat'><b class='good'>0 bits</b><span>leaked below threshold. Exhaustive enumeration of every polynomial in fields p = 31, 101 and 13 (E1).</span></div>
 <div class='stat'><b class='good'>0</b><span>bits a Z3 solver extracts from t − 1 SAKSI shares, against <b class='bad' style='display:inline;font-size:inherit'>{e3['mignotte_control']['bits_leaked']} bits</b> from a Mignotte CRT control (E3).</span></div>
 <div class='stat'><b class='good'>p &gt; 0.01</b><span>χ² share uniformity over {e2['sharings']:,} sharings; a biased-coefficient control leaks {e2['exact_MI_bits_biased_coeffs_control']} bits (E2).</span></div></div>
<div class='row' style='margin-top:30px;align-items:center'><div class='sheet' style='width:640px'><img src='{IMG/'fig_forgery.png'}'></div>
<p style='flex:1'>Measured forgery success for nine field sizes, 200,000 forgeries each, sits on the 1/<i>p</i> line (E4).</p></div></div>"""

rows = "".join(f"<tr><td>{r['attack']}</td><td class='n'>{r['trials']}</td><td class='n bad'>{pct(r['control_wrong_key_rate'])}</td><td class='n good'>{pct(r['saksi_wrong_key_rate'])}</td><td class='n good'>{pct(r['saksi_cheater_named_rate'])}</td></tr>" for r in e5)
slides["s6b"] = f"""<div class='f'><h2>Survives cryptanalysis: active attacks</h2>
<table><thead><tr><th>Attack (3-of-5, 32-byte key)</th><th>Trials</th><th>Plain Shamir wrong key</th><th>SAKSI wrong key</th><th>Cheater named</th></tr></thead><tbody>{rows}</tbody></table>
<p style='margin-top:26px'>Same attacks on the Rust binary: {d['E6_rust_core']['trials']}/{d['E6_rust_core']['trials']} correct. Fuzzing: {e7['mutated_bundles']:,} malformed inputs, {e7['crashes']} crashes, {e7['wrong_key_returned']} wrong keys.</p></div>"""

slides["s7"] = f"""<div class='f'><h2>Minimises attack surface: side channels</h2>
<div class='row'><div class='sheet' style='width:960px'><img src='{IMG/'fig_timing.png'}'></div>
<div class='col'><p>Constant-time Rust core:</p><ul style='padding-left:30px;margin:0'>
<li>branch-free Mersenne reduction</li><li>fixed-shape 64×64-bit products</li><li>fixed 127-step inversion ladder</li><li>masked select, constant-time compare, zeroised memory</li></ul>
<p style='margin-top:20px'>dudect, 10<sup>6</sup> samples: core |t| ≤ {tmax:.2f}; leaky controls |t| ≥ {tctl:.0f}.</p></div></div></div>"""

slides["s8"] = f"""<div class='f'><h2>A 13-page paper with proofs, and honest limits</h2>
<div class='row' style='gap:26px'>
 <img src='{V/'slides/pg-01.png'}' style='height:560px;border:2px solid #14304a;box-shadow:8px 8px 0 #e2e8df'>
 <img src='{V/'slides/pg-06.png'}' style='height:560px;border:2px solid #14304a;box-shadow:8px 8px 0 #e2e8df'>
 <div class='col'><p><b>Limits</b></p><ul style='padding-left:30px;margin:0'><li>dealer trusted per epoch</li><li>key material grows as n²</li><li>honest majority needed: 3 of 5 colluders defeat it, as E5 shows</li><li>key is in memory at the moment of use</li></ul></div></div></div>"""

slides["s9"] = f"""<div class='f' style='justify-content:center'>
<div style='font-size:140px;font-weight:800;letter-spacing:.05em;line-height:1'>SAKSI</div>
<p style='font-size:44px;color:#14304a;margin:20px 0 50px'>Saksi means “witness” in Malay.</p>
<table style='width:auto;font-size:34px'><tr><td style='color:#5a6a70;border:0;padding:8px 40px 8px 0'>Code</td><td style='border:0'>{LINKS.get('repo','github.com')}</td></tr>
<tr><td style='color:#5a6a70;border:0;padding:8px 40px 8px 0'>Live demo</td><td style='border:0'>{LINKS.get('demo','(link in the description)')}</td></tr>
<tr><td style='color:#5a6a70;border:0;padding:8px 40px 8px 0'>Paper</td><td style='border:0'>saksi.pdf in the repository</td></tr></table></div>"""

out = V / "slides" / "html"
out.mkdir(parents=True, exist_ok=True)
only = set(sys.argv[1:])
for k, body in slides.items():
    if only and k not in only:
        continue
    (out / f"{k}.html").write_text(page(body))
js = """
const { chromium } = require(process.env.PW_PATH);
(async () => { const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
 for (const k of process.argv.slice(2)) { await p.goto('file://' + k + '.html', { waitUntil: 'networkidle' }); await p.waitForTimeout(300);
  await p.screenshot({ path: k + '.png' }); } await b.close(); })();
"""
(V / "shot.cjs").write_text(js)
keys = [str(out / k) for k in slides if not only or k in only]
pw = subprocess.check_output(["npm", "root", "-g"], text=True).strip() + "/playwright"
subprocess.run(["node", str(V / "shot.cjs"), *keys], check=True, env={**__import__('os').environ, "PW_PATH": pw})
print("rendered", len(keys))
