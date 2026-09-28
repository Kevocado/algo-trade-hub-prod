import { describe, expect, it } from "vitest";

import {
  QUARANTINE_MARK,
  engineText,
  headlineCount,
  headlineReason,
  isUnitsArtefact,
  quarantineText,
  rowKindLabel,
  type QuarantineResponse,
  type QuarantineRow,
} from "@/lib/quarantine";
import { NOT_MEASURED } from "@/lib/edgeFigures";

/**
 * The wording half of the quarantine, and the arithmetic it is NOT allowed to do.
 *
 * The measured run of 2026-09-28 is the record this file works from: 295 rows, 213 that are not a
 * units artefact, 82 artefacts, 187 restatements, and **26 independent opportunities**. Everything
 * below is about making sure a surface built on those rows leads with 26 and cannot be talked into
 * leading with 295.
 */

const COUNTS = {
  rows: 295,
  opportunities: 213,
  units_artefacts: 82,
  buy_no_rows: 141,
  independent_forecasts: 30,
  restatements: 265,
  independent_opportunities: 26,
  restated_opportunities: 187,
};

function payload(over: Partial<QuarantineResponse> = {}): QuarantineResponse {
  return {
    as_of: "2026-09-28T00:00:00Z",
    marker: QUARANTINE_MARK,
    quarantined: true,
    note: "QUARANTINED. No row reaches kalshi_edges.",
    rows: COUNTS.rows,
    measured: true,
    unmeasured_reason: null,
    totals: COUNTS,
    engines: [
      { engine: "Macro", marker: QUARANTINE_MARK, quarantined: true, note: "", counts: COUNTS },
    ],
    reasons: {},
    kalshi_edges_written: 0,
    sink: "kalshi_quarantine_edges",
    rows_page: [],
    ...over,
  };
}

const ROW: QuarantineRow = {
  market_id: "KXGDPYEAR-26-T2.5",
  title: "GDP above 2.5% in 2026",
  engine: "Macro",
  edge_type: "MACRO",
  action: "BUY NO",
  market_ticker: "KXGDPYEAR-26-T2.5",
  event_ticker: "KXGDPYEAR-26",
  price_cents: 99,
  model_probability_pct: 15,
  edge_points: 84,
  edge_kind: "units_artefact",
  independent: true,
  forecast_key: "Macro | GDP | 10",
  reasoning: "Latest GDP: 1.9%.",
  kalshi_url: null,
};

describe("the headline is the independent count, never the row count", () => {
  it("prints 26 and not 295", () => {
    // This is the whole test file in one assertion. 295 rows is what the scan produced; 26 is how
    // many separate things the engines thought. A reader shown the first has been shown a number
    // about rows while believing it is a number about opportunities.
    expect(headlineCount(payload())).toBe("26");
    expect(headlineCount(payload())).not.toBe(String(COUNTS.rows));
    expect(headlineCount(payload())).not.toBe(String(COUNTS.opportunities));
  });

  it("cannot print a row total even if the payload is handed one", () => {
    // The fail-safe. `headlineCount` reads `independent_opportunities` and nothing else, so there is
    // no key in the payload it could be talked into reading instead.
    const tampered = payload({ totals: { ...COUNTS, independent_opportunities: undefined as never } });
    expect(headlineCount(tampered)).toBe("undefined");
    // Which is the point: there is no fallback to `rows`. A function that fell back would be a
    // function that prints 295 the moment the independent count went missing.
    expect(headlineCount(tampered)).not.toBe("295");
  });

  it("says the reason 295 is not the headline, in the same panel", () => {
    const reason = headlineReason(payload());
    expect(reason).toContain("295");
    expect(reason).toContain("187");
    expect(reason).toContain("82");
    expect(reason).toContain("26");
    expect(reason).toMatch(/independent opportunities, not rows/i);
  });

  it("has no reason when nothing was measured, so the caller renders the other branch", () => {
    const unmeasured = payload({ measured: false, totals: null, unmeasured_reason: "sink is empty" });
    expect(headlineReason(unmeasured)).toBe("sink is empty");
    expect(headlineReason(null)).toBeNull();
  });
});

describe("a missing measurement is a dash, never a zero", () => {
  it("draws the headline as a dash when there is nothing to report", () => {
    // The empty sink is NOT a count of zero opportunities. It is either no scan yet or a migration
    // that has not been applied, and printing 0 there would be a measurement of a search that never
    // happened -- the same defect as a stopped engine's empty tab, in a different place.
    expect(headlineCount(payload({ measured: false, totals: null }))).toBe(NOT_MEASURED);
    expect(headlineCount(null)).toBe(NOT_MEASURED);
    expect(headlineCount(undefined)).toBe(NOT_MEASURED);
    expect(headlineCount(payload({ measured: false, totals: null }))).not.toMatch(/\d/);
  });

  it("says the sink is empty rather than claiming the engines found nothing", () => {
    const text = quarantineText(payload({ measured: false, totals: null, unmeasured_reason: "sink is empty" }));
    expect(text).toBe("sink is empty");
    expect(text).not.toMatch(/\b0\b/);
  });

  it("says the read did not arrive rather than that there are none", () => {
    // A 500 on /api/quarantine must not read as a product with nothing quarantined. Same rule as
    // the engine-health ruling, and the reason the two reads are kept apart.
    expect(quarantineText(null)).toMatch(/did not arrive/i);
  });

  it("still prints real numbers when there are real numbers to print", () => {
    // The dash is a fail-safe, not a hardcoded string. A figure that could only ever be a dash would
    // be a figure nobody reads, and a future repair that publishes these engines would have nothing
    // to fall back on.
    const measured = payload({ totals: { ...COUNTS, independent_opportunities: 0 } });
    expect(headlineCount(measured)).toBe("0");
  });
});

describe("the one-liner counts things by their own names", () => {
  it("says 26 independent opportunities, 295 rows, 187 restated, 82 artefacts", () => {
    const text = quarantineText(payload());
    expect(text).toContain("26 independent opportunities");
    expect(text).toContain("295 rows");
    expect(text).toContain("187 restated");
    expect(text).toContain("82 artefacts");
  });

  it("agrees its own nouns, because this is the page whose job is numbers reading right", () => {
    const one = payload({
      totals: { ...COUNTS, independent_opportunities: 1, rows: 1, restated_opportunities: 0, units_artefacts: 1 },
    });
    expect(quarantineText(one)).toContain("1 independent opportunity ·");
    expect(quarantineText(one)).toContain("1 row ·");
    expect(quarantineText(one)).toContain("1 artefact");
  });
});

describe("row classification is read, not recomputed", () => {
  it("takes the server's verdict rather than comparing a price to a threshold", () => {
    // The 95c threshold is a written ruling in `tradehub/quarantine.py`, applied there. A client
    // re-deriving it could disagree with the rows it is displaying -- which is how a surface ends
    // up showing 82 artefacts and counting 91.
    expect(isUnitsArtefact(ROW)).toBe(true);
    expect(isUnitsArtefact({ ...ROW, edge_kind: "opportunity" })).toBe(false);
    expect(isUnitsArtefact({ ...ROW, price_cents: 40 })).toBe(true);
    expect(isUnitsArtefact(null)).toBe(false);
  });

  it("labels a row by both verdicts, which are independent", () => {
    expect(rowKindLabel(ROW)).toMatch(/units artefact/i);
    expect(rowKindLabel({ ...ROW, edge_kind: "opportunity", independent: false })).toMatch(/restatement/i);
    expect(rowKindLabel({ ...ROW, edge_kind: "opportunity", independent: true })).toMatch(/independent/i);
    // A row the scan recorded no classification for gets no label. Inventing one would be the
    // defect this whole feature exists to prevent, at row level.
    expect(rowKindLabel({ ...ROW, edge_kind: null })).toBeNull();
    expect(rowKindLabel(null)).toBeNull();
  });
});

describe("the per-engine line is the server's counts", () => {
  it("says the engine's own independent figure out of its own rows", () => {
    expect(engineText(payload().engines[0])).toBe("Macro: 26 independent of 295 rows");
  });

  it("says nothing was measured rather than showing a zero", () => {
    expect(engineText(null)).toBe("no measurement");
    expect(engineText({ ...payload().engines[0], counts: undefined as never })).toBe("no measurement");
  });
});

describe("the marker travels everywhere", () => {
  it("is the literal word, pinned without reference to the constant", () => {
    // The load-bearing test in this file, and it is here because of how a mutation behaves.
    //
    // Every other assertion in this file compares against `QUARANTINE_MARK`, so emptying the
    // constant satisfies all of them at once: `getByText("")` matches every element, which is how
    // the row-marking test above caught the mutation by accident rather than by assertion. A test
    // that pins the WORD is the one that fails when somebody "tidies up" the constant to a shared
    // value or a computed string.
    //
    // A quarantined number that travels alone is indistinguishable from a published one, and that is
    // the whole failure this feature exists to prevent.
    expect(QUARANTINE_MARK).toBe("QUARANTINED");
  });

  it("is on the payload, and a reader who screenshots one figure keeps it in the image", () => {
    const response = payload();
    expect(response.marker).toBe("QUARANTINED");
    expect(response.note).toContain("QUARANTINED");
    for (const rollup of response.engines) {
      expect(rollup.marker).toBe("QUARANTINED");
      expect(rollup.quarantined).toBe(true);
    }
  });

  it("is a word, not a number, so it cannot be mistaken for a figure", () => {
    expect(QUARANTINE_MARK).not.toMatch(/\d/);
    expect(QUARANTINE_MARK.length).toBeGreaterThan(0);
  });
});
