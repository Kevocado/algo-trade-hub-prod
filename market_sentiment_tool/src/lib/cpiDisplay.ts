/**
 * Copy rules for the CPI display.
 *
 * CPI was approved DISPLAY ONLY on 2026-09-27 (spec 5a, section 9 approval 3: "DISPLAY ONLY. Show
 * the nowcast vs the market for context; it's not an edge engine"). The evidence is that the market
 * prices this series about as accurately 5 days out (Brier 0.0710) as 25 minutes before close
 * (0.0677), so Kalshi is not pricing off the Cleveland Fed nowcast, a nowcast-based model has
 * nothing to exploit by being early, and at every lead we are 1.33-1.43x behind with negative P&L.
 * CPI is not a weak edge. It is not an edge.
 *
 * THIS MODULE EXISTS BECAUSE THE PAGE CAN MISREPRESENT THE ENGINE ON ITS OWN. A model probability
 * beside a market price reads as an opportunity everywhere else in finance, so the label has to be
 * in the row, not only in the page title. Four claims the endpoint makes about itself have to
 * survive into the rendering, and each of them is a claim a reader would otherwise have to assume:
 *
 *   1. `gate_checked: false` -- the gate was NEVER CHECKED. `gate_status` is "SHADOW" only because
 *      the gate fails closed, and "SHADOW" is the gate's own vocabulary: it reads as a verdict that
 *      was reached, i.e. as *pending*. Section 5 records CPI as REFUTED, not as pending, and a
 *      pending engine is a live opportunity in everything but name. So nothing here prints the bare
 *      value, and a checked gate is the only case that reports a verdict.
 *   2. `truncated` -- the read is bounded, so a truncated list must not read as a complete one.
 *   3. `withheld_count` / `withheld_reason` -- a release with no market mid is shown and says it is
 *      not a comparison. A withheld row without its reason is a silent filter with extra steps.
 *   4. `comparable` -- and, underneath all of it, a figure the scan did not record is rendered as
 *      words. Never as 0, never as 0.0, never as a dash standing in for a number: a CPI release with
 *      no market mid has NO market probability, which is a different fact from a market probability
 *      of zero.
 *
 * Everything here is pure, so all of it is testable without a browser and without a network.
 *
 * UNITS, because getting them wrong is a 100x error that still typechecks: `our_prob` and
 * `market_prob` are probabilities in [0, 1]. `nowcast` and `sigma` are NOT. `nowcast` is the
 * Cleveland Fed's CPI **month-over-month percent change** -- the chart's own y-axis is
 * "Month-over-month percent change" and a real reading is 0.39, i.e. +0.39% MoM
 * (tests/fixtures/cleveland_nowcast_month_trimmed.json). `cpi_prob` (tradehub/engines/cpi.py:83)
 * compares `nowcast + bias` against `yes_interval(market, CPI_RESOLUTION)` with `CPI_RESOLUTION =
 * 0.1`, so nowcast, sigma and the market's strike all live in the same space: percentage points of
 * MoM change. Rendering 0.39 as "39%" would say the print is forty times larger than it is.
 */

export interface CpiDisplayRow {
  market_ticker: string | null;
  /** P(Kalshi resolves YES), 0..1. Null when the scan did not record one. */
  our_prob: number | null;
  /** The quote mid. NOT what an edge would be measured against -- there is no edge here. */
  market_prob: number | null;
  /** Present and always null. Asserted by the endpoint so a client has to handle the absence. */
  edge_pct: null;
  /** CPI month-over-month percent change, in percentage points. 0.39 means +0.39% MoM. */
  nowcast: number | null;
  nowcast_obs: string | null;
  /** Standard deviation of the MoM print, same units as `nowcast`. */
  sigma: number | null;
  n_train: number | null;
  hours_to_close: number | null;
  /** The ledger's own timestamp. NOT `updated_at`: `predictions` has no such column. */
  as_of: string | null;
  /** So a row from a market that closed last month cannot render as if it were live. */
  status: string | null;
  /** True when there is a market mid to set the nowcast against. */
  comparable: boolean;
  /** Why this row is withheld FROM THE COMPARISON. Never withheld from the page. */
  withheld_reason: string | null;
  gate_status: string;
  gate_checked: boolean;
}

export interface CpiDisplayResponse {
  as_of: string;
  mode: string;
  engine: string;
  suggest_only: boolean;
  reason: string;
  edge_pct: null;
  gate_status: string;
  gate_checked: boolean;
  gate_checked_reason: string;
  row_order: string;
  rows: CpiDisplayRow[];
  /** Rows read. A FLOOR, not a count, whenever `truncated` is true. */
  total: number;
  truncated: boolean;
  /** Over the whole read, not this page. A page cannot supply it. */
  withheld_count: number;
  limit: number;
  offset: number;
}

/**
 * Display-only unless the payload positively claims otherwise.
 *
 * Fails closed, in the same direction as the promotion gate: an older payload, or one missing
 * `mode`, is not evidence that this engine became an edge engine.
 */
export function isDisplayOnly(payload: { mode?: string } | null | undefined): boolean {
  return (payload?.mode ?? "display") === "display";
}

// ── figures ───────────────────────────────────────────────────────────────────

/** A figure with its honest absence. `value` is null when the response carried none. */
export interface Measure {
  value: string | null;
  known: boolean;
  /** Why it is unknown, in words. Empty when it is known. */
  note: string;
}

export const NOT_RECORDED = "not recorded";
const NOT_A_PROBABILITY =
  "No model probability was recorded for this release, so there is nothing to compare.";
const NOT_A_MID =
  "No market mid was recorded for this release, so there is no market probability to set the " +
  "nowcast against. A missing mid is not a market mid of zero.";

const isNum = (raw: number | null | undefined): raw is number =>
  typeof raw === "number" && Number.isFinite(raw);

function measure(formatted: string | null, note: string): Measure {
  return formatted === null
    ? { value: null, known: false, note }
    : { value: formatted, known: true, note: "" };
}

/** 0.55 -> "55.0%". `null` is a fact, not a zero, and is rendered as words. */
export function probMeasure(raw: number | null | undefined, note = NOT_A_PROBABILITY): Measure {
  return measure(isNum(raw) ? `${(raw * 100).toFixed(1)}%` : null, note);
}

/**
 * 0.39 -> "+0.39% MoM". Percentage points of month-over-month change, NOT a probability -- see
 * the unit note at the top of this file. A genuine 0 is a measurement and is rendered; only an
 * absent value is not.
 */
export function nowcastMeasure(raw: number | null | undefined): Measure {
  return measure(isNum(raw) ? `${raw >= 0 ? "+" : ""}${raw.toFixed(2)}% MoM` : null, NOT_RECORDED);
}

/** 0.15 -> "±0.15pp". Null sigma prints nothing rather than a zero-width band. */
export function sigmaText(raw: number | null | undefined): string | null {
  return isNum(raw) ? `±${raw.toFixed(2)}pp` : null;
}

export function hoursText(raw: number | null | undefined): Measure {
  return measure(isNum(raw) ? `${raw.toFixed(1)}h` : null, "close time not recorded");
}

/** An ISO timestamp, or null. Never "Invalid Date", and never today's date standing in for one. */
export function stampText(raw: string | null | undefined): string | null {
  if (typeof raw !== "string" || raw.trim() === "") return null;
  const at = new Date(raw);
  return Number.isNaN(at.getTime()) ? null : at.toISOString().replace("T", " ").slice(0, 16) + "Z";
}

/** A status the row actually carries, or an honest "state not reported". */
export function statusText(raw: string | null | undefined): string {
  return typeof raw === "string" && raw.trim() !== "" ? raw.trim().toUpperCase() : "state not reported";
}

// ── the four claims ───────────────────────────────────────────────────────────

export interface GateNote {
  /** The one line a reader sees. Never the bare gate value on its own. */
  headline: string;
  detail: string;
  checked: boolean;
}

const UNCHECKED_GATE_DETAIL =
  "No gate was consulted and none is expected. cpi_nowcast is a display engine, not a candidate " +
  "for promotion, so there is nothing for a gate to rule on.";

/**
 * Obligation 1: say the gate was never checked, not that it was checked and declined.
 *
 * `SHADOW` stays the wire value so a string-checking client is safe, but printing it is the defect:
 * it is the gate's own vocabulary, it means "not promoted", and against a REFUTED engine it reads
 * as a live candidate waiting its turn. So the unchecked branch never emits that word, and this is
 * the only branch that reports a verdict.
 */
export function cpiGateNote(payload: CpiDisplayResponse | null | undefined): GateNote {
  if (payload?.gate_checked !== true) {
    return {
      checked: false,
      headline: "Gate: never checked — none applies to a display engine",
      detail:
        (typeof payload?.gate_checked_reason === "string" && payload.gate_checked_reason.trim()) ||
        UNCHECKED_GATE_DETAIL,
    };
  }
  const verdict = (payload?.gate_status || "unknown").toUpperCase();
  return {
    checked: true,
    headline: `Gate: checked — ${verdict}`,
    detail: "A promotion gate was consulted for this engine and returned the verdict above.",
  };
}

/** Obligation 2: the bounded read says so. Null when the read was not truncated. */
export function cpiTruncationNote(payload: CpiDisplayResponse | null | undefined): string | null {
  if (payload?.truncated !== true) return null;
  const read = typeof payload.total === "number" ? payload.total : 0;
  return (
    `Truncated. ${read} rows were read and the ledger holds more, so this list is not the whole ` +
    `set — the older history was not fetched. "total" below is a floor, not a count.`
  );
}

/**
 * Obligation 2 again: `withheld_count` is over the WHOLE read, so the page must not derive its own
 * count from the rows it happens to be holding. On page 2 a page-derived count reads "nothing
 * withheld" while page 1 had one, which is the same shape as the sports board's reject banner.
 */
export function cpiCoverageNote(payload: CpiDisplayResponse | null | undefined): string {
  const read = typeof payload?.total === "number" ? payload.total : 0;
  const shown = Array.isArray(payload?.rows) ? payload.rows.length : 0;
  const withheld = typeof payload?.withheld_count === "number" ? payload.withheld_count : 0;
  const readPart =
    payload?.truncated === true
      ? `at least ${read} rows read`
      : `${read} row${read === 1 ? "" : "s"} read`;
  const withheldPart =
    withheld > 0
      ? `${withheld} of the read ${withheld === 1 ? "has" : "have"} no market mid, so ${
          withheld === 1 ? "it is" : "they are"
        } listed without a comparison`
      : "every row read has a market mid to set the nowcast against";
  return `${readPart} · ${shown} on this page · ${withheldPart}`;
}

/**
 * The per-row sentence. No edge figure, ever — there is not one, and the label must not then hand
 * the reader a number that looks like one. Carries `comparable`/`withheld_reason`, the nowcast and
 * its source, the lead, the ledger's own timestamp and state, and the words "not an edge".
 */
export function cpiRowNote(row: CpiDisplayRow): string {
  const nowcast = nowcastMeasure(row?.nowcast);
  const sigma = sigmaText(row?.sigma);
  const lead = hoursText(row?.hours_to_close);
  const at = stampText(row?.as_of);
  const parts: string[] = [];
  parts.push(
    nowcast.known
      ? `Cleveland Fed nowcast ${nowcast.value}${sigma ? ` ${sigma}` : ""}${
          row.nowcast_obs ? ` from ${row.nowcast_obs}` : ""
        }`
      : "Cleveland Fed nowcast not recorded",
  );
  parts.push(lead.known ? `${lead.value} to close` : lead.note);
  // The state is reported whether or not the timestamp is, so a row missing one still cannot read
  // as live. Neither field is ever substituted for the other.
  parts.push(
    at
      ? `recorded ${at} (${statusText(row.status)})`
      : `ledger time not reported (${statusText(row.status)})`,
  );
  // The comparison's own status, in words. A withheld row without its reason is a silent filter.
  parts.push(
    row?.comparable === true
      ? "comparable against the market mid"
      : row?.withheld_reason?.trim() || "not comparable: no market mid was recorded",
  );
  parts.push("not an edge");
  return parts.join(" · ");
}

export interface CpiHeadline {
  label: string;
  value: string;
  tone: "default" | "muted";
}

/**
 * Counts rows and labels the mode. It deliberately carries no win/loss word: nothing has been
 * traded and nothing has settled here, so any outcome word would be a claim.
 */
export function cpiHeadline(payload: CpiDisplayResponse | null | undefined): CpiHeadline {
  const shown = Array.isArray(payload?.rows) ? payload.rows.length : 0;
  return {
    label: isDisplayOnly(payload) ? "CPI nowcast vs market — display only" : `CPI nowcast vs market (${payload?.mode})`,
    value: `${shown} market${shown === 1 ? "" : "s"} shown, for context`,
    tone: isDisplayOnly(payload) ? "muted" : "default",
  };
}

/** The suggest-only line. Present so the page states the product's nature, not just the engine's. */
export function suggestOnlyNote(payload: CpiDisplayResponse | null | undefined): string | null {
  return payload?.suggest_only === true
    ? "Suggest-only: this product places no orders, and nothing on this page is a trade."
    : null;
}
