/**
 * Wording and shape for the engine scoreboard (spec section 9, approval 4).
 *
 * This module holds NO threshold, NO gate logic and NO rounding policy of its own. Every number it
 * prints is a number the response carried, and every verdict it words is a verdict the server
 * resolved:
 *
 *   - "is this engine ahead of the market" is `BEHIND_THE_MARKET = 1.0` in
 *     `tradehub/scoreboard.py`, applied once by `market_verdict`, and it rides on the row as
 *     `market_verdict`. Comparing ratios in TypeScript would be a second copy of a threshold in a
 *     second language, with nothing downstream able to tell which one the reader was shown.
 *   - the settled requirement and whether it is met is `settled_distance`, in the same module.
 *   - the headline, its kind, and the count that says how much of the board it covers are
 *     `market_comparison`, in the same module.
 *
 * What lives here is the layer the server cannot: how a resolved fact is worded, and the fail-safe
 * presentation of a figure nobody measured. Every formatter below returns a dash for anything it
 * cannot read, because a missing figure rendered as `0` or `0.0` is a measurement nobody made.
 *
 * Every engine currently loses (spec section 1). The temptation on a page like this is to soften
 * that -- "close", "competitive", a coloured delta that reads as near-parity. Gas sits at 4.29x the
 * market's Brier, which is not close, and a reader told otherwise cannot judge the engine. So
 * `brierVerdict` states the multiple and calls nothing close, and that is pinned by test.
 */

/** What one run's Brier is against the market's. `not_comparable` is "nobody measured this". */
export type MarketVerdict = "ahead" | "behind" | "level" | "not_comparable";

/** Which of the four server-side headlines this is. Not derivable from `any_beats_market`. */
export type HeadlineKind = "no_runs" | "not_comparable" | "behind" | "ahead";

/** Which bar `met` was a verdict against. `unknown` is "nothing here shows the gate ran". */
export type SettledBarSource = "gate" | "engine" | "unknown";

/**
 * BOTH bars, in the reducer's ten-field shape. Two, deliberately.
 *
 * The gate states its own requirement, which differs by cadence (200 daily, 50 monthly), and the
 * reviewer has a separate flat evidence floor. A monthly engine holding 70 settled has MET its own
 * 50 bar, so reporting it as 70/100 and unmet is a verdict against a number that was never its bar.
 * `required_source` is what stops the number and its attribution being read apart.
 */
export interface SettledDistance {
  n_settled: number;
  required: number | null;
  required_source: SettledBarSource;
  remaining: number | null;
  /** Tri-state: true, false, or null where nothing was measured. null is NOT false. */
  met: boolean | null;
  pct: number | null;
  floor: number | null;
  floor_remaining: number | null;
  floor_met: boolean | null;
  floor_pct: number | null;
}

export interface ScoreboardRow {
  engine: string;
  engine_version: string | null;
  mode: string;
  date_from: string | null;
  date_to: string | null;
  created_at: string | null;
  n_decisions: number | null;
  n_fills: number | null;
  n_settled: number | null;
  brier_ours: number | null;
  brier_market: number | null;
  brier_ratio: number | null;
  /** The server's verdict on this row. `BEHIND_THE_MARKET` is not re-applied here. */
  market_verdict: MarketVerdict;
  pnl_after_fees: number | null;
  max_drawdown: number | null;
  /** What `check_promotion_gate` returned when the run was recorded. NOT the promotion decision. */
  gate_status: string | null;
  /**
   * The full promotion decision, from the shared `latest_gate_statuses` lookup, keyed on
   * `(engine, engine_version)`. A field carrying the word PROMOTED off a partial gate reads as a
   * promotion to a human, so the two gates are carried separately and labelled separately.
   */
  promotion_status: string;
  gate_reasons: string[];
  settled_distance: SettledDistance | null;
}

export interface ScoreboardResponse {
  as_of: string;
  runs_read: number;
  rows: ScoreboardRow[];
  /** Distinct engine names among the rows. A row is one (engine, mode) pair. */
  engines: number;
  /** True when the promotion verdict could not be read: every row then reads SHADOW, unverified. */
  promotion_lookup_failed: boolean;
  rows_total: number;
  rows_behind_market: number;
  rows_ahead_of_market: number;
  rows_level_with_market: number;
  rows_not_comparable: number;
  any_beats_market: boolean;
  headline: string;
  headline_kind: HeadlineKind;
  /** The sentence qualifying the headline, when some row was never comparable. Otherwise null. */
  caveat: string | null;
}

/** Brier is `numeric(6,5)` and compared at the fifth decimal, so that is how it is shown. */
export function formatBrier(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toFixed(5);
}

/** A count, grouped. An unreadable one is a dash, never a zero. */
export function formatCount(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US");
}

/**
 * A simulated backtest figure in dollars, sign kept. `pnl_after_fees` and `max_drawdown` are
 * `numeric(12,4)`; a dash when absent, and a real `$0.00` when the measurement is genuinely zero --
 * those are different facts and the page has to be able to tell them apart.
 */
export function formatSimulatedMoney(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value < 0 ? "-" : ""}$${Math.abs(value).toFixed(2)}`;
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/**
 * How one row stands against the market, in words.
 *
 * Keyed on `row.market_verdict` rather than on `row.brier_ratio`, so the page cannot hold a second
 * copy of `BEHIND_THE_MARKET`. The multiple is stated rather than characterised: 4.29x is not
 * "competitive", and a reader told it was cannot judge the engine.
 */
export function brierVerdict(row: ScoreboardRow): string {
  const ratio = row.brier_ratio;
  if (row.market_verdict === "not_comparable" || !isNumber(ratio)) {
    return "Not measured: no market Brier was recorded for this run.";
  }
  if (row.market_verdict === "level") {
    return `Level with the market on Brier (ratio ${ratio.toFixed(2)}).`;
  }
  if (row.market_verdict === "ahead") {
    return `Ahead of the market: its Brier is ${ratio.toFixed(2)}x the market's.`;
  }
  return `${ratio.toFixed(1)}x the market's Brier — behind.`;
}

export type SettledBarKey = "own_gate" | "reviewer_floor";

/** One of the two bars, with everything the page needs to draw it and nothing it has to decide. */
export interface SettledBar {
  key: SettledBarKey;
  /** Shown as the bar's own heading, so a reader can tell the bars apart without reading prose. */
  label: string;
  /** The bar the response carried. null means it stated none -- never 0, which reads as "met". */
  required: number | null;
  /** Tri-state, passed through untouched: true, false, or null where nothing was measured. */
  met: boolean | null;
  /** Fill fraction as measured, already capped at 100 by the reducer. null where there is no bar. */
  pct: number | null;
  /** The numbers, already worded. Says why there is no number when there is none. */
  line: string;
}

/**
 * The two bars, always two, in a fixed order.
 *
 * Both are returned whether or not the response measured them, so a rendering that dropped one
 * would be dropping a value rather than a branch -- and the reviewer's floor is reported on every
 * row because "distance to the gate" is half the approval and the reviewer is the component that
 * will eventually make the keep-or-drop call.
 */
export function settledBars(row: ScoreboardRow): [SettledBar, SettledBar] {
  const d = row.settled_distance;
  const count = d && isNumber(d.n_settled) ? d.n_settled : null;

  const ownRequired = d && isNumber(d.required) && d.required > 0 ? d.required : null;
  const ownMet = ownRequired === null && d?.required_source !== "gate" ? (d?.met ?? null) : d?.met ?? null;
  const ownLine =
    ownRequired !== null
      ? `${count === null ? "?" : count} of ${ownRequired} settled` +
        (d?.remaining ? ` — ${d.remaining} more needed` : " — met")
      : d?.required_source === "engine"
        ? `${count === null ? "?" : count} settled — the gate named no bar, so its own bar is not ` +
          `recoverable from this run`
        : "Not measured: nothing in this run shows the gate ran.";

  const floorRequired = d && isNumber(d.floor) && d.floor > 0 ? d.floor : null;
  const floorLine =
    floorRequired === null
      ? "Not measured: the response carried no reviewer's floor."
      : `${count === null ? "?" : count} of ${floorRequired} settled` +
        (d?.floor_remaining ? ` — ${d.floor_remaining} more needed` : " — met");

  return [
    {
      key: "own_gate",
      label: "Own gate",
      required: ownRequired,
      met: ownMet,
      pct: ownRequired === null ? null : (d?.pct ?? null),
      line: ownLine,
    },
    {
      key: "reviewer_floor",
      label: "Reviewer's settled floor",
      required: floorRequired,
      met: d?.floor_met ?? null,
      pct: floorRequired === null ? null : (d?.floor_pct ?? null),
      line: floorLine,
    },
  ];
}

/**
 * The run's OWN backtest gate, worded so it cannot be read as the promotion decision.
 *
 * `backtest_runs.gate_status` is what `check_promotion_gate` returned at record time and it never
 * consulted `track_record`, so "PROMOTED" here means the backtest gate passed and nothing more.
 * The word "Promoted" is therefore not used for it; the promotion verdict is `promotion_status`,
 * and the page renders that through the shared `GateBadge`.
 */
export function backtestGateLabel(status: string | null | undefined): string {
  const known = typeof status === "string" ? status.trim().toUpperCase() : "";
  if (known === "PROMOTED") return "Backtest gate passed";
  if (known === "SHADOW") return "Backtest gate: shadow";
  return "Backtest gate: not recorded";
}

export interface ScoreboardSummary {
  /** The server's sentence, restated. Never recomputed here. */
  headline: string;
  headlineKind: HeadlineKind;
  /** The count that says how much of the board the headline covers. Null when nothing was skipped. */
  caveat: string | null;
  /** All four buckets, named. A row silently uncounted is how "3 of 5" becomes true of a board of 5. */
  counts: string;
  /**
   * How to present the headline. Taken from `headline_kind`, NOT from `any_beats_market` -- which
   * is False both when every engine lost and when nothing was comparable, and would paint a board
   * nobody measured as a board that had been beaten.
   */
  tone: "behind" | "ahead" | "unknown";
}

/** Restates the server's own headline and its caveat. Recomputing either here is how they drift. */
export function summarise(body: ScoreboardResponse): ScoreboardSummary {
  const tone =
    body.headline_kind === "behind" ? "behind" : body.headline_kind === "ahead" ? "ahead" : "unknown";
  return {
    headline: body.headline,
    headlineKind: body.headline_kind,
    caveat: body.caveat,
    counts:
      `${formatCount(body.rows_total)} rows · ` +
      `${formatCount(body.rows_behind_market)} behind the market · ` +
      `${formatCount(body.rows_ahead_of_market)} ahead · ` +
      `${formatCount(body.rows_level_with_market)} level · ` +
      `${formatCount(body.rows_not_comparable)} not comparable`,
    tone,
  };
}
