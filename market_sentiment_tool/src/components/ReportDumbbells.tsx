export interface ReportPoint {
  month: string;
  nowcast: number | null;
  kalshi: number | null;
  firstPrint: number | null;
}

const OURS = "#10b981";
const KALSHI = "#f59e0b";
const PRINT = "#f8fafc";
const SHOWN = 24;

/** Who was closer to the first reported figure: "ours", "kalshi", "tie", or null when a figure is missing. */
export function closer(p: ReportPoint): "ours" | "kalshi" | "tie" | null {
  if (p.nowcast === null || p.kalshi === null || p.firstPrint === null) return null;
  const a = Math.abs(p.nowcast - p.firstPrint);
  const b = Math.abs(p.kalshi - p.firstPrint);
  return a < b ? "ours" : b < a ? "kalshi" : "tie";
}

/** One row per report, latest first: a scale with the first reported figure (white bar), our nowcast (green)
 *  and Kalshi's estimate (amber), the closer of the two ringed. Plain HTML, no interpolation between months,
 *  a figure that was not recorded is simply not drawn. `fmt` formats a value in the series' own units. */
export function ReportDumbbells({ points, fmt }: { points: ReportPoint[]; fmt: (v: number) => string }) {
  const rows = [...points].sort((a, b) => b.month.localeCompare(a.month)).slice(0, SHOWN);
  const values = rows.flatMap((p) => [p.nowcast, p.kalshi, p.firstPrint]).filter((v): v is number => v !== null);
  if (values.length === 0) return <p className="text-sm text-slate-500">No reports yet.</p>;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo) * 0.05 || 1;
  const pos = (v: number) => `${((v - (lo - pad)) / (hi - lo + 2 * pad)) * 100}%`;

  return (
    <div className="space-y-1" role="list" aria-label="Each report: first print, our nowcast, Kalshi's estimate">
      <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
        <span><span className="mr-1 inline-block h-3 w-0.5 bg-slate-50 align-middle" />First reported figure</span>
        <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: OURS }} />Our nowcast</span>
        <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ background: KALSHI }} />Kalshi</span>
        <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-full border-2 border-slate-100 align-middle" />Closer one</span>
      </div>
      {rows.map((p) => {
        const win = closer(p);
        const mark = (v: number | null, color: string, who: "ours" | "kalshi", label: string) =>
          v === null ? null : (
            <div key={who} title={`${label}: ${fmt(v)}`} data-mark={who} data-closer={win === who}
              className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full"
              style={{ left: pos(v), background: color, boxShadow: win === who ? "0 0 0 3px #0f172a, 0 0 0 5px #f1f5f9" : undefined }} />
          );
        return (
          <div key={p.month} role="listitem" className="grid grid-cols-[4.5rem_1fr_9rem] items-center gap-3 text-xs">
            <span className="font-mono text-slate-400">{p.month}</span>
            <div className="relative h-6">
              <div className="absolute inset-x-0 top-1/2 h-px bg-slate-800" />
              {p.firstPrint !== null && (
                <div title={`First reported figure: ${fmt(p.firstPrint)}`} data-mark="print"
                  className="absolute inset-y-0.5 w-0.5 bg-slate-50" style={{ left: pos(p.firstPrint) }} />
              )}
              {mark(p.kalshi, KALSHI, "kalshi", "Kalshi")}
              {mark(p.nowcast, OURS, "ours", "Our nowcast")}
            </div>
            <span className="text-right tabular-nums text-slate-300">
              {p.firstPrint === null ? "—" : fmt(p.firstPrint)}
              <span className="block text-[10px] text-slate-500">
                {win === "ours" ? "We were closer" : win === "kalshi" ? "Kalshi was closer" : win === "tie" ? "Even" : "not scored"}
              </span>
            </span>
          </div>
        );
      })}
    </div>
  );
}
