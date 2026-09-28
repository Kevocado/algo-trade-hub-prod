export interface ShadowThreshold {
  yes: number;
  no: number;
}

export interface ShadowFreshness {
  asset: string;
  latest_bar: string | null;
  age_hours: number | null;
  is_stale: boolean | null;
}

export interface ShadowSummary {
  evaluated_count: number;
  considered_count: number;
  dead_zone_count: number;
  hit_rate: number | null;
  brier_score: number | null;
  virtual_pnl_pct: number;
}

export interface ShadowPerformancePoint {
  timestamp: string;
  asset: string;
  market_ticker: string;
  probability_yes: number;
  threshold_side: string | null;
  threshold_triggered: boolean;
  current_price: number;
  next_hour_price: number;
  realized_yes: number;
  shadow_outcome: "win" | "loss";
  correct: boolean;
  virtual_return_pct: number;
}

export interface ShadowPerformanceResponse {
  domain: string;
  hours: number;
  generated_at: string;
  thresholds: Record<string, ShadowThreshold>;
  summary: ShadowSummary;
  freshness: Record<string, ShadowFreshness>;
  series: ShadowPerformancePoint[];
}

/* ── Words, not figures ───────────────────────────────────────────────────── */

/**
 * What goes in a figure's slot when the server sent no figure.
 *
 * A dash (`—`) is what this page used to print, and it is a figure that reads as
 * a number. `hit_rate` and `brier_score` are genuinely `None` from
 * `tradehub/scripts/shadow_performance.py:312` when nothing finished in the
 * window -- a measurement nobody made -- and a dash in a figure column is how
 * "not measured" becomes "measured as zero" the moment anyone screenshots the
 * board. So the slot says so in words. Same ruling, and the same reason, as
 * `UNMEASURED_SCORE` on `/models`.
 */
export const NO_FIGURE = "no completed signal finished in this window";

/**
 * Why this page is a different page from the engine scoreboard.
 *
 * The collision that sent the owner to the wrong page on 2026-09-28 was not
 * cosmetic: `/shadow` is the crypto shadow-timeline backtester and the engine
 * scoreboard is every engine's Brier against the market, and the two were one
 * word apart. This is the sentence the crypto page says to correct it, and it
 * lives here rather than in the page because prose is what nobody re-reads when
 * the chart is what they are looking at.
 *
 * The scoreboard's canonical route is `/scoreboard` and its name is "Engine
 * Scoreboard". An earlier revision of this branch made `/shadow-scoreboard`
 * canonical, which was wrong: "shadow" already means two other things in this
 * product, so that route would have kept the ambiguity alive in the one place
 * that is expensive to change. `/shadow-scoreboard` is a redirect now, so the
 * string the owner approved the page under still works without being the name.
 */
export const NOT_THE_SCOREBOARD =
  "This is the crypto shadow timeline, not the engine scoreboard. If you were " +
  "looking for how each engine scored against the market, that is the Engine Scoreboard.";

/**
 * The unavailable state, in the words a reader is actually looking at.
 *
 * `waiting` is the case that was broken. `/api/shadow-performance` reads
 * `signal_events`, the table `20260415090000_signal_events_unification.sql`
 * creates by RENAMING `crypto_signal_events`, and that migration has never been
 * applied to the live project -- so the read has nothing to read. The API
 * already says so, precisely, at `tradehub/api/main.py:246`, and it names the
 * file. So the page surfaces that sentence and calls the state what it is: a
 * deployment step waiting on a person, not a fault in this page and not a red
 * alarm. An operator reading "apply this file" knows what to do; an operator
 * reading "API unavailable" does not.
 */
export type ShadowUnavailableTone = "waiting" | "fault";

export interface ShadowUnavailable {
  /** The heading. Never the bare string "API unavailable". */
  title: string;
  /** The lead-in, so the server's sentence is quoted rather than dumped. */
  lead: string;
  /** The server's own words, verbatim, when it sent any. */
  body: string | null;
  tone: ShadowUnavailableTone;
  /**
   * True only when the server named a migration file, which is the only claim
   * on this page that is about something a human can go and do. It is keyed on
   * the server's sentence, not on a status code: `_missing_table_message`
   * forwards any non-PGRST runtime error through the same 503, so the status
   * code alone would promise an operator step that may not exist.
   */
  waiting_on_operator: boolean;
}

/** Only the migration-naming path at `main.py:66` emits a path like this. */
const MIGRATION_PATH = /supabase\/migrations\//;

const WAITING_TITLE = "Waiting on a database migration";
const WAITING_LEAD =
  "This page is not broken and nothing is wrong with the charts. The table it reads was " +
  "renamed by a migration that has not been applied to the live database, so there is nothing " +
  "to read yet. Only an operator can finish this, and the step is:";
const FAULT_TITLE = "The shadow timeline could not be read";
const FAULT_LEAD = "The read failed and this page has nothing to show. The server said:";

/**
 * Word a failed read. A missing body is a real state -- a proxy that returned
 * HTML, a body that was not JSON -- and it is rendered as a sentence rather than
 * as an empty paragraph.
 */
export function shadowUnavailable(status: number | null, detail: string | null): ShadowUnavailable {
  const body = detail && detail.trim().length > 0 ? detail.trim() : null;
  const waiting = body !== null && MIGRATION_PATH.test(body);
  return {
    title: waiting ? WAITING_TITLE : FAULT_TITLE,
    lead: waiting ? WAITING_LEAD : FAULT_LEAD,
    body: body ?? `The request failed${status == null ? "" : ` with status ${status}`} and the server sent no explanation.`,
    tone: waiting ? "waiting" : "fault",
    waiting_on_operator: waiting,
  };
}

/* ── Formatting ───────────────────────────────────────────────────────────── */

/**
 * Figure formatting, moved out of the page so this file can be tested for it.
 *
 * These take an already-non-null number. A null is the caller's business to
 * word as `NO_FIGURE` -- the point of the split is that there is no code path
 * from "no figure" to "0", in either direction.
 */
export function formatHitRate(hitRate: number): string {
  return `${(hitRate * 100).toFixed(1)}%`;
}

export function formatBrier4(brier: number): string {
  return brier.toFixed(4);
}

/** Signed, because the sign is the whole of a P&L figure. */
export function formatSignedPct(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function formatHours(hours: number): string {
  return `${hours.toFixed(2)}h`;
}

export function getShadowAssets(series: ShadowPerformancePoint[]): string[] {
  return Array.from(new Set(series.map((point) => point.asset))).sort();
}


export function filterShadowSeriesByAsset(
  series: ShadowPerformancePoint[],
  asset: string,
): ShadowPerformancePoint[] {
  return series.filter((point) => point.asset === asset);
}


export function getShadowThresholdValue(
  thresholds: Record<string, ShadowThreshold>,
  asset: string,
): number | null {
  const threshold = thresholds[asset];
  return threshold ? threshold.yes : null;
}


export function getShadowMarkerColor(point: ShadowPerformancePoint): string {
  if (!point.threshold_triggered) {
    return "transparent";
  }
  return point.correct ? "#10b981" : "#f43f5e";
}


export function getShadowMarkerRadius(point: ShadowPerformancePoint): number {
  return point.threshold_triggered ? 5 : 0;
}
