import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { LiveSkill, gapText, liveRows, verdict } from "@/components/LiveSkill";
import type { JournalScore } from "@/lib/journal";

function score(over: Partial<JournalScore>): JournalScore {
  return {
    forecaster: "sports_nfl", forecaster_version: "feed-v1", cadence: "daily", baseline: "market", n_targets: 50,
    n_settled: 50, brier: 0.2, brier_baseline: 0.2, bss: 0, reliability: [], murphy: {}, calibration_ready: false,
    gate_status: "SHADOW", gate_reasons: [], computed_at: "x", gap: -0.01, gap_se: 0.004, ...over,
  } as JournalScore;
}

describe("LiveSkill", () => {
  it("draws the live forecasters, never the Kalshi mid, the baselines or a forecaster with no gap", () => {
    const rows = liveRows([
      score({}), score({ forecaster: "sports_cfb", gap: 0.05, gap_se: 0.01 }),
      score({ forecaster: "kalshi_implied_sports_nfl", gap: 0, gap_se: 0 }),
      score({ forecaster: "baseline_climatology_weather_high", gap: 0.1, gap_se: 0.01 }),
      score({ forecaster: "weather_rain", gap: null, gap_se: null }),
      score({ forecaster: "spy_quant", baseline: "climatology" }),
    ]);
    expect(rows.map((r) => r.key)).toEqual(["sports_nfl@feed-v1", "sports_cfb@feed-v1"]);   // best (lowest gap) first
  });

  it("says Ahead or Behind only when the whole 95% interval is on one side of zero", () => {
    expect(verdict(-0.03, 0.005)).toBe("ahead");
    expect(verdict(0.03, 0.005)).toBe("behind");
    expect(verdict(-0.01, 0.01)).toBe("none");       // interval straddles zero
    expect(verdict(-0.03, null)).toBe("none");       // no interval, no claim
  });

  it("prints three decimals with a signed gap and its 95% half-width, never a raw float", () => {
    expect(gapText(-0.0474215000000002, 0.004)).toBe("−0.047 ± 0.008");
    expect(gapText(0.1, null)).toBe("+0.100");
    render(<LiveSkill scores={[score({ gap: -0.0474215000000002 })]} />);
    expect(screen.queryByText(/0000000/)).toBeNull();
  });

  it("draws a forecaster with under 30 scored contracts hollow and labels it", () => {
    render(<LiveSkill scores={[score({ n_settled: 12 }), score({ forecaster: "sports_cfb", n_settled: 100 })]} />);
    const dots = screen.getAllByTestId("dot");
    expect(dots.map((d) => d.getAttribute("data-hollow"))).toEqual(["true", "false"]);
    expect(screen.getByText(/12 scored/)).toBeInTheDocument();
  });

  it("labels the zero line and the direction, and says so when nothing has a gap", () => {
    const { rerender } = render(<LiveSkill scores={[score({})]} />);
    const list = screen.getByRole("list", { name: "Skill against the Kalshi price" });
    expect(within(list).getByText(/better/)).toBeInTheDocument();
    expect(within(list).getByText("0")).toBeInTheDocument();
    rerender(<LiveSkill scores={[score({ gap: null })]} />);
    expect(screen.getByText("No forecaster has a measured gap yet.")).toBeInTheDocument();
  });
});
