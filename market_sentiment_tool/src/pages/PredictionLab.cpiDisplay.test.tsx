import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import PredictionLab from "@/pages/PredictionLab";
import { DISPLAY_ONLY_REASON } from "@/lib/displayOnlyEngines";

/**
 * The page half of Ruling 1, and the two tests that were waiting for it.
 *
 * These were `it.fails` while nothing rendered the withheld bucket: the hook withheld `cpi_nowcast`
 * rows and conserved them, but both consumers of the hook are pages, so a reader on the MACRO tab
 * saw a quieter tab and no statement that CPI exists and is display-only. `it.fails` was the marker
 * -- green now, red the moment the relabelling landed, so it could not rot into an assertion that
 * asserts nothing. It has landed, so the wrapper is gone and both tests are ordinary. Do not put it
 * back, and do not delete either test: they are the only thing that stops a CPI row reaching
 * `EdgeCard`, which prints `{edge_pct}% EDGE` for anything in `edges`.
 *
 * The same notice is rendered by the War Room (`Home.tsx`) and is tested in
 * `WithheldEdgesNotice.test.tsx`; the two here are about what the LAB page can do with a row.
 */

const cpiRow = {
  id: "cpi-1",
  market_id: "KXCPI-26SEP09-T0.3",
  market_title: "Will CPI be above 3.0%?",
  edge_type: "MACRO" as const,
  engine: "cpi_nowcast",
  engine_version: "cpi-v1",
  gate_status: "SHADOW" as const,
  market_prob: 0.32,
  our_prob: 0.52,
  edge_pct: 20.0,
  discovered_at: "2026-09-27T12:00:00Z",
  raw_payload: {},
};

/**
 * `vi.mock` is hoisted above the imports, so a factory closing over a function parameter throws a
 * ReferenceError at render time -- which the `it.fails` wrapper was happy to count as "the page
 * does not render this yet". The marker was green for the wrong reason: it proved a stub was
 * broken, not that the page was. `vi.hoisted` puts the mutable cell above the mock so the factory
 * can read the current value, which is what makes these two tests real.
 */
const HOOK = vi.hoisted(() => ({
  current: { edges: [] as unknown[], withheld: [] as unknown[], loading: false },
}));

vi.mock("@/hooks/useMarketEdges", () => ({ useMarketEdges: () => HOOK.current }));

function stubHook(withheld: unknown[], edges: unknown[] = []) {
  HOOK.current = { edges, withheld, loading: false };
}

describe("PredictionLab must say that cpi_nowcast exists and is not an edge engine", () => {
  it("shows the withheld CPI row with the 'not an edge engine' reason, rather than an empty tab", () => {
    stubHook([{ edge: cpiRow, engine: "cpi_nowcast", reason: DISPLAY_ONLY_REASON.cpi_nowcast }]);

    render(<PredictionLab />);

    // The row is read, so it must be accounted for on screen: either presented with the label, or
    // explicitly accounted for. Before this landed it was neither -- it was simply absent.
    expect(screen.getByText(/not an edge engine/i)).toBeTruthy();
    expect(screen.getByText(/KXCPI-26SEP09-T0\.3/)).toBeTruthy();
  });

  it("never renders a cpi_nowcast row through the opportunity EdgeCard", () => {
    // The failure this guards: the EdgeCard prints `{edge_pct}% EDGE` for anything in `edges`, so
    // a CPI row reaching it claims a 20.0% edge on an engine that has none. The data-layer tests
    // prove the hook withholds it; this proves the page cannot reintroduce it.
    stubHook([], [cpiRow]);

    render(<PredictionLab />);

    expect(screen.queryByText(/20\.0% EDGE/)).toBeNull();
  });

  it("pulls a leaked display-only row out of the board and relabels it instead", () => {
    // The stub above stands in for a hook regression, not a real read. Whatever the reason, a
    // display-only row in `edges` must come out again, on the page, labelled -- not rendered as an
    // opportunity and not dropped either.
    stubHook([], [cpiRow]);

    const { container } = render(<PredictionLab />);

    expect(screen.getByText(/not an edge engine/i)).toBeTruthy();
    expect(container.textContent).not.toMatch(/20\.0/);
  });

  it("leaves the other MACRO engine alone", () => {
    const labor = {
      ...cpiRow,
      id: "labor-1",
      market_id: "KXPAYROLLS-26OCT-T0.1",
      engine: "labor_nowcast",
      edge_pct: 10.0,
    };
    stubHook([], [labor]);

    render(<PredictionLab />);

    expect(screen.getByText(/10\.0% EDGE/)).toBeTruthy();
    expect(screen.queryByText(/not an edge engine/i)).toBeNull();
  });
});
