import { displayOnlyReason } from "@/lib/displayOnlyEngines";
import {
  formatBrier,
  formatCount,
  formatRatio,
  type MarketVerdict,
  type ScoreboardResponse,
  type ScoreboardRow,
} from "@/lib/scoreboard";

/**
 * Wording and shape for the MODELS page — the page that answers the owner's question:
 * *what are the models, what are they doing, and how did they do?*
 *
 * The product had a War Room, a Prediction Lab, a shadow backtester, a sports-edges page, a jobs
 * scorecard, a CPI display and an engine scoreboard, and no page that said any of that. Kevin is
 * capable and not a quant, and on every existing page he has to reverse-engineer what a Brier is,
 * why there are two bars, and which of six pages is telling him whether an engine is any good. So
 * this module is the wording half of that answer and `/api/scoreboard` is the data half.
 *
 * It holds NO threshold, NO ratio and NO gate logic, on the same terms as `@/lib/scoreboard`:
 *
 *   - whether an engine is ahead of or behind the market is `BEHIND_THE_MARKET` in
 *     `tradehub/scoreboard.py`, applied once by `market_verdict` and carried per ROW as
 *     `market_verdict`, then rolled up to the engine by `engine_catalogue`. Comparing ratios here
 *     would be a second copy of a threshold in a second language.
 *   - which engines EXIST, what each one CLAIMS to predict, and how many have never been measured
 *     are `tradehub/engine_catalogue.py`. The catalogue is authoritative about which engines there
 *     are; the scoreboard is authoritative about what was measured. Neither is re-derived here.
 *   - both settled bars are `settledBars()` in `@/lib/scoreboard`, and this page renders them with
 *     the same component `/scoreboard` uses.
 *
 * So the two things this module does decide are the two things the server cannot: how a resolved
 * fact is worded, and the fail-safe presentation of a figure nobody measured. Every formatter and
 * every "not measured" line below returns or says words where there is no number, because a
 * missing figure rendered as `0` or `0.0` is a measurement nobody made — and on THIS page, where
 * four of seven engines have no backtest at all, that is the normal case rather than the edge case.
 */

/**
 * One engine's standing, as the server resolved it.
 *
 * `not_measured` is NOT a `MarketVerdict`: it is the absence of one, and it is a fifth state rather
 * than a flavour of `not_comparable`. "A run exists and recorded no market Brier" and "there is no
 * run" are different facts, and collapsing them turns a gap in the evidence into a verdict.
 */
export type EngineStatus = MarketVerdict | "not_measured" | "retired";

/** One engine, joined to the scoreboard rows that measured it. Self-contained by construction. */
export interface CatalogueEntry {
  engine: string;
  label: string;
  /** The checkable claim: what this engine predicts, in a sentence. Null when undeclared. */
  claim: string | null;
  /** Why there is no claim. Empty whenever there is one. Never a plausible-sounding guess. */
  claim_note: string;
  in_catalogue: boolean;
  /** "daily" or "monthly", the gate's own word. Null when the catalogue declares none. */
  cadence: string | null;
  measured: boolean;
  measured_rows: number;
  status: EngineStatus;
  /** The LARGEST comparable ratio among the engine's rows — its worst. Null, never 0. */
  worst_brier_ratio: number | null;
  /** The scoreboard's own rows, whole and unmodified. The page re-derives nothing from them. */
  rows: ScoreboardRow[];
  /** Present only on a deleted engine's tombstone (status "retired"). */
  retired?: Retirement | null;
}

/** What happened to a deleted engine. `replaced_by` is null when nothing took over. */
export interface Retirement {
  removed: string;
  reason: string;
  replaced_by: string | null;
}

export interface Catalogue {
  engines_total: number;
  engines_measured: number;
  engines_not_measured: number;
  /** Engines with a backtest run that the catalogue has never heard of. */
  engines_unlisted: number;
  /** Deleted engines, shown as tombstones. Not counted in `engines_total`. Absent on an older API. */
  engines_retired?: number;
  entries: CatalogueEntry[];
}

/** The scoreboard's response plus the catalogue. One read, one join, one page. */
export interface ModelsResponse extends ScoreboardResponse {
  catalogue: Catalogue;
}

// ── the three ways a figure is absent ─────────────────────────────────────────

/**
 * The score cell for an engine with no backtest run.
 *
 * The whole sentence matters, and the last clause most: "not measured" and "measured as zero" are
 * different facts, and a reader who cannot tell them apart will read an absent figure as a good
 * one — or, on a product where every measured engine loses, as a bad one. Both readings are
 * claims nobody made about the engine.
 */
export const UNMEASURED_SCORE =
  "Not measured. No backtest run is recorded for this engine, so there is no score to report " +
  "against any market. That is not the same as scoring zero, and it is not a verdict on the " +
  "engine either.";

/** The two-bar cell for an engine with no run. There is no count, so neither bar can be stated. */
export const UNMEASURED_BARS =
  "No bars to state. Both are counts of settled contracts, and nothing has been settled, so " +
  "there is no distance to either one. Neither bar is reported as met and neither as unmet.";

/** The gate cell for an engine with no run. The gate is keyed on a run, so there is no verdict. */
export const UNMEASURED_GATE =
  "No gate verdict. Promotion is a decision about a recorded run, and this engine has none, " +
  "so there is nothing to be promoted or kept in shadow.";

// ── wording ───────────────────────────────────────────────────────────────────

/**
 * What the engine claims to predict, or why there is no claim.
 *
 * The claim is data — `tradehub/engine_catalogue.py` — because it is a statement about the same
 * code that makes the prediction, and a claim written here would drift from the engine with
 * nothing able to tell. An undeclared engine is worded by the server's own `claim_note`, which
 * names the gap: the catalogue is behind, not the engine.
 */
export function claimText(entry: CatalogueEntry): string {
  if (entry.claim) return entry.claim;
  return entry.claim_note || "Not described in the engine catalogue.";
}

/**
 * The status word, in the product's own vocabulary.
 *
 * The four market verdicts and the gate's SHADOW/PROMOTED are the words the rest of the product
 * already uses; nothing here is a fifth vocabulary invented for this page. `not_measured` is the
 * one addition, and it is the honest one: the product has no word for it, which is why engines
 * with no run used to simply be absent.
 */
export function statusWord(status: EngineStatus): string {
  switch (status) {
    case "ahead":
      return "Ahead of the market";
    case "behind":
      return "Behind the market";
    case "level":
      return "Level with the market";
    case "not_comparable":
      return "Not comparable";
    case "retired":
      return "Retired";
    default:
      return "Not measured";
  }
}

/**
 * How to colour a status.
 *
 * `not_comparable` and `not_measured` both take the muted treatment, and that is the load-bearing
 * part: an amber "behind" on an engine nobody measured is the page inventing a loss, which is the
 * same defect as dropping the engine, pointed the other way.
 */
export function statusTone(status: EngineStatus): "behind" | "ahead" | "level" | "unknown" {
  if (status === "behind") return "behind";
  if (status === "ahead") return "ahead";
  if (status === "level") return "level";
  return "unknown";
}

/**
 * The engine's headline multiple, at the shared ONE precision.
 *
 * `formatRatio` rather than a second rounding, for the reason it exists: two precisions on one
 * quantity tell a reader the more precise number is the more true one, which is a claim about
 * nothing. A dash where there is no figure — and the page prints the dash beside the word
 * "measured", so it cannot be skimmed as a 0.00x.
 */
export function worstRatioText(entry: CatalogueEntry): string {
  return `${formatRatio(entry.worst_brier_ratio)}x`;
}

/** Our Brier beside the market's, in the shared formatters. Absent is a dash, never 0.00000. */
export function brierPair(row: ScoreboardRow): string {
  return `${formatBrier(row.brier_ours)} ours · ${formatBrier(row.brier_market)} market`;
}

/**
 * Why this engine is not presented as an opportunity, when it is a display engine.
 *
 * A pass-through to `@/lib/displayOnlyEngines`, deliberately a pass-through and not a second
 * list: `DISPLAY_ONLY_ENGINES` is the product's single ruling on which engines may be shown as
 * edges, and CPI's reason sentence already carries the evidence for it. A copy here would be a
 * copy that could disagree with the edge list about which engine is being withheld.
 */
export function displayOnlyNote(entry: CatalogueEntry): string | null {
  return displayOnlyReason({ engine: entry.engine });
}

/**
 * How much of the product has been measured, in one line.
 *
 * The numbers are the server's — `engines_not_measured` is a subtraction on a set, and a page
 * that does it at render time does it in a component. They are not the row buckets `summarise`
 * reports: those count (engine, mode) pairs, and this counts engines. Both lines are rendered,
 * because a reader shown "3 rows behind the market" and nothing about seven engines has been
 * handed the half of the board that is empty.
 *
 * Each count agrees its own noun, for the reason `summarise` does the same: "1 engines" is a
 * number rendered wrong, and this is the page whose whole job is that numbers read right.
 *
 * A missing catalogue is a FAILURE, not a zero, and it is worded as one. The API and the SPA
 * deploy together, but a browser can hold the previous bundle against a newer API, and a page that
 * threw on the missing key would replace "here are your engines" with a blank screen — strictly
 * worse than saying the join did not arrive. Never "0 engines", which is a claim that the product
 * has none.
 */
export function catalogueCounts(catalogue: Catalogue | null | undefined): string {
  if (!catalogue) return "engine counts not in the response — the catalogue did not arrive";
  const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);
  return (
    `${formatCount(catalogue.engines_total)} ${plural(catalogue.engines_total, "engine", "engines")} · ` +
    `${formatCount(catalogue.engines_measured)} measured · ` +
    `${formatCount(catalogue.engines_not_measured)} not measured` +
    (catalogue.engines_unlisted > 0
      ? ` · ${formatCount(catalogue.engines_unlisted)} not in the catalogue`
      : "") +
    (catalogue.engines_retired ? ` · ${formatCount(catalogue.engines_retired)} retired` : "")
  );
}

/** One sentence for a tombstone: when it went, why, and what replaced it. Null for a live engine. */
export function retirementText(entry: Pick<CatalogueEntry, "retired">): string | null {
  const r = entry.retired;
  if (!r) return null;
  const successor = r.replaced_by ? `Replaced by ${r.replaced_by}.` : "Nothing replaced it.";
  return `Retired ${r.removed}: ${r.reason}. ${successor}`;
}
