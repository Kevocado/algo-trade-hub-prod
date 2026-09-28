/**
 * The three numbers on an edge row, and what it means when one of them was never measured.
 *
 * `useMarketEdges` used to normalise `our_prob`, `market_prob` and `edge_pct` with `?? 0`, so a row
 * that recorded neither the column nor a `raw_payload` fallback was handed to every page as a
 * model that rates the outcome at exactly zero and an edge of exactly 0.0%. Both are specific,
 * confident, and false:
 *
 *   * `our_prob: 0` is not "we have no view". It is "the model puts 0% on YES", which is a
 *     prediction, and the reader is entitled to act on a prediction.
 *   * `edge_pct: 0` is not "no opportunity". It is "we measured, and there is nothing here", and
 *     that is the single most misleading thing a display can say about a number it does not have.
 *
 * This is the same defect as the `$0.00` the War Room printed for a portfolio it had never
 * measured, one screen over: a figure the system did not measure, rendered in the exact shape of
 * one it did. The fix is not a better fallback value, it is a TYPE that can say `null` and a
 * renderer that says so in words.
 *
 * So the rule this module holds: a missing figure is `null` in the data and a dash with a reason
 * on screen, and a MEASURED zero is a number and is printed as one. Those are different facts and
 * the two branches never share an expression -- the classic way to get this wrong is
 * `value || 0`, which cannot tell them apart.
 *
 * Pure and dependency-free, so all of it is testable without a browser and without a network, and
 * so no calculated value has to live in a `.tsx`. The same arrangement as `lib/cpiDisplay.ts`.
 */

/** What an absent figure looks like on screen. A dash is a PLACEHOLDER, not a number. */
export const NOT_MEASURED = "—";

/** Why a dash is showing, in words. Never empty, so a `title` is never blank. */
export const NO_PROBABILITY_REASON =
  "No model probability was recorded for this row, so there is no figure to show. A dash here " +
  "is not a probability of zero.";
export const NO_MID_REASON =
  "No market quote was recorded for this row, so there is no price to show. A dash here is not " +
  "a market that priced this at zero.";
export const NO_EDGE_REASON =
  "No edge was recorded for this row. A dash means it was not measured -- not that the edge " +
  "was measured and found to be zero.";

const isNum = (raw: unknown): raw is number => typeof raw === "number" && Number.isFinite(raw);

/** Whether a figure was actually recorded. The badge colours branch on this, not on `value > 0`. */
export const edgePctNumber = (raw: number | null | undefined): raw is number => isNum(raw);

/**
 * One number for a field, from the column if it recorded one and from `raw_payload` if it did not.
 *
 * `divisor` is the unit conversion for the payload fallback only: `my_prob`/`yes_ask` are stored in
 * percent and the columns in [0, 1], so those divide by 100, while `raw_payload.edge` is already
 * the same unit as `edge_pct` and divides by 1.
 *
 * Null in, null out. The two failure modes this replaces were `x ?? 0` (a missing number becomes a
 * measured zero) and a truthiness test on the fallback (a recorded `my_prob` of 0 falls through to
 * the fabricated default, so a real zero was indistinguishable from a missing one). Both are gone:
 * a genuine 0 is a number and comes back as a number, and an absent one comes back as `null`.
 */
export function readNumber(
  column: unknown,
  payloadFallback: unknown,
  divisor: number,
): number | null {
  if (isNum(column)) return column;
  if (isNum(payloadFallback)) return payloadFallback / divisor;
  return null;
}

/** 0.523 -> "52.3%". Null -> a dash and the reason. */
export function probText(raw: number | null | undefined, unit: "percent" | "cents" = "percent"): string {
  if (!isNum(raw)) return NOT_MEASURED;
  return unit === "cents" ? `${(raw * 100).toFixed(1)}¢` : `${(raw * 100).toFixed(1)}%`;
}

/** The reason to attach to a dash from `probText`, so the dash is not the only thing on screen. */
export function probReason(raw: number | null | undefined, unit: "percent" | "cents" = "percent"): string | null {
  if (isNum(raw)) return null;
  return unit === "cents" ? NO_MID_REASON : NO_PROBABILITY_REASON;
}

/** 20 -> "+20.0%". Null -> a dash and the reason. */
export function edgePctText(raw: number | null | undefined): string {
  if (!isNum(raw)) return NOT_MEASURED;
  return `${raw > 0 ? "+" : ""}${raw.toFixed(1)}%`;
}

export function edgeReason(raw: number | null | undefined): string | null {
  return isNum(raw) ? null : NO_EDGE_REASON;
}

export interface MeanEdge {
  /** The mean over the rows that recorded one. Null when no row did -- a mean of nothing is not 0. */
  value: number | null;
  /** How many rows carried an edge figure. */
  measured: number;
  /** How many rows were on the board. */
  considered: number;
}

/**
 * The mean `edge_pct` of a board, over the rows that actually recorded one.
 *
 * The version this replaces was `reduce((a, b) => a + (b.edge_pct || 0), 0) / (edges.length || 1)`,
 * and it was wrong twice. An unmeasured row contributed 0 to the SUM and 1 to the DENOMINATOR, so
 * every missing figure quietly pulled the board's headline number down towards zero -- an average
 * that moved because data was absent. And `length || 1` turned an empty board into `0/1`, i.e. a
 * confident `0.00%` for a board with no edges on it at all.
 *
 * So the mean is over the measured rows only, `value` is null when there are none, and the caller
 * renders a dash. `measured`/`considered` are exposed so a page can say how much of the board the
 * number actually covers, which is the difference between a mean and a claim about a mean.
 */
export function meanEdgePct(rows: readonly { edge_pct: number | null }[]): MeanEdge {
  let sum = 0;
  let measured = 0;
  for (const row of rows) {
    if (isNum(row.edge_pct)) {
      sum += row.edge_pct;
      measured += 1;
    }
  }
  return {
    value: measured === 0 ? null : sum / measured,
    measured,
    considered: rows.length,
  };
}

/** The `title` for a mean, saying what it covers. Null when it is worth showing. */
export function meanEdgeReason(mean: MeanEdge): string | null {
  if (mean.value === null) {
    return mean.considered === 0
      ? "There are no edges on the board, so there is no average to report."
      : `None of the ${mean.considered} rows on the board recorded an edge figure, so there is ` +
        `nothing to average. A dash here is not an average edge of 0.00%.`;
  }
  if (mean.measured < mean.considered) {
    return (
      `Averaged over the ${mean.measured} of ${mean.considered} rows that recorded an edge ` +
      `figure; the other ${mean.considered - mean.measured} recorded none and are not counted ` +
      `as zeros.`
    );
  }
  return null;
}
