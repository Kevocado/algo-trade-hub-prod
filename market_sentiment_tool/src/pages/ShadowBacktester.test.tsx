import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, within } from "@testing-library/react";

import ShadowBacktester from "@/pages/ShadowBacktester";
import { NO_FIGURE, type ShadowPerformanceResponse } from "@/lib/shadowPerformance";

/**
 * The failed read, and what it is not allowed to print.
 *
 * The owner went to `/shadow` on 2026-09-28 looking for the engine scoreboard and got a red card
 * reading "Shadow API unavailable". That string was the second-worst thing about the page. The
 * first was the twenty cards underneath it: `data?.summary.considered_count ?? 0` and three
 * siblings, so a page that had read a single row was displaying "Considered Trades 0", "Dead Zone
 * 0", "Evaluated 0" and "Series Points 0" as measurements. Those are claims about the crypto
 * engine -- that it considered nothing and sat in no dead zone -- and nobody measured them.
 *
 * So the obligations below, in the order they matter:
 *
 * 1. A failed read with no data prints the reason AND the operator step, and prints no figure at
 *    all. Not one. The strongest form of this test is the one that walks the whole document and
 *    fails on any stray digit.
 * 2. It says why, in the server's own sentence, which names the migration file. The page is not
 *    allowed to paraphrase that mapping -- a second copy is a second place to be wrong.
 * 3. It does not alarm. A migration wait is an amber notice. Red says "nobody knows why".
 * 4. It still tells the visitor they are on the wrong page, and links to the right one, because
 *    they arrived here by typing a name that means something else.
 * 5. A read that came back empty says the read succeeded, and says the absent figures in words.
 *    A dash is a figure; `NO_FIGURE` is not.
 */

/** The sentence `tradehub/api/main.py:246` sends when the table has not been renamed. */
const MIGRATION_SENTENCE =
  "table 'signal_events' is not in the database. Apply " +
  "market_sentiment_tool/supabase/migrations/20260415090000_signal_events_unification.sql " +
  "and redeploy. The database still has crypto_signal_events under its old name.";

function emptyRead(over: Partial<ShadowPerformanceResponse> = {}): ShadowPerformanceResponse {
  return {
    domain: "crypto",
    hours: 24,
    generated_at: "2026-09-28T00:00:00Z",
    thresholds: {},
    // What the server really sends for a window with nothing in it: hit_rate and brier_score are
    // `None` (`tradehub/scripts/shadow_performance.py:312`) and the counts are real zeros.
    summary: {
      evaluated_count: 0,
      considered_count: 0,
      dead_zone_count: 0,
      hit_rate: null,
      brier_score: null,
      virtual_pnl_pct: 0.0,
    },
    freshness: {},
    series: [],
    ...over,
  };
}

function answerWith(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

async function renderPage(response: Response | Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(async () => response));
  await act(async () => {
    render(<ShadowBacktester />);
  });
}

/** Every figure card, as a block of text, so a count can be checked across the whole page. */
function figureText(): string {
  return screen
    .getAllByText(/Considered Trades|Hit Rate|Brier Score|Virtual PnL|Dead Zone/)
    .map((label) => label.parentElement?.textContent ?? "")
    .join(" | ");
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("a read that failed with nothing to show", () => {
  it("says the reason and the operator step, in the server's own words", async () => {
    await renderPage(answerWith(503, { detail: MIGRATION_SENTENCE }));

    // The file. This is the whole point of the state: a human can act on it.
    expect(screen.getByText(/20260415090000_signal_events_unification\.sql/)).toBeInTheDocument();
    // And that it is a step a person takes, not a fault to stare at.
    expect(screen.getByRole("heading", { name: /Waiting on a database migration/i })).toBeInTheDocument();
    expect(screen.getByText(/Only an operator can finish this/i)).toBeInTheDocument();
  });

  it("prints no figure at all, and no figure-shaped zero", async () => {
    await renderPage(answerWith(503, { detail: MIGRATION_SENTENCE }));

    // The old page drew all five summary cards here, with four of them reading 0. None of the
    // cards may be present at all -- a card whose description exists and whose figure is absent is
    // a broken-looking page, and one whose figure is 0 is a lie about the crypto engine.
    for (const label of ["Considered Trades", "Hit Rate", "Brier Score", "Virtual PnL", "Dead Zone"]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
    expect(screen.queryByText("Evaluated")).not.toBeInTheDocument();
    expect(screen.queryByText("Series Points")).not.toBeInTheDocument();
  });

  it("puts no number on the panel but the migration's own timestamp", async () => {
    // The blunt form of the obligation above, and the one that catches a figure the eye misses: a
    // "Series Points 0" buried in a sidebar card, a freshness line reading "0.00h", a hit rate of
    // "0.0%". The one number this panel is allowed to contain is the timestamp inside the
    // migration filename, because naming the file is the entire job of this state. So the
    // assertion is exact rather than "none", which would have hidden a future figure here
    // behind a loosening of the test.
    await renderPage(answerWith(503, { detail: MIGRATION_SENTENCE }));

    const panel = screen.getByRole("heading", { name: /Waiting on a database migration/i })
      .closest("div.rounded-xl") as HTMLElement;
    expect(panel).not.toBeNull();
    expect((panel.textContent ?? "").match(/[0-9]+/g) ?? []).toEqual(["20260415090000"]);
  });

  it("does not alarm: a migration wait is a notice, not a red fault", async () => {
    await renderPage(answerWith(503, { detail: MIGRATION_SENTENCE }));

    expect(screen.queryByText(/API unavailable/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
  });

  it("tells a visitor who wanted the scoreboard where it is", async () => {
    // The collision that sent the owner here, corrected by the page he landed on. Without this the
    // rename alone leaves him with nowhere to go.
    await renderPage(answerWith(503, { detail: MIGRATION_SENTENCE }));

    // One link, and it is the right one: the CANONICAL /scoreboard, not the /shadow-scoreboard
    // alias. The header states the same sentence, so the count of 1 also pins that the failed
    // state does not render the disambiguation twice.
    const link = screen.getByRole("link", { name: /Open the Engine Scoreboard/i });
    expect(link).toHaveAttribute("href", "/scoreboard");
  });

  it("keeps a genuine fault distinguishable from a migration wait", async () => {
    // A 503 that names no migration is not an operator step, and calling it one would send
    // someone to apply a file that is not the problem.
    await renderPage(answerWith(500, { detail: "Upstream connect error" }));

    expect(screen.getByRole("heading", { name: /could not be read/i })).toBeInTheDocument();
    expect(screen.queryByText(/Waiting on a database migration/i)).not.toBeInTheDocument();
  });
});

describe("a read that succeeded and returned nothing", () => {
  it("says the read succeeded, so an empty window is not read as a fault", async () => {
    await renderPage(answerWith(200, emptyRead()));

    expect(screen.getByRole("heading", { name: /Crypto Shadow Timeline/i })).toBeInTheDocument();
    expect(screen.getByText(/The read succeeded and returned no points/i)).toBeInTheDocument();
  });

  it("gives the two absent figures words rather than a dash or a zero", async () => {
    await renderPage(answerWith(200, emptyRead()));

    // `hit_rate` and `brier_score` are None here. A dash is what this page used to print, and a
    // dash in a figure column is a number that reads as zero.
    expect(figureText()).toContain(NO_FIGURE);
    expect(figureText()).not.toContain("—");
    expect(figureText()).not.toMatch(/Hit Rate[^|]*0\.0%/);
  });

  it("keeps the counts the server really computed, including a real zero", async () => {
    await renderPage(answerWith(200, emptyRead()));

    // A zero the server sent IS a measurement -- no signal was considered -- and the rule against
    // a missing figure is not a rule against zero. What may not happen is a zero arriving from a
    // read that did not happen, which is what the first describe block is about.
    const considered = screen.getByText("Considered Trades").closest("div")?.parentElement;
    expect(within(considered as HTMLElement).getByText("0")).toBeInTheDocument();
  });

  it("still says what it is not, on the page that caused the collision", async () => {
    await renderPage(answerWith(200, emptyRead()));

    expect(screen.getByText(/crypto shadow timeline, not the engine scoreboard/i)).toBeInTheDocument();
  });
});
