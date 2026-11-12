"use client";

type Props = {
  n: number;
  names: string[];
  cells: [number, number, boolean][]; // [verifier j, share i, ok]
  votes: [number, number][];          // [share i, confirmations]
  need: number;
  present: Set<number>;               // shares that were submitted
  title?: string;
  sub?: string;
  animateKey?: string | number;
};

/** Rows: share i being checked. Columns: custodian j whose one-time key checks it. */
export default function WitnessMatrix({ n, names, cells, votes, need, present, title, sub, animateKey }: Props) {
  const lookup = new Map(cells.map(([j, i, ok]) => [`${i}:${j}`, ok]));
  const v = new Map(votes);
  const idx = Array.from({ length: n }, (_, k) => k + 1);
  return (
    <div className="matrix" aria-label="Witness matrix">
      {title && <h3>{title}</h3>}
      {sub && <p className="sub">{sub}</p>}
      <div
        key={animateKey}
        className="grid reveal"
        style={{ gridTemplateColumns: `minmax(64px, 96px) repeat(${n}, minmax(26px, 1fr)) 58px` }}
        role="table"
      >
        <div />
        {idx.map((j) => (
          <div key={`h${j}`} className="lab" role="columnheader" title={names[j - 1]}>
            {j}
          </div>
        ))}
        <div className="lab" title={`a share needs ${need} confirmations`}>need {need}</div>
        {idx.map((i, r) => {
          const submitted = present.has(i);
          const count = v.get(i);
          return [
            <div key={`r${i}`} className="row-lab" role="rowheader">
              share {i}
            </div>,
            ...idx.map((j, c) => {
              if (i === j) return <div key={`${i}-${j}`} className="cell self" aria-label="own share" />;
              const ok = lookup.get(`${i}:${j}`);
              const cls = !submitted || ok === undefined ? "cell none" : ok ? "cell ok" : "cell no";
              return (
                <div
                  key={`${i}-${j}`}
                  className={cls}
                  style={{ ["--d" as string]: r * n + c }}
                  aria-label={ok === undefined ? "no witness" : ok ? `custodian ${j} confirms share ${i}` : `custodian ${j} rejects share ${i}`}
                >
                  {ok === undefined || !submitted ? "" : ok ? "✓" : "✗"}
                </div>
              );
            }),
            <div key={`v${i}`} className={`votes ${count === undefined ? "" : count >= need ? "pass" : "fail"}`}>
              {count === undefined ? "–" : `${count} of ${n - 1}`}
            </div>,
          ];
        })}
      </div>
      <div className="legend">
        <span className="l-ok">key confirms tag</span>
        <span className="l-no">tag fails: forgery</span>
        <span className="l-self">own share</span>
      </div>
    </div>
  );
}
