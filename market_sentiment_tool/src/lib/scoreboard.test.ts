import { describe, expect, it } from "vitest";

import {
  backtestGateLabel,
  brierVerdict,
  formatBrier,
  formatCount,
  formatSimulatedMoney,
  settledBars,
  summarise,
  type ScoreboardResponse,
  type ScoreboardRow,
} from "@/lib/scoreboard";

/**
 * Wording and shape for the engine scoreboard.
 *
 * Every engine currently loses (spec section 1). The temptation on a page like this is to soften
 * that -- "close", "competitive", a coloured delta that reads as near-parity. Gas sits at 4.29x the
 * market's Brier, which is not close, and a reader told otherwise cannot judge the engine. So the
 * wording is pinned by test rather than left to taste.
 *
 * The other thing pinned here is what this module is NOT allowed to do. It holds no threshold, no
 * gate logic and no rounding policy of its own: every number it prints is a number the response
 * carried, and every verdict it words is a verdict the server resolved. `brier_verdict` and
 * `settled_distance` exist in `tradehub/scoreboard.py` for exactly that reason, and a second copy
 * of either in the browser is a second thing to keep wrong.
 */

/** A gas run at the production 2h: 4.29x the market, 42 settled against its own 200. */
const behind: ScoreboardRow = {
  engine: "gas",
  engine_version: "gas-v1",
  mode: "taker",
  date_from: "2026-06-01T00:00:00+00:00",
  date_to: "2026-09-20T00:00:00+00:00",
  created_at: "2026-09-20T00:00:00+00:00",
  n_decisions: 1982,
  n_fills: 274,
  n_settled: 42,
  brier_ours: 0.1148,
  brier_market: 0.02676,
  brier_ratio: 4.29,
  market_verdict: "behind",
  pnl_after_fees: -3.84,
  max_drawdown: 7.06,
  gate_status: "SHADOW",
  promotion_status: "SHADOW",
  gate_reasons: ["only 42 settled contracts, need 200 (daily)"],
  settled_distance: {
    n_settled: 42,
    required: 200,
    required_source: "gate",
    remaining: 158,
    met: false,
    pct: 21.0,
    floor: 100,
    floor_remaining: 58,
    floor_met: false,
    floor_pct: 42.0,
  },
};

/** A monthly engine at 70 settled. It has MET its own unstateable 50 bar; the floor is 100. */
const metOwnGate: ScoreboardRow = {
  ...behind,
  engine: "labor_nowcast",
  engine_version: "labor-v1",
  n_settled: 70,
  gate_reasons: ["model Brier 0.2 is not below market Brier 0.1"],
  settled_distance: {
    n_settled: 70,
    required: null,
    required_source: "engine",
    remaining: 0,
    met: true,
    pct: null,
    floor: 100,
    floor_remaining: 30,
    floor_met: false,
    floor_pct: 70.0,
  },
};

const unmeasured: ScoreboardRow = {
  ...behind,
  engine: "weather",
  engine_version: "weather-v1",
  mode: "maker",
  brier_ours: 0.13,
  brier_market: null,
  brier_ratio: null,
  market_verdict: "not_comparable",
  gate_reasons: ["no market Brier recorded; gate cannot be evaluated"],
};

function body(over: Partial<ScoreboardResponse> = {}): ScoreboardResponse {
  return {
    as_of: "2026-09-27T00:00:00+00:00",
    runs_read: 3,
    rows: [behind, metOwnGate, unmeasured],
    engines: 3,
    promotion_lookup_failed: false,
    rows_total: 3,
    rows_behind_market: 1,
    rows_ahead_of_market: 0,
    rows_level_with_market: 0,
    rows_not_comparable: 1,
    any_beats_market: false,
    headline: "No engine beats the market on Brier.",
    headline_kind: "behind",
    caveat: null,
    ...over,
  };
}

describe("formatBrier", () => {
  it("renders a Brier to five decimals, the precision the column stores", () => {
    // numeric(6,5) -- 20260416000004_backtest_runs.sql:22
    expect(formatBrier(0.1148)).toBe("0.11480");
    expect(formatBrier(0.02676)).toBe("0.02676");
  });

  it("renders an absent Brier as unknown, never as a zero", () => {
    for (const absent of [null, undefined, NaN]) {
      expect(formatBrier(absent)).toBe("—");
      expect(formatBrier(absent)).not.toBe("0.00000");
    }
  });
});

describe("formatCount and formatSimulatedMoney", () => {
  it("groups counts and dashes an absent one", () => {
    expect(formatCount(1982)).toBe("1,982");
    expect(formatCount(null)).toBe("—");
    expect(formatCount(0)).toBe("0");
  });

  it("keeps the sign on a loss and dashes an absent figure", () => {
    expect(formatSimulatedMoney(-3.84)).toBe("-$3.84");
    expect(formatSimulatedMoney(7.06)).toBe("$7.06");
    expect(formatSimulatedMoney(null)).toBe("—");
    // A zero P&L is a measurement and stays a measurement; only an absent one dashes.
    expect(formatSimulatedMoney(0)).toBe("$0.00");
  });
});

describe("brierVerdict", () => {
  it("states the multiple when the model is behind", () => {
    expect(brierVerdict(behind)).toMatch(/4\.3/);
  });

  it("never calls a deficit competitive, at any size", () => {
    for (const ratio of [1.1, 2, 4.29, 9]) {
      const verdict = brierVerdict({ ...behind, market_verdict: "behind", brier_ratio: ratio });
      expect(verdict).not.toMatch(/close|competitive|nearly|almost/i);
      expect(verdict).toMatch(/behind/i);
    }
  });

  it("says so when the model is ahead, with the multiple", () => {
    const verdict = brierVerdict({ ...behind, market_verdict: "ahead", brier_ratio: 0.5 });
    expect(verdict).toMatch(/ahead/i);
    expect(verdict).toMatch(/0\.50/);
  });

  it("says level rather than calling a tie a loss", () => {
    const verdict = brierVerdict({ ...behind, market_verdict: "level", brier_ratio: 1.0 });
    expect(verdict).toMatch(/level/i);
    expect(verdict).not.toMatch(/behind|lose/i);
  });

  it("says the comparison could not be made, and makes no claim about the market", () => {
    const verdict = brierVerdict(unmeasured);
    expect(verdict).toMatch(/not measured|cannot|no market/i);
    // "No engine beats the market" is a claim about the market; there is nothing here to claim.
    expect(verdict).not.toMatch(/behind|ahead|market's/i);
  });

  it("falls back to unknown when a verdict arrives with no ratio behind it", () => {
    expect(brierVerdict({ ...behind, brier_ratio: null })).toMatch(/not measured|cannot/i);
  });
});

describe("settledBars -- TWO bars, never one", () => {
  it("returns exactly two bars, each labelled, so neither can be read as the other", () => {
    const bars = settledBars(behind);

    expect(bars).toHaveLength(2);
    expect(bars.map((b) => b.label)).toEqual(["Own gate", "Reviewer's settled floor"]);
    expect(new Set(bars.map((b) => b.key)).size).toBe(2);
  });

  it("reports the gate's own stated bar and the reviewer's floor as separate numbers", () => {
    const [own, floor] = settledBars(behind);

    expect(own.required).toBe(200);
    expect(own.met).toBe(false);
    expect(own.line).toMatch(/42/);
    expect(own.line).toMatch(/158/);
    expect(floor.required).toBe(100);
    expect(floor.met).toBe(false);
    expect(floor.line).toMatch(/58/);
  });

  it("does not report a cleared monthly engine as failing a number that was never its bar", () => {
    // 70 settled against the engine's own unstateable 50 bar: MET. The floor is 100 and is unmet.
    const [own, floor] = settledBars(metOwnGate);

    expect(own.met).toBe(true);
    expect(own.required).toBeNull();
    expect(own.line).toMatch(/70/);
    expect(own.line).not.toMatch(/100/);
    expect(floor.required).toBe(100);
    expect(floor.met).toBe(false);
  });

  it("keeps met tri-state, and never turns nothing-measured into a pass", () => {
    const silent = settledBars({
      ...behind,
      settled_distance: { ...behind.settled_distance!, required: null, required_source: "unknown",
                         remaining: null, met: null, pct: null },
    });

    expect(silent[0].met).toBeNull();
    expect(silent[0].line).toMatch(/not measured/i);
    expect(silent[1].met).toBe(false);
  });

  it("says so when the response measured nothing at all", () => {
    const bars = settledBars({ ...behind, settled_distance: null });

    expect(bars).toHaveLength(2);
    for (const bar of bars) {
      expect(bar.required).toBeNull();
      expect(bar.met).toBeNull();
      expect(bar.line).toMatch(/not measured/i);
      expect(bar.line).not.toMatch(/\b0\b/);
    }
  });

  it("never invents a bar of zero, which would read as having met the gate", () => {
    const bars = settledBars({
      ...behind,
      settled_distance: { ...behind.settled_distance!, floor: null, floor_remaining: null,
                         floor_met: null, floor_pct: null },
    });

    expect(bars[1].required).toBeNull();
    expect(bars[1].line).not.toMatch(/\b0 of\b/);
  });

  it("carries the fill fraction the response measured, and none where it measured none", () => {
    expect(settledBars(behind)[0].pct).toBe(21.0);
    expect(settledBars(behind)[1].pct).toBe(42.0);
    expect(settledBars(metOwnGate)[0].pct).toBeNull();
  });
});

describe("backtestGateLabel", () => {
  it("names the run's OWN gate, so it can never be read as the promotion decision", () => {
    expect(backtestGateLabel("SHADOW")).toMatch(/shadow/i);
    expect(backtestGateLabel("PROMOTED")).toMatch(/passed/i);
    expect(backtestGateLabel("PROMOTED")).not.toBe("Promoted");
  });

  it("fails closed on an absent or unrecognised status", () => {
    for (const absent of [null, undefined, "", "DEMOTED", "PROMOTED_V2"]) {
      expect(backtestGateLabel(absent)).toMatch(/shadow|not recorded/i);
    }
  });

  it("reads a status case- and whitespace-insensitively, as edgeGate does", () => {
    // Same convention as @/lib/edgeGate, on purpose: two gate formatters that disagreed about
    // whether `"promoted "` counts would put two answers on one page.
    expect(backtestGateLabel("promoted ")).toBe(backtestGateLabel("PROMOTED"));
    expect(backtestGateLabel(" shadow")).toBe(backtestGateLabel("SHADOW"));
  });
});

describe("summarise", () => {
  it("repeats the server's own headline rather than inventing one", () => {
    // The server computes it from the rows; the page restating its own logic is how the two drift.
    const summary = summarise(body());
    expect(summary.headline).toBe("No engine beats the market on Brier.");
  });

  it("carries the caveat that says how much of the board it covers", () => {
    // 1 of 3 rows unmeasured. The headline is about ENGINES; the count is about ROWS, and only
    // rendering the count together with the sentence keeps the sentence honest.
    const summary = summarise(body({
      rows_not_comparable: 2,
      caveat: "2 of 3 rows could not be compared: no market Brier was recorded for them.",
    }));

    expect(summary.headline).toBe("No engine beats the market on Brier.");
    expect(summary.caveat).toContain("2 of 3");
  });

  it("has no caveat to render when every row was compared", () => {
    expect(summarise(body({ rows_not_comparable: 0, caveat: null })).caveat).toBeNull();
  });

  it("names all four buckets, so no row is silently uncounted", () => {
    const counts = summarise(body({ rows_not_comparable: 2 })).counts;
    for (const n of ["3", "1", "2"]) expect(counts).toContain(n);
  });

  it("does not claim a win when the sample is too small to mean one", () => {
    const summary = summarise(body({
      headline: "At least one engine beats the market on Brier. Check the settled count before reading that as an edge.",
      headline_kind: "ahead",
    }));
    expect(summary.headline).toMatch(/Check the settled count/i);
  });

  it("styles a board nobody could measure as unknown, not as a board that lost", () => {
    // any_beats_market is False for BEHIND and for NOT_COMPARABLE alike, so a tone derived from it
    // would colour an unmeasured board as though it had been beaten.
    const lost = summarise(body({ headline_kind: "behind" }));
    const unmeasuredBoard = summarise(body({
      headline: "No engine run could be compared: no market Brier was recorded at decision time.",
      headline_kind: "not_comparable",
    }));

    expect(lost.tone).toBe("behind");
    expect(unmeasuredBoard.tone).toBe("unknown");
    expect(summarise(body({ headline_kind: "no_runs" })).tone).toBe("unknown");
  });
});
