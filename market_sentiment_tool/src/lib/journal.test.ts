import { describe, expect, it } from "vitest";

import { biasReadout, pct, skillText, tiles, type JournalScore } from "@/lib/journal";

function score(over: Partial<JournalScore> = {}): JournalScore {
  return {
    forecaster: "cpi_nowcast",
    forecaster_version: "cpi-v1",
    cadence: "monthly",
    baseline: "market",
    n_targets: 12,
    n_settled: 10,
    brier: 0.071,
    brier_baseline: 0.068,
    bss: -0.044,
    reliability: [],
    murphy: {},
    calibration_ready: false,
    gate_status: "SHADOW",
    gate_reasons: ["only 10 settled targets, need 50 (monthly)"],
    computed_at: "2026-10-01T13:00:00+00:00",
    ...over,
  };
}

describe("tiles", () => {
  it("puts each market pseudo-forecaster beneath its model and never drops an orphan", () => {
    const out = tiles([
      score(),
      score({ forecaster: "kalshi_implied_cpi", forecaster_version: "v1" }),
      score({ forecaster: "kalshi_implied_fomc", forecaster_version: "v1" }),
      score({ forecaster: "unrate_direction", forecaster_version: "unrate-dir-v1", baseline: "climatology" }),
    ]);
    expect(out.map((t) => [t.model.forecaster, t.market?.forecaster ?? null])).toEqual([
      ["cpi_nowcast", "kalshi_implied_cpi"],
      ["unrate_direction", null],
      ["kalshi_implied_fomc", null],
    ]);
  });
});

describe("wording", () => {
  it("says a missing skill in words, never as zero, and labels the baseline", () => {
    expect(skillText(score({ bss: null }))).toBe("Brier skill not scored yet");
    expect(skillText(score())).toBe("Brier skill -0.044 vs the Kalshi market");
    expect(skillText(score({ bss: 0.12, baseline: "climatology" }))).toBe("Brier skill +0.120 vs climatology");
    expect(pct(null)).toBe("no market price");
  });

  it("reads bias off the best-populated bucket", () => {
    const buckets = [
      { bucket: "60-70", n: 30, predicted: 0.65, observed: 0.55 },
      { bucket: "90-100", n: 4, predicted: 0.95, observed: 1.0 },
    ];
    expect(biasReadout(buckets)).toBe("overconfident by 10.0pp in the 60-70 bucket (n=30)");
    expect(biasReadout([])).toBeNull();
  });
});
