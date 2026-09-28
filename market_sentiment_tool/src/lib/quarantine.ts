import { NOT_MEASURED } from "@/lib/edgeFigures";

/**
 * The quarantine surface, and the one number it exists to prevent being misread.
 *
 * The Weather and Macro real-edge engines were repaired on 2026-09-28. They had been reading a
 * Kalshi quote field the API stopped sending, so every market they fetched looked like a 0c quote,
 * every one was skipped, and they published nothing while appearing to run (PR #38). Repaired, they
 * produce real output -- 295 rows on the measured run -- and **none of it is published**. The output
 * goes to `kalshi_quarantine_edges` and is read here.
 *
 * So the owner's question ("what would these engines do?") finally has an answer, and the answer is
 * 26. Not 295. This module exists because that gap is the whole content of the feature:
 *
 *     295  rows the scan produced
 *     213  rows that are not a units artefact
 *      26  independent opportunities. THIS is the number.
 *
 * A surface that showed "295 opportunities" would be a number on screen that looks authoritative and
 * is not, which is the exact failure this effort exists to prevent -- the same failure as PR #38's
 * "No high-confidence edges detected in weather", reached from the opposite direction.
 *
 * It holds NO threshold and NO arithmetic, on the same terms as `@/lib/scoreboard` and
 * `@/lib/edgeFigures`:
 *
 *   - whether a row is a units artefact is `edge_kind` from the server, decided in
 *     `tradehub/quarantine.py` by a WRITTEN threshold (95c). A client comparing a price to a number
 *     would be a second normaliser of the same fact, and a threshold that can drift from the one the
 *     rows were classified under.
 *   - whether a row is a restatement is `independent`, resolved in Python over the whole scan.
 *     Whether 143 rows are one GDP forecast restated across eleven year-events is a fact about the
 *     SET, and a client counting a subset of it is a number nobody can audit.
 *   - every count is the server's. There is no subtraction in this file.
 *
 * What it does decide is the thing the server cannot: how a quarantined figure is worded, and the
 * fail-safe presentation of a measurement that has not arrived.
 */

/** The marker the server sends. Travels in the payload and is rendered beside every figure. */
export const QUARANTINE_MARK = "QUARANTINED";

/**
 * The word for a quarantined engine, as a reader reads it. Not "stopped" (it runs) and not
 * "shadow" (which implies the trades are live but small).
 */
export const QUARANTINED_WORD = "quarantined";

/** The phrase that must never appear beside a quarantined board. See {@link QUARANTINE_FORBIDDEN}. */
export const OPPORTUNITY_HEADLINE_PHRASE = "opportunities found";

/**
 * The one sentence that must never appear on this surface.
 *
 * Exported so a test can forbid it by content rather than by inspection. "295 opportunities" is how
 * this page would collapse rows into claims, and it is the phrasing most likely to drift back in: it
 * is the natural thing to write for a list of rows.
 */
export const QUARANTINE_FORBIDDEN = "265 opportunities";

/** The measured counts, all resolved server-side. */
export interface QuarantineCounts {
  /** Rows the scan produced. NOT a count of opportunities. */
  rows: number;
  /** Rows that are not a units artefact. Still not independent opinions. */
  opportunities: number;
  /** Rows whose headline edge is a difference between the wrong two quantities. */
  units_artefacts: number;
  /**
   * Every `BUY NO` row, which carries a price taken from the YES side of the book. Wider than
   * `units_artefacts` and reported separately rather than folded in: at a sane price it is
   * arithmetically harmless, at 99c it is a headline nobody could act on.
   */
  buy_no_rows: number;
  /** Distinct (engine, asset, model probability) triples across the whole scan. */
  independent_forecasts: number;
  /** Rows whose forecast an earlier row already made. */
  restatements: number;
  /** THE HEADLINE. Opportunities that are also independent statements. */
  independent_opportunities: number;
  /** Opportunities that restate a forecast another row already made. */
  restated_opportunities: number;
}

/** One quarantined row, as the sink stored it at scan time. */
export interface QuarantineRow {
  market_id: string;
  title: string;
  engine: string | null;
  edge_type: string | null;
  action: string | null;
  market_ticker: string | null;
  event_ticker: string | null;
  /** Cents. NULL when the engine recorded no price -- never 0. */
  price_cents: number | null;
  model_probability_pct: number | null;
  edge_points: number | null;
  edge_kind: "opportunity" | "units_artefact" | null;
  independent: boolean | null;
  forecast_key: string | null;
  reasoning: string | null;
  kalshi_url: string | null;
  quarantined?: boolean;
  marker?: string;
}

export interface QuarantineEngineRollup {
  engine: string | null;
  marker: string;
  quarantined: boolean;
  note: string;
  counts: QuarantineCounts;
}

export interface QuarantineResponse {
  as_of: string;
  marker: string;
  quarantined: boolean;
  note: string;
  /** The row count. Present and 0 when the table is empty; see `measured` for what that means. */
  rows: number;
  /** Whether rows were actually read. False when the sink is empty, which is NOT a zero. */
  measured: boolean;
  /** Why nothing was measured, when it was not. Null when it was. */
  unmeasured_reason: string | null;
  /** null when not measured. A missing measurement is never a number. */
  totals: QuarantineCounts | null;
  engines: QuarantineEngineRollup[];
  reasons: Record<string, string>;
  /** Always 0. There is no code path from a quarantined row to `kalshi_edges`. */
  kalshi_edges_written: number;
  sink: string;
  rows_page: QuarantineRow[];
  limit?: number;
  offset?: number;
  read_count?: number;
  truncated?: boolean;
}

/**
 * The headline figure, or `NOT_MEASURED` when nothing was.
 *
 * `independent_opportunities` and not `rows` and not `opportunities`, and the order is the point:
 * 295 is what the scan produced, 213 is what survived the artefact filter, and 26 is how many
 * separate things the engines actually thought. A reader shown any of the other two has been shown
 * a number about rows while believing it is a number about opportunities.
 */
export function headlineCount(payload: QuarantineResponse | null | undefined): string {
  if (!payload?.totals) return NOT_MEASURED;
  return String(payload.totals.independent_opportunities);
}

/**
 * The sentence under the headline, and the reason 295 is not on it.
 *
 * Returns null when nothing was measured, so the caller renders the unmeasured branch rather than a
 * sentence about a scan that did not happen.
 */
export function headlineReason(payload: QuarantineResponse | null | undefined): string | null {
  if (!payload?.totals) return payload?.unmeasured_reason ?? null;
  const { rows, opportunities, restated_opportunities, units_artefacts } = payload.totals;
  return (
    `Independent opportunities, not rows. The scan produced ${rows} rows: ` +
    `${restated_opportunities} of the ${opportunities} non-artefact rows restate a forecast another ` +
    `row already made, and ${units_artefacts} carry an edge measured in the wrong units. The ` +
    `remaining ${payload.totals.independent_opportunities} are separate statements.`
  );
}

/**
 * The one-line summary, in the order a reader needs it: the finding, then the two things it is not.
 *
 * Each count agrees its own noun, on the same terms as `catalogueCounts` in `@/lib/models` -- "1
 * opportunities" is a number rendered wrong, and this is the page whose whole job is that the
 * numbers read right. A missing payload is a FAILURE and is worded as one, never "0 opportunities",
 * which is a claim that the engines found nothing.
 */
export function quarantineText(payload: QuarantineResponse | null | undefined): string {
  if (!payload) return "quarantine not in the response — the read did not arrive";
  if (!payload.measured || !payload.totals) {
    return payload.unmeasured_reason ?? "Nothing was measured, so there is no figure to show.";
  }
  const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);
  const { rows, independent_opportunities, restated_opportunities, units_artefacts } = payload.totals;
  return (
    `${independent_opportunities} independent ${plural(independent_opportunities, "opportunity", "opportunities")} · ` +
    `${rows} ${plural(rows, "row", "rows")} · ` +
    `${restated_opportunities} restated · ` +
    `${units_artefacts} ${plural(units_artefacts, "artefact", "artefacts")}`
  );
}

/**
 * Whether a row is a units artefact, from the classification stamped on it at scan time.
 *
 * A lookup, not a decision. The price threshold is in Python and was applied there, and a client
 * that re-derived it would be able to disagree with the rows it is displaying -- which is how a
 * surface ends up showing 82 artefacts and counting 91.
 */
export function isUnitsArtefact(row: QuarantineRow | null | undefined): boolean {
  return row?.edge_kind === "units_artefact";
}

/** The label for a row's kind, in words a reader uses. Null for a row that recorded neither. */
export function rowKindLabel(row: QuarantineRow | null | undefined): string | null {
  if (!row) return null;
  if (row.edge_kind === "units_artefact") return "Units artefact — not an opportunity";
  if (row.edge_kind === "opportunity") {
    return row.independent === false ? "Restatement of a forecast above" : "Independent opportunity";
  }
  return null;
}

/** The one-line summary for one engine, from the server's own per-engine counts. */
export function engineText(rollup: QuarantineEngineRollup | null | undefined): string {
  if (!rollup?.counts) return "no measurement";
  const { rows, independent_opportunities } = rollup.counts;
  return `${rollup.engine ?? "(unattributed)"}: ${independent_opportunities} independent of ${rows} rows`;
}
