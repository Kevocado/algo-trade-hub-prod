import { AlertTriangle, EyeOff } from "lucide-react";

import { EDGES_READ_LIMIT, displayOnlyReason, type EngineTagged, type WithheldEdge } from "@/lib/displayOnlyEngines";

/**
 * The half of Ruling 1 that only a page can close.
 *
 * `scan_cpi` no longer writes CPI edges, and the historical rows are deliberately kept rather than
 * deleted by migration -- but ONLY while their markets are still open. `remove_closed_cpi_edges`
 * (tradehub/scripts/scan.py) deletes a `cpi_nowcast` row on the first hourly scan after its
 * `expires_at`, so a row is gone within an hour of its market closing, exactly like
 * `remove_stale_edges` prunes and `remove_closed_labor_edges` prunes. A row is a record of what the
 * scan did while the market it measured was still open to act on; it is not a permanent archive.
 * So the copy on screen says the bounded thing, because the unbounded thing is false. See
 * `RETENTION_SENTENCE` below, which the test file pins against drift back to the overclaim.
 *
 * That is also why `useMarketEdges` splits its read into `edges` and `withheld`, conserving every
 * row it was given. But a row that is read and then not rendered is, to a reader, indistinguishable
 * from there having been no rows -- so a MACRO tab that simply got quieter says "the engine was
 * retired" when what happened is "the engine was relabelled". An engine that is no longer an edge
 * engine has to be *visibly* relabelled.
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
 * matters is non-zero by definition. The one exception is a FAILED READ, which is not an absence --
 * see `readError` below.
 */

/**
 * The retention claim, as one string so the copy has exactly one home and the test can assert on
 * what is actually rendered.
 *
 * The earlier wording was "they are not deleted either, so the record of what the scan did
 * survives". That was false on screen: `remove_closed_cpi_edges` deletes every `cpi_nowcast` row
 * whose `expires_at` has passed, on every hourly scan, so the rows are gone within the hour their
 * market closes. The behaviour is defensible -- it is lifecycle cleanup of a closed market, not
 * hiding a losing engine, and `tests/test_cpi_no_edges.py` pins the delete as intended -- but a
 * claim the data does not back is the one failure this whole page exists to prevent. So the
 * sentence is bounded to the market's life.
 *
 * `RETENTION_UNCONDITIONAL` is the phrasing this must never drift back to. It is exported so the
 * test can forbid it by content rather than by inspection.
 */
export const RETENTION_SENTENCE =
  "Each is kept while its market is still open and is deleted when that market closes, so the " +
  "record of what the scan did survives for as long as the market it measured was open.";

/** The claim as it was written, and as it must not be written again. */
export const RETENTION_UNCONDITIONAL = ["not deleted", "never deleted", "permanently kept"];

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
  /**
   * A failure to read `kalshi_edges` at all. When set, nothing is claimed about the table: an
   * empty bucket is evidence only when the read that produced it succeeded, and a bucket emptied
   * by a failure is the exact "a row that never existed vs. one I could not see" ambiguity the
   * withholding rule exists to remove. So the authoritative copy below is SUPPRESSED and what
   * renders instead is the reason the bucket cannot be trusted.
   */
  readError?: string | null;
  /**
   * Whether the underlying read hit its row cap with more rows behind it. The count in the heading
   * is a count OF THE READ, and the hook reads the newest `readLimit` rows, so without this the
   * number reads as the table's row count and is not one.
   */
  truncated?: boolean;
  readLimit?: number;
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
  readError = null,
  truncated = false,
  readLimit = EDGES_READ_LIMIT,
  className = "",
}: WithheldEdgesNoticeProps<T>) {
  // A failed read outranks everything else, including a non-empty bucket. The hook clears both
  // buckets on failure, so this is defensive, but the direction matters: claim nothing rather than
  // claim from a read that did not complete.
  if (readError) {
    return (
      <section
        aria-label="Edge ledger could not be read"
        data-testid="edges-read-failure"
        className={`rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 ${className}`}
      >
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-rose-400" aria-hidden="true" />
          <h2 className="text-sm font-bold uppercase tracking-widest text-rose-200">
            Could not read the edge ledger
          </h2>
        </div>
        <p className="mt-1 text-xs text-rose-100/80">{readError}</p>
        <p className="mt-1 text-xs text-rose-100/70">
          This is a failed read, not an empty one. Nothing is claimed here: not that rows exist,
          and not that none do. The board above is empty for the same reason, and its emptiness is
          not a finding.
        </p>
      </section>
    );
  }

  if (withheld.length === 0) return null;

  // One paragraph per engine, not per row, so the rows stay visible inside the explanation.
  const byEngine = new Map<string, { reason: string; rows: T[] }>();
  for (const item of withheld) {
    const bucket = byEngine.get(item.engine) ?? { reason: item.reason, rows: [] };
    bucket.rows.push(item.edge);
    byEngine.set(item.engine, bucket);
  }

  const count = withheld.length;
  const rowsWord = count === 1 ? "row" : "rows";
  // The read is bounded at `readLimit`, newest first, so the heading counts the READ and not the
  // table. `truncated` is what distinguishes "that is all of them" from "there are more behind
  // this", which is the same distinction `/api/cpi-display` makes with its own `truncated`.
  const scope = truncated
    ? `of the newest ${readLimit} ${readLimit === 1 ? "row" : "rows"} read · the table holds more`
    : `of the ${readLimit} ${readLimit === 1 ? "row" : "rows"} read`;

  return (
    <section
      aria-label="Display-only engines, withheld from opportunities"
      className={`rounded-xl border border-amber-900/50 bg-amber-950/20 p-4 ${className}`}
    >
      <div className="flex items-center gap-2">
        <EyeOff className="h-4 w-4 text-amber-400" aria-hidden="true" />
        <h2 className="text-sm font-bold uppercase tracking-widest text-amber-200">
          Display-only engine{count === 1 ? "" : "s"} · withheld from opportunities ({count}{" "}
          {rowsWord} {scope})
        </h2>
      </div>

      <p className="mt-1 text-xs text-amber-100/70">
        These rows were read and are shown here on purpose. They are not opportunities, so they are
        not on the board above. {RETENTION_SENTENCE}
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
