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

/* ── What a failed read IS: the status and the code, never the prose ────────── */

/**
 * The three failed reads this endpoint can serve, and the machine-readable field that names each.
 *
 * `tradehub/api/main.py:_table_fault` has sent three distinguishable answers since PR #43 (`f856fb3`):
 *
 * | status | `X-Error-Code`        | what it is                                  | the next step        |
 * |--------|------------------------|---------------------------------------------|----------------------|
 * | 503    | `missing_table`        | a migration has not been applied            | apply a file        |
 * | 424    | `missing_credentials`  | the table is fine, a credential is not set  | set two env vars    |
 * | 500    | `internal_error`       | this code is broken                         | fix a bug           |
 *
 * Three different next steps, and until PR #43 all three arrived as prose in a `detail` with no way
 * to tell them apart. This file is the client half of that fix, and the rule it exists to hold is
 * that **`detail` is output, never input**. The status is the field a client branches on;
 * `X-Error-Code` is the same answer by name and is the narrower of the two, so it wins when it is
 * present and the status is the fallback for a response that did not carry it. Neither is prose, and
 * prose is not a machine-readable difference -- which is why the old code, which tested `detail` for
 * `supabase/migrations/`, called a 424 a fault: the 424 body says "this is not a migration" and has
 * no path in it, so the only branch this page had put a person setting environment variables behind
 * a red panel about a broken page. That is the undiagnosable outcome PR #43 set out to remove, and
 * it survived PR #43 because the frontend was never changed.
 */

/** `X-Error-Code`, spelled as `tradehub/api/main.py` sends it. */
export const SHADOW_ERROR_CODE_HEADER = "X-Error-Code";

const STATUS_MISSING_TABLE = 503;
const STATUS_MISSING_CREDENTIALS = 424;
const CODE_MISSING_TABLE = "missing_table";
const CODE_MISSING_CREDENTIALS = "missing_credentials";

/**
 * Which of the three a failed read is.
 *
 * The header decides when it arrived, because it is the narrower claim; the status decides when it
 * did not, because a proxy that does not forward custom headers is a real and ordinary thing and
 * must not turn an operator step back into a fault. Anything else -- a 502 from a load balancer, a
 * 500, a status this client has never heard of -- is a fault, which is the safe direction to be
 * wrong in: it never promises an operator a step that does not exist.
 */
function shadowFaultClass(status: number | null, errorCode: string | null): ShadowUnavailableClass {
  if (errorCode !== null) {
    if (errorCode === CODE_MISSING_CREDENTIALS) return "missing_credentials";
    if (errorCode === CODE_MISSING_TABLE) return "missing_table";
    return "internal_error";
  }
  if (status === STATUS_MISSING_CREDENTIALS) return "missing_credentials";
  if (status === STATUS_MISSING_TABLE) return "missing_table";
  return "internal_error";
}

export type ShadowUnavailableClass = "missing_table" | "missing_credentials" | "internal_error";

/**
 * The unavailable state, in the words a reader is actually looking at.
 *
 * Three presentations for three facts, and the third is the one this change added:
 *
 * - `waiting` -- a migration. `/api/shadow-performance` reads `signal_events`, the table
 *   `20260415090000_signal_events_unification.sql` creates by RENAMING `crypto_signal_events`, and
 *   that migration has never been applied to the live project, so the read has nothing to read. The
 *   API says so precisely and names the file, so the page surfaces that sentence and calls the
 *   state what it is: a deployment step waiting on a person. Correct before this change, and
 *   unchanged by it.
 * - `operator_step` -- an environment variable. The same shape and the same amber, because it is
 *   the same kind of fact about the same deployment, and a person closes it the same way. What
 *   changed is that this state exists at all: `vps-stack/compose.yml` passes no `ALPACA_*` to the
 *   tradehub service, so once the migration is applied this is the read every reader gets, and a
 *   red fault panel for it was telling them the product was broken when the only thing wrong was
 *   that two variables are unset.
 * - `fault` -- a bug in this code. The one that stays red, because it is the only one that is a
 *   claim about the code rather than about the deployment, and it is the only one no operator step
 *   closes.
 *
 * The same shape as `StoppedEnginesNotice` and `QuarantineNotice`: a heading that says which of the
 * states this is, and a sentence saying the absence is not a finding about the market. The two
 * operator states differ only in what the server's own sentence names, because that sentence is
 * already the instruction -- the two variables, the `.env` beside `vps-stack/compose.yml`, and the
 * `environment:` block that has to name them too -- and a second copy of it here would be a second
 * place to be wrong.
 */
export type ShadowUnavailableTone = "waiting" | "operator_step" | "fault";

export interface ShadowUnavailable {
  /** The heading. Never the bare string "API unavailable". */
  title: string;
  /** The lead-in, so the server's sentence is quoted rather than dumped. */
  lead: string;
  /** The server's own words, verbatim, when it sent any. */
  body: string | null;
  tone: ShadowUnavailableTone;
  /**
   * True when the read failed for a reason only a person can close, by going and doing something to
   * the deployment. False for a fault, which no operator step closes.
   *
   * For a missing credential this is the STATUS, and only the status: `_missing_credentials` is
   * emitted by exactly one branch of the server, so the status is as strong a claim as the answer
   * and does not go stale if the sentence is ever reworded.
   *
   * For a missing table it is the migration path in the body, and that asymmetry is deliberate
   * rather than an oversight. `_missing_table_message` forwards any non-PGRST runtime error through
   * the same 503, so a 503 on its own would promise an operator step that may not exist -- and the
   * lead above claims the table was renamed, which a body saying "cannot read the timeline: 42"
   * would contradict on screen. A file path is not a sentence, so reading one is not parsing prose;
   * it is the claim the panel is about to make, checked against the only text that can support it.
   */
  waiting_on_operator: boolean;
  /** The class the status and code resolved to. Kept so a caller can branch without re-deriving it. */
  failure: ShadowUnavailableClass;
  /** `X-Error-Code` as received, or null when the response carried none. */
  error_code: string | null;
}

/** Only the migration-naming path at `main.py:_missing_table_message` emits a path like this. */
const MIGRATION_PATH = /supabase\/migrations\//;

const WAITING_TITLE = "Waiting on a database migration";
const WAITING_LEAD =
  "This page is not broken and nothing is wrong with the charts. The table it reads was " +
  "renamed by a migration that has not been applied to the live database, so there is nothing " +
  "to read yet. Only an operator can finish this, and the step is:";

/**
 * The credential state, worded in the same four beats as `WAITING_LEAD` and deliberately not
 * naming the variables: the sentence underneath is the server's, it names them exactly, and
 * restating them here would be a second copy to keep in step with `CREDENTIAL_SOURCES` in
 * `tradehub/api/main.py`. Two operators is also not a fact about credentials in general -- a third
 * credentialed service is a one-line change there and would make a count printed here a lie.
 */
const CREDENTIAL_TITLE = "Waiting on environment variables";
const CREDENTIAL_LEAD =
  "This page is not broken, and nothing is wrong with the charts or with the database. The " +
  "shadow timeline reads market data from a service this deployment has no credentials for, so " +
  "there is nothing to read yet. Only an operator can finish this, and the step is:";

const FAULT_TITLE = "The shadow timeline could not be read";
const FAULT_LEAD = "The read failed and this page has nothing to show. The server said:";

/** What to print when the server explained nothing, worded from the status and not from the body. */
function noExplanation(status: number | null): string {
  return `The request failed${status == null ? "" : ` with status ${status}`} and the server sent no explanation.`;
}

/**
 * Word a failed read, from the status and the code.
 *
 * The evidence is consulted in one order, and the order is the whole content of this function:
 *
 *   1. `X-Error-Code`, if the response carried one. The narrowest claim, and a name rather than a
 *      number.
 *   2. The status, which is what decides when there was no header -- a proxy in front of the API may
 *      not forward custom headers, and an operator step that depends on a header surviving the
 *      network is not an operator step.
 *   3. A migration path in the body, and ONLY when there was neither a header nor a status at all.
 *
 * Step 3 is the last resort and it is narrow on purpose. A transport failure reaches this function
 * with no status and no code, and it must not lose a genuine deployment step the server named --
 * that behaviour is older than this change and is correct. But it is a PATH, never a sentence: with
 * no machine-readable field to read, the one thing in the body that is not English is a file path,
 * and a file path is the claim the migration panel is about to make, so checking it is checking the
 * claim rather than guessing at prose. It is deliberately not extended to credentials: naming a
 * variable in a sentence is English, and a 424 that never arrived here with a status is a shape this
 * client cannot claim anything about.
 *
 * A missing body is a real state -- a proxy that returned HTML, a body that was not JSON, a 424 from
 * a gateway that dropped the payload -- and it is rendered as a sentence rather than as an empty
 * paragraph.
 */
export function shadowUnavailable(
  status: number | null,
  detail: string | null,
  errorCode: string | null = null,
): ShadowUnavailable {
  const body = detail && detail.trim().length > 0 ? detail.trim() : null;
  const namesMigration = body !== null && MIGRATION_PATH.test(body);
  const noMachineSignal = errorCode === null && status === null;

  // Step 3, ahead of the classification because with no status and no code the classification has
  // nothing to work from and would answer "fault" for a sentence that names a file to apply.
  if (noMachineSignal && namesMigration) {
    return {
      title: WAITING_TITLE,
      lead: WAITING_LEAD,
      body,
      tone: "waiting",
      waiting_on_operator: true,
      failure: "missing_table",
      error_code: errorCode,
    };
  }

  const failure = shadowFaultClass(status, errorCode);

  if (failure === "missing_credentials") {
    return {
      title: CREDENTIAL_TITLE,
      lead: CREDENTIAL_LEAD,
      body: body ?? noExplanation(status),
      tone: "operator_step",
      waiting_on_operator: true,
      failure,
      error_code: errorCode,
    };
  }

  // See `waiting_on_operator`: the migration claim is checked against the path that supports it,
  // because `_missing_table_message` forwards non-table runtime errors through the same 503.
  const waiting = failure === "missing_table" && namesMigration;
  if (waiting) {
    return {
      title: WAITING_TITLE,
      lead: WAITING_LEAD,
      body,
      tone: "waiting",
      waiting_on_operator: true,
      failure,
      error_code: errorCode,
    };
  }

  return {
    title: FAULT_TITLE,
    lead: FAULT_LEAD,
    body: body ?? noExplanation(status),
    tone: "fault",
    waiting_on_operator: false,
    failure,
    error_code: errorCode,
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
