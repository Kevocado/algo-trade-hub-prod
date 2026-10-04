import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const HOME = readFileSync(resolve(process.cwd(), "src/pages/Home.tsx"), "utf8");

describe("home page tells the truth", () => {
  it("carries no hardcoded equity series", () => {
    // Spec §1: hero copy "leads with settled-ledger stats (N settled, Brier skill vs market),
    // NEVER with projected returns." A hardcoded `chartData` array rendered under "Growth Trajectory"
    // / "Aggregated account performance history" is exactly that: a fabricated $10k -> $24.1k curve
    // presented as this account's history. Same class of lie as PR #20.
    //
    // There is no real series to plot either -- `portfolio_metrics` is a single row
    // (`id INTEGER PRIMARY KEY`), so an equity trajectory cannot be reconstructed from it without a
    // new table and a snapshot writer. So the chart goes rather than becoming a different fiction.
    expect(HOME).not.toMatch(/const\s+chartData/);
    expect(HOME).not.toMatch(/Growth Trajectory/);
    expect(HOME).not.toMatch(/Aggregated account performance history/);
  });

  it("still reads its headline numbers from the real portfolio", () => {
    // The guard on the guard: deleting the chart must not take the truthful hero with it.
    expect(HOME).toMatch(/usePortfolioMetrics/);
    expect(HOME).toMatch(/usePortfolio\b/);
  });
});
