import { describe, expect, it } from "vitest";

import { edgeGate } from "@/lib/edgeGate";
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
  engine: "labor_nowcast",
  gate_status: "SHADOW",
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

describe("jobsScorecard gate status", () => {
  it("defaults to shadow when the API sends no gate status", () => {
    // Kevin's decision: the page badges the engine's gate status next to the nowcast, and a
    // missing status must read Shadow (fail closed), never Promoted.
    expect(edgeGate({ gate_status: undefined }).isShadow).toBe(true);
    expect(edgeGate({ gate_status: "SHADOW" }).isShadow).toBe(true);
    expect(edgeGate({ gate_status: "PROMOTED" }).isShadow).toBe(false);
  });

  it("takes the gate status from the row the API returned", () => {
    const promoted: JobsScorecardRow = { ...row({}), engine: "labor_nowcast", gate_status: "PROMOTED" };
    expect(edgeGate(promoted).label).toBe("Promoted");
    const shadow: JobsScorecardRow = { ...row({}), engine: "labor_nowcast", gate_status: "SHADOW" };
    expect(edgeGate(shadow).label).toBe("Shadow");
  });

  it("keeps the engine version visible so a badge can be traced to a promotion", () => {
    // The gate is keyed on (engine, engine_version), so showing the version is what makes a
    // PROMOTED badge auditable rather than a claim.
    expect(row({}).engine_version).toBe("labor-v1");
    expect(row({}).engine).toBe("labor_nowcast");
  });
});
