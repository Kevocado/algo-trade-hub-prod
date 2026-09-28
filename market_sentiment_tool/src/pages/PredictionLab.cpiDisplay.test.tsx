import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import PredictionLab from "@/pages/PredictionLab";
import { DISPLAY_ONLY_REASON } from "@/lib/displayOnlyEngines";
import type { EngineHealthResponse } from "@/lib/engineHealth";

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
  current: {
    edges: [] as unknown[],
    withheld: [] as unknown[],
    loading: false,
    error: null as string | null,
    truncated: false,
  },
}));

vi.mock("@/hooks/useMarketEdges", () => ({ useMarketEdges: () => HOOK.current }));

/**
 * The page's SECOND read, stubbed with a ruling that has nothing stopped.
 *
 * The page now distinguishes "this engine ran and found nothing" from "this engine could not run",
 * and the difference between those two is `/api/engine-health` rather than the board. So a page
 * test that stubs only the board is a page whose board read SUCCEEDED and whose ruling did not
 * arrive, and the honest rendering of that is "the emptiness is not established" -- not the quiet
 * sentence. The test below that says "a successful read with no rows is an empty board" is right
 * about the board and needs the ruling to be present before it can say anything at all, so it is
 * stubbed here rather than weakened. Its own test cases about a FAILED board read are unaffected:
 * that branch is above the ruling entirely, and it is tested in
 * `PredictionLab.stoppedEngines.test.tsx` that a failed RULING claims nothing either way.
 */
const HEALTH = vi.hoisted(() => ({
  current: {
    data: {
      as_of: "2026-09-28T00:00:00Z",
      edge_types: [
        { edge_type: "MACRO", label: "Macro", state: "ran", reason: null, stopped_sites: [],
          opportunities_found: null, opportunities_found_reason: "Not counted here." },
        { edge_type: "WEATHER", label: "Weather", state: "ran", reason: null, stopped_sites: [],
          opportunities_found: null, opportunities_found_reason: "Not counted here." },
      ],
      edge_types_total: 2,
      edge_types_could_not_run: 0,
      edge_types_ran: 2,
      board_state: "ran",
      board_reason: null,
      sites: [],
      sites_total: 0,
      sites_wired: 0,
      sites_unwired: 0,
      note: "An engine on this list did not run.",
    } as unknown as EngineHealthResponse,
    loading: false,
    error: null as string | null,
  },
}));

vi.mock("@/hooks/useEngineHealth", () => ({ useEngineHealth: () => HEALTH.current }));

function stubHook(withheld: unknown[], edges: unknown[] = [], over: Record<string, unknown> = {}) {
  HOOK.current = { edges, withheld, loading: false, error: null, truncated: false, ...over };
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

/**
 * The failed read, on the page. The hook swallows nothing now, but the BOARD is the other half:
 * "No high-confidence edges detected" is a finding, and a read that never completed cannot produce
 * one. This is the same ambiguity one layer up that the withholding rule exists to remove.
 */
describe("PredictionLab must not report a failed read as a finding", () => {
  it("does not say no edges were detected when the table could not be read", () => {
    stubHook([], [], { error: "Could not find the table 'public.kalshi_edges'" });

    render(<PredictionLab />);

    expect(screen.queryByText(/No high-confidence edges detected/i)).toBeNull();
    expect(screen.getByText(/could not be read/i)).toBeTruthy();
    // Twice on purpose: the board says it and so does the withheld notice below, because they are
    // making the same claim about two different things (the board, and the withheld bucket).
    expect(screen.getAllByText(/kalshi_edges/).length).toBeGreaterThan(0);
    expect(screen.getByText(/not an empty result/i)).toBeTruthy();
  });

  it("withholds the edge count and the global heat rather than reporting zero", () => {
    // `0` and `0.00%` are measurements of nothing that was measured.
    stubHook([], [], { error: "boom" });

    const { container } = render(<PredictionLab />);

    expect(container.textContent).not.toMatch(/\b0\.00%/);
    expect(screen.queryByText(/Active Edges/i)).toBeTruthy();
  });

  it("keeps the 'nothing was withheld' claim off the page when the read failed", () => {
    // The notice's authoritative wording is suppressed rather than rendered against an empty bucket
    // that a failure produced.
    stubHook([], [], { error: "boom" });

    const { container } = render(<PredictionLab />);

    expect(screen.getByTestId("edges-read-failure")).toBeTruthy();
    expect(container.textContent).not.toMatch(/not deleted/i);
    expect(container.textContent).not.toMatch(/of the \d+ rows read/i);
  });

  it("still says no edges were detected on a read that SUCCEEDED and found none", () => {
    // The other direction, and the one that would be broken by a fix that only ever renders the
    // failure: an empty successful read really is an empty board, and hiding that would be its own
    // kind of lie.
    stubHook([], []);

    render(<PredictionLab />);

    expect(screen.getByText(/No high-confidence edges detected in all/i)).toBeTruthy();
    expect(screen.queryByTestId("edges-read-failure")).toBeNull();
  });
});
