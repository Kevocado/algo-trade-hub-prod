import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { QuarantineNotice } from "@/components/QuarantineNotice";
import { QUARANTINE_MARK, type QuarantineResponse, type QuarantineRow } from "@/lib/quarantine";
import { NOT_MEASURED } from "@/lib/edgeFigures";

/**
 * The component half of the quarantine, and the assertions that matter most are the negative ones.
 *
 * A quarantined number that looks authoritative and is not is the exact failure this effort exists
 * to prevent -- the same class of failure as PR #38's "No high-confidence edges detected in
 * weather", reached from the other direction. So the tests are mostly about what the component must
 * NOT be able to print: 295 as an opportunity count, a 0 for a measurement that did not arrive, or
 * anything at all after a failed read.
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

const ARTEFACT_ROW: QuarantineRow = {
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

function payload(over: Partial<QuarantineResponse> = {}): QuarantineResponse {
  return {
    as_of: "2026-09-28T00:00:00Z",
    marker: QUARANTINE_MARK,
    quarantined: true,
    note: "QUARANTINED. These engines run and compute their real output, and none of it is published.",
    rows: COUNTS.rows,
    measured: true,
    unmeasured_reason: null,
    totals: COUNTS,
    engines: [
      { engine: "Weather", marker: QUARANTINE_MARK, quarantined: true, note: "", counts: COUNTS },
      { engine: "Macro", marker: QUARANTINE_MARK, quarantined: true, note: "", counts: COUNTS },
    ],
    reasons: {},
    kalshi_edges_written: 0,
    sink: "kalshi_quarantine_edges",
    rows_page: [ARTEFACT_ROW],
    ...over,
  };
}

describe("what the owner sees", () => {
  it("leads with 26, not 295", () => {
    render(<QuarantineNotice payload={payload()} />);
    const headline = screen.getByTestId("quarantine-headline");
    expect(headline.textContent).toBe("26");
    // And the row count is present, labelled as rows, beside it rather than instead of it.
    expect(screen.getByTestId("quarantine-rows").textContent).toBe("295");
  });

  it("says the measurement is real and unpublished, in the note", () => {
    render(<QuarantineNotice payload={payload()} />);
    expect(screen.getByText(/none of it is published/i)).toBeTruthy();
  });

  it("puts the marker on the heading, so a screenshot keeps it", () => {
    render(<QuarantineNotice payload={payload()} />);
    // The literal word, not the imported constant. A test that referenced `QUARANTINE_MARK` here
    // would pass with the constant emptied -- `new RegExp("")` matches any heading -- and this is
    // the assertion that has to fail when somebody hides the marker.
    expect(screen.getByRole("heading", { name: /QUARANTINED/ })).toBeTruthy();
  });

  it("gives the proof in the place a reader who doubts the label will look", () => {
    render(<QuarantineNotice payload={payload()} />);
    // A hard 0, by construction rather than by tonight's scan, and the sink it went to instead.
    expect(screen.getByText(/Rows written to kalshi_edges: 0/)).toBeTruthy();
    expect(screen.getByText(/kalshi_quarantine_edges/)).toBeTruthy();
  });

  it("shows the split, so the headline is not the only number on screen", () => {
    render(<QuarantineNotice payload={payload()} />);
    const text = screen.getByTestId("quarantine-notice").textContent ?? "";
    expect(text).toContain("187");
    expect(text).toContain("82");
    expect(text).toContain("Independent opportunities");
    expect(text).toContain("Rows measured");
  });

  it("marks every row it renders, and labels the artefacts", () => {
    render(<QuarantineNotice payload={payload()} />);
    const notice = screen.getByTestId("quarantine-notice");
    // The marker on the row card as well as on the panel, so a row cannot be screenshotted on its
    // own and look live. Asserted on the CARD rather than by counting occurrences in the panel,
    // because the panel's marker is inside a heading and the panel carries other numbers.
    const card = screen.getByText("KXGDPYEAR-26-T2.5").closest("li") as HTMLElement;
    // The literal word again -- `getByText("")` matches everything, which is how a test written
    // against the constant passes while the marker is not on screen at all.
    expect(within(card).getByText("QUARANTINED")).toBeTruthy();
    expect(within(notice).getByText(/units artefact/i)).toBeTruthy();
    // And the forecast key, which is how a reader checks the restatement count from the page.
    expect(within(card).getByText(/Macro \| GDP \| 10/)).toBeTruthy();
  });
});

describe("what it must not be able to print", () => {
  it("never prints 295 as the opportunity count", () => {
    const { container } = render(<QuarantineNotice payload={payload()} />);
    const headline = screen.getByTestId("quarantine-headline");
    expect(headline.textContent).not.toBe("295");
    // And the phrase that would pair them, which is the natural thing to write and the wrong thing.
    expect(container.textContent).not.toMatch(/295 opportunities/i);
  });

  it("prints a dash, not a zero, when the sink is empty", () => {
    // An empty table is either no scan yet or a migration that has not been applied. Neither is a
    // count of zero opportunities, and a 0 here is the most damaging value this surface could show.
    render(
      <QuarantineNotice
        payload={payload({
          measured: false,
          totals: null,
          rows: 0,
          unmeasured_reason: "kalshi_quarantine_edges is empty. This is not a count of zero opportunities.",
          rows_page: [],
        })}
      />,
    );
    expect(screen.getByTestId("quarantine-unmeasured")).toBeTruthy();
    expect(screen.queryByTestId("quarantine-headline")).toBeNull();
    expect(screen.getByText(/not a count of zero opportunities/i)).toBeTruthy();
  });

  it("claims nothing at all when the read failed", () => {
    render(<QuarantineNotice payload={null} readError="503 from /api/quarantine" />);
    expect(screen.getByTestId("quarantine-read-failure")).toBeTruthy();
    expect(screen.queryByTestId("quarantine-notice")).toBeNull();
    // Neither of the two false readings: "nothing quarantined" and "the engines found nothing".
    const text = screen.getByTestId("quarantine-read-failure").textContent ?? "";
    expect(text).not.toMatch(/\b0\b/);
    expect(text).toMatch(/not that the engines found opportunities, and not that they found none/i);
  });

  it("says nothing is established when the read has not arrived", () => {
    render(<QuarantineNotice payload={null} />);
    expect(screen.getByTestId("quarantine-missing")).toBeTruthy();
    expect(screen.queryByTestId("quarantine-notice")).toBeNull();
  });

  it("draws a missing figure on a row as a dash rather than 0", () => {
    // A row that recorded no price has no price. Writing 0 would put a fabricated figure into the
    // one table whose entire purpose is to hold figures that were really measured.
    const noPrice: QuarantineRow = { ...ARTEFACT_ROW, price_cents: null, model_probability_pct: null, edge_points: null };
    render(<QuarantineNotice payload={payload({ rows_page: [noPrice] })} />);
    const card = screen.getByText("KXGDPYEAR-26-T2.5").closest("li") as HTMLElement;
    expect(card.textContent).toContain(NOT_MEASURED);
    expect(card.textContent).not.toMatch(/at 0c/);
  });
});
