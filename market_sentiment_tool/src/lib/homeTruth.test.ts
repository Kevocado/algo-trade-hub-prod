import { describe, expect, it } from "vitest";

import {
  HOME_INTRO,
  gapText,
  headlineStats,
  homeLinks,
  plainName,
  verdictChip,
  type Standings,
} from "@/lib/homeTruth";

const STANDINGS: Standings = {
  best: {
    forecaster: "gas",
    version: "gas-v2",
    baseline: "market",
    cadence: "daily",
    gap: -0.03,
    se: 0.005,
    n: 760,
    n_settled: 1982,
    bss: 0.045,
    verdict: "beats",
    date_from: "2026-06-01",
    date_to: "2026-09-20",
  },
  worst: {
    forecaster: "ercot_peak",
    version: "v1",
    baseline: "climatology",
    cadence: "daily",
    gap: 0.02,
    se: 0.004,
    n: 500,
    n_settled: 300,
    bss: -0.01,
    verdict: "loses to",
    date_from: "2026-06-01",
    date_to: "2026-09-20",
  },
  n_settled: 2282,
  n_replayed: 2,
  forecasters: 9,
  market_linked: ["gas"],
  distinct_se: 2,
  verdict:
    "gas beats the Kalshi price by -0.030 ± 0.005 over 760 replayed sessions, on 1982 settled contracts in total.",
};

const EMPTY: Standings = {
  best: null,
  worst: null,
  n_settled: 0,
  n_replayed: 0,
  forecasters: 0,
  market_linked: [],
  distinct_se: 2,
  verdict: "No forecaster has settled results yet, so there is nothing to compare against the Kalshi price.",
};

const words = (s: string) => s.trim().split(/\s+/).filter(Boolean).length;

describe("front page truth", () => {
  it("keeps the intro within the word budget", () => {
    expect(words(HOME_INTRO)).toBeLessThanOrEqual(15);
  });

  // The verdict words are the whole point of the page, so they are pinned exactly. A refactor that
  // softens "Loses to" into "Underperforming" would still read fine and would be dishonest.
  it("renders each verdict as a one- or two-word chip", () => {
    expect(verdictChip("beats").label).toBe("Beats");
    expect(verdictChip("loses to").label).toBe("Loses to");
    expect(verdictChip("indistinguishable").label).toBe("No signal");
    expect(verdictChip("unknown").label).toBe("No interval");
    for (const v of ["beats", "loses to", "indistinguishable", "unknown", "no difference"]) {
      const n = words(verdictChip(v).label);
      expect(n).toBeGreaterThanOrEqual(1);
      expect(n).toBeLessThanOrEqual(2);
    }
  });

  it("never renders a missing gap or interval as zero", () => {
    expect(gapText(null, 0.005)).toBe("—");
    expect(gapText(-0.03, null)).toBe("—");
    // A standard error of exactly 0 is a measured zero-width bar, not a missing one: the backend's
    // `gap_verdict` treats it as a decisive result, so rendering it as a dash here would contradict it.
    expect(gapText(-0.03, 0)).toBe("−0.030 ± 0.000");
  });

  it("renders the gap with its interval when both are measured", () => {
    expect(gapText(-0.03, 0.005)).toContain("−0.030");
    expect(gapText(-0.03, 0.005)).toContain("0.005");
  });

  it("uses the plain forecast name, not the machine key", () => {
    expect(plainName("gas")).toBe("AAA gasoline prices");
    expect(plainName("ercot_peak")).toBe("Texas grid peak demand");
    // An unknown key degrades to a title-cased version of itself, never to a blank.
    expect(plainName("brand_new_thing")).toBe("Brand new thing");
  });

  it("summarises for the big stats without inventing a score", () => {
    const s = headlineStats(STANDINGS);
    expect(s.settled).toBe(2282);
    expect(s.forecasters).toBe(9);
    expect(s.replayed).toBe(2);
    expect(s.bestName).toBe("AAA gasoline prices");
    // No "edge", no "accuracy", no percentage that is not a count or a measured gap.
    expect(Object.keys(s)).not.toContain("edge");
    expect(Object.keys(s)).not.toContain("accuracy");
  });

  it("reports empty standings as dashes, not zeroes", () => {
    const s = headlineStats(EMPTY);
    expect(s.bestName).toBe("—");
    expect(s.bestGap).toBe("—");
    expect(s.settled).toBe(0); // a real measured count of zero settled is 0, not a dash
  });

  // Only pages that exist are linked. The weather page and the order-book study are not built yet,
  // and a link to a route that 404s is a broken promise on the landing page.
  it("links only to pages that exist", () => {
    const paths = homeLinks.map((l) => l.to);
    expect(paths).toContain("/journal");
    expect(paths).toContain("/models");
    expect(paths).toContain("/sports");
    expect(paths).toContain("/health");
    expect(paths).not.toContain("/weather");
  });

  it("serves the verdict from the server rather than typing one", () => {
    expect(STANDINGS.verdict).toContain("gas");
    expect(EMPTY.verdict).toContain("No forecaster");
  });
});