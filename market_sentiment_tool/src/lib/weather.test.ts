import { describe, expect, it } from "vitest";

import {
  WEATHER_INTRO,
  formatProb,
  formatOutcome,
  weatherStats,
  weatherLabel,
  weatherChip,
  type WeatherTodayRow,
  type WeatherSettledRow,
} from "@/lib/weather";

const baseRow = {
  target: "kalshi:KXHIGHNY-26OCT18",
  date: "26OCT18",
  ensemble: 0.65,
  kalshi: 0.6,
  climatology: 0.55,
  strike_type: null as string | null,
  floor_strike: null as number | null,
  cap_strike: null as number | null,
  yes_sub_title: null as string | null,
  no_sub_title: null as string | null,
};

const TODAY_ROW: WeatherTodayRow = { ...baseRow, target: "kalshi:KXHIGHNY-26OCT18" };
const SETTLED_ROW: WeatherSettledRow = {
  ...baseRow,
  target: "kalshi:KXHIGHNY-26OCT17",
  outcome: 1,
  realized_value: 92.0,
  settled_at: "2026-10-18T00:00:00+00:00",
};

const words = (s: string) => s.trim().split(/\s+/).filter(Boolean).length;

describe("weather page truth", () => {
  it("keeps the intro within the word budget", () => {
    expect(words(WEATHER_INTRO)).toBeLessThanOrEqual(15);
  });

  it("formats probabilities as percentages", () => {
    expect(formatProb(0.65)).toBe("65%");
    expect(formatProb(0.6)).toBe("60%");
    expect(formatProb(null)).toBe("—");
    expect(formatProb(undefined)).toBe("—");
  });

  it("formats outcomes as YES or NO", () => {
    expect(formatOutcome(1)).toBe("YES");
    expect(formatOutcome(0)).toBe("NO");
    expect(formatOutcome(null)).toBe("—");
    expect(formatOutcome(undefined)).toBe("—");
  });

  it("summarises for the big stats without inventing a score", () => {
    const s = weatherStats([TODAY_ROW], [SETTLED_ROW]);
    expect(s.todayCount).toBe(1);
    expect(s.settledCount).toBe(1);
    expect(s.cities).toBe(1);
    // No "edge", no "accuracy", no percentage that is not a count or a measured gap.
    expect(Object.keys(s)).not.toContain("edge");
    expect(Object.keys(s)).not.toContain("accuracy");
  });

  it("reports empty data as dashes, not zeroes", () => {
    const s = weatherStats([], []);
    expect(s.todayCount).toBe(0);
    expect(s.settledCount).toBe(0);
    expect(s.cities).toBe(0);
  });

  it("counts cities from unique targets", () => {
    const rows: WeatherTodayRow[] = [
      { ...TODAY_ROW, target: "T-KXHIGHNY-26OCT18" },
      { ...TODAY_ROW, target: "T-KXHIGHLAX-26OCT18" },
      { ...TODAY_ROW, target: "T-KXHIGHPHIL-26OCT18" },
    ];
    const s = weatherStats(rows, []);
    expect(s.cities).toBe(3);
  });
});

describe("weatherLabel", () => {
  const base = {
    target: "kalshi:KXHIGHNY-26OCT18",
    date: "26OCT18",
    ensemble: 0.65,
    kalshi: 0.6,
    climatology: 0.55,
  } as WeatherTodayRow;

  it("uses yes_sub_title when present (strike_type 'less', e.g., '64° or below')", () => {
    const row = { ...base, strike_type: "less", yes_sub_title: "64° or below" };
    expect(weatherLabel(row)).toBe("NYC 64° or below");
    // Must NEVER contain "above"
    expect(weatherLabel(row)).not.toContain("above");
  });

  it("uses yes_sub_title when present (strike_type 'greater', e.g., '73° or above')", () => {
    const row = { ...base, strike_type: "greater", yes_sub_title: "73° or above" };
    expect(weatherLabel(row)).toBe("NYC 73° or above");
    // Must NEVER contain "below"
    expect(weatherLabel(row)).not.toContain("below");
  });

  it("uses no_sub_title when yes_sub_title absent", () => {
    const row = { ...base, strike_type: "greater", no_sub_title: "73° or above" };
    expect(weatherLabel(row)).toBe("NYC 73° or above");
  });

  it("renders bracket range for strike_type 'between'", () => {
    const row = { ...base, strike_type: "between", floor_strike: 65, cap_strike: 66 };
    expect(weatherLabel(row)).toBe("NYC 65-66°F");
  });

  it("falls back to floor/cap when yes/no_sub_title absent", () => {
    const row = { ...base, strike_type: "greater", floor_strike: 60, cap_strike: 70 };
    expect(weatherLabel(row)).toBe("NYC 60°F+ 70°F-");
  });

  it("falls back to neutral ticker label when no metadata", () => {
    const row = { ...base, target: "kalshi:KXHIGHNY-26OCT18-T75" };
    expect(weatherLabel(row)).toBe("NYC high tail at 75°F");
  });

  it("handles missing (undefined) fields the same as null", () => {
    const row = { ...base, strike_type: undefined, yes_sub_title: undefined, target: "kalshi:KXHIGHNY-26OCT18-T75" };
    // Should fall through to ticker-based fallback
    expect(weatherLabel(row)).toBe("NYC high tail at 75°F");
  });
});

describe("weatherChip", () => {
  const base = {
    target: "kalshi:KXHIGHNY-26OCT18",
    date: "26OCT18",
    ensemble: 0.65,
    kalshi: 0.6,
    climatology: 0.55,
  } as WeatherTodayRow;

  it("uses ≥ for 'greater' markets (yes_sub_title '73° or above')", () => {
    const row = { ...base, strike_type: "greater", yes_sub_title: "73° or above" };
    expect(weatherChip(row)).toBe("NYC ≥73");
    // Must NOT be ≤
    expect(weatherChip(row)).not.toContain("≤");
  });

  it("uses ≤ for 'less' markets (yes_sub_title '64° or below')", () => {
    const row = { ...base, strike_type: "less", yes_sub_title: "64° or below" };
    expect(weatherChip(row)).toBe("NYC ≤64");
    // Must NOT be ≥
    expect(weatherChip(row)).not.toContain("≥");
  });

  it("uses no_sub_title direction correctly", () => {
    const row = { ...base, strike_type: "greater", no_sub_title: "73° or above" };
    expect(weatherChip(row)).toBe("NYC ≥73");
  });

  it("renders bracket range for strike_type 'between'", () => {
    const row = { ...base, strike_type: "between", floor_strike: 65, cap_strike: 66 };
    expect(weatherChip(row)).toBe("NYC 65-66°F");
  });

  it("falls back to cap_strike with ≤ when only cap present", () => {
    const row = { ...base, strike_type: "greater", cap_strike: 70 };
    expect(weatherChip(row)).toBe("NYC ≤70");
  });

  it("falls back to floor_strike with ≥ when only floor present", () => {
    const row = { ...base, strike_type: "less", floor_strike: 60 };
    expect(weatherChip(row)).toBe("NYC ≥60");
  });

  it("handles missing (undefined) fields the same as null", () => {
    const row = { ...base, strike_type: undefined, cap_strike: undefined };
    expect(weatherChip(row)).toBe("NYC H");
  });

  it("never renders the literal string 'undefined'", () => {
    const row = { ...base, strike_type: "greater", yes_sub_title: "73° or above" };
    const chip = weatherChip(row);
    expect(chip).not.toContain("undefined");
  });
});