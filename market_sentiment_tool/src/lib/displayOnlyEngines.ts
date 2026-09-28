/**
 * Which engines are DISPLAY engines, and the rule that stops them being presented as edges.
 *
 * CPI (`cpi_nowcast`) was approved display-only on 2026-09-27 (spec 5a, section 9 approval 3:
 * "DISPLAY ONLY. Show the nowcast vs the market for context; it's not an edge engine"). The
 * evidence is that the market prices this series about as accurately 5 days out (Brier 0.0710) as
 * it does 25 minutes before close (0.0677), so Kalshi is not pricing off the Cleveland Fed
 * nowcast, a nowcast-based model has nothing to exploit by being early, and at every lead we are
 * 1.33-1.43x behind with negative P&L. CPI is not a weak edge; it is not an edge.
 *
 * `scan_cpi` stopped writing `kalshi_edges` rows on the same date. That alone is not enough, for
 * two reasons this module exists to handle:
 *
 * 1. THE ROWS ARE NOT DELETED. They are a record of what the scan did, and the ruling is no
 *    migration: the standing rule is a read filter, because a filter keeps holding and a one-time
 *    delete does not. The `kalshi_edges` rows written before the change are still in the table.
 * 2. A READ THAT DROPS A ROW SILENTLY IS INDISTINGUISHABLE FROM THERE HAVING BEEN NO ROWS. That
 *    is the "unrecognised kinds" defect already ruled on in the sports path, where
 *    `sportsTierOf` returns null for a MACRO row and the MACRO tab simply gets quieter. A reader
 *    who sees the tab go empty concludes the engine was retired. It was not: it is relabelled.
 *
 * So `partitionDisplayOnly` never drops. Every row it is given comes back in exactly one of two
 * buckets, and a display-only row comes back WITH the reason it is not an edge. The count is
 * conserved on purpose -- that is what makes a missing bucket a detectable bug rather than a
 * plausible-looking empty state.
 */

/** Engines whose rows are context, not opportunities. Add to this only with a written ruling. */
export const DISPLAY_ONLY_ENGINES = ["cpi_nowcast"] as const;

export type DisplayOnlyEngine = (typeof DISPLAY_ONLY_ENGINES)[number];

/**
 * Why the engine is not an edge engine, in the words a reader actually reads.
 *
 * A bare flag is jargon, and the numbers behind it are the point: a model probability shown beside
 * a market price reads as an opportunity everywhere else in finance, so the label has to say what
 * the engine is rather than only what it is not.
 */
export const DISPLAY_ONLY_REASON: Record<DisplayOnlyEngine, string> = {
  cpi_nowcast:
    "Not an edge engine. CPI is shown for context only. Measured over 2026-06-01..2026-09-20 the " +
    "market's Brier score was 0.0677 at 25 minutes before close and 0.0710 five days out, so it " +
    "prices this series about as accurately a week ahead as in the last half hour. The market is " +
    "not pricing off the Cleveland Fed nowcast, so a nowcast-based model has nothing to exploit by " +
    "being early. At every lead this model is 1.33-1.43x behind the market, with negative P&L.",
};

/** The minimal shape this policy needs. Deliberately not the `KalshiEdge` type: it must not
 *  depend on the reader, or the rule and its consumer would move together. */
export interface EngineTagged {
  engine?: string | null;
}

export function isDisplayOnlyEngine(engine: string | null | undefined): boolean {
  if (typeof engine !== "string") return false;
  const normalized = engine.trim().toLowerCase();
  return (DISPLAY_ONLY_ENGINES as readonly string[]).includes(normalized);
}

export function isDisplayOnlyEdge(row: EngineTagged | null | undefined): boolean {
  return isDisplayOnlyEngine(row?.engine);
}

/** The sentence for a row's engine, or null when the engine IS an edge engine. */
export function displayOnlyReason(row: EngineTagged | null | undefined): string | null {
  const engine = row?.engine;
  if (typeof engine !== "string") return null;
  const normalized = engine.trim().toLowerCase() as DisplayOnlyEngine;
  return isDisplayOnlyEngine(normalized) ? DISPLAY_ONLY_REASON[normalized] : null;
}

export interface WithheldEdge<T> {
  /** The row exactly as read. Unmodified -- the numbers stay auditable. */
  edge: T;
  /** The engine it belongs to, so a caller can group the withheld set. */
  engine: DisplayOnlyEngine;
  /** Why this row is not presented as an opportunity. Never empty. */
  reason: string;
}

export interface PartitionedEdges<T> {
  /** Rows that ARE opportunities. Safe to render as edges. */
  edges: T[];
  /**
   * Rows deliberately held back, each with its reason. These are NOT dropped: a caller that
   * renders nothing for this bucket is making the filter silent, which is the defect.
   */
  withheld: WithheldEdge<T>[];
}

/**
 * Split a `kalshi_edges` read into what may be presented as an edge and what must be relabelled.
 *
 * Conservation is the contract: `edges.length + withheld.length === rows.length`, always. A row is
 * never silently discarded, and a display-only row never appears in `edges`.
 */
export function partitionDisplayOnly<T extends EngineTagged>(rows: T[]): PartitionedEdges<T> {
  const edges: T[] = [];
  const withheld: WithheldEdge<T>[] = [];
  for (const row of rows) {
    const reason = displayOnlyReason(row);
    if (reason === null) {
      edges.push(row);
      continue;
    }
    withheld.push({ edge: row, engine: row.engine!.trim().toLowerCase() as DisplayOnlyEngine, reason });
  }
  return { edges, withheld };
}
