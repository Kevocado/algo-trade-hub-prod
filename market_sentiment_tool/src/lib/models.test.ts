import { describe, expect, it } from "vitest";

import {
  UNMEASURED_BARS,
  UNMEASURED_GATE,
  UNMEASURED_SCORE,
  brierPair,
  catalogueCounts,
  claimText,
  displayOnlyNote,
  retirementText,
  statusTone,
  statusWord,
  worstRatioText,
  type Catalogue,
  type CatalogueEntry,
} from "@/lib/models";
import type { ScoreboardRow } from "@/lib/scoreboard";

/**
 * Wording for the models page, and the one rule that governs all of it.
 *
 * Every engine currently loses (spec section 1) and most of them have never been measured at all,
 * which makes this page the one place both of those facts are on screen at once. Two failure
 * modes follow, and both are pinned here:
 *
 *   1. **Softening a loss.** The temptation on a page introducing the product is to make three
 *      losing engines sound competitive. `statusWord("behind")` and `worstRatioText` are pinned so
 *      that gas reads at 4.29x the market's Brier and nothing in the module's vocabulary can
 *      characterise a deficit as near-parity.
 *   2. **Collapsing an absence into a number.** Four of seven engines have no backtest run. A
 *      formatter that returned "0" or "0.00x" for one would make the page indistinguishable from a
 *      board of engines that measured zero, and on a product where every measured engine loses,
 *      that reads as the best news on the page.
 *
 * What this module may NOT do is decide anything: no threshold, no ratio, no gate, no engine list.
 * Those are `tradehub/scoreboard.py` and `tradehub/engine_catalogue.py`, and the tests below only
 * ever pass values the server already resolved.
 */

const row = (over: Partial<ScoreboardRow> = {}): ScoreboardRow => ({
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
  ...over,
});

const entry = (over: Partial<CatalogueEntry> = {}): CatalogueEntry => ({
  engine: "gas",
  label: "Gasoline — AAA US average, day over day",
  claim: "Whether the AAA US average gasoline price will finish the day above or below a strike, on KXAAAGASD.",
  claim_note: "",
  in_catalogue: true,
  cadence: "daily",
  measured: true,
  measured_rows: 1,
  status: "behind",
  worst_brier_ratio: 4.29,
  rows: [row()],
  ...over,
});

describe("the claim is the page's reason for existing", () => {
  it("prints the server's sentence rather than one written here", () => {
    expect(claimText(entry())).toMatch(/KXAAAGASD/);
  });

  it("says the catalogue is behind when it declares no engine, and does not guess", () => {
    // An undeclared engine with a real run. A plausible-sounding claim here would be the page
    // inventing what a model does, which is the exact thing the owner said he could not find out.
    const undeclared = entry({
      engine: "fx_carry",
      label: "fx_carry",
      claim: null,
      claim_note: "Not described. No entry in the engine catalogue.",
      in_catalogue: false,
      measured: true,
    });

    expect(claimText(undeclared)).toBe("Not described. No entry in the engine catalogue.");
    expect(claimText(undeclared)).not.toMatch(/predicts|forecast/);
  });

  it("never returns an empty claim, whatever the response carried", () => {
    expect(claimText(entry({ claim: null, claim_note: "" }))).toMatch(/\S/);
  });
});

describe("status words, in the product's own vocabulary", () => {
  it("uses the four market verdicts and the one honest addition", () => {
    expect(statusWord("ahead")).toMatch(/ahead/i);
    expect(statusWord("behind")).toMatch(/behind/i);
    expect(statusWord("level")).toMatch(/level/i);
    expect(statusWord("not_comparable")).toMatch(/not comparable/i);
    expect(statusWord("not_measured")).toMatch(/not measured/i);
  });

  it("never calls a deficit competitive, at any size", () => {
    // Pinned on the WORD, because the number is the server's and cannot be argued with here --
    // only the adjective wrapped around it can.
    for (const status of ["behind", "not_comparable", "not_measured"] as const) {
      expect(statusWord(status)).not.toMatch(/close|competitive|nearly|almost|roughly/i);
    }
  });

  it("does not paint an unmeasured engine as a board that lost", () => {
    // `not_comparable` and `not_measured` are the two states where a colour would be a verdict.
    expect(statusTone("behind")).toBe("behind");
    expect(statusTone("ahead")).toBe("ahead");
    expect(statusTone("level")).toBe("level");
    expect(statusTone("not_comparable")).toBe("unknown");
    expect(statusTone("not_measured")).toBe("unknown");
  });

  it("falls closed on a word it does not know rather than defaulting to a verdict", () => {
    // A status from a future server. Defaulting to "behind" would be the page inventing a loss.
    expect(statusWord("demoted" as never)).toBe("Not measured");
    expect(statusTone("demoted" as never)).toBe("unknown");
  });
});

describe("the multiple, and the figures beside it", () => {
  it("states the worst measured ratio at the ONE precision the product uses", () => {
    expect(worstRatioText(entry())).toBe("4.29x");
    // 0.50 and 9.00, not 0.5 and 9: two precisions on one quantity tells a reader the more precise
    // number is the more true one, which is a claim about nothing.
    expect(worstRatioText(entry({ status: "ahead", worst_brier_ratio: 0.5 }))).toBe("0.50x");
    expect(worstRatioText(entry({ worst_brier_ratio: 9 }))).toBe("9.00x");
  });

  it("dashes an unmeasured ratio rather than printing 0.00x", () => {
    for (const absent of [null, undefined, NaN]) {
      expect(worstRatioText(entry({ worst_brier_ratio: absent as unknown as number }))).toBe("—x");
      expect(worstRatioText(entry({ worst_brier_ratio: absent as unknown as number }))).not.toBe("0.00x");
    }
  });

  it("keeps a measured zero, because zero is a measurement and absence is not", () => {
    expect(worstRatioText(entry({ worst_brier_ratio: 0 }))).toBe("0.00x");
  });

  it("puts our Brier beside the market's, and dashes an absent one", () => {
    expect(brierPair(row())).toBe("0.11480 ours · 0.02676 market");
    // The weather maker fixture: the run exists, no market Brier was recorded.
    const uncompared = row({ brier_market: null, brier_ratio: null, market_verdict: "not_comparable" });
    expect(brierPair(uncompared)).toBe("0.11480 ours · — market");
    expect(brierPair(uncompared)).not.toBe("0.11480 ours · 0.00000 market");
  });
});

describe("an engine with no backtest run", () => {
  const unmeasured = entry({
    engine: "crypto",
    label: "Crypto — BTC and ETH, next hourly close",
    claim: "Whether an asset's next hourly close resolves YES against a fixed threshold.",
    cadence: "daily",
    measured: false,
    measured_rows: 0,
    status: "not_measured",
    worst_brier_ratio: null,
    rows: [],
  });

  it("says not measured, and never a zero", () => {
    for (const line of [UNMEASURED_SCORE, UNMEASURED_BARS, UNMEASURED_GATE]) {
      expect(line).toMatch(/not measured|no bars|no gate|no count|nothing/i);
      expect(line).not.toMatch(/\b0\b/);
    }
  });

  it("distinguishes 'no run' from 'run with no market Brier'", () => {
    // The claim survives: a claim is not a measurement, and the engine is real either way.
    expect(claimText(unmeasured)).toMatch(/next hourly close/);
    expect(statusWord(unmeasured.status)).toBe("Not measured");
    // And the ratio is absent, which is the fact the page must not round into a figure.
    expect(worstRatioText(unmeasured)).toBe("—x");
  });

  it("states that the bars and the gate have nothing to report, rather than passing them", () => {
    expect(UNMEASURED_BARS).toMatch(/neither bar/i);
    expect(UNMEASURED_GATE).toMatch(/nothing to be promoted|no verdict/i);
  });
});

describe("the display-only ruling rides on the row, from the one module that holds it", () => {
  it("passes CPI's reason through rather than keeping a second copy of the list", () => {
    const cpi = entry({ engine: "cpi_nowcast", label: "CPI — first print" });

    expect(displayOnlyNote(cpi)).toMatch(/not an edge engine|display/i);
    // Anything not on that list gets nothing, and a string here would be a second ruling.
    expect(displayOnlyNote(entry({ engine: "gas" }))).toBeNull();
  });
});

describe("catalogueCounts", () => {
  const catalogue = (over: Partial<Catalogue> = {}): Catalogue => ({
    engines_total: 7,
    engines_measured: 3,
    engines_not_measured: 4,
    engines_unlisted: 0,
    entries: [],
    ...over,
  });

  it("counts engines, and the product's real state is that most of them are unmeasured", () => {
    const counts = catalogueCounts(catalogue());

    expect(counts).toBe("7 engines · 3 measured · 4 not measured");
  });

  it("agrees each noun with its own count", () => {
    // "1 engines" is a number rendered wrong, and this is the page whose whole job is that
    // numbers read right. One count, all three nouns, so the singular case is genuinely reachable.
    expect(catalogueCounts(catalogue({ engines_total: 1, engines_measured: 1, engines_not_measured: 0 })))
      .toContain("1 engine ·");
  });

  it("says so when an engine has a run the catalogue has never heard of", () => {
    // The failure the count exists for: a new engine on the board that nothing describes.
    expect(catalogueCounts(catalogue({ engines_total: 8, engines_unlisted: 1 })))
      .toContain("1 not in the catalogue");
  });

  it("says nothing about the catalogue when there is nothing to say", () => {
    expect(catalogueCounts(catalogue())).not.toMatch(/catalogue/);
  });
});

describe("retired engines leave a tombstone", () => {
  const retired = { removed: "2026-10-15", reason: "deleted with the legacy daemon", replaced_by: "cpi_nowcast" };

  it("has its own status word, and the muted tone rather than a loss", () => {
    expect(statusWord("retired")).toBe("Retired");
    expect(statusTone("retired")).toBe("unknown");
  });

  it("says when, why and what replaced it; nothing for a live engine", () => {
    expect(retirementText({ retired })).toBe(
      "Retired 2026-10-15: deleted with the legacy daemon. Replaced by cpi_nowcast.",
    );
    expect(retirementText({ retired: { ...retired, replaced_by: null } })).toContain("Nothing replaced it.");
    expect(retirementText({})).toBeNull();
  });

  it("counts retired engines beside the live ones, and is silent when there are none", () => {
    const base = { engines_total: 7, engines_measured: 3, engines_not_measured: 4, engines_unlisted: 0, entries: [] };
    expect(catalogueCounts({ ...base, engines_retired: 2 })).toBe("7 engines · 3 measured · 4 not measured · 2 retired");
    expect(catalogueCounts({ ...base, engines_retired: 0 })).not.toMatch(/retired/);
  });
});
