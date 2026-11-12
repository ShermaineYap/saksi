"""Render the paper's displayed maths, algorithm boxes and main theorems to PNG for Devpost
(Devpost does not render LaTeX). Output: docs/img/*.png, all 14 cm wide at 300 dpi.

Run from the repo root:  python3 docs/render_png.py
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "docs" / "img"
IMG.mkdir(parents=True, exist_ok=True)

PRE = r"""\documentclass[11pt,border=10pt]{standalone}
\usepackage[T1]{fontenc}\usepackage{lmodern}
\usepackage{amsmath,amssymb,amsthm,mathtools}
\usepackage{cryptocode}\usepackage{xcolor}\usepackage{graphicx}
\usepackage{tikz}\usetikzlibrary{arrows.meta,positioning,shapes.geometric}
\newcommand{\F}{\mathbb{F}_p}\newcommand{\ctx}{\mathsf{ctx}}\newcommand{\Vote}{\mathsf{votes}}
\newcommand{\bad}{\bot}\DeclareMathOperator{\Syn}{Syn}
\providecommand{\adv}{\mathcal{A}}\providecommand{\sample}{\xleftarrow{\$}}
\pagecolor{white}
\begin{document}
\begin{minipage}{14cm}
"""
POST = r"""
\end{minipage}
\end{document}
"""

BLOCKS = {
"eq_sharing": r"""\textbf{Share (Vandermonde encoding).} For each 120-bit limb $s_\ell$ of the key:
\[ f_\ell(X)=s_\ell+a_{\ell,1}X+\dots+a_{\ell,t-1}X^{t-1},\qquad a_{\ell,k}\xleftarrow{\$}\mathbb F_p,\qquad p=2^{127}-1, \]
\[ \mathbf y_\ell = V\mathbf a_\ell,\quad V=\begin{pmatrix}1&1&\cdots&1\\1&2&\cdots&2^{t-1}\\
\vdots&&&\vdots\\1&n&\cdots&n^{t-1}\end{pmatrix},\qquad y_{i,\ell}=f_\ell(i). \]""",
"eq_context_tag": r"""\textbf{Witness tag} on share $i$ under custodian $j$'s one-time key
$\kappa_{j,i}=(\alpha_0,\dots,\alpha_L,\beta)\xleftarrow{\$}\mathbb F_p^{L+2}$:
\[ \ctx_i=\mathsf{sid}+2^{64}e+2^{96}i,\qquad
\tau_{j,i}=\beta+\alpha_0\,\ctx_i+\sum_{\ell=1}^{L}\alpha_\ell\,y_{i,\ell}\pmod p. \]""",
"eq_vote": r"""\textbf{Two-round reveal and vote.} Round 1: shares and tags. Round 2: keys. Then
\begin{gather*} \Vote_i=\#\Big\{j\neq i:\ \tau_{j,i}\overset{\text{ct}}{=}\beta_{j,i}+\alpha_{j,i,0}\ctx_i+\sum_\ell\alpha_{j,i,\ell}\,y_{i,\ell}\Big\},\\
\text{accept share } i \iff \Vote_i\ \ge\ T=\Big\lfloor\frac{n-1}{2}\Big\rfloor. \end{gather*}""",
"eq_syndrome": r"""\textbf{Syndrome cross-check} over the accepted points $x_1,\dots,x_m$:
\[ \Syn(\mathbf y)_k=\sum_{i=1}^{m}v_i\,x_i^{k}\,y_i\quad(k=0,\dots,m-t-1),\qquad
v_i=\prod_{j\neq i}(x_i-x_j)^{-1}. \]
$\Syn(\mathbf y)=\mathbf 0$ iff the shares lie on one polynomial of degree $<t$; otherwise Gao
decoding locates up to $\lfloor (m-t)/2\rfloor$ bad shares.""",
"eq_lagrange": r"""\textbf{Reconstruct} (only from validated shares, fail closed if fewer than $t$):
\[ s_\ell=\sum_{i\in A_t}\lambda_i\,y_{i,\ell},\qquad \lambda_i=\prod_{j\in A_t,\,j\neq i}\frac{x_j}{x_j-x_i}. \]""",
"eq_refresh": r"""\textbf{Proactive refresh} (new epoch $e+1$, fresh keys):
\[ y'_{i,\ell}=y_{i,\ell}+z_\ell(i),\qquad z_\ell(X)=\sum_{k=1}^{t-1}b_{\ell,k}X^k,\ \ z_\ell(0)=0. \]""",
"eq_mersenne": r"""\textbf{Mersenne reduction} (branch-free in Rust): since $2^{127}\equiv1$ and $2^{128}\equiv2 \pmod p$,
\[ h\cdot 2^{128}+\ell \;\equiv\; 2h+(\ell\bmod 2^{127})+\lfloor \ell/2^{127}\rfloor \pmod{2^{127}-1},
\qquad a^{-1}=a^{\,p-2}. \]""",
"alg_deal": r"""\centering
\procedure[linenumbering]{$\mathsf{Deal}(S, n, t)$}{%
\textbf{assert } 2\le t\le n,\ n\ge 3,\ S\ne\varepsilon \\
(s_1,\dots,s_L) \gets \mathsf{Limbs}_{15}(S);\quad \mathsf{sid}\sample\{0,\dots,2^{53}-1\};\quad e\gets 0\\
\pcfor \ell=1..L \pcdo \\
\pcind a_{\ell,0}\gets s_\ell;\quad a_{\ell,1},\dots,a_{\ell,t-1}\sample\F \\
\pcind \pcfor i=1..n \pcdo\ y_{i,\ell}\gets \textstyle\sum_{k} a_{\ell,k}\, i^k \\
\pcfor \text{ordered } (j,i),\ j\ne i \pcdo \\
\pcind \kappa_{j,i}=(\alpha_0,\dots,\alpha_L,\beta)\sample\F^{L+2}\\
\pcind \tau_{j,i}\gets \beta+\alpha_0\ctx_i+\textstyle\sum_{\ell}\alpha_\ell y_{i,\ell}\\
\text{custodian } i \text{ gets } \big(\mathbf y_i, \{\tau_{j,i}\}_{j\ne i}, \{\kappa_{i,k}\}_{k\ne i}\big)
}""",
"alg_reconstruct": r"""\centering
\procedure[linenumbering]{$\mathsf{Reconstruct}(H)$}{%
\text{\textbf{Round 1:} receive } (i,\mathbf y_i,\{\tau_{j,i}\}_j)\text{; drop malformed / duplicate / non-canonical}\\
\text{\textbf{Round 2:} receive keys } \{\kappa_{j,i}\}_i \text{ (only after round 1 is fixed)}\\
A\gets\{i : \Vote_i\ge \lfloor (n-1)/2\rfloor\};\ \text{report the rest as rejected}\\
\pcif |A|<t \pcthen \pcreturn \bot \\
\pcif \Syn_A(\mathbf y_\ell)=\mathbf 0\ \forall\ell \pcthen s_\ell\gets\textstyle\sum_{i\in A_t}\lambda_i y_{i,\ell}\\
\pcelse (f_\ell,E_\ell)\gets\mathsf{Gao}(A,\mathbf y_\ell,t);\ \text{report } \cup E_\ell \text{ as located; } \pcif \text{fail} \pcthen \pcreturn\bot\\
\pcif \text{limb} \ge 2^{120} \text{ or padding}\ne0 \pcthen \pcreturn\bot \quad\text{(sanity check)}\\
\pcreturn S
}""",
"thm_privacy": r"""\textbf{Theorem 1 (Perfect secrecy, including tags).} \emph{For every coalition $C$ with
$|C|\le t-1$ and any two secrets $S,S'$ of equal length, the joint view of $C$ after dealing
(shares, tags, keys, header) has the same distribution under $S$ and $S'$.}

\smallskip\emph{Proof idea.} For fixed $s$ the system $\sum_{k\ge1}a_kx_i^k=y_i-s$ ($i\in C$) has full row
rank, so exactly $p^{\,t-1-|C|}$ polynomials match any view, independent of $s$. Tags under honest
keys contain a fresh uniform $\beta$, so they are uniform and independent. \hfill$\square$""",
"thm_forgery": r"""\textbf{Theorem 2 (Witness forgery).} \emph{An adversary that sees $(m,\tau)$ with
$\tau=\beta+\langle\alpha,m\rangle$ and outputs $(m',\tau')$ with $m'\neq m$ succeeds with
probability exactly $1/p=2^{-127}$, even with unlimited computing power.}

\smallskip\emph{Proof idea.} $\tau$ fixes only $\beta$; $\alpha$ stays uniform, so
$\tau'-\tau=\langle\alpha,m'-m\rangle$ is a uniform field element. \hfill$\square$""",
"thm_robust": r"""\textbf{Theorem 3 (Robustness and identification).} \emph{With $c\le T=\lfloor(n-1)/2\rfloor$
cheaters and the two rounds ordered: every honest share is accepted; a modified share is accepted
with probability at most $\binom{n-c}{T-c+1}p^{-(T-c+1)}\le 2^n/p$. So if $\ge t$ honest custodians
respond, the output is the correct key and every modified share is named, except with
probability $\le c\cdot 2^n/p$ (below $2^{-120}$ for $n=5$).}""",
}


def render(name, body):
    with tempfile.TemporaryDirectory() as d:
        tex = Path(d) / f"{name}.tex"
        tex.write_text(PRE + body + POST)
        subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex.name],
                       cwd=d, check=True, capture_output=True)
        log = (Path(d) / f"{name}.log").read_text(errors="ignore")
        if "Overfull" in log:
            print("OVERFULL:", name)
        subprocess.run(["pdftoppm", "-r", "300", "-png", "-singlefile", f"{name}.pdf", str(IMG / name)],
                       cwd=d, check=True)


def flow():
    body = r"""\centering\resizebox{14cm}{!}{%
\begin{tikzpicture}[node distance=5mm and 6mm, >=Stealth,
 box/.style={draw, rounded corners=2pt, align=center, font=\small, minimum height=8mm, inner sep=3pt},
 cust/.style={draw, circle, font=\small, minimum size=7mm, inner sep=0pt},
 dec/.style={draw, diamond, aspect=2.2, align=center, font=\footnotesize, inner sep=1pt}]
\node[box, fill=blue!6] (dealer) {Dealer};
\node[cust, right=10mm of dealer, yshift=12mm] (c1) {1};
\node[cust, below=1.5mm of c1] (c2) {2}; \node[cust, below=1.5mm of c2] (c3) {3};
\node[cust, below=1.5mm of c3] (c4) {4}; \node[cust, below=1.5mm of c4] (c5) {5};
\foreach \c in {c1,c2,c3,c4,c5} \draw[->, gray] (dealer.east) -- (\c.west);
\node[box, right=10mm of c3, fill=orange!8] (r1) {Round 1\\shares + tags};
\foreach \c in {c1,c2,c3,c4,c5} \draw[->, gray!70] (\c.east) -- (r1.west);
\node[box, right=of r1, fill=orange!8] (r2) {Round 2\\keys};
\node[box, right=of r2] (v) {votes\\$\ge\lfloor\frac{n-1}{2}\rfloor$};
\node[dec, right=of v] (s) {$\mathrm{Syn}=\mathbf 0$?};
\node[box, above right=2mm and 6mm of s, fill=green!8] (l) {Lagrange\\$\Rightarrow$ key};
\node[box, below right=2mm and 6mm of s, fill=yellow!10] (g) {Gao: locate\\or $\bot$};
\draw[->] (r1)--(r2); \draw[->] (r2)--(v); \draw[->] (v)--(s);
\draw[->] (s)--node[above left,font=\scriptsize]{yes}(l); \draw[->] (s)--node[below left,font=\scriptsize]{no}(g);
\draw[->] (g)--(l);
\node[box, below=6mm of v, fill=red!8] (f) {$<t$ valid: $\bot$ (fail closed)};
\draw[->] (v)--(f);
\end{tikzpicture}}"""
    render("flow", body)


if __name__ == "__main__":
    for k, v in BLOCKS.items():
        render(k, v)
    flow()
    for f in ["uniformity", "forgery", "timing"]:
        shutil.copy(ROOT / "paper" / "figures" / f"{f}.png", IMG / f"fig_{f}.png")
    print(sorted(p.name for p in IMG.glob("*.png")))
