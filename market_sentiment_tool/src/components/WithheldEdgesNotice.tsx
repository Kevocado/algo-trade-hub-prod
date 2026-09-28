import { EyeOff } from "lucide-react";

import { displayOnlyReason, type EngineTagged, type WithheldEdge } from "@/lib/displayOnlyEngines";

/**
 * The half of Ruling 1 that only a page can close.
 *
 * `scan_cpi` no longer writes CPI edges and the historical rows are deliberately NOT deleted (no
 * migration: a read filter keeps holding and a one-time delete does not). `useMarketEdges` splits
 * its read into `edges` and `withheld`, conserving every row. But a row that is read and then not
 * rendered is, to a reader, indistinguishable from there having been no rows -- so a MACRO tab that
 * simply got quieter says "the engine was retired" when what happened is "the engine was
 * relabelled". An engine that is no longer an edge engine has to be *visibly* relabelled.
 *
 * So this renders the withheld rows, names the engine, and prints the reason -- once per engine,
 * because the reason is a paragraph and repeating it per row would bury the rows it is about.
 *
 * Deliberately NOT rendered: the recorded `edge_pct`. The row still carries it, and the number is
 * exactly what a reader would read as an opportunity, so printing it with a caveat attached would
 * be the defect with a footnote. The row's identity, the engine and the reason are what make the
 * withholding visible; the figure was never the point.
 *
 * An empty bucket renders nothing at all. There is no "0 display-only engines" line: a
 * placeholder for an absence is the same noise this component exists to remove, and the count that
 * matters is non-zero by definition.
 */
/**
 * The fields the notice reads off a row. All optional, so a reader's own edge type satisfies it
 * structurally -- `KalshiEdge` is an interface with no index signature and cannot satisfy
 * `Record<string, unknown>`, which is what a `Record` constraint would have demanded here.
 */
export type WithheldEdgeLabel = EngineTagged & {
  id?: string | null;
  market_id?: string | null;
  market_ticker?: string | null;
  market_title?: string | null;
  title?: string | null;
};

export interface WithheldEdgesNoticeProps<T extends WithheldEdgeLabel> {
  withheld: WithheldEdge<T>[];
  /** Shown only when there is something withheld. */
  className?: string;
}

/** The label a withheld row is shown under. Kept out of the row so a row can be identified. */
function rowLabel(edge: WithheldEdgeLabel): string {
  const marketId = edge.market_id ?? edge.market_ticker ?? edge.id;
  const title = edge.market_title ?? edge.title;
  return [marketId, title].filter(Boolean).join(" · ");
}

export function WithheldEdgesNotice<T extends WithheldEdgeLabel>({
  withheld,
  className = "",
}: WithheldEdgesNoticeProps<T>) {
  if (withheld.length === 0) return null;

  // One paragraph per engine, not per row, so the rows stay visible inside the explanation.
  const byEngine = new Map<string, { reason: string; rows: T[] }>();
  for (const item of withheld) {
    const bucket = byEngine.get(item.engine) ?? { reason: item.reason, rows: [] };
    bucket.rows.push(item.edge);
    byEngine.set(item.engine, bucket);
  }

  return (
    <section
      aria-label="Display-only engines, withheld from opportunities"
      className={`rounded-xl border border-amber-900/50 bg-amber-950/20 p-4 ${className}`}
    >
      <div className="flex items-center gap-2">
        <EyeOff className="h-4 w-4 text-amber-400" aria-hidden="true" />
        <h2 className="text-sm font-bold uppercase tracking-widest text-amber-200">
          Display-only engine{withheld.length === 1 ? "" : "s"} · withheld from opportunities (
          {withheld.length} row{withheld.length === 1 ? "" : "s"})
        </h2>
      </div>

      <p className="mt-1 text-xs text-amber-100/70">
        These rows were read and are shown here on purpose. They are not opportunities, so they are not
        on the board above — and they are not deleted either, so the record of what the scan did
        survives.
      </p>

      {[...byEngine.entries()].map(([engine, bucket]) => (
        <div key={engine} className="mt-3 border-t border-amber-900/40 pt-3">
          <p className="font-mono text-xs font-bold text-amber-300">{engine}</p>
          {/* The reason, in the words a reader actually reads. A bare flag is jargon. */}
          <p className="mt-1 text-xs leading-relaxed text-amber-100/90">
            {bucket.reason || displayOnlyReason({ engine }) || "Not an edge engine."}
          </p>
          <ul className="mt-2 space-y-1">
            {bucket.rows.map((edge, i) => (
              <li key={String(edge.id ?? i)} className="text-xs text-amber-100/80">
                <span className="font-mono">{rowLabel(edge)}</span>
                <span className="text-amber-100/50"> · shown for context, not as an opportunity</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}

export default WithheldEdgesNotice;
