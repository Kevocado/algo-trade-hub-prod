import { baselineName, CAUTIOUS_SUFFIX, forecasterLabel } from "@/lib/forecasterLabels";
import { EXPERIMENTAL, tiles, type Baseline, type JournalScore } from "@/lib/journal";

/**
 * The /journal page's view of the scorecards: one row per forecaster, ordered by how much evidence it has.
 * Presentation only. Every number comes from the server; the only constants here are display rules.
 */

/** Below this many scored forecasts a skill number is too noisy to praise or blame. Display rule, not a gate. */
export const EARLY_N = 30;

/** Mirrors `MIN_SETTLED` in tradehub/journal/scoring.py, for the "x of y" progress hint only. */
export const NEEDED: Record<JournalScore["cadence"], number> = { daily: 200, monthly: 50, meeting: 50 };

export type Status = "waiting" | "early" | "ahead" | "behind" | "promoted";

export interface ViewRow {
  key: string;
  label: string;
  /** The bare forecaster name, so the tile can look up a note without re-splitting `key`. */
  forecaster: string;
  /** Spec §5: `fomc_mapped` ships "labelled experimental" from its first row. */
  experimental: boolean;
  frozen: number;
  scored: number;
  needed: number;
  skill: number | null;
  against: string;
  baseline: Baseline;
  status: Status;
  score: JournalScore;
  market: JournalScore | null;
}

export function statusOf(score: JournalScore): Status {
  if (score.n_settled === 0) return "waiting";
  if (score.gate_status === "PROMOTED") return "promoted";
  if (score.n_settled < EARLY_N || score.bss === null) return "early";
  return score.bss > 0 ? "ahead" : "behind";
}

export const STATUS_WORDS: Record<Status, string> = {
  waiting: "Waiting",
  early: "Too early",
  ahead: "Ahead",
  behind: "Behind",
  promoted: "Promoted",
};

export function viewRows(scores: JournalScore[]): ViewRow[] {
  return tiles(scores).map(({ model, market }) => ({
    key: `${model.forecaster}@${model.forecaster_version}`,
    label: forecasterLabel(model.forecaster, model.forecaster_version),
    forecaster: model.forecaster,
    experimental: EXPERIMENTAL.has(model.forecaster),
    frozen: model.n_targets,
    scored: model.n_settled,
    needed: NEEDED[model.cadence] ?? NEEDED.daily,
    skill: model.bss,
    against: baselineName(model.baseline),
    baseline: model.baseline,
    status: statusOf(model),
    score: model,
    market,
  }));
}

/** Rows with at least one scored forecast first (most evidence first); the rest wait. */
export function split(rows: ViewRow[]): { results: ViewRow[]; waiting: ViewRow[] } {
  const results = rows.filter((r) => r.scored > 0).sort((a, b) => b.scored - a.scored);
  const waiting = rows.filter((r) => r.scored === 0).sort((a, b) => a.label.localeCompare(b.label));
  return { results, waiting };
}

export interface Totals {
  forecasters: number;
  frozen: number;
  scored: number;
  promoted: number;
}

export function totals(rows: ViewRow[]): Totals {
  // A cautious copy is a forecaster, so it appears in the list and in `forecasters` -- but it shares
  // its model's targets, so counting both would report 200 locked-in forecasts as 400. The hero
  // numbers count evidence, and this is the same row twice.
  // And spec §10: "headline stats aggregate ONLY post-calibration forecasters." A provisional card has
  // targets locked in but no settled evidence yet, so counting its rows inflated the hero with
  // forecasts that have never been graded. The server has always gated this at `scoring.headline()`;
  // this function did not, so `/journal` and `/cpi` both reported the ungated sum.
  const evidence = (r: ViewRow) =>
    !r.key.replace(/@.*$/, "").endsWith(CAUTIOUS_SUFFIX) && r.score.calibration_ready;
  return {
    forecasters: rows.length,
    frozen: rows.filter(evidence).reduce((n, r) => n + r.frozen, 0),
    scored: rows.filter(evidence).reduce((n, r) => n + r.scored, 0),
    promoted: rows.filter((r) => r.status === "promoted").length,
  };
}

/** Signed to three places, never a bare 0 for "not measured". */
export function skillText(skill: number | null): string {
  if (skill === null) return "—";
  return `${skill > 0 ? "+" : ""}${skill.toFixed(2)}`;
}
