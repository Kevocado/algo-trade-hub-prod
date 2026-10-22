import { describe, expect, it } from "vitest";

import {
  WEATHER_INTRO,
  formatProb,
  formatOutcome,
  weatherStats,
  type WeatherTodayRow,
  type WeatherSettledRow,
} from "@/lib/weather";

const TODAY_ROW: WeatherTodayRow = {
  target: "T-KXHIGHNY-26OCT18",
  date: "26OCT18",
  ensemble: 0.65,
  kalshi: 0.6,
  climatology: 0.55,
  strike_type: null,
  floor_strike: null,
  cap_strike: null,
  yes_sub_title: null,
  no_sub_title: null,
};

const SETTLED_ROW: WeatherSettledRow = {
  target: "T-KXHIGHNY-26OCT17",
  date: "26OCT17",
  ensemble: 0.7,
  kalshi: 0.72,
  climatology: 0.6,
  outcome: 1,
  realized_value: 92.0,
  settled_at: "2026-10-18T00:00:00+00:00",
  strike_type: null,
  floor_strike: null,
  cap_strike: null,
  yes_sub_title: null,
  no_sub_title: null,
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