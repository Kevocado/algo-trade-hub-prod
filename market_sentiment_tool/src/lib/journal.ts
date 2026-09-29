/**
 * The prediction journal's wire types and its wording (v2 spec §11).
 *
 * Every number on /journal is computed by the server (`tradehub/journal/scoring.py`) and rendered
 * here as-is. This module decides words, pairings and formatting only; it never computes a Brier
 * score, a skill score or a gate, because a second implementation is a second place to be wrong.
 */

export type Baseline = "market" | "climatology" | "none";

export interface ReliabilityBucket {
  bucket: string;
  n: number;
  predicted: number;
  observed: number;
}

export interface JournalScore {
  forecaster: string;
  forecaster_version: string;
  cadence: "daily" | "monthly" | "meeting";
  baseline: Baseline;
  n_targets: number;
  n_settled: number;
  brier: number | null;
  brier_baseline: number | null;
  bss: number | null;
  reliability: ReliabilityBucket[];
  murphy: { reliability?: number; resolution?: number; uncertainty?: number };
  calibration_ready: boolean;
  gate_status: "SHADOW" | "PROMOTED";
  gate_reasons: string[];
  computed_at: string;
}

export interface JournalHeadline {
  forecasters: number;
  calibrated: number;
  settled_calibrated: number;
  promoted: number;
}

export interface JournalResponse {
  as_of: string;
  forecasters: JournalScore[];
  headline: JournalHeadline;
}

export interface FrozenForecast {
  target: string;
  probability: number;
  market_prob: number | null;
  frozen_at: string;
  rebuilt: boolean;
  source_hash: string;
}

export interface JournalFeed {
  forecaster: string;
  forecaster_version: string;
  generated_at: string;
  forecasts: FrozenForecast[];
  calibration: ReliabilityBucket[];
  gate_status: "SHADOW" | "PROMOTED";
  provisional: boolean;
}

/** Market pseudo-forecasters are prefixed; their tile sits beneath the model they price. */
export const MARKET_PREFIX = "kalshi_implied_";

/** Model forecaster -> the pseudo-forecaster for the same Kalshi markets (registry, plans b-c). */
export const MARKET_PAIR: Record<string, string> = {
  cpi_nowcast: "kalshi_implied_cpi",
  fomc_mapped: "kalshi_implied_fomc",
  labor_nowcast: "kalshi_implied_labor",
};

/** Forecasters the spec labels experimental (ruling Q5). */
export const EXPERIMENTAL = new Set(["fomc_mapped"]);

export const NOT_SCORED = "not scored yet";

export function key(score: Pick<JournalScore, "forecaster" | "forecaster_version">): string {
  return `${score.forecaster}@${score.forecaster_version}`;
}

export function isMarket(score: Pick<JournalScore, "forecaster">): boolean {
  return score.forecaster.startsWith(MARKET_PREFIX);
}

export interface Tile {
  model: JournalScore;
  market: JournalScore | null;
}

/**
 * One tile per model forecaster, its market pseudo-forecaster beneath it. A pseudo-forecaster
 * whose model is absent still gets a tile of its own: dropping it would hide a row of the ledger.
 */
export function tiles(scores: JournalScore[]): Tile[] {
  const markets = new Map(scores.filter(isMarket).map((s) => [s.forecaster, s]));
  const used = new Set<string>();
  const out: Tile[] = [];
  for (const model of scores.filter((s) => !isMarket(s))) {
    const pair = MARKET_PAIR[model.forecaster];
    const market = pair ? markets.get(pair) ?? null : null;
    if (market) used.add(market.forecaster);
    out.push({ model, market });
  }
  for (const market of scores.filter(isMarket)) {
    if (!used.has(market.forecaster)) out.push({ model: market, market: null });
  }
  return out;
}

export function baselineWord(baseline: Baseline): string {
  if (baseline === "market") return "vs the Kalshi market";
  if (baseline === "climatology") return "vs climatology";
  return "no baseline";
}

export function brierText(value: number | null): string {
  return value === null ? NOT_SCORED : value.toFixed(4);
}

/** Skill in words and a signed number; never a bare 0 for "not measured". */
export function skillText(score: JournalScore): string {
  if (score.bss === null) return `Brier skill ${NOT_SCORED}`;
  const sign = score.bss > 0 ? "+" : "";
  return `Brier skill ${sign}${score.bss.toFixed(3)} ${baselineWord(score.baseline)}`;
}

export function settledText(score: JournalScore): string {
  return `${score.n_settled} settled of ${score.n_targets} frozen (${score.cadence})`;
}

export function pct(value: number | null): string {
  return value === null ? "no market price" : `${(value * 100).toFixed(1)}%`;
}

/** "CPI runs hot by 4.0pp": observed minus predicted in the best-populated bucket, when it exists. */
export function biasReadout(buckets: ReliabilityBucket[]): string | null {
  if (!buckets.length) return null;
  const top = [...buckets].sort((a, b) => b.n - a.n)[0];
  const gap = (top.observed - top.predicted) * 100;
  if (Math.abs(gap) < 0.05) return `calibrated in the ${top.bucket} bucket (n=${top.n})`;
  const word = gap < 0 ? "overconfident" : "underconfident";
  return `${word} by ${Math.abs(gap).toFixed(1)}pp in the ${top.bucket} bucket (n=${top.n})`;
}
