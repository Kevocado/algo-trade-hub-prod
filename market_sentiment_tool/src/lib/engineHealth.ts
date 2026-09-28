import { NOT_MEASURED } from "@/lib/edgeFigures";

/**
 * The edge board's empty states, and the one distinction it could not make until now.
 *
 * The defect: Kalshi's API stopped sending `yes_ask`, and the Tier-1 real-edge weather and macro
 * engines still read it with a `0` default (`weather_engine.py:214`, `macro_engine.py:453`). Every
 * market they fetch reads as a 0c quote, so they skip all of them and publish nothing -- and they
 * raise nothing either, because skipping an unpriceable market is the right move. The engines fail
 * CLOSED. Nothing wrong was ever written to the ledger, which is exactly why nobody noticed, and
 * also why nothing anywhere said so either: the WEATHER tab rendered "No high-confidence edges
 * detected in weather", and that sentence is a FINDING. The engine had not looked for anything.
 *
 * So this module exists to keep two things apart that the product used to render identically:
 *
 *   - an engine that RAN and found no qualifying opportunity. A measurement. The empty board IS
 *     the finding, and it is the only one of the two that is allowed to say "nothing here".
 *   - an engine that COULD NOT RUN. The absence of a measurement. There is no finding, and the
 *     absence is never a number.
 *
 * This is the rule `lib/displayOnlyEngines.ts` already keeps for CPI, applied one step earlier. Its
 * comment describes the identical shape on the sports path: "A READ THAT DROPS A ROW SILENTLY IS
 * INDISTINGUISHABLE FROM THERE HAVING BEEN NO ROWS." CPI's rows are read and withheld; these
 * engines produce no row to withhold at all, so the row-level bucket cannot help and the empty
 * state itself has to carry the difference.
 *
 * It holds NO threshold and NO state logic, on the same terms as `@/lib/scoreboard` and
 * `@/lib/models`:
 *
 *   - whether an engine is `could_not_run` is the written ruling in `tradehub/engine_health.py`,
 *     served by `/api/engine-health`. It is NOT derived here from an empty board, and the reason
 *     is not cosmetic: inferring "broken" from the absence of rows relabels a merely quiet engine
 *     the first time a market is thin, and relabels a broken one quiet whenever the breakage
 *     happens to coincide with a real lull. A guess here would be the defect restated in the same
 *     costume.
 *   - the counts (`edgeTypesText`) are the server's. `edge_types_could_not_run` is a subtraction on
 *     a set, and a component that does it at render time is a rule in a second language with no
 *     test on it.
 *
 * What it does decide is the two things the server cannot: how a resolved fact is worded, and the
 * fail-safe presentation of a figure nobody measured. Same division of labour as `models.ts`.
 */

/**
 * Whether an engine ran. The server's own three words, not a re-wording of them.
 *
 * `quarantined` was added on 2026-09-28, when the two live sites were repaired. It is not a synonym
 * for either neighbour and the distinction is the whole reason it exists:
 *
 *   ran             the engine ran, looked, and nothing qualified. A measurement, and the empty
 *                   board is the finding.
 *   quarantined     the engine RAN and computed real opportunities, and none of them were published,
 *                   by ruling rather than by defect. Something was measured; it is visible on its own
 *                   surface and it is marked.
 *   could_not_run   the engine did not run at all. Nothing was measured.
 *
 * Collapsing `quarantined` into `ran` puts "the market was quiet" next to a board that was empty by
 * decision. Collapsing it into `could_not_run` tells a reader the engine looked at nothing, when it
 * measured 295 rows on 2026-09-28. Both are false, and the second is the original defect of this
 * page wearing a different hat.
 *
 * Deliberately NOT `MarketVerdict`. Those are verdicts on a MEASUREMENT -- ahead, behind, level --
 * and an engine that never ran has no measurement to be ahead or behind on. Borrowing the
 * vocabulary would imply a comparison nobody made, which is the confusion this whole page is about.
 * `tests/test_engine_health.py` pins that the sets stay disjoint.
 */
export type EngineState = "ran" | "quarantined" | "could_not_run";

/** One ruled-against site: a class or function that reads a Kalshi quote field the API moved. */
export interface StoppedSite {
  /**
   * The class or function name, NEVER the `kalshi_edges.engine` value.
   *
   * `WeatherEngine` writes `engine: "Weather"`, which `upsert_opportunities` lower-cases to
   * `weather` -- the same key the MEASURED `weather` engine writes from `tradehub/scripts/scan.py`.
   * Joining these two on that column would put "stopped" beside a real Brier, which is a claim
   * about an engine that demonstrably runs. The module and the line are the only unambiguous join.
   */
  name: string;
  module: string;
  /** `module:line`, so the reader can go and check the ruling instead of taking it on trust. */
  site: string;
  /** The edge type this site would publish under, or null when it feeds no board at all. */
  edge_type: string | null;
  /**
   * Whether any scanner actually CALLS it. The difference between "this is why the tab is empty"
   * and "this code is not on the scan path", and the two must not be collapsed: a helper nothing
   * calls cannot be the reason a live board has nothing on it.
   */
  wired_to_a_scanner: boolean;
  /**
   * Whether the drift is still there. Travels for the same reason `wired_to_a_scanner` does: the
   * ruling now holds both kinds, and a site with no disposition is indistinguishable from a live
   * defect. A client that guessed would call a fixed engine broken -- this page's own defect,
   * reintroduced one layer up, by a client this time.
   */
  disposition: "repaired_quarantined" | "unrepaired";
  reason: string;
}

/** One edge type's live state, as the server resolved it. */
export interface EdgeTypeState {
  edge_type: string;
  label: string;
  state: EngineState;
  /** Why this edge type is in this state. Never empty when stopped; null when nothing stopped it. */
  reason: string | null;
  stopped_sites: StoppedSite[];
  /**
   * Always null, and always present.
   *
   * Not an unfinished field. This endpoint says whether an engine RAN; a count of what it found
   * belongs to the read of the ledger, which is a different read over a different bound. A null
   * here is the machine-readable half of "nothing was measured", and for a stopped engine `0`
   * would be the most damaging value this product could print: it would read as a search that ran
   * and found nothing.
   */
  opportunities_found: number | null;
  opportunities_found_reason: string | null;
  /**
   * Where this edge type's measurement lives, when it has one. `null` for the two states with
   * nothing measured, so a reader is not sent to a ledger that deliberately has none of these rows.
   *
   * Present-and-null rather than absent, for the same reason as `opportunities_found`: a client that
   * checks for the key gets `null` rather than `undefined`, and the difference between "there is no
   * quarantine sink for this board" and "the server is an old bundle" is one a reader should not have
   * to guess at.
   */
  quarantine_sink: string | null;
}

export interface EngineHealthResponse {
  as_of: string;
  edge_types: EdgeTypeState[];
  edge_types_total: number;
  edge_types_could_not_run: number;
  edge_types_ran: number;
  /**
   * The UNFILTERED view's state, derived by the server rather than asked here.
   *
   * "Is any of these stopped" is a rule, and a rule written in a component is a rule nothing can
   * test and nothing downstream can tell has drifted. It is also the answer the whole product turns
   * on: a board with one stopped engine out of five is not a working board, and the landing view
   * has to say so rather than showing a healthy-looking summary over a dead feed.
   */
  board_state: EngineState;
  /** The wired reasons, joined, when the board is stopped or quarantined. Null when it is not. */
  board_reason: string | null;
  /**
   * How many boards are quarantined. The server's count, for the same reason
   * `edge_types_could_not_run` is: "is any of these quarantined" is a rule, and a rule in a
   * component is a rule nothing can test.
   */
  edge_types_quarantined: number;
  /**
   * How many of the ruled-against sites are still drifting, and how many were repaired. Two numbers
   * rather than one, because "3 sites" answers neither question a reader has: is anything broken,
   * and what was fixed.
   */
  sites_repaired: number;
  sites_unrepaired: number;
  /** The whole ruling, including sites that feed no board. Nothing here is truncated. */
  sites: StoppedSite[];
  sites_total: number;
  sites_wired: number;
  sites_unwired: number;
  note: string;
}

/**
 * How the board's empty state is presented. Three branches and no fourth.
 *
 * `quiet` is the only one that is allowed to claim a finding, and it is reachable only when the
 * ruling was actually read. `unchecked` is the one this codebase keeps finding new ways to skip:
 * a read that failed is not evidence of anything, so an empty board we could not classify is not
 * "no edge today", it is a board whose emptiness nobody has established.
 */
export type EmptyBoardKind = "quiet" | "stopped" | "quarantined" | "unchecked";

export interface EmptyBoard {
  kind: EmptyBoardKind;
  headline: string;
  body: string | null;
}

/** The word for a stopped engine, as a reader reads it. Not "could_not_run", which is our jargon. */
export const STOPPED_WORD = "not running";

/**
 * The word for a quarantined engine, and the sentence that goes with it.
 *
 * NOT `STOPPED_WORD`. A quarantined engine runs; it measured 295 rows on 2026-09-28. Calling it "not
 * running" is false, and a reader who believes it goes and tries to fix something that is already
 * fixed. NOT "shadow" either, which would imply the trades are live but small, when nothing here is
 * published at all.
 *
 * The headline is deliberately not "found N opportunities". It is the shape a reader needs when the
 * board is empty BY DECISION and there is a measurement sitting elsewhere: something ran, and what
 * it found is being shown on its own marked surface.
 */
export const QUARANTINED_WORD = "quarantined";

/**
 * Why an empty tab is not yet a finding, when the ruling itself could not be read.
 *
 * The third state, and the one that makes the other two trustworthy. Before this existed, a failed
 * read of the ruling and a quiet engine both fell through to the same sentence, so the label was
 * only ever as good as the read behind it. A reader who cannot tell whether the Weather tab is
 * empty because the engine found nothing or because nobody could find out has been handed the
 * product's whole problem, in miniature.
 */
export const HEALTH_UNREAD_REASON =
  "The board is empty, and this could not be read, so which engine state that is has not been " +
  "established. An empty tab here is not yet a finding either way: it may be an engine that ran " +
  "and found nothing, or an engine that did not run at all.";

/** The quiet case, said as a measurement. The one branch allowed to say "nothing here". */
export const QUIET_REASON =
  "This engine ran. It looked at the markets it covers and no opportunity qualified, which is a " +
  "measurement of this scan rather than a gap in the evidence.";

/**
 * The one sentence that must never appear next to a stopped engine.
 *
 * Exported so a test can forbid it by content rather than by inspection. "Found no opportunity" is
 * how this page would collapse the two states back into one, and it is the phrasing most likely
 * to drift back in: it is the natural thing to write for an empty tab, and the natural thing to
 * write for a tab that is empty because the engine is broken.
 */
export const FOUND_NOTHING_PHRASE = "found no qualifying opportunity";

/** The label for a stopped engine's figure, which is a dash and never a zero. */
export function opportunitiesFoundText(entry: EdgeTypeState | null | undefined): string {
  if (!entry) return NOT_MEASURED;
  return typeof entry.opportunities_found === "number" ? String(entry.opportunities_found) : NOT_MEASURED;
}

/** Why that figure is a dash, in words, so the dash is not the only thing on screen. */
export function opportunitiesFoundReason(entry: EdgeTypeState | null | undefined): string | null {
  if (!entry) return "No engine state was read, so there is no figure to show. This is not a count of zero.";
  if (typeof entry.opportunities_found === "number") return null;
  return entry.opportunities_found_reason ?? "Nothing was measured, so there is no figure to show.";
}

/**
 * Whether a quarantined engine's measurement is on the other surface, and where.
 *
 * The figure is not on this page and must not be: it is in `kalshi_quarantine_edges` and it is 26
 * independent opportunities, not 295 rows. Pointing at the sink rather than repeating the number
 * keeps the one count of each fact on the one surface that can support it, which is the same
 * division of labour as `edgeTypesText` reading the server's counts.
 */
export function quarantineSinkOf(entry: EdgeTypeState | null | undefined): string | null {
  return entry?.quarantine_sink ?? null;
}

/**
 * The ruling's entry for one edge type, or null when the response did not carry it.
 *
 * A lookup by key, not a decision. The state is the server's; this only finds where it is, and says
 * null rather than guessing, because a guessed "ran" is the quiet reading and the quiet reading is
 * the one that is wrong when the engine is broken.
 */
export function edgeTypeStateOf(
  health: EngineHealthResponse | null | undefined,
  edgeType: string,
): EdgeTypeState | null {
  if (!health || !Array.isArray(health.edge_types)) return null;
  const wanted = edgeType.trim().toUpperCase();
  return health.edge_types.find((entry) => entry?.edge_type?.trim().toUpperCase() === wanted) ?? null;
}

/** The stopped engine for one edge type, or null. The single engine a reader needs to be told about. */
export function stoppedEngineOf(
  health: EngineHealthResponse | null | undefined,
  edgeType: string,
): StoppedSite | null {
  const entry = edgeTypeStateOf(health, edgeType);
  if (!entry || entry.state !== "could_not_run") return null;
  // The wired one, always. An unwired site can be named in the full notice and must never be the
  // headline cause of an empty board.
  return entry.stopped_sites.find((site) => site.wired_to_a_scanner) ?? null;
}

/**
 * What an empty board says, which is the whole point of this module.
 *
 * `healthError` is the read of the ruling, kept SEPARATE from the board's own read error: a board
 * that could not be read and a ruling that could not be read are two different gaps, and merging
 * them would let one suppress the other. The board's error is handled where it already was, above
 * this, and only the ruling's arrives here.
 */
/**
 * Whether this edge type is quarantined, from the server's state. A lookup, not a decision.
 *
 * The point of it is that the empty board and the quarantine notice have to agree. A board can be
 * empty because a quarantined engine's output is withheld, and the two surfaces say so in the same
 * words; if either derived that for itself they would eventually disagree, and the reader would be
 * left deciding which of two true-looking statements about one engine to believe.
 */
export function isQuarantined(health: EngineHealthResponse | null | undefined, edgeType: string): boolean {
  return edgeTypeStateOf(health, edgeType)?.state === "quarantined";
}

export function emptyBoard(
  health: EngineHealthResponse | null | undefined,
  edgeType: string,
  tabLabel: string,
  healthError?: string | null,
): EmptyBoard {
  if (healthError) {
    // The error is quoted AND the consequence stated. A raw error string is a status line, and a
    // reader who is handed one is left to work out for themselves whether the empty board below it
    // means anything -- which is the question they came to this page with.
    return {
      kind: "unchecked",
      headline: `Nothing on the ${tabLabel} board, and which engines are running has not been read`,
      body: `${HEALTH_UNREAD_REASON} (The read failed: ${healthError})`,
    };
  }
  // A blank edge type is the UNFILTERED view -- the board as a whole, fed by several engines. The
  // state for it is the server's `board_state`, not a question asked here: "is any of these
  // stopped" is a rule, and a rule in a component is a rule nothing can test.
  if (!edgeType.trim()) {
    if (!health?.board_state) {
      return {
        kind: "unchecked",
        headline: "Nothing on the board, and which engines are running has not been read yet",
        body: HEALTH_UNREAD_REASON,
      };
    }
    if (health.board_state === "could_not_run") {
      return {
        kind: "stopped",
        headline: `${health.edge_types_could_not_run} of ${health.edge_types_total} boards are fed by an engine that is ${STOPPED_WORD} — this is not a finding about the market`,
        body:
          health.board_reason ??
          "At least one engine that publishes to this board is stopped, and no reason travelled with the ruling.",
      };
    }
    if (health.board_state === "quarantined") {
      // The board is empty because its engines' output is being withheld, not because the market
      // was quiet. Saying "no high-confidence edges detected" here would be the original defect of
      // this page reached from the other direction: a confident finding about a search that ran and
      // whose result was deliberately not published.
      return {
        kind: "quarantined",
        headline: `${health.edge_types_quarantined} of ${health.edge_types_total} boards are ${QUARANTINED_WORD} — this board is empty by decision, not by a quiet market`,
        body:
          health.board_reason ??
          "At least one engine that feeds this board is quarantined, and no reason travelled with the ruling.",
      };
    }
    return { kind: "quiet", headline: `No high-confidence edges detected in ${tabLabel}`, body: QUIET_REASON };
  }
  const entry = edgeTypeStateOf(health, edgeType);
  if (!entry) {
    // The read succeeded but carried no entry for this tab. A board with no state is a gap in the
    // ruling, and the honest rendering of a gap is that it is one -- never a quiet engine. The
    // copy covers the transient case too: on first paint the ruling has not arrived yet, and that
    // is not a fault, but it is equally not a finding.
    return {
      kind: "unchecked",
      headline: `Nothing on the ${tabLabel} board, and which engine feeds it has not been read yet`,
      body: HEALTH_UNREAD_REASON,
    };
  }
  if (entry.state === "could_not_run") {
    const engine = stoppedEngineOf(health, edgeType);
    return {
      kind: "stopped",
      headline: `${entry.label} is ${STOPPED_WORD} — this is not a finding about the market`,
      body:
        entry.reason ??
        `An engine that publishes to the ${entry.label} board is stopped, and no reason travelled with the ruling.`,
    };
  }
  if (entry.state === "quarantined") {
    // The sentence must not contain the quiet claim in any form. This engine RAN and measured; its
    // output is in kalshi_quarantine_edges and is shown on its own marked surface. "No
    // high-confidence edges detected" beside a board that is empty because a decision was made is
    // the one thing this branch exists to prevent.
    //
    // "empty by decision" is in the headline rather than only in the body because a reader scanning
    // the tab sees the headline. The body is where the mechanism goes; the headline has to carry the
    // finding on its own.
    return {
      kind: "quarantined",
      headline: `${entry.label} is ${QUARANTINED_WORD} — this board is empty by decision, not by a quiet market`,
      body:
        entry.reason ??
        `An engine that feeds the ${entry.label} board is quarantined, and no reason travelled with the ruling.`,
    };
  }
  return {
    kind: "quiet",
    headline: `No high-confidence edges detected in ${tabLabel}`,
    body: QUIET_REASON,
  };
}

/**
 * How much of the board cannot run, in one line, from the server's counts.
 *
 * Each count agrees its own noun, for the reason `catalogueCounts` in `@/lib/models` does the same:
 * "1 engines" is a number rendered wrong, and this is the page whose whole job is that numbers read
 * right. A missing ruling is a FAILURE and is worded as one, on the same terms -- never "0 stopped",
 * which is a claim that the product has none.
 */
export function edgeTypesText(health: EngineHealthResponse | null | undefined): string {
  if (!health) return "engine states not in the response — the ruling did not arrive";
  const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);
  return (
    `${health.edge_types_total} ${plural(health.edge_types_total, "board", "boards")} · ` +
    `${health.edge_types_could_not_run} cannot run · ` +
    `${health.edge_types_quarantined} ${QUARANTINED_WORD} · ` +
    `${health.edge_types_ran} ran`
  );
}
