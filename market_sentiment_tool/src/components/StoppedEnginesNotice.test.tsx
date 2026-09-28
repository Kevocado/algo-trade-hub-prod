import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { StoppedEnginesNotice } from "@/components/StoppedEnginesNotice";
import type { EngineHealthResponse } from "@/lib/engineHealth";

/**
 * The notice that makes a stopped engine visible at all.
 *
 * `WithheldEdgesNotice` exists because a row that is read and not rendered is indistinguishable
 * from there having been no rows. This one is the same rule for a run that produces no row: the
 * Tier-1 real-edge weather and macro engines read `yes_ask`, Kalshi stopped sending that key, and
 * the `0` default made every market look unpriceable -- so they skipped all of them and published
 * nothing, without raising anything. Nothing is wrong in the ledger, which is exactly why nothing
 * is on screen either.
 *
 * The load-bearing test here is the LAST one: the notice must render when the tab is full of rows.
 * A MACRO tab with rows on it is fed by labor_nowcast, so a stopped engine's board can look
 * perfectly healthy, and "the tab is empty, therefore something is wrong" does not survive contact
 * with this product.
 */

const WEATHER_REASON =
  "Not running. WeatherEngine prices every market against `yes_ask`, which Kalshi's API no longer sends.";
const MACRO_REASON =
  "Not running. MacroEngine prices every market against `yes_ask`, which Kalshi's API no longer sends.";

function site(name: string, module: string, line: number, wired: boolean, why: string) {
  return {
    name,
    module,
    site: `${module}:${line}`,
    edge_type: "WEATHER" as const,
    wired_to_a_scanner: wired,
    disposition: (wired ? "repaired_quarantined" : "unrepaired") as "repaired_quarantined" | "unrepaired",
    reason: why,
  };
}

const WEATHER_ENGINE = site("WeatherEngine", "tradehub/engines/weather_engine.py", 220, true, WEATHER_REASON);
const WEATHER_MAKER = site("WeatherMaker", "tradehub/engines/weather_maker.py", 258, false, "Not wired.");
const MACRO_ENGINE = site("MacroEngine", "tradehub/engines/macro_engine.py", 459, true, MACRO_REASON);

function health(over: Partial<EngineHealthResponse> = {}): EngineHealthResponse {
  return {
    as_of: "2026-09-28T00:00:00Z",
    edge_types: [
      {
        edge_type: "WEATHER",
        label: "Weather",
        state: "could_not_run",
        reason: WEATHER_REASON,
        stopped_sites: [WEATHER_ENGINE, WEATHER_MAKER],
        quarantine_sink: null,
        opportunities_found: null,
        opportunities_found_reason: "No count, because nothing ran. Not a count of zero.",
      },
      {
        edge_type: "MACRO",
        label: "Macro",
        state: "could_not_run",
        reason: MACRO_REASON,
        stopped_sites: [MACRO_ENGINE],
        quarantine_sink: null,
        opportunities_found: null,
        opportunities_found_reason: "No count, because nothing ran. Not a count of zero.",
      },
    ],
    edge_types_total: 5,
    edge_types_could_not_run: 2,
    edge_types_quarantined: 0,
    edge_types_ran: 3,
    board_state: "could_not_run",
    board_reason: WEATHER_REASON,
    sites: [],
    sites_total: 0,
    sites_wired: 0,
    sites_unwired: 0,
    sites_repaired: 0,
    sites_unrepaired: 0,
    note: "An engine on this list did not run.",
    ...over,
  };
}

describe("a broken engine is named, with a reason", () => {
  it("says so in a heading, with the server's count", () => {
    render(<StoppedEnginesNotice health={health()} />);
    const notice = screen.getByTestId("stopped-engines");
    const heading = within(notice).getByRole("heading", { name: /not running/i });
    expect(heading.textContent).toContain("2 of 5 boards");
  });

  it("prints the reason for each stopped engine, not a bare state", () => {
    render(<StoppedEnginesNotice health={health()} />);
    expect(screen.getByText(WEATHER_REASON)).toBeTruthy();
    expect(screen.getByText(MACRO_REASON)).toBeTruthy();
  });

  it("gives the module and line, so the ruling can be checked rather than believed", () => {
    render(<StoppedEnginesNotice health={health()} />);
    const notice = screen.getByTestId("stopped-engines");
    expect(notice.textContent).toContain("tradehub/engines/weather_engine.py:220");
    expect(notice.textContent).toContain("tradehub/engines/macro_engine.py:459");
  });

  it("keeps the unwired engine visible AND says it is not a cause", () => {
    // Dropping it would hide a real defect from whoever fixes it; calling it a cause would blame a
    // dead branch for a live board. Both halves have to be on the same line.
    render(<StoppedEnginesNotice health={health()} />);
    const notice = screen.getByTestId("stopped-engines");
    const makers = within(notice).getAllByText("WeatherMaker");
    expect(makers.length).toBe(1);
    const maker = makers[0].closest("li") as HTMLElement;
    expect(maker.textContent).toMatch(/not wired to any scanner/i);
    expect(maker.textContent).toMatch(/not a cause of an empty board/i);
  });

  it("never says an engine found nothing", () => {
    render(<StoppedEnginesNotice health={health()} />);
    expect(screen.getByTestId("stopped-engines").textContent?.toLowerCase()).not.toContain(
      "found no qualifying opportunity",
    );
  });
});

describe("the opportunity count is a dash, not a zero", () => {
  it("prints a dash where a stopped engine has no count", () => {
    render(<StoppedEnginesNotice health={health()} />);
    const notice = screen.getByTestId("stopped-engines");
    expect(notice.textContent).toMatch(/Opportunities found:\s*—/);
  });

  it("does not print a zero beside it", () => {
    render(<StoppedEnginesNotice health={health()} />);
    const notice = screen.getByTestId("stopped-engines");
    // `0 of 5` is the server's count of BOARDS and is a real number; what must not appear is a
    // zero standing in for a search nobody ran.
    expect(notice.textContent).not.toMatch(/Opportunities found:\s*0/);
  });

  it("says what the dash means", () => {
    render(<StoppedEnginesNotice health={health()} />);
    expect(screen.getByTestId("stopped-engines").textContent).toMatch(/nothing ran/i);
  });
});

describe("a ruling that could not be read says so, and claims nothing", () => {
  it("suppresses the ruling's own wording and shows the failure", () => {
    render(<StoppedEnginesNotice health={health()} readError="503 from /api/engine-health" />);
    expect(screen.getByTestId("engine-health-read-failure")).toBeTruthy();
    expect(screen.getByText("503 from /api/engine-health")).toBeTruthy();
    expect(screen.queryByTestId("stopped-engines")).toBeNull();
  });

  it("does not let a failed read read as 'nothing is stopped'", () => {
    render(<StoppedEnginesNotice health={health()} readError="boom" />);
    const failure = screen.getByTestId("engine-health-read-failure");
    expect(failure.textContent).toMatch(/failed read, not an empty one/i);
    expect(failure.textContent).toMatch(/not that engines are stopped/i);
  });

  it("says a missing ruling is a fault rather than rendering nothing", () => {
    // An empty component is the defect: a page that says nothing about which engines run is a page
    // where an empty board is a finding.
    render(<StoppedEnginesNotice health={null} />);
    expect(screen.getByTestId("engine-health-missing")).toBeTruthy();
  });

  it("renders nothing at all when the ruling says nothing is stopped", () => {
    const clean = health({
      edge_types: [{ ...health().edge_types[1], edge_type: "SPORTS", state: "ran", reason: null }],
      edge_types_could_not_run: 0,
      board_state: "ran",
      board_reason: null,
    });
    const { container } = render(<StoppedEnginesNotice health={clean} />);
    // There is no "0 stopped engines" line. A placeholder for an absence is the same noise this
    // component exists to remove.
    expect(container.textContent).toBe("");
  });
});

describe("the notice does not wait for the board to look empty", () => {
  it("renders the same way regardless of what is on the board", () => {
    // This component is handed the ruling and nothing else -- it has no rows and no way to know
    // whether a tab is empty. The property under test is structural: it CANNOT be conditional on
    // the board, so it cannot be the thing that goes away when another engine fills the tab.
    const { container } = render(<StoppedEnginesNotice health={health()} />);
    expect(container.querySelector("[data-testid='stopped-engines']")).toBeTruthy();
  });
});
