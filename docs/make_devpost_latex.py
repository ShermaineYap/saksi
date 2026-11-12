"""Build docs/devpost_latex.md (Devpost description with native LaTeX) from docs/devpost.md.

Devpost runs Markdown before MathJax, so every formula is escaped for Markdown:
backslash-punctuation pairs are doubled, `\\\\` row breaks become `\\\\\\\\`, and `_`/`*` are escaped.
Inline maths uses \\\\( ... \\\\); display maths uses $$ on its own lines.
"""
import re
from pathlib import Path

D = Path(__file__).parent
IMG = "https://raw.githubusercontent.com/ShermaineYap/saksi/main/docs/img/"


def esc(body: str) -> str:
    body = body.replace("\\\\", "\x00")
    body = re.sub(r"\\([!-/:-@\[-`{-~])", lambda m: "\\\\" + m.group(1), body)
    body = body.replace("_", r"\_").replace("*", r"\*")
    return body.replace("\x00", "\\\\\\\\")


def disp(*eqs: str) -> str:
    return "\n\n".join("$$\n" + esc(e.strip()) + "\n$$" for e in eqs)


def inl(tex: str) -> str:
    return r"\\(" + esc(tex) + r"\\)"


BLOCKS = {
    "eq_sharing.png": disp(
        r"f_\ell(X) = s_\ell + a_{\ell,1}X + \cdots + a_{\ell,t-1}X^{t-1}, \qquad a_{\ell,k} \in \mathbb{F}_p \text{ uniform}",
        r"\mathbf{y}_\ell = V\mathbf{a}_\ell, \qquad V = \begin{pmatrix} 1 & 1 & \cdots & 1 \\ 1 & 2 & \cdots & 2^{t-1} \\ \vdots & \vdots & & \vdots \\ 1 & n & \cdots & n^{t-1} \end{pmatrix}",
    ),
    "eq_context_tag.png": disp(
        r"\mathsf{ctx}_i = \mathsf{sid} + 2^{64}e + 2^{96}i",
        r"\tau_{j,i} = \beta_{j,i} + \alpha_{j,i,0}\,\mathsf{ctx}_i + \sum_{\ell=1}^{L} \alpha_{j,i,\ell}\, y_{i,\ell} \pmod{p}",
    ),
    "eq_vote.png": disp(
        r"\mathrm{votes}_i = \#\{\, j \neq i : \kappa_{j,i} \text{ confirms } \tau_{j,i} \,\}",
        r"\text{accept } i \iff \mathrm{votes}_i \ge T = \left\lfloor \tfrac{n-1}{2} \right\rfloor",
    ),
    "eq_syndrome.png": disp(
        r"S_k = \sum_{i \in A} v_i\, x_i^{k}\, y_i, \qquad k = 0, \dots, m-t-1",
        r"v_i = \prod_{j \in A,\, j \neq i} (x_i - x_j)^{-1}",
        r"\mathbf{S} = \mathbf{0} \iff \exists f,\ \deg f < t : f(x_i) = y_i \ \ \forall i \in A",
    ),
    "eq_lagrange.png": disp(
        r"s_\ell = \sum_{i \in A'} \lambda_i\, y_{i,\ell}, \qquad |A'| = t",
        r"\lambda_i = \prod_{j \in A',\, j \neq i} \frac{x_j}{x_j - x_i}",
    ),
    "eq_refresh.png": disp(
        r"y'_{i,\ell} = y_{i,\ell} + z_\ell(i), \qquad z_\ell(0) = 0,\ \ \deg z_\ell < t, \qquad e \mapsto e+1",
    ),
    "eq_mersenne.png": disp(
        r"2^{127} \equiv 1 \pmod{p} \;\Longrightarrow\; x \bmod p = (x \bmod 2^{127}) + \lfloor x / 2^{127} \rfloor",
        r"a^{-1} = a^{\,p-2} \pmod{p}",
    ),
}

THEOREMS = (
    f"**Theorem 1 (perfect secrecy, including tags).** For every coalition {inl('C')} with {inl('|C| \\le t-1')} "
    f"and every two secrets {inl("S, S'")} of equal length, the joint view of {inl('C')} after Deal "
    f"(shares, tags, keys and header) has the same distribution under {inl('S')} and {inl("S'")}.\n\n"
    f"**Theorem 2 (witness forgery).** For every adversary, even a computationally unbounded one,\n\n"
    + disp(r"\Pr[\mathsf{Forge}] \le \frac{1}{p} = 2^{-127},")
    + "\n\nwith equality for the best strategy.\n\n"
    f"**Theorem 3 (robustness and identification).** Let {inl(r'c = |C| \le T = \lfloor (n-1)/2 \rfloor')} and "
    f"{inl('k = T - c + 1')}, with the two rounds ordered. Every honest share is accepted, and a modified share from "
    f"a corrupted custodian is accepted with probability at most\n\n"
    + disp(r"\binom{n-c}{k}\, p^{-k} \;\le\; \frac{2^{n}}{p}.")
    + f"\n\nSo if at least {inl('t')} honest custodians respond, Reconstruct outputs the key and names every modified "
    f"share, except with probability at most {inl(r'c \cdot 2^n / p')}.\n\n"
    f"**Theorem 4 (keyless decoding).** With {inl(r'm \ge t')} shares of which {inl('e')} are wrong, Gao decoding "
    f"returns the dealt polynomial and exactly the wrong indices when {inl(r'e \le \lfloor (m-t)/2 \rfloor')}, and the "
    f"syndrome is non-zero whenever {inl(r'1 \le e \le m-t')}."
)


def main():
    s = (D / "devpost.md").read_text()
    for name, block in BLOCKS.items():
        pat = re.compile(r"!\[[^\]]*\]\(" + re.escape(IMG + name) + r"\)")
        assert pat.search(s), name
        s = pat.sub(lambda _m: block, s)
    old = "\n".join(f"![Theorem {k}]({IMG}{n})" for k, n in [(1, "thm_privacy.png"), (2, "thm_forgery.png"), (3, "thm_robust.png")])
    assert old in s
    s = s.replace(old, THEOREMS)
    s = s.replace("SAKSI works over the Mersenne prime field 𝔽ₚ with **p = 2¹²⁷ − 1**.",
                  f"SAKSI works over the Mersenne prime field {inl(r'\mathbb{F}_p')} with {inl('p = 2^{127} - 1')}.")
    s = s.replace("The three security theorems below are proved in full", "The theorems below are proved in full")
    (D / "devpost_latex.md").write_text(s)
    print(len(s), "chars,", s.count("$$") // 2, "display,", s.count(r"\\("), "inline")


if __name__ == "__main__":
    main()
