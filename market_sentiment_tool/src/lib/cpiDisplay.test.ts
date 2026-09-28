import { describe, expect, it } from "vitest";

import {
  CPI_CONTEXT_ROWS,
  NOT_RECORDED,
  cpiComparableNote,
  cpiCoverageNote,
  cpiEmptyNote,
  cpiGateNote,
  cpiHeadline,
  cpiRowNote,
  cpiTruncationNote,
  hoursText,
  isComparableOnly,
  isDisplayOnly,
  nTrainText,
  nowcastMeasure,
  probMeasure,
  readCount,
  sigmaText,
  stampText,
  statusText,
  suggestOnlyNote,
  type CpiDisplayResponse,
  type CpiDisplayRow,
} from "@/lib/cpiDisplay";

/**
 * The four claims the endpoint makes about itself, tested as copy.
 *
 * Each of them exists because the API refused to let something be silently wrong, and a page that
 * drops one reinstates exactly the defect it was added to prevent. These are pure functions on
 * purpose: the failure mode being guarded is a rendering one, and a rendering bug is cheapest to
 * kill before a browser is involved.
 */

const row = (extra: Partial<CpiDisplayRow> = {}): CpiDisplayRow => ({
  market_ticker: "KXCPI-26SEP09-3.0",
  our_prob: 0.55,
  market_prob: 0.52,
  edge_pct: null,
  nowcast: 0.39,
  nowcast_obs: "CLEVELAND-2026-09",
  sigma: 0.15,
  n_train: 24,
  default_error_model: false,
  default_error_model_reason: null,
  hours_to_close: 6.5,
  as_of: "2026-09-27T12:00:00+00:00",
  status: "OPEN",
  comparable: true,
  withheld_reason: null,
  gate_status: "SHADOW",
  gate_checked: false,
  ...extra,
});

const payload = (extra: Partial<CpiDisplayResponse> = {}): CpiDisplayResponse => ({
  as_of: "2026-09-27T12:00:00+00:00",
  mode: "display",
  engine: "cpi_nowcast",
  suggest_only: true,
  reason: "Not an edge engine. CPI is shown for context only.",
  edge_pct: null,
  gate_status: "SHADOW",
  gate_checked: false,
  gate_checked_reason: "No gate was consulted and none is expected.",
  row_order: "as_of desc",
  rows: [row()],
  total: 1,
  truncated: false,
  withheld_count: 0,
  read_count: 1,
  comparable_only: false,
  limit: CPI_CONTEXT_ROWS,
  offset: 0,
  ...extra,
});

describe("isDisplayOnly", () => {
  it("is true unless the payload positively claims otherwise", () => {
    expect(isDisplayOnly({ mode: "display" })).toBe(true);
    // Fails closed, like the promotion gate: an older or absent payload is not evidence that the
    // engine became an edge engine.
    expect(isDisplayOnly({})).toBe(true);
    expect(isDisplayOnly(null)).toBe(true);
    expect(isDisplayOnly({ mode: "edge" })).toBe(false);
  });
});

describe("figures", () => {
  it("renders a probability as a percentage", () => {
    expect(probMeasure(0.55).value).toBe("55.0%");
    expect(probMeasure(0).value).toBe("0.0%");
    expect(probMeasure(0.55).known).toBe(true);
  });

  it("renders an absent figure as words, and never as a number", () => {
    // The whole point. `useMarketEdges` used to fabricate this same zero with `?? 0`, and repeating
    // it here would be the same defect one layer over; that hook now returns null (see
    // lib/edgeFigures.ts) and this page still renders an absence in words.
    for (const missing of [null, undefined, NaN, "0.4" as unknown as number]) {
      const m = probMeasure(missing);
      expect(m.value).toBeNull();
      expect(m.known).toBe(false);
      expect(m.note).toMatch(/\S/);
      expect(m.note).not.toMatch(/0\.0/);
    }
    expect(probMeasure(null).note).toMatch(/no model probability/i);
    expect(hoursText(null).value).toBeNull();
    expect(hoursText(null).note).toMatch(/close time/i);
  });

  it("renders the nowcast in the units it is measured in, not as a probability", () => {
    // 0.39 is +0.39% month-over-month (the Cleveland Fed chart's own y-axis is "Month-over-month
    // percent change"; cpi_prob compares it against CPI_RESOLUTION = 0.1, the strike increment).
    // Formatting it as a probability gives "39.0%", which is a hundred-fold overstatement of the
    // print and would still typecheck.
    expect(nowcastMeasure(0.39).value).toBe("+0.39% MoM");
    expect(nowcastMeasure(0.39).value).not.toBe("39.0%");
    expect(sigmaText(0.15)).toBe("±0.15pp");
    expect(sigmaText(null)).toBeNull();
  });

  it("renders a genuine zero, because zero is a measurement and null is not", () => {
    expect(nowcastMeasure(0).value).toBe("+0.00% MoM");
    expect(nowcastMeasure(0).known).toBe(true);
    expect(nowcastMeasure(null).value).toBeNull();
    expect(nowcastMeasure(null).note).toBe(NOT_RECORDED);
  });

  it("never prints an unparseable timestamp or today's date in its place", () => {
    expect(stampText("2026-09-27T12:00:00+00:00")).toBe("2026-09-27 12:00Z");
    expect(stampText(null)).toBeNull();
    expect(stampText("")).toBeNull();
    expect(stampText("not a date")).toBeNull();
  });

  it("says so when a row carries no state, rather than showing an empty cell", () => {
    expect(statusText("OPEN")).toBe("OPEN");
    expect(statusText("settled")).toBe("SETTLED");
    expect(statusText(null)).toBe("state not reported");
  });
});

describe("obligation 1: the gate was never checked, not checked and declined", () => {
  it("never prints the bare gate value, which reads as a verdict that was reached", () => {
    const note = cpiGateNote(payload());
    expect(note.checked).toBe(false);
    expect(note.headline).toMatch(/never checked/i);
    // The three ways this rendering would turn a REFUTED engine back into a live candidate.
    expect(note.headline).not.toMatch(/shadow/i);
    expect(note.headline).not.toMatch(/pending/i);
    expect(note.headline).not.toMatch(/\byet\b|not passed|awaiting/i);
  });

  it("carries the endpoint's reason for the absent gate", () => {
    expect(cpiGateNote(payload()).detail).toMatch(/no gate was consulted/i);
  });

  it("still says something true if the payload is missing the reason", () => {
    const note = cpiGateNote({ ...payload(), gate_checked_reason: "" });
    expect(note.detail).toMatch(/no gate was consulted/i);
    expect(cpiGateNote(null).headline).toMatch(/never checked/i);
  });

  it("reports a verdict only when a gate was actually consulted", () => {
    const note = cpiGateNote(payload({ gate_checked: true, gate_status: "PROMOTED" }));
    expect(note.checked).toBe(true);
    expect(note.headline).toMatch(/PROMOTED/);
  });
});

describe("obligation 2: the bounded read, and the rows withheld from the comparison", () => {
  it("says nothing about truncation when the read was complete", () => {
    expect(cpiTruncationNote(payload())).toBeNull();
  });

  it("says the list is not the whole set when it is not", () => {
    // `read_count` is the "rows were read" figure and is what the endpoint sends; on an unfiltered
    // payload it is the same number as `total`, which is why this test is unchanged in shape.
    const note = cpiTruncationNote(payload({ truncated: true, total: 200, read_count: 200 }));
    expect(note).toMatch(/truncated/i);
    expect(note).toMatch(/200/);
    expect(note).toMatch(/not the whole set/i);
  });

  it("reports the withheld count over the whole read, not over the page", () => {
    // The withheld row is on page 2. A page-derived count would say "nothing withheld" here.
    const body = payload({ rows: [row()], withheld_count: 1, total: 2, limit: 1, offset: 0 });
    expect(cpiCoverageNote(body)).toMatch(/1 of the read has no market mid/);
    expect(cpiCoverageNote(body)).not.toMatch(/every row read/);
  });

  it("claims full coverage only when the count says so", () => {
    expect(cpiCoverageNote(payload({ withheld_count: 0 }))).toMatch(
      /every row read has a market mid/i,
    );
  });

  it("does not call a truncated total a count", () => {
    const body = payload({ truncated: true, total: 200, read_count: 200 });
    expect(cpiCoverageNote(body)).toMatch(/at least 200 rows read/);
    expect(cpiCoverageNote(body)).not.toMatch(/^200 rows read/);
  });

  it("counts the page it is actually showing", () => {
    expect(cpiCoverageNote(payload({ rows: [row(), row({ market_ticker: "b" })], total: 9, read_count: 9 })))
      .toMatch(/2 on this page/);
  });
});

describe("cpiRowNote", () => {
  it("states the nowcast, its source and the lead", () => {
    const note = cpiRowNote(row());
    expect(note).toMatch(/CLEVELAND-2026-09/);
    expect(note).toMatch(/\+0\.39% MoM/);
    expect(note).toMatch(/±0\.15pp/);
    expect(note).toMatch(/6\.5h to close/);
  });

  it("names what the row is and never implies an edge", () => {
    const note = cpiRowNote(row());
    expect(note).toMatch(/not an edge/i);
    // The only "edge" the note may contain is the one saying there is none.
    expect(note.replace(/not an edge/g, "")).not.toMatch(/edge/i);
  });

  it("carries the withheld reason on a row with no market mid", () => {
    // A withheld row without its reason is a silent filter with extra steps, and the page cannot
    // invent this sentence: it is the endpoint's, and it is the only thing that distinguishes
    // "no mid recorded" from "the market said zero".
    const note = cpiRowNote(
      row({ comparable: false, market_prob: null, withheld_reason: "No market mid was recorded." }),
    );
    expect(note).toMatch(/No market mid was recorded/);
    expect(note).toMatch(/not an edge/i);
  });

  it("says the row is not comparable even if the endpoint sent no reason", () => {
    const note = cpiRowNote(row({ comparable: false, market_prob: null, withheld_reason: null }));
    expect(note).toMatch(/not comparable/i);
  });

  it("carries the ledger timestamp and state, so a closed row cannot read as live", () => {
    const note = cpiRowNote(row({ status: "SETTLED" }));
    expect(note).toMatch(/2026-09-27 12:00Z/);
    expect(note).toMatch(/SETTLED/);
  });

  it("does not invent a timestamp the row does not carry", () => {
    const note = cpiRowNote(row({ as_of: null, status: null }));
    expect(note).not.toMatch(/recorded/);
    expect(note).toMatch(/ledger time not reported/);
    // The state still travels, or reports its own absence: neither field substitutes for the other.
    expect(note).toMatch(/state not reported/);
    expect(cpiRowNote(row({ as_of: null }))).toMatch(/ledger time not reported \(OPEN\)/);
  });

  it("says the nowcast is unrecorded rather than showing a zero for it", () => {
    const note = cpiRowNote(row({ nowcast: null, sigma: null }));
    expect(note).toMatch(/nowcast not recorded/i);
    expect(note).not.toMatch(/\+0\.00% MoM/);
  });

  it("states where the error model came from, so a DEFAULT is not read as a fit", () => {
    // `fit_cpi_error` returns a hardcoded DEFAULT_CPI_ERROR below CPI_MIN_TRAIN pairs, so a row's
    // probability can come out of a constant. Nothing on the page used to say so.
    const note = cpiRowNote(
      row({
        n_train: 3,
        default_error_model: true,
        default_error_model_reason: "The error model is the default, not a fit.",
      }),
    );
    expect(note).toMatch(/the error model is the default, not a fit/i);
    expect(note).not.toMatch(/fitted on/i);
  });

  it("says the fit's size on a fitted row", () => {
    expect(cpiRowNote(row({ n_train: 24 }))).toMatch(/error model fitted on 24 pairs/i);
  });

  it("claims neither a fit nor a default when n_train is absent", () => {
    // An absent count is not evidence of a fit. Guessing in either direction is the same defect the
    // rest of this module exists to prevent, so the row says the count is unknown.
    const note = cpiRowNote(row({ n_train: null, default_error_model: null }));
    expect(note).toMatch(/training-set size not recorded/i);
    expect(note).not.toMatch(/fitted on/i);
    expect(note).not.toMatch(/default/i);
  });

  it("has a fallback reason if the flag says default but the endpoint sent no words", () => {
    const note = cpiRowNote(row({ n_train: 3, default_error_model: true, default_error_model_reason: null }));
    expect(note).toMatch(/error model is the engine's default, not a fit/i);
  });
});

describe("nTrainText", () => {
  it("formats the count with its unit, and never a zero for an absent count", () => {
    expect(nTrainText(24)).toBe("24 pairs");
    expect(nTrainText(1)).toBe("1 pair");
    expect(nTrainText(0)).toBe("0 pairs"); // a measured zero
    expect(nTrainText(null)).toBeNull();
    expect(nTrainText(undefined)).toBeNull();
    expect(nTrainText(Number.NaN)).toBeNull();
  });
});

describe("cpiHeadline", () => {
  it("labels the mode rather than letting the page title imply a board of opportunities", () => {
    expect(cpiHeadline(payload()).label).toMatch(/display/i);
    expect(cpiHeadline(payload({ mode: "edge" })).label).toMatch(/\(edge\)/);
  });

  it("counts rows rather than claiming an outcome", () => {
    expect(cpiHeadline(payload()).value).not.toMatch(/win|loss|lose|profit|pnl/i);
    expect(cpiHeadline(payload({ rows: [row(), row()], total: 12 })).value).toContain("2");
  });

  it("does not invent rows when the payload never arrived", () => {
    expect(cpiHeadline(null).value).toBe("0 markets shown, for context");
  });
});

describe("suggestOnlyNote", () => {
  it("states that this product places no orders when the payload says so", () => {
    expect(suggestOnlyNote(payload())).toMatch(/places no orders/i);
  });

  it("says nothing when the payload does not claim it", () => {
    expect(suggestOnlyNote(payload({ suggest_only: false }))).toBeNull();
    expect(suggestOnlyNote(null)).toBeNull();
  });
});

/**
 * The page stopped being a 50-row history on 2026-09-28, and the reason it could was that the
 * FILTER MOVED TO THE ENDPOINT. These tests are about the copy that has to survive that: a short
 * page is only honest if it still says what the short page left out.
 *
 * The failure being guarded is specific and was the reason for the change. With `comparable_only`
 * on, the withheld rows are not merely un-compared, they are ABSENT. So nothing on screen would
 * reveal that any were dropped: a 12-row list of comparable releases and a 12-row list picked at
 * random from 200 would render identically. `withheld_count` is the only thing that tells them
 * apart, which is why it is counted over the read and why the coverage note has to print it.
 */
describe("the comparable filter, and the disclosure that has to survive it", () => {
  const comparablePayload = (extra: Partial<CpiDisplayResponse> = {}) =>
    payload({
      rows: [row({ market_ticker: "KXCPI-26SEP09-3.0" })],
      total: 1,
      read_count: 70,
      withheld_count: 69,
      comparable_only: true,
      limit: CPI_CONTEXT_ROWS,
      ...extra,
    });

  it("keeps saying what was withheld, even though none of it is on the page", () => {
    // The obligation that matters more after the page got shorter, not less.
    const note = cpiCoverageNote(comparablePayload());
    expect(note).toMatch(/70 rows read/);
    expect(note).toMatch(/1 of the 1 comparable on this page/);
    expect(note).toMatch(/69 of the read have no market mid/);
    expect(note).toMatch(/not listed/);
  });

  it("distinguishes the two withhold phrasings, so the page never says it is listing them", () => {
    // Unfiltered: the row is on the page without a comparison. Filtered: it is not on the page.
    // One string for both would be a lie in one of the two states.
    expect(cpiCoverageNote(payload({ withheld_count: 4, total: 5, read_count: 5 }))).toMatch(
      /4 of the read have no market mid, so they are listed without a comparison/,
    );
    expect(cpiCoverageNote(comparablePayload())).not.toMatch(/listed without a comparison/);
  });

  it("prints the number of rows READ, which is not `total` once the filter has run", () => {
    // The reason `read_count` exists. `total` is 1 here; saying "1 row read" would be a different
    // and much smaller number than the one that was read.
    expect(readCount(comparablePayload())).toBe(70);
    expect(cpiTruncationNote(comparablePayload({ truncated: true }))).toMatch(/70 rows were read/);
  });

  it("falls back to `total` for a payload that predates `read_count`", () => {
    // A stale response must not make the page print a count it cannot support. `total` is the same
    // number on an unfiltered payload, so nothing a reader can see changes.
    const old = { ...payload({ total: 4 }), read_count: undefined } as unknown as CpiDisplayResponse;
    expect(readCount(old)).toBe(4);
    expect(cpiCoverageNote(old)).toMatch(/4 rows read/);
  });

  it("says the list is comparable-only, from the response's own flag", () => {
    // Rendered from `comparable_only`, not from "the list happens to be short" -- a short list is
    // not evidence of a filter, and a page that inferred one would be describing a window the
    // response never said it had opened.
    expect(isComparableOnly(comparablePayload())).toBe(true);
    expect(cpiComparableNote(comparablePayload())).toMatch(/Comparable releases only, newest first/);
    expect(cpiComparableNote(comparablePayload())).toMatch(new RegExp(`up to ${CPI_CONTEXT_ROWS} row`));
    expect(cpiComparableNote(payload({ withheld_count: 3 }))).toBeNull();
  });

  it("does not claim the rows are 'the most recent comparable', which is only true at offset 0", () => {
    // A sentence that is true of one page and false of the next is the window-misdescription the
    // whole endpoint exists to prevent, and the cap is the response's own `limit`.
    const note = cpiComparableNote(comparablePayload({ offset: 12 })) ?? "";
    expect(note).not.toMatch(/most recent/i);
    expect(note).toMatch(/newest first/);
  });

  it("marks the headline count as comparable, so '12 markets' is not read as the whole ledger", () => {
    expect(cpiHeadline(comparablePayload()).value).toMatch(/^1 comparable market shown/);
    expect(cpiHeadline(payload()).value).toMatch(/^1 market shown/);
  });

  it("does not say an empty comparable board is an empty ledger", () => {
    // The green-and-wrong case this filter makes reachable: 70 rows read, none carrying a mid, and
    // the old wording would have told a reader the ledger has no CPI markets in it.
    const empty = comparablePayload({ rows: [], total: 0, read_count: 70, withheld_count: 70 });
    const note = cpiEmptyNote(empty);
    expect(note).toMatch(/70 CPI releases were read/);
    expect(note).toMatch(/nothing to compare yet/);
    expect(note).toMatch(/not an empty ledger/);
    expect(note).not.toMatch(/No CPI markets in the ledger/);
  });

  it("still says the between-prints sentence when the ledger really is empty", () => {
    const note = cpiEmptyNote(payload({ rows: [], total: 0, read_count: 0, withheld_count: 0 }));
    expect(note).toMatch(/between prints is expected/i);
  });

  it("does not claim an empty board is empty when rows were read but none could be shown", () => {
    const note = cpiEmptyNote(payload({ rows: [], total: 0, read_count: 12, withheld_count: 0 }));
    expect(note).toMatch(/12 rows were read and none of them could be shown/);
    expect(note).not.toMatch(/No CPI markets in the ledger/);
  });
});

/**
 * The row count is a product decision, so it is pinned as one: a low-teens number, with a floor
 * under it. The complaint being answered was "we don't need to see everything that didn't make it",
 * and a test that only asserted `rows.length` would have passed unchanged at 50 -- which is the
 * defect restated as a test.
 */
describe("CPI_CONTEXT_ROWS", () => {
  it("is a low-teens count, not the 50 the page used to ask for", () => {
    expect(CPI_CONTEXT_ROWS).toBeLessThanOrEqual(15);
    expect(CPI_CONTEXT_ROWS).toBeGreaterThanOrEqual(5);
    expect(CPI_CONTEXT_ROWS).not.toBe(50);
  });
});
