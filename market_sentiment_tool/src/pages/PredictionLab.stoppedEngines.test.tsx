import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import PredictionLab from "@/pages/PredictionLab";
import type { EngineHealthResponse } from "@/lib/engineHealth";

/**
 * The Prediction Lab must be able to say an engine is broken, and this file is that test.
 *
 * The defect, in one sentence: the WEATHER and MACRO tabs rendered "No high-confidence edges
 * detected in <tab>", which is a FINDING, for engines that had not looked at anything. Kalshi's API
 * stopped sending `yes_ask`; the Tier-1 real-edge weather and macro engines still read it with a `0`
 * default, so every market they fetched read as a 0c quote, got skipped, and was never published.
 * They raise nothing, because skipping an unpriceable market is the right move -- they fail CLOSED,
 * which is why the ledger is clean and why nobody noticed.
 *
 * So the board needed a third state, and these tests hold all three apart:
 *
 *   stopped    the engine could not run. Says so, with the reason. Never says "nothing found".
 *   quiet      the engine ran and nothing qualified. Still says "no high-confidence edges", because
 *              that is the one case where the sentence is a measurement and not an absence.
 *   unchecked  the ruling could not be read. Says neither, because claiming either would be the
 *              defect moved up a layer.
 *
 * The `it` that fails if the fix is undone is "never renders the quiet sentence for a stopped
 * engine" -- that is the mutation this file exists to catch, and the last describe block runs it.
 */

const HOOKS = vi.hoisted(() => ({
  edges: {
    edges: [] as unknown[],
    withheld: [] as unknown[],
    loading: false,
    error: null as string | null,
    truncated: false,
  },
  health: { data: null as EngineHealthResponse | null, loading: false, error: null as string | null },
}));

vi.mock("@/hooks/useMarketEdges", () => ({ useMarketEdges: () => HOOKS.edges }));
vi.mock("@/hooks/useEngineHealth", () => ({ useEngineHealth: () => HOOKS.health }));

const WEATHER_REASON =
  "Not running. WeatherEngine prices every market against `yes_ask`, which Kalshi's API no longer sends.";

function entry(edge_type: string, state: "ran" | "could_not_run", reason: string | null) {
  return {
    edge_type,
    label: edge_type[0] + edge_type.slice(1).toLowerCase(),
    state,
    reason,
    stopped_sites: state === "could_not_run"
      ? [{
          name: `${edge_type}Engine`,
          module: `tradehub/engines/${edge_type.toLowerCase()}_engine.py`,
          site: `tradehub/engines/${edge_type.toLowerCase()}_engine.py:214`,
          edge_type,
          wired_to_a_scanner: true,
          reason: reason ?? "",
        }]
      : [],
    opportunities_found: null,
    opportunities_found_reason:
      state === "could_not_run"
        ? "No count, because nothing ran. Not a count of zero."
        : "Not counted here.",
  };
}

function health(stopped: string[]): EngineHealthResponse {
  const entries = ["WEATHER", "MACRO", "SPORTS", "CRYPTO", "ENERGY"].map((t) =>
    entry(t, stopped.includes(t) ? "could_not_run" : "ran", stopped.includes(t) ? WEATHER_REASON : null),
  );
  const reasons = entries.filter((e) => e.state === "could_not_run").map((e) => e.reason);
  return {
    as_of: "2026-09-28T00:00:00Z",
    edge_types: entries,
    edge_types_total: entries.length,
    edge_types_could_not_run: stopped.length,
    edge_types_ran: entries.length - stopped.length,
    board_state: stopped.length > 0 ? "could_not_run" : "ran",
    board_reason: reasons.length ? reasons.join(" ") : null,
    sites: [],
    sites_total: 0,
    sites_wired: 0,
    sites_unwired: 0,
    note: "An engine on this list did not run.",
  };
}

function stub(over: { edges?: unknown[]; health?: EngineHealthResponse | null; healthError?: string | null } = {}) {
  HOOKS.edges = { edges: over.edges ?? [], withheld: [], loading: false, error: null, truncated: false };
  HOOKS.health = { data: over.health === undefined ? health([]) : over.health, loading: false, error: over.healthError ?? null };
}

/**
 * `mouseDown`, not `click`.
 *
 * The tab strip is a Radix `TabsTrigger`, which selects on POINTER down rather than on click, so a
 * `fireEvent.click` leaves `activeTab` on "all" and the assertion below silently reads the unfiltered
 * board -- the same tree the mutation block is trying to distinguish from. Worth knowing that this
 * failure mode is a green test that measured nothing, which is the exact class of bug this page is
 * about.
 */
function selectTab(label: string) {
  fireEvent.mouseDown(screen.getByRole("tab", { name: label }));
}

describe("a broken engine renders as broken, with a reason", () => {
  it("does not print the quiet sentence for a stopped engine's tab", () => {
    stub({ health: health(["WEATHER", "MACRO"]) });
    render(<PredictionLab />);
    selectTab("WEATHER");

    expect(screen.queryByText(/No high-confidence edges detected in weather/i)).toBeNull();
    expect(screen.getByText(/Weather is not running/i)).toBeTruthy();
    // The same reason appears on the tab and in the notice below, so `getAllByText` rather than
    // `getByText`: two renderings of one server sentence is the intended shape, and a test that
    // demanded exactly one would push someone to drop one of them.
    expect(screen.getAllByText(WEATHER_REASON).length).toBeGreaterThan(0);
  });

  it("says the same for the Macro tab, which the same drift broke", () => {
    stub({ health: health(["WEATHER", "MACRO"]) });
    render(<PredictionLab />);
    selectTab("MACRO");

    expect(screen.queryByText(/No high-confidence edges detected in macro/i)).toBeNull();
    expect(screen.getByText(/Macro is not running/i)).toBeTruthy();
  });

  it("says an empty tab is not a finding about the market", () => {
    // The sentence that was being implied, and the whole point: the emptiness is a fact about the
    // engine, not about the weather.
    stub({ health: health(["WEATHER"]) });
    render(<PredictionLab />);
    selectTab("WEATHER");

    expect(screen.getByText(/not a finding about the market/i)).toBeTruthy();
  });

  it("names the engine and the line, so the claim can be checked", () => {
    stub({ health: health(["WEATHER"]) });
    render(<PredictionLab />);

    const notice = screen.getByTestId("stopped-engines");
    expect(notice.textContent).toContain("weather_engine.py:214");
  });

  it("still renders the notice when the tab is NOT empty", () => {
    // The structural half of the requirement. A MACRO tab with rows on it is fed by labor_nowcast,
    // so a stopped engine's board can look perfectly healthy -- and "the tab is empty, therefore
    // something is wrong" does not survive contact with this product.
    stub({
      health: health(["MACRO"]),
      edges: [{
        id: "labor-1",
        market_id: "KXPAYROLLS-26OCT-T0.1",
        market_title: "Payrolls above 0.1%?",
        edge_type: "MACRO",
        engine: "labor_nowcast",
        gate_status: "SHADOW",
        our_prob: 0.5,
        market_prob: 0.4,
        edge_pct: 10,
        discovered_at: "2026-09-28T00:00:00Z",
        raw_payload: {},
      }],
    });
    render(<PredictionLab />);
    selectTab("MACRO");

    expect(screen.getByText(/10\.0% EDGE/)).toBeTruthy();
    expect(screen.getByTestId("stopped-engines")).toBeTruthy();
  });
});

describe("an engine that ran and found nothing still reads as quiet", () => {
  it("keeps saying no high-confidence edges when nothing is stopped", () => {
    // The direction a fix that only ever renders the failure would break. Hiding this would make
    // every unfashionable engine look broken and train the reader to ignore the label.
    stub({ health: health([]) });
    render(<PredictionLab />);
    selectTab("WEATHER");

    expect(screen.getByText(/No high-confidence edges detected in weather/i)).toBeTruthy();
    expect(screen.queryByTestId("stopped-engines")).toBeNull();
  });

  it("does not mention a stopped engine on a tab the ruling says ran", () => {
    stub({ health: health(["WEATHER"]) });
    render(<PredictionLab />);
    selectTab("SPORTS");

    const board = screen.getByText(/No high-confidence edges detected in sports/i).closest("div");
    expect(within(board as HTMLElement).queryByText(/not running/i)).toBeNull();
  });

  it("leaves a running engine's own rows alone", () => {
    stub({
      health: health(["WEATHER"]),
      edges: [{
        id: "labor-1",
        market_id: "KXPAYROLLS-26OCT-T0.1",
        market_title: "Payrolls above 0.1%?",
        edge_type: "MACRO",
        engine: "labor_nowcast",
        gate_status: "SHADOW",
        our_prob: 0.5,
        market_prob: 0.4,
        edge_pct: 12.5,
        discovered_at: "2026-09-28T00:00:00Z",
        raw_payload: {},
      }],
    });
    render(<PredictionLab />);
    selectTab("MACRO");

    expect(screen.getByText(/12\.5% EDGE/)).toBeTruthy();
  });

  it("still says nothing detected on the unfiltered board when the ruling is clean", () => {
    stub({ health: health([]) });
    render(<PredictionLab />);

    expect(screen.getByText(/No high-confidence edges detected in all/i)).toBeTruthy();
  });
});

describe("a missing figure is a word or a null, never 0", () => {
  it("draws the stopped engine's opportunity count as a dash", () => {
    stub({ health: health(["WEATHER"]) });
    render(<PredictionLab />);

    const notice = screen.getByTestId("stopped-engines");
    expect(notice.textContent).toMatch(/Opportunities found:\s*—/);
  });

  it("does not print a zero in its place anywhere on the page", () => {
    // `2 of 5 boards` is the server's count of BOARDS and is a real number. What must not appear is
    // a zero standing in for a search that never ran.
    stub({ health: health(["WEATHER", "MACRO"]) });
    const { container } = render(<PredictionLab />);

    expect(container.textContent).not.toMatch(/Opportunities found:\s*0/);
    expect(container.textContent).not.toMatch(/found 0 (weather|macro) opportunities/i);
  });

  it("explains the dash, so it is not the only thing on screen", () => {
    stub({ health: health(["WEATHER"]) });
    render(<PredictionLab />);

    expect(screen.getByTestId("stopped-engines").textContent).toMatch(/nothing ran/i);
  });
});

describe("a ruling that could not be read claims nothing either way", () => {
  it("does not say an engine found nothing", () => {
    stub({ health: null, healthError: "503 from /api/engine-health" });
    render(<PredictionLab />);
    selectTab("WEATHER");

    expect(screen.queryByText(/No high-confidence edges detected in weather/i)).toBeNull();
  });

  it("does not say an engine is broken either", () => {
    stub({ health: null, healthError: "boom" });
    render(<PredictionLab />);
    selectTab("WEATHER");

    expect(screen.queryByText(/Weather is not running/i)).toBeNull();
    expect(screen.getByTestId("engine-health-read-failure")).toBeTruthy();
  });

  it("says the emptiness has not been established", () => {
    stub({ health: null, healthError: "boom" });
    render(<PredictionLab />);
    selectTab("WEATHER");

    expect(screen.getByText(/not yet a finding/i)).toBeTruthy();
  });

  it("does not report a ruling that has not arrived as a quiet board", () => {
    // The state between mount and the read resolving. Rendering the quiet sentence here would put
    // the original defect back for as long as the request takes.
    stub({ health: null });
    render(<PredictionLab />);
    selectTab("WEATHER");

    expect(screen.queryByText(/No high-confidence edges detected in weather/i)).toBeNull();
    expect(screen.getByTestId("engine-health-missing")).toBeTruthy();
  });
});

/**
 * THE MUTATION.
 *
 * Break the fix the way the defect was broken -- by reporting the stopped engine as a normal quiet
 * board with a count of zero -- and these are the tests that must go red. Run this block after
 * changing `edgeTypeStateOf` to return "ran" for a ruled-against engine, or after defaulting
 * `opportunities_found` to 0 in `tradehub/engine_health.py`.
 */
describe("MUTATION: a stopped engine reported as a normal zero", () => {
  const mutated = (): EngineHealthResponse => {
    const base = health(["WEATHER", "MACRO"]);
    return {
      ...base,
      board_state: "ran",
      board_reason: null,
      edge_types: base.edge_types.map((e) =>
        e.state === "could_not_run"
          ? { ...e, state: "ran" as const, reason: null, stopped_sites: [], opportunities_found: 0 }
          : e,
      ),
    };
  };

  it("would be caught by the quiet-sentence assertion above", () => {
    stub({ health: mutated() });
    render(<PredictionLab />);
    selectTab("WEATHER");

    // The mutation succeeds at putting the lie back on the screen, which is what makes the assertion
    // in the first describe block worth having.
    expect(screen.getByText(/No high-confidence edges detected in weather/i)).toBeTruthy();
  });

  it("would be caught by the notice-disappearing assertion", () => {
    stub({ health: mutated() });
    render(<PredictionLab />);

    expect(screen.queryByTestId("stopped-engines")).toBeNull();
  });

  it("would be caught by the missing-figure assertion", () => {
    stub({ health: mutated() });
    render(<PredictionLab />);

    expect(screen.queryByTestId("stopped-engines")).toBeNull();
  });
});
