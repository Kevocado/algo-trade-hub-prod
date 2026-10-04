import { describe, expect, it } from "vitest";

import { forecasterLabel } from "@/lib/forecasterLabels";
import { baselineName } from "@/lib/forecasterLabels";
import type { JournalScore } from "@/lib/journal";
import { EARLY_N, skillText, split, statusOf, totals, viewRows } from "@/lib/journalView";

/**
 * Every naive baseline the registry publishes, with the plain-language label it must render as. Asserted
 * in full: a wrong word in any ONE of them (mutation: gold persistence relabelled "the usual rate") is a
 * visitor reading the wrong baseline on the tile, and nothing else would notice.
 */
const BASELINE_LABELS: Record<string, string> = {
  baseline_persistence_spx: "S&P 500 tomorrow: yesterday again (baseline)",
  baseline_climatology_spx: "S&P 500 tomorrow: the usual rate (baseline)",
  baseline_persistence_vix: "Volatility (VIX) tomorrow: yesterday again (baseline)",
  baseline_climatology_vix: "Volatility (VIX) tomorrow: the usual rate (baseline)",
  baseline_persistence_gold: "Gold tomorrow: yesterday again (baseline)",
  baseline_climatology_gold: "Gold tomorrow: the usual rate (baseline)",
  baseline_persistence_eurusd: "Euro vs dollar tomorrow: yesterday again (baseline)",
  baseline_climatology_eurusd: "Euro vs dollar tomorrow: the usual rate (baseline)",
  baseline_persistence_housing: "US home prices: last month again (baseline)",
  baseline_climatology_housing: "US home prices: the usual rate (baseline)",
};

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

  // Spec §8: a baseline "must not read as a prediction". The fallback would render
  // `baseline_persistence_vix` as "Baseline persistence vix", which reads like a forecaster name.
  it("says a naive baseline is a baseline, and never gives it the model's label", () => {
    for (const [name, label] of Object.entries(BASELINE_LABELS)) {
      expect(forecasterLabel(name)).toBe(label);
      expect(label).toContain("(baseline)");
    }
    // Distinct from every model it sits beside, and distinct from its sibling kind.
    expect(forecasterLabel("baseline_persistence_spx")).not.toBe(forecasterLabel("spy_quant"));
    expect(forecasterLabel("baseline_persistence_spx")).not.toBe(forecasterLabel("baseline_climatology_spx"));
    expect(forecasterLabel("baseline_persistence_vix")).not.toBe(forecasterLabel("vix_direction"));
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
  // All calibrated: this fixture is about the CADENCE minimum (`needed`), not the display gate, so
  // its cards must clear the gate to contribute at all. The gate has its own tests.
  const scores = [
    score({ calibration_ready: true }),
    score({ forecaster: "sports_nfl", forecaster_version: "feed-v1", baseline: "market", n_settled: 4, n_targets: 6, calibration_ready: true }),
    score({ forecaster: "kalshi_implied_sports_nfl", forecaster_version: "v1", n_settled: 4, n_targets: 6, calibration_ready: true }),
    score({ forecaster: "housing_direction", forecaster_version: "housing-wf-v1", cadence: "monthly", calibration_ready: true }),
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

  it("counts one set of evidence when a model and its cautious copy share a target set", () => {
    const rows = viewRows([
      score({ forecaster: "cpi_nowcast", forecaster_version: "cpi-v1", baseline: "market", n_targets: 200, n_settled: 200, calibration_ready: true }),
      score({ forecaster: "cpi_nowcast_cautious", forecaster_version: "cpi-v1+w25", baseline: "market", n_targets: 200, n_settled: 200, calibration_ready: true }),
    ]);
    expect(totals(rows)).toEqual({ forecasters: 2, frozen: 200, scored: 200, promoted: 0 });
  });

  it("leaves a provisional card out of the aggregate but not out of the count", async () => {
    // Mutation testing caught that this gate was untested: `/journal` reads the server headline now,
    // so only `/cpi` still calls `totals()`, and every fixture above is calibrated. Dropping
    // `&& r.score.calibration_ready` passed the whole suite.
    //
    // Spec §10: "any forecaster appears from its first frozen row; headline stats aggregate ONLY
    // post-calibration forecasters." The card is still COUNTED (`forecasters`), just not summed.
    const rows = viewRows([
      score({ forecaster: "spy_quant", forecaster_version: "v1", n_targets: 200, n_settled: 120, calibration_ready: true }),
      score({ forecaster: "vix_direction", forecaster_version: "v1", n_targets: 999, n_settled: 888, calibration_ready: false }),
    ]);
    expect(totals(rows)).toEqual({ forecasters: 2, frozen: 200, scored: 120, promoted: 0 });
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

describe("skill never prints as zero when it is not zero", () => {
  it("keeps a small measured skill visible instead of rounding it to +0.00", () => {
    // CodeRabbit Minor on #105: `skillText` formats to two decimals, so a BSS of 0.000482 renders
    // "+0.00" -- a measured result displayed as exactly zero. This is the same defect the whole
    // readable-UI effort exists to prevent, and it is worst in the hero, where a real (if tiny)
    // measurement is the number a reader came for.
    //
    // The gold replay measured +0.0006 and the page showed "+0.00". Gold has no skill; saying so
    // with a number that reads as a clean zero is not the same claim as "we could not tell".
    expect(skillText(0.000482)).not.toBe("+0.00");
    expect(skillText(0.000482)).toBe("+0.0005");
    expect(skillText(-0.0006)).toBe("-0.0006");
  });

  it("still says nothing measured as an em dash, and keeps ordinary magnitudes readable", () => {
    // The guard on the guard: extra precision must not turn "we have no measurement" into a number,
    // and the common cases must not become unreadable strings.
    expect(skillText(null)).toBe("—");
    expect(skillText(0.23)).toBe("+0.23");
    expect(skillText(-0.1)).toBe("-0.10");
    expect(skillText(0)).toBe("0.00");
  });
});
