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
  strike_type: string | null;
  floor_strike: number | null;
  cap_strike: number | null;
  yes_sub_title: string | null;
  no_sub_title: string | null;
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

/** Map Kalshi series (highs and lows) to a city label. Rain is one series per all cities: see RAIN_CITY. */
const CITY_MAP: Record<string, string> = {
  KXHIGHNY: "NYC",
  KXHIGHLAX: "Los Angeles",
  KXHIGHPHIL: "Philadelphia",
  KXHIGHTNOLA: "New Orleans",
  KXLOWTATL: "Atlanta",
  KXLOWTAUS: "Austin",
  KXLOWTDEN: "Denver",
  KXLOWTEWR: "Newark",
  KXLOWTOKC: "Oklahoma City",
  KXLOWTSDF: "Louisville",
};

/** KXRAIN-<code>: the city code is the LAST part of the ticker (e.g. kalshi:KXRAIN-26OCT20-NYC). */
const RAIN_CITY: Record<string, string> = {
  ABQ: "Albuquerque", ATL: "Atlanta", AUS: "Austin", BOS: "Boston", CHI: "Chicago", CLL: "College Station",
  CMH: "Columbus", DAL: "Dallas", DC: "Washington DC", DEN: "Denver", EWR: "Newark", HOU: "Houston",
  LAX: "Los Angeles", LEX: "Lexington", LV: "Las Vegas", MIA: "Miami", MIN: "Minneapolis", MKE: "Milwaukee",
  NOLA: "New Orleans", NYC: "NYC", OKC: "Oklahoma City", PHIL: "Philadelphia", PHX: "Phoenix", PIT: "Pittsburgh",
  PVD: "Providence", SATX: "San Antonio", SEA: "Seattle", SFO: "San Francisco", SGF: "Springfield",
  STL: "St. Louis", TPA: "Tampa", TTN: "Trenton", WPB: "West Palm Beach",
};

/** Parse the target ticker into {city, kind, strike} (fallback when API fields missing). */
export function parseWeatherTarget(target: string): { city: string; kind: "high" | "low" | "rain"; strike: number | null } {
  // target format: kalshi:KXHIGHNY-26OCT16-T75 or KXHIGHNY-26OCT16-T75
  const clean = target.replace(/^kalshi:/, "");
  const parts = clean.split("-");
  if (parts.length < 2) return { city: "?", kind: "high", strike: null };
  const series = parts[0];
  // city from series
  const last0 = parts[parts.length - 1];
  // a code we do not know is shown as itself, never as "?", so the row is still identifiable
  const city = series === "KXRAIN" ? (RAIN_CITY[last0] ?? last0) : (CITY_MAP[series] ?? series);
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

/**
 * Build a human-readable label from the API market metadata.
 * Uses the frozen yes_sub_title/no_sub_title when available (the source of truth),
 * falls back to strike_type + floor/cap_strike, then to ticker parsing.
 */
export function weatherLabel(row: WeatherTodayRow | WeatherSettledRow): string {
  // Prefer the frozen yes_sub_title (the exact text Kalshi shows, e.g., "64° or below")
  if (isDefined(row.yes_sub_title) && row.strike_type !== "between") {
    const { city, kind } = parseWeatherTarget(row.target);
    return `${city} ${row.yes_sub_title}`;
  }
  if (isDefined(row.no_sub_title) && row.strike_type !== "between") {
    const { city, kind } = parseWeatherTarget(row.target);
    return `${city} ${row.no_sub_title}`;
  }
  // For 'between' (bracket) markets, show the range from floor/cap
  if (row.strike_type === "between" && isDefined(row.floor_strike) && isDefined(row.cap_strike)) {
    const { city } = parseWeatherTarget(row.target);
    return `${city} ${row.floor_strike}-${row.cap_strike}°F`;
  }
  // Fallback: use strike_type + floor/cap if available
  if (isDefined(row.floor_strike) || isDefined(row.cap_strike)) {
    const { city } = parseWeatherTarget(row.target);
    const parts: string[] = [];
    if (isDefined(row.floor_strike)) parts.push(`${row.floor_strike}°F+`);
    if (isDefined(row.cap_strike)) parts.push(`${row.cap_strike}°F-`);
    if (parts.length > 0) return `${city} ${parts.join(" ")}`;
  }
  // Final fallback: parse from ticker (neutral, no direction claimed)
  return weatherLabelFallback(row.target);
}

/** Check if a value is defined (not null/undefined). */
function isDefined<T>(v: T | null | undefined): v is T {
  return v != null;
}

/** Fallback label using only the ticker (neutral, no direction claimed). */
/** A bracket ticker 'B65.5' is Kalshi's 1-degree range 65 to 66 (the number is the midpoint). Null if not a bracket. */
export function bracketFromTicker(target: string): [number, number] | null {
  const last = target.replace(/^kalshi:/, "").split("-").pop() ?? "";
  const m = /^B(-?\d+(?:\.\d+)?)$/.exec(last);
  if (!m) return null;
  const mid = parseFloat(m[1]);
  return Number.isInteger(mid - 0.5) ? [mid - 0.5, mid + 0.5] : null;
}

export function weatherLabelFallback(target: string): string {
  const { city, kind, strike } = parseWeatherTarget(target);
  if (kind === "rain") {
    return `${city} rain`;
  }
  const bracket = bracketFromTicker(target);
  if (bracket) return `${city} ${kind} ${bracket[0]}-${bracket[1]}°F`;
  if (strike !== null) {
    return `${city} ${kind} tail at ${strike}°F`;
  }
  return `${city} ${kind}`;
}

/** Short chip label: "NYC ≤65" / "LA 65-66°F" / "NOLA rain" */
export function weatherChip(row: WeatherTodayRow | WeatherSettledRow): string {
  const { city, kind } = parseWeatherTarget(row.target);
  if (kind === "rain") return `${city} rain`;
  
  // Helper to check if a value is defined (not null/undefined)
  const isDefined = (v: unknown): v is string | number => v != null;
  
  // For 'between' (bracket) markets, show the range
  if (row.strike_type === "between" && isDefined(row.floor_strike) && isDefined(row.cap_strike)) {
    return `${city} ${row.floor_strike}-${row.cap_strike}°F`;
  }
  
  // Prefer yes_sub_title for chip - check direction from text
  if (isDefined(row.yes_sub_title) && row.strike_type !== "between") {
    const match = row.yes_sub_title.match(/(\d+)/);
    if (match) {
      const num = match[1];
      // Check direction from text: "or above" -> ≥, "or below" -> ≤
      if (row.yes_sub_title.includes("or above")) {
        return `${city} ≥${num}`;
      }
      return `${city} ≤${num}`;
    }
  }
  
  // Fall back to no_sub_title
  if (isDefined(row.no_sub_title) && row.strike_type !== "between") {
    const match = row.no_sub_title.match(/(\d+)/);
    if (match) {
      const num = match[1];
      if (row.no_sub_title.includes("or above")) {
        return `${city} ≥${num}`;
      }
      return `${city} ≤${num}`;
    }
  }
  
  // Fall back to strike_type + floor/cap
  if (row.strike_type === "between" && isDefined(row.floor_strike) && isDefined(row.cap_strike)) {
    return `${city} ${row.floor_strike}-${row.cap_strike}°F`;
  }
  if (isDefined(row.cap_strike)) return `${city} ≤${row.cap_strike}`;
  if (isDefined(row.floor_strike)) return `${city} ≥${row.floor_strike}`;
  
  // Fallback: the ticker alone (a bracket is a known range; a tail has no known direction)
  const bracket = bracketFromTicker(row.target);
  if (bracket) return `${city} ${bracket[0]}-${bracket[1]}°F`;
  const { strike } = parseWeatherTarget(row.target);
  return strike !== null ? `${city} ${kind} ${strike}` : `${city} ${kind}`;
}