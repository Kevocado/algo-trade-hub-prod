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

  it("no longer leads with portfolio figures that can only ever be unknown", () => {
    // The old hero led with Total Value, Daily PnL and Available Cash. This product places no
    // orders, so all three were dashes with a note -- three large numbers that could never carry a
    // value, above the fold, on the first thing a reader sees. The guard the old test wrote ("the
    // hero still reads real numbers") survives as a better one: the hero now reads the journal.
    expect(HOME).not.toMatch(/usePortfolioMetrics/);
    expect(HOME).not.toMatch(/War Room HQ/);
    expect(HOME).not.toMatch(/Aggregating cross-engine alpha/);
  });

  it("leads with the journal's own measured standings", () => {
    // The guard on the guard: replacing the hero must not leave the page without real numbers.
    // `standings` is computed by `tradehub/journal/standings.py`, so the page cannot invent a skill.
    expect(HOME).toMatch(/useStandings/);
    expect(HOME).toMatch(/standings\.verdict/);
    expect(HOME).toMatch(/headlineStats/);
  });

  it("computes no score of its own", () => {
    // A gap is only a result once it clears its standard error. That comparison lives on the server
    // (`gap_verdict`), deliberately in one place. A threshold or a division here would be a second
    // implementation of the rule, and a second place to be wrong.
    expect(HOME).not.toMatch(/Math\.abs\(/); // any threshold comparison
    expect(HOME).not.toMatch(/\bse\s*[<>*/]/); // the interval used in arithmetic
    expect(HOME).not.toMatch(/distinct_se\s*[<>/*]/); // the threshold applied, not merely read
    expect(HOME).not.toMatch(/\bverdict\s*=[^=]/); // the verdict derived here rather than received
  });
});