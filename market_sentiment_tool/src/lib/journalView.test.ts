import { describe, expect, it } from "vitest";

import { forecasterLabel } from "@/lib/forecasterLabels";
import { baselineName } from "@/lib/forecasterLabels";
import type { JournalScore } from "@/lib/journal";
import { EARLY_N, skillText, split, statusOf, totals, viewRows } from "@/lib/journalView";

function score(over: Partial<JournalScore> = {}): JournalScore {
  return {
    forecaster: "spy_quant", forecaster_version: "spy-wf-v1", cadence: "daily", baseline: "climatology",
    n_targets: 3, n_settled: 0, brier: null, brier_baseline: null, bss: null, reliability: [], murphy: {},
    calibration_ready: false, gate_status: "SHADOW", gate_reasons: [], computed_at: "2026-10-01T00:00:00Z", ...over,
  };
}

describe("labels", () => {
  it("speaks plainly and falls back to the raw name made readable", () => {
    expect(forecasterLabel("spy_quant")).toBe("S&P 500 tomorrow: model");
    expect(forecasterLabel("cpi_nowcast", "cpi-core-v1")).toBe("Core inflation (CPI)");
    expect(forecasterLabel("cpi_nowcast", "cpi-v1")).toBe("Inflation (CPI)");
    expect(forecasterLabel("new_thing")).toBe("New thing");
    expect(baselineName("market")).toBe("the Kalshi price");
  });
});

describe("status", () => {
  it("is waiting with nothing scored, too early before enough evidence, then ahead or behind", () => {
    expect(statusOf(score())).toBe("waiting");
    expect(statusOf(score({ n_settled: 1, bss: 0.2 }))).toBe("early");
    expect(statusOf(score({ n_settled: EARLY_N, bss: null }))).toBe("early");
    expect(statusOf(score({ n_settled: EARLY_N, bss: 0.05 }))).toBe("ahead");
    expect(statusOf(score({ n_settled: EARLY_N, bss: -0.05 }))).toBe("behind");
    expect(statusOf(score({ n_settled: 250, bss: 0.1, gate_status: "PROMOTED" }))).toBe("promoted");
  });
});

describe("view", () => {
  const scores = [
    score(),
    score({ forecaster: "sports_nfl", forecaster_version: "feed-v1", baseline: "market", n_settled: 4, n_targets: 6 }),
    score({ forecaster: "kalshi_implied_sports_nfl", forecaster_version: "v1", n_settled: 4, n_targets: 6 }),
    score({ forecaster: "housing_direction", forecaster_version: "housing-wf-v1", cadence: "monthly" }),
  ];

  it("folds the Kalshi baseline into its model's row and orders scored rows first", () => {
    const { results, waiting } = split(viewRows(scores));
    expect(results.map((r) => r.label)).toEqual(["NFL winners"]);
    expect(results[0].market?.forecaster).toBe("kalshi_implied_sports_nfl");
    expect(results[0].against).toBe("the Kalshi price");
    expect(waiting.map((r) => r.label)).toEqual(["S&P 500 tomorrow: model", "US home prices"]);
  });

  it("pairs a spread or total forecaster with its own Kalshi baseline and names it in plain words", () => {
    const rows = viewRows([
      score({ forecaster: "sports_nfl_spread", forecaster_version: "feed-v1", baseline: "market", n_settled: 3, n_targets: 5 }),
      score({ forecaster: "kalshi_implied_sports_nfl_spread", forecaster_version: "v1", n_settled: 3, n_targets: 5 }),
      score({ forecaster: "sports_nfl_total", forecaster_version: "feed-v1", n_targets: 2 }),
    ]);
    const spread = rows.find((r) => r.label === "NFL point spreads");
    expect(spread?.market?.forecaster).toBe("kalshi_implied_sports_nfl_spread");
    expect(rows.find((r) => r.label === "NFL game totals")?.market).toBeNull();
  });

  it("names a cautious copy after its model and grades it against the same Kalshi baseline", () => {
    const rows = viewRows([
      score({ forecaster: "cpi_nowcast_cautious", forecaster_version: "cpi-core-v1+w25", baseline: "market", n_targets: 3 }),
      score({ forecaster: "sports_nfl_spread_cautious", forecaster_version: "feed-v1+w25", baseline: "market", n_targets: 2 }),
      score({ forecaster: "kalshi_implied_cpi", forecaster_version: "v1", n_targets: 3 }),
      score({ forecaster: "kalshi_implied_sports_nfl_spread", forecaster_version: "v1", n_targets: 2 }),
    ]);
    expect(rows.map((r) => r.label).sort()).toEqual(["Core inflation (CPI) (cautious)", "NFL point spreads (cautious)"]);
    expect(rows.every((r) => r.market !== null)).toBe(true);
  });

  it("counts what the page headlines, and a monthly forecaster needs 50 not 200", () => {
    const rows = viewRows(scores);
    expect(totals(rows)).toEqual({ forecasters: 3, frozen: 12, scored: 4, promoted: 0 });
    expect(rows.find((r) => r.label === "US home prices")?.needed).toBe(50);
  });

  it("writes skill signed and never as a bare zero for 'not measured'", () => {
    expect(skillText(0.234)).toBe("+0.23");
    expect(skillText(-0.097)).toBe("-0.10");
    expect(skillText(null)).toBe("—");
  });
});
