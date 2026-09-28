import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import PredictionLab from "@/pages/PredictionLab";
import type { EngineHealthResponse, EngineState } from "@/lib/engineHealth";

/**
 * The Prediction Lab must be able to say an engine is broken, quarantined, or quiet, and this file
 * is that test.
 *
 * The defect, in one sentence: the WEATHER and MACRO tabs rendered "No high-confidence edges
 * detected in <tab>", which is a FINDING, for engines that had not looked at anything. Kalshi's API
 * stopped sending `yes_ask`; the Tier-1 real-edge weather and macro engines still read it with a `0`
 * default, so every market they fetched read as a 0c quote, got skipped, and was never published.
 * They raise nothing, because skipping an unpriceable market is the right move -- they fail CLOSED,
 * which is why the ledger is clean and why nobody noticed.
 *
 * The board then needed a third state, and it now needs a fourth. These tests hold all four apart:
 *
 *   stopped     the engine could not run. Says so, with the reason. Never says "nothing found".
 *   quarantined the engine RAN, measured 295 rows on 2026-09-28, and had them withheld by ruling.
 *               Says neither "not running" (false -- it runs) nor "nothing found" (false -- and the
 *               original defect of this page reached from the other direction).
 *   quiet       the engine ran and nothing qualified. Still says "no high-confidence edges", because
 *               that is the one case where the sentence is a measurement and not an absence.
 *   unchecked   the ruling could not be read. Says neither, because claiming either would be the
 *               defect moved up a layer.
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
// Stubbed separately from the ruling on purpose. Three reads, three questions: "I cannot see the
// published rows", "I cannot tell whether an engine ran", "I cannot see what the withheld engines
// measured". Merging any two of them would let one hide another, and the third shown as the first
// would conclude there are no quarantined rows -- a count of zero reached through a different door.
vi.mock("@/hooks/useQuarantine", () => ({ useQuarantine: () => QUARANTINE_STUB }));

const WEATHER_REASON =
  "Not running. WeatherEngine prices every market against `yes_ask`, which Kalshi's API no longer sends.";

function entry(edge_type: string, state: EngineState, reason: string | null) {
  return {
    edge_type,
    label: edge_type[0] + edge_type.slice(1).toLowerCase(),
    state,
    reason,
    stopped_sites: state === "ran"
      ? []
      : [{
          name: `${edge_type}Engine`,
          module: `tradehub/engines/${edge_type.toLowerCase()}_engine.py`,
          site: `tradehub/engines/${edge_type.toLowerCase()}_engine.py:220`,
          edge_type,
          wired_to_a_scanner: true,
          disposition: state === "quarantined" ? "repaired_quarantined" : "unrepaired",
          reason: reason ?? "",
        } as const],
    quarantine_sink: state === "quarantined" ? "kalshi_quarantine_edges" : null,
    opportunities_found: null,
    opportunities_found_reason:
      state === "could_not_run"
        ? "No count, because nothing ran. Not a count of zero."
        : state === "quarantined"
          ? "Counted elsewhere, and withheld here on purpose. See /api/quarantine."
          : "Not counted here.",
  };
}

/**
 * Build a ruling. `stopped` and `quarantined` are separate lists because they are separate facts and
 * this file is the test that they stay separate on the PAGE, not only in the payload.
 */
function health(stopped: string[] = [], quarantined: string[] = []): EngineHealthResponse {
  const entries = ["WEATHER", "MACRO", "SPORTS", "CRYPTO", "ENERGY"].map((t) => {
    const state: EngineState = stopped.includes(t)
      ? "could_not_run"
      : quarantined.includes(t)
        ? "quarantined"
        : "ran";
    return entry(t, state, state === "ran" ? null : WEATHER_REASON);
  });
  const reasons = entries
    .filter((e) => e.state !== "ran")
    .map((e) => e.reason);
  return {
    as_of: "2026-09-28T00:00:00Z",
    edge_types: entries,
    edge_types_total: entries.length,
    edge_types_could_not_run: stopped.length,
    edge_types_quarantined: quarantined.length,
    edge_types_ran: entries.length - stopped.length - quarantined.length,
    // A broken engine outranks a quarantined one for the whole board, on the same terms as the
    // server: the unfiltered view cannot say "measured but withheld" without also saying what was
    // not measured at all.
    board_state: stopped.length > 0 ? "could_not_run" : quarantined.length > 0 ? "quarantined" : "ran",
    board_reason: reasons.length ? reasons.join(" ") : null,
    sites: [],
    sites_total: 0,
    sites_wired: 0,
    sites_unwired: 0,
    sites_repaired: quarantined.length,
    sites_unrepaired: stopped.length,
    note: "An engine on this list either did not run, or had its output quarantined.",
  };
}

const QUARANTINE_STUB = {
  data: null as unknown,
  loading: false,
  error: null as string | null,
};

function stub(over: {
  edges?: unknown[];
  health?: EngineHealthResponse | null;
  healthError?: string | null;
  quarantine?: unknown;
  quarantineError?: string | null;
} = {}) {
  HOOKS.edges = { edges: over.edges ?? [], withheld: [], loading: false, error: null, truncated: false };
  HOOKS.health = { data: over.health === undefined ? health([]) : over.health, loading: false, error: over.healthError ?? null };
  QUARANTINE_STUB.data = over.quarantine ?? null;
  QUARANTINE_STUB.error = over.quarantineError ?? null;
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
    expect(notice.textContent).toContain("weather_engine.py:220");
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

// ── the fourth state: ran, measured, withheld on purpose ───────────────────────────────────

describe("a quarantined engine reads as neither stopped nor quiet", () => {
  it("never prints the quiet sentence for a quarantined engine's tab", () => {
    // The assertion that catches the ruling going straight from "not running" to "quiet" after the
    // repair. The engine measured 295 rows on 2026-09-28 and had them withheld; saying "no
    // high-confidence edges detected" is a confident finding about a scan whose result was never
    // published, which is this page's original defect reached from the other direction.
    stub({ health: health([], ["WEATHER", "MACRO"]) });
    render(<PredictionLab />);
    selectTab("WEATHER");

    expect(screen.queryByText(/No high-confidence edges detected in weather/i)).toBeNull();
    expect(screen.getByText(/Weather is quarantined/i)).toBeTruthy();
  });

  it("never claims the engine is not running, which is false", () => {
    // A reader who believes it goes and tries to fix something that is already fixed.
    stub({ health: health([], ["WEATHER"]) });
    render(<PredictionLab />);
    selectTab("WEATHER");

    expect(screen.queryByText(/Weather is not running/i)).toBeNull();
  });

  it("says on the tab that the board is empty by decision, not by a quiet market", () => {
    // In the HEADLINE, not only in the body. A reader scanning tabs sees the headline, and a finding
    // that lives in the paragraph below it is a finding that gets missed.
    stub({ health: health([], ["WEATHER"]) });
    render(<PredictionLab />);
    selectTab("WEATHER");

    expect(screen.getByText(/empty by decision, not by a quiet market/i)).toBeTruthy();
  });

  it("says the same for the Macro tab", () => {
    stub({ health: health([], ["MACRO"]) });
    render(<PredictionLab />);
    selectTab("MACRO");

    expect(screen.queryByText(/No high-confidence edges detected in macro/i)).toBeNull();
    expect(screen.getByText(/Macro is quarantined/i)).toBeTruthy();
  });

  it("renders a QUARANTINED notice, distinct from the stopped one", () => {
    stub({ health: health([], ["WEATHER", "MACRO"]) });
    render(<PredictionLab />);

    // `stopped-engines` is the testid for a BROKEN engine. A quarantined board must not produce it,
    // or the two states are the same state with a different border colour.
    expect(screen.queryByTestId("stopped-engines")).toBeNull();
    const notice = screen.getByTestId("quarantined-engines");
    expect(notice.textContent).toContain("2 of 5 boards are quarantined");
  });

  it("still renders a stopped notice when one engine is broken and another quarantined", () => {
    // Both, and the broken one wins the frame. A page with one quarantined board and one broken
    // board is in the broken state, and colouring it amber would tell a reader the product is in
    // better shape than it is.
    stub({ health: health(["MACRO"], ["WEATHER"]) });
    render(<PredictionLab />);

    const notice = screen.getByTestId("stopped-engines");
    expect(notice.textContent).toContain("1 of 5 boards are fed by an engine that is not running");
    // The quarantined count is on its own line so a reader cannot read the stopped count as the
    // whole story: "0 of 5 are not working" is the healthy-looking summary this panel exists to stop.
    expect(notice.textContent).toContain("1 of 5 boards are quarantined");
  });

  it("points at the quarantine surface rather than repeating its numbers", () => {
    stub({ health: health([], ["WEATHER"]) });
    render(<PredictionLab />);

    const notice = screen.getByTestId("quarantined-engines");
    expect(notice.textContent).toContain("kalshi_quarantine_edges");
    // A second, worse copy of the count on this panel: a bare row total would throw away the split
    // that makes the number worth having, and would put two counts of one fact on two screens.
    expect(notice.textContent).not.toMatch(/\b295\b/);
  });

  it("keeps a genuinely quiet tab quiet, with a quarantined board elsewhere", () => {
    // The mirror, and the reason the quarantined tests are worth having: a label that fires on
    // everything is a label nobody reads.
    stub({ health: health([], ["WEATHER"]) });
    render(<PredictionLab />);
    selectTab("SPORTS");

    expect(screen.getByText(/No high-confidence edges detected in sports/i)).toBeTruthy();
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
