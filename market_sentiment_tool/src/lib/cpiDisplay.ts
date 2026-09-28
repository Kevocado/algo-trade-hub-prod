/**
 * Copy rules for the CPI display.
 *
 * CPI was approved DISPLAY ONLY on 2026-09-27 (spec 5a, section 9 approval 3, quoted verbatim from
 * docs/superpowers/specs/2026-09-27-hub-redesign.md:505: "DISPLAY ONLY. Show the nowcast against
 * the market for context; not an edge engine."). The evidence is that the market
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
 *      A page that FILTERS those rows away has to keep counting them, and that is the whole reason
 *      the count is over the whole read rather than the page.
 *   4. `comparable` -- and, underneath all of it, a figure the scan did not record is rendered as
 *      words. Never as 0, never as 0.0, never as a dash standing in for a number: a CPI release with
 *      no market mid has NO market probability, which is a different fact from a market probability
 *      of zero.
 *
 * Plus two more, added when the page was shortened: `read_count` (rows the read examined, which is
 * not `total` once `comparable` has filtered) and `comparable_only` (whether it filtered, so a
 * reader is told why the list is short rather than left to wonder).
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
  /** Training-set size. A sigma printed without it is a number of unknown origin. */
  n_train: number | null;
  /**
   * True when the engine had too few nowcast/print pairs to fit an error model and used its
   * hardcoded fallback sigma, so `our_prob` came from a CONSTANT. False when it fitted. `null` when
   * `n_train` was not recorded -- which is not evidence either way, so the row says the count is
   * unknown rather than asserting which of the two it was.
   */
  default_error_model: boolean | null;
  /** Why it is a default, in words. Present exactly when `default_error_model` is true. */
  default_error_model_reason: string | null;
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
  /**
   * The number of rows in the set THIS RESPONSE DESCRIBES: the whole read, or the comparable
   * subset when `comparable_only` is on. A FLOOR, not a count, whenever `truncated` is true.
   *
   * Not the number of rows read -- `read_count` is that, and the two differ the moment the page
   * asks for comparable rows only. `total` used to be read as "rows read" on the page, which is
   * only true when nothing has been filtered.
   */
  total: number;
  truncated: boolean;
  /** Over the whole read, not this page. A page cannot supply it. */
  withheld_count: number;
  /**
   * How many rows the bounded read examined, BEFORE `comparable` removed any. This is the "N rows
   * read" a page is entitled to print, and the number the reader needs in order to check the
   * others: with `comparable_only` on, `read_count === total + withheld_count` exactly.
   */
  read_count: number;
  /**
   * Whether the endpoint applied the comparable filter. Echoed because a short page has to be able
   * to say WHY it is short, and a client that cannot tell "this is all of them" from "this is the
   * comparable subset" would be rendering a window the response never described.
   */
  comparable_only: boolean;
  limit: number;
  offset: number;
}

/**
 * How many recent comparable rows the page asks for.
 *
 * A deliberate low-teens number, and here is the reasoning, because the choice is a product
 * decision rather than a default:
 *
 * * The page's job is the COMPARISON -- nowcast against the market. A release with no market mid has
 *   no comparison in it. On 2026-09-28 the unfiltered read returned 50 rows with 69 withheld across
 *   the read, and of the first three only one was comparable, so most of what the page showed was
 *   rows with nothing to set the nowcast against. That is the padding, and it is what
 *   `comparable=true` removes.
 * * It is RECENT, not a history. CPI runs three scans a day (08/12/16 ET) over a handful of open
 *   markets, so a low-teens count is roughly three to four scan runs -- about a day of releases.
 *   That is enough for a reader to see the nowcast/market pair at more than one timestamp, which is
 *   the minimum for "vs market" to mean anything, and it stops short of the two-month tail a
 *   bounded 200-row read would otherwise offer.
 * * It is a SMALLER number than the row limit the page used to pass (50) by an order of magnitude,
 *   which is the actual complaint: the page was showing everything, including what did not make it.
 *
 * It lives here, beside the copy that describes the page, and not in the component: the number is
 * a request parameter, and the honest place for a rule a reader is shown is next to that reader.
 * The endpoint is told the count, not left to assume one -- and it does not clamp it, because a
 * short page enforced server-side would be a policy the reader could not see. Pinned by
 * `CpiDisplay.test.tsx` (the URL the page actually requests) and by `tests/test_cpi_display.py`
 * (that the endpoint serves this exact count through the filter).
 */
export const CPI_CONTEXT_ROWS = 12;

/** True when the endpoint filtered to comparable rows, whatever the page asked for. */
export function isComparableOnly(payload: CpiDisplayResponse | null | undefined): boolean {
  return payload?.comparable_only === true;
}

/**
 * How many rows the read examined. Falls back to `total` for an older payload that predates
 * `read_count`, so the count a page prints is never silently the wrong one.
 */
export function readCount(payload: CpiDisplayResponse | null | undefined): number {
  if (typeof payload?.read_count === "number") return payload.read_count;
  return typeof payload?.total === "number" ? payload.total : 0;
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

/**
 * 24 -> "24 pairs". The size of the set a sigma was measured over.
 *
 * Published, not optional decoration: `fit_cpi_error` returns a hardcoded DEFAULT_CPI_ERROR
 * whenever it has fewer than CPI_MIN_TRAIN pairs, so a sigma -- and a probability derived from it
 * -- used to sit on the page looking exactly like one from a fit. The count is what tells them
 * apart, and `cpiRowNote` pairs it with `default_error_model` so the distinction is made in words
 * rather than left to a reader who would not know to look.
 */
export function nTrainText(raw: number | null | undefined): string | null {
  return isNum(raw) ? `${raw} pair${raw === 1 ? "" : "s"}` : null;
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

/**
 * Obligation 2: the bounded read says so. Null when the read was not truncated.
 *
 * `read_count` rather than `total`, and that is the whole reason it is not a cosmetic change: once
 * the page asks for comparable rows only, `total` is the number of COMPARABLE rows, so printing it
 * as "N rows were read" would be a different and smaller number than the one that was read. The
 * sentence still ends by calling `total` a floor, which remains true of a filtered set.
 */
export function cpiTruncationNote(payload: CpiDisplayResponse | null | undefined): string | null {
  if (payload?.truncated !== true) return null;
  const read = readCount(payload);
  return (
    `Truncated. ${read} rows were read and the ledger holds more, so this list is not the whole ` +
    `set — the older history was not fetched. "total" below is a floor, not a count.`
  );
}

/**
 * Obligation 2 again: `withheld_count` is over the WHOLE read, so the page must not derive its own
 * count from the rows it happens to be holding. On page 2 a page-derived count reads "nothing
 * withheld" while page 1 had one, which is the same shape as the sports board's reject banner.
 *
 * It is also the obligation that has to survive the page getting SHORTER, and that is the point of
 * the second half. With `comparable_only` the page does not even show the withheld rows, so nothing
 * on screen would reveal that any were dropped: without the count, a 12-row list of comparable
 * releases and a 12-row list chosen at random from 200 would render identically. The count is what
 * distinguishes them, which is why it is counted over the read rather than derived from `rows`.
 */
export function cpiCoverageNote(payload: CpiDisplayResponse | null | undefined): string {
  const read = readCount(payload);
  const shown = Array.isArray(payload?.rows) ? payload.rows.length : 0;
  const withheld = typeof payload?.withheld_count === "number" ? payload.withheld_count : 0;
  const filtered = isComparableOnly(payload);
  const readPart =
    payload?.truncated === true
      ? `at least ${read} rows read`
      : `${read} row${read === 1 ? "" : "s"} read`;
  const shownPart = filtered
    ? `${shown} of the ${typeof payload?.total === "number" ? payload.total : 0} comparable on this page`
    : `${shown} on this page`;
  if (withheld <= 0) {
    return `${readPart} · ${shownPart} · every row read has a market mid to set the nowcast against`;
  }
  const withheldPart =
    `${withheld} of the read ${withheld === 1 ? "has" : "have"} no market mid, so ` +
    (filtered
      ? `${withheld === 1 ? "it is" : "they are"} not listed: a release with no quote is nothing to set the nowcast against`
      : `${withheld === 1 ? "it is" : "they are"} listed without a comparison`);
  return `${readPart} · ${shownPart} · ${withheldPart}`;
}

/**
 * Why the list is short, when it is short because the endpoint filtered it.
 *
 * Null unless `comparable_only` is on, so an unfiltered page says nothing here. The wording
 * deliberately does NOT claim "the N most recent comparable releases": that is only true at
 * `offset: 0`, and a sentence that is true of one page and false of the next is exactly the kind
 * of window-misdescription this page is built to avoid. It says the order and the cap instead, both
 * of which are the response's own fields.
 */
export function cpiComparableNote(payload: CpiDisplayResponse | null | undefined): string | null {
  if (!isComparableOnly(payload)) return null;
  const cap = typeof payload?.limit === "number" ? payload.limit : 0;
  return (
    `Comparable releases only, newest first, up to ${cap} row${cap === 1 ? "" : "s"}. A release ` +
    `scanned before its first quote has no market mid and so is nothing to set the nowcast ` +
    `against; those are counted below rather than listed here.`
  );
}

/**
 * The empty board, and the one case where the obvious wording is false.
 *
 * "No CPI markets in the ledger right now" is the right sentence for a ledger with nothing in it.
 * It is a lie for a ledger that holds 200 rows of which none carries a market mid -- which is
 * exactly what a `comparable=true` read can return, and exactly what a reader would be told by the
 * old string. So the state that distinguishes them is named: rows were read, and none of them is
 * comparable. Same reason the failed read is a 503 rather than an empty list, one layer up.
 */
export function cpiEmptyNote(payload: CpiDisplayResponse | null | undefined): string {
  const read = readCount(payload);
  const withheld = typeof payload?.withheld_count === "number" ? payload.withheld_count : 0;
  if (isComparableOnly(payload) && withheld > 0) {
    return (
      `${withheld} CPI release${withheld === 1 ? "" : "s"} ${withheld === 1 ? "was" : "were"} read ` +
      `and none of them carries a market mid, so there is nothing to compare yet. This is not an ` +
      `empty ledger: the rows are there, they just cannot be set against the market.`
    );
  }
  if (read > 0) {
    return (
      `${read} row${read === 1 ? "" : "s"} were read and none of them could be shown. That is not ` +
      `the same as an empty ledger, and it is not a claim that the nowcast has no markets.`
    );
  }
  return (
    "No CPI markets in the ledger right now. The nowcast is published on a schedule, so an empty " +
    "board between prints is expected rather than a fault."
  );
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
  // The error model's provenance, next to the sigma it produced. This is the INVERSE of the rule
  // above and the same class of defect: a figure the scan did not measure, presented in the shape
  // of one it did. `null` (n_train absent) is not evidence either way, so the row says the count
  // is unknown rather than guessing, and it never claims a fit it cannot see.
  if (row?.default_error_model === true) {
    parts.push(
      row.default_error_model_reason?.trim() ||
        "the error model is the engine's default, not a fit, so this probability came from a constant",
    );
  } else if (nTrainText(row?.n_train)) {
    parts.push(`error model fitted on ${nTrainText(row?.n_train)}`);
  } else {
    parts.push("training-set size not recorded, so the error model's origin is unknown");
  }
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
 *
 * The comparable-only case says so in the count itself rather than only in the note below, because
 * a headline reading "12 markets shown" beside a ledger that holds 200 is the exact shape of a
 * figure that has been quietly redefined -- the reader has to be able to see from the count that
 * these twelve are the comparable ones.
 */
export function cpiHeadline(payload: CpiDisplayResponse | null | undefined): CpiHeadline {
  const shown = Array.isArray(payload?.rows) ? payload.rows.length : 0;
  const qualifier = isComparableOnly(payload) ? "comparable " : "";
  return {
    label: isDisplayOnly(payload) ? "CPI nowcast vs market — display only" : `CPI nowcast vs market (${payload?.mode})`,
    value: `${shown} ${qualifier}market${shown === 1 ? "" : "s"} shown, for context`,
    tone: isDisplayOnly(payload) ? "muted" : "default",
  };
}

/** The suggest-only line. Present so the page states the product's nature, not just the engine's. */
export function suggestOnlyNote(payload: CpiDisplayResponse | null | undefined): string | null {
  return payload?.suggest_only === true
    ? "Suggest-only: this product places no orders, and nothing on this page is a trade."
    : null;
}
