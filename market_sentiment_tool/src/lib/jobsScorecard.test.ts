import { describe, expect, it } from "vitest";

import {
  formatValue,
  summarizeScorecard,
  toChartPoints,
  type JobsScorecardRow,
} from "@/lib/jobsScorecard";

const row = (overrides: Partial<JobsScorecardRow>): JobsScorecardRow => ({
  series: "payrolls",
  reference_month: "2026-08-01",
  kalshi_event: "KXPAYROLLS-26AUG",
  release_date: "2026-09-04",
  nowcast_mu: 60,
  nowcast_sigma: 90,
  engine_version: "labor-v1",
  kalshi_mean_1h: 45,
  kalshi_median_1h: 44,
  first_print: 162,
  rev2: null,
  rev3: null,
  benchmark: null,
  latest: 162,
  n_strikes: 17,
  nowcast_abs_err: 102,
  kalshi_abs_err: 117,
  nowcast_brier: 0.2,
  kalshi_brier: 0.25,
  ...overrides,
});

describe("jobsScorecard helpers", () => {
  it("sorts chart points by month and keeps missing values as null", () => {
    const points = toChartPoints([
      row({ reference_month: "2026-08-01" }),
      row({ reference_month: "2026-07-01", kalshi_mean_1h: null, first_print: -23 }),
    ]);
    expect(points.map((p) => p.month)).toEqual(["2026-07", "2026-08"]);
    expect(points[0]).toEqual({ month: "2026-07", nowcast: 60, kalshi: null, firstPrint: -23, latest: 162 });
  });

  it("coerces numeric strings from PostgREST numeric columns", () => {
    const [point] = toChartPoints([row({ nowcast_mu: "12.5" as unknown as number })]);
    expect(point.nowcast).toBe(12.5);
  });

  it("summarizes only fully scored months", () => {
    const summary = summarizeScorecard([
      row({}),
      row({ reference_month: "2026-07-01", nowcast_abs_err: 10, kalshi_abs_err: 30, nowcast_brier: 0.1, kalshi_brier: 0.05 }),
      row({ reference_month: "2026-09-01", first_print: null, nowcast_abs_err: null, kalshi_abs_err: null,
            nowcast_brier: null, kalshi_brier: null }),
    ]);
    expect(summary.months).toBe(3);
    expect(summary.scored).toBe(2);
    expect(summary.nowcastMae).toBeCloseTo(56);
    expect(summary.kalshiMae).toBeCloseTo(73.5);
    expect(summary.nowcastBrier).toBeCloseTo(0.15);
    expect(summary.kalshiBrier).toBeCloseTo(0.15);
    expect(summary.nowcastCloser).toBe(2);
  });

  it("formats payrolls in signed thousands and unemployment in percent", () => {
    expect(formatValue("payrolls", 162)).toBe("+162k");
    expect(formatValue("payrolls", -23.4)).toBe("-23k");
    expect(formatValue("unemployment", 4.1)).toBe("4.1%");
    expect(formatValue("payrolls", null)).toBe("—");
  });
});
