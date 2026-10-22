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

/** Map Kalshi series prefix to city/region label. */
const CITY_MAP: Record<string, string> = {
  KXHIGHNY: "NYC",
  KXHIGHLAX: "Los Angeles",
  KXHIGHPHIL: "Philadelphia",
  KXHIGHTNOLA: "New Orleans",
  KXLOWNY: "NYC",
  KXLOWLAX: "Los Angeles",
  KXLOWPHIL: "Philadelphia",
  KXLOWTNOLA: "New Orleans",
  KXRAINNY: "NYC",
  KXRAINCHI: "Chicago",
  KXRAINMIA: "Miami",
};

/** Parse the target ticker into {city, kind, strike}. */
export function parseWeatherTarget(target: string): { city: string; kind: "high" | "low" | "rain"; strike: number | null } {
  // target format: kalshi:KXHIGHNY-26OCT16-T75 or KXHIGHNY-26OCT16-T75
  const clean = target.replace(/^kalshi:/, "");
  const parts = clean.split("-");
  if (parts.length < 2) return { city: "?", kind: "high", strike: null };
  const series = parts[0];
  // city from series
  const city = CITY_MAP[series] ?? "?";
  // kind from series
  let kind: "high" | "low" | "rain" = "high";
  if (series.startsWith("KXHIGH")) kind = "high";
  else if (series.startsWith("KXLOW")) kind = "low";
  else if (series.startsWith("KXRAIN")) kind = "rain";
  // strike from last part (e.g., T75 -> 75)
  let strike: number | null = null;
  const last = parts[parts.length - 1];
  if (last.startsWith("T")) {
    const n = parseInt(last.slice(1), 10);
    if (!isNaN(n)) strike = n;
  }
  return { city, kind, strike };
}

/** Human-readable label for a weather target: "NYC high above 70°F" */
export function weatherLabel(target: string): string {
  const { city, kind, strike } = parseWeatherTarget(target);
  if (kind === "rain") {
    return `${city} rain`;
  }
  if (strike !== null) {
    return `${city} ${kind} above ${strike}°F`;
  }
  return `${city} ${kind}`;
}

/** Short chip label: "NYC H70" / "LA L65" / "NOLA rain" */
export function weatherChip(target: string): string {
  const { city, kind, strike } = parseWeatherTarget(target);
  if (kind === "rain") return `${city} rain`;
  return `${city} ${kind[0].toUpperCase()}${strike ?? ""}`;
}
