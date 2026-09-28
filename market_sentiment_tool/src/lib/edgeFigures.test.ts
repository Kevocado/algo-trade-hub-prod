import { describe, expect, it } from "vitest";

import {
  NOT_MEASURED,
  edgePctNumber,
  edgePctText,
  edgeReason,
  meanEdgePct,
  meanEdgeReason,
  probReason,
  probText,
  readNumber,
} from "@/lib/edgeFigures";

/**
 * The rendering half of "a figure it did not measure is absent, never 0".
 *
 * `useMarketEdges` handed every page three zeros for the rows that recorded nothing, and these
 * functions are the other half of the fix: the hook now returns `null`, and every consumer formats
 * through here. The branch that matters is the one where the two must not be confused -- a missing
 * figure renders as a dash with a reason, a measured zero renders as a number. Both branches are
 * one expression apart in a way that is trivially collapsed back into `value || 0` by accident, so
 * both are pinned.
 *
 * Pure, for the reason `lib/cpiDisplay.ts` is pure: a rendering bug is cheapest to kill before a
 * browser is involved, and the rule has to be in one place so a new consumer cannot get it wrong.
 */
describe("readNumber", () => {
  it("prefers the column, and converts only the payload fallback", () => {
    // `my_prob`/`yes_ask` are stored in percent and the columns in [0, 1], so those divide by 100.
    // `raw_payload.edge` is already the column's unit and divides by 1. Getting this backwards is a
    // 100x error that still typechecks and still renders.
    expect(readNumber(0.52, 99, 100)).toBe(0.52);
    expect(readNumber(null, 52, 100)).toBeCloseTo(0.52);
    expect(readNumber(null, 4, 1)).toBe(4);
    expect(readNumber(null, 4, 100)).toBeCloseTo(0.04);
  });

  it("returns null when there is nothing to read, which is the whole point", () => {
    expect(readNumber(null, null, 100)).toBeNull();
    expect(readNumber(undefined, undefined, 1)).toBeNull();
    expect(readNumber(Number.NaN, Number.NaN, 100)).toBeNull();
    expect(readNumber("0.52", "52", 100)).toBeNull();
  });

  it("keeps a recorded zero a zero", () => {
    // The truthiness test this replaced sent `my_prob: 0` down the "no value" branch, which is how
    // a real zero and a missing figure ended up indistinguishable.
    expect(readNumber(0, 99, 100)).toBe(0);
    expect(readNumber(null, 0, 100)).toBe(0);
    expect(readNumber(null, 0, 1)).toBe(0);
  });
});

describe("probText", () => {
  it("renders a probability and a price in the units each column is measured in", () => {
    expect(probText(0.523)).toBe("52.3%");
    expect(probText(0.523, "cents")).toBe("52.3¢");
  });

  it("renders a measured zero as a number", () => {
    expect(probText(0)).toBe("0.0%");
    expect(probText(0, "cents")).toBe("0.0¢");
  });

  it("renders an absent figure as a dash, never as 0.0", () => {
    // `0.0%` here would be a model that rates the outcome at zero: a prediction, and the reader is
    // entitled to act on a prediction.
    for (const missing of [null, undefined, Number.NaN]) {
      expect(probText(missing)).toBe(NOT_MEASURED);
      expect(probText(missing)).not.toMatch(/0\.0/);
    }
  });

  it("always has a reason for the dash, so the dash is not the only thing on screen", () => {
    expect(probReason(null)).toMatch(/no model probability/i);
    expect(probReason(null, "cents")).toMatch(/no market quote/i);
    expect(probReason(null)).toMatch(/not a probability of zero/i);
    // ...and no reason when there is a number, so a `title` attribute is never noise.
    expect(probReason(0.5)).toBeNull();
  });
});

describe("edgePctText", () => {
  it("signs a positive edge and leaves a negative one alone", () => {
    expect(edgePctText(20)).toBe("+20.0%");
    expect(edgePctText(-4.5)).toBe("-4.5%");
    expect(edgePctText(0)).toBe("0.0%");
  });

  it("renders an unmeasured edge as a dash, never as +0.0%", () => {
    // "+0.0%" is the War Room's headline number and it reads as "we measured, and there is no
    // opportunity here". That is the claim a missing figure most resembles and must never make.
    expect(edgePctText(null)).toBe(NOT_MEASURED);
    expect(edgePctText(null)).not.toMatch(/0\.0/);
    expect(edgeReason(null)).toMatch(/not measured/i);
    expect(edgeReason(null)).toMatch(/found to be zero/i);
    expect(edgeReason(0)).toBeNull();
  });

  it("tells a measured zero from an unmeasured one, for the badge colour", () => {
    expect(edgePctNumber(0)).toBe(true);
    expect(edgePctNumber(null)).toBe(false);
    expect(edgePctNumber(undefined)).toBe(false);
  });
});

describe("meanEdgePct", () => {
  const withEdge = (edge_pct: number | null, i: number) => ({ edge_pct, id: `e-${i}` });

  it("averages the rows that recorded a figure", () => {
    const mean = meanEdgePct([withEdge(10, 1), withEdge(20, 2), withEdge(30, 3)]);
    expect(mean.value).toBeCloseTo(20);
    expect(mean.measured).toBe(3);
    expect(mean.considered).toBe(3);
  });

  it("does not count an unmeasured row as a zero in either the sum or the denominator", async () => {
    // The expression this replaces was `reduce((a, b) => a + (b.edge_pct || 0), 0) / (length || 1)`,
    // which was wrong twice over: a missing figure went into the sum as 0 while still counting in
    // the denominator, so a board could go quiet and its headline number would slide towards 0.00%
    // because data was missing. The mean of 10 and 30 is 20, not 13.33.
    const mean = meanEdgePct([withEdge(10, 1), withEdge(null, 2), withEdge(30, 3)]);
    expect(mean.value).toBeCloseTo(20);
    expect(mean.measured).toBe(2);
    expect(mean.considered).toBe(3);
  });

  it("has no value at all when nothing on the board recorded one", () => {
    // `length || 1` turned an empty board into 0/1, i.e. a confident `0.00%` for no edges at all.
    expect(meanEdgePct([]).value).toBeNull();
    expect(meanEdgePct([withEdge(null, 1), withEdge(null, 2)]).value).toBeNull();
  });

  it("keeps a measured zero in the mean", () => {
    expect(meanEdgePct([withEdge(0, 1), withEdge(20, 2)]).value).toBeCloseTo(10);
  });

  it("says what the mean covers, so a mean is not read as a claim about the whole board", () => {
    expect(meanEdgeReason(meanEdgePct([withEdge(10, 1), withEdge(null, 2)]))).toMatch(
      /1 of 2 rows that recorded an edge figure/,
    );
    expect(meanEdgeReason(meanEdgePct([withEdge(10, 1), withEdge(20, 2)]))).toBeNull();
    expect(meanEdgeReason(meanEdgePct([]))).toMatch(/no edges on the board/i);
    expect(meanEdgeReason(meanEdgePct([withEdge(null, 1)]))).toMatch(/not an average edge of 0\.00%/);
  });
});
