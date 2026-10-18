/**
 * The weather page's wire types, words and formatting.
 *
 * Every number here arrives computed from the server (`/api/weather`). This module
 * decides words, chips and layout only; it never computes a forecast or a score.
 */

export interface WeatherTodayRow {
  target: string;
  date: string;
  ensemble: number | null;
  kalshi: number | null;
  climatology: number | null;
}

export interface WeatherSettledRow extends WeatherTodayRow {
  outcome: number | null;
  realized_value: number | null;
  settled_at: string | null;
}

export interface Chip {
  label: string;
  tone: "ok" | "warn" | "bad" | "flat";
}

/** Lede. Kept under the word budget and asserted by test. */
export const WEATHER_INTRO =
  "Today's ensemble forecast against the Kalshi price and climatology. No new forecasting.";

/**
 * Format a probability as a percentage string.
 * Returns a dash for null/undefined — a missing probability is not 0%.
 */
export function formatProb(prob: number | null | undefined): string {
  if (prob === null || prob === undefined) return "—";
  return `${Math.round(prob * 100)}%`;
}

/**
 * Format an outcome as YES or NO.
 * Returns a dash for null/undefined — a missing outcome is not a loss.
 */
export function formatOutcome(outcome: number | null | undefined): string {
  if (outcome === null || outcome === undefined) return "—";
  return outcome === 1 ? "YES" : "NO";
}

export interface WeatherStat {
  todayCount: number;
  settledCount: number;
  cities: number;
}

/** The big numbers. Formatting only; no score is derived here. */
export function weatherStats(today: WeatherTodayRow[], settled: WeatherSettledRow[]): WeatherStat {
  const cities = new Set(today.map((r) => r.target)).size;
  return {
    todayCount: today.length,
    settledCount: settled.length,
    cities,
  };
}
