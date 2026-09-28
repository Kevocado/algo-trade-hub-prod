import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, within } from "@testing-library/react";

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

/** The sentence `tradehub/api/main.py:_missing_table_message` sends when the table has not been renamed. */
const MIGRATION_SENTENCE =
  "table 'signal_events' is not in the database. Apply " +
  "market_sentiment_tool/supabase/migrations/20260415090000_signal_events_unification.sql " +
  "and redeploy. The database still has crypto_signal_events under its old name.";

/**
 * The sentence the same handler sends for a MISSING CREDENTIAL, quoted from
 * `tradehub/api/main.py:_missing_credential_message` with the real arguments
 * (`sp.MissingCredentialError("Alpaca API", ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"))`).
 *
 * This is the 424 PR #43 (`f856fb3`) added, and it is the read every reader will get once
 * `20260415090000` is applied: `vps-stack/compose.yml` passes no `ALPACA_*` to the tradehub service,
 * so the table becomes fine and the credential does not. Quoted rather than retyped so that a
 * change to the server's wording shows up here as a failing test -- which is the point, because the
 * page is not allowed a second copy of an instruction that names a file and two variables.
 */
const CREDENTIAL_SENTENCE =
  "This service has no Alpaca API credentials, so the shadow timeline cannot be read. " +
  "The database is fine -- this is not a migration. " +
  "Set ALPACA_API_KEY and ALPACA_SECRET_KEY in the stack's .env file, beside " +
  "vps-stack/compose.yml. Then add 'ALPACA_API_KEY: ${ALPACA_API_KEY:-}' and " +
  "'ALPACA_SECRET_KEY: ${ALPACA_SECRET_KEY:-}' to the tradehub service's environment: block, " +
  "and redeploy.";

/** What a real bug in the builder produces: a 500, and the one case no operator step closes. */
const BUG_SENTENCE = "unsupported operand type(s) for +: 'int' and 'NoneType'";

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

/**
 * A failed read, as `fetch` really returns one.
 *
 * `headers` is a real part of what a failed read carries and was left out of this mock for a long
 * time, which is precisely why `X-Error-Code` never reached the classifier: the test suite could not
 * have noticed. `get` returns null for an absent header rather than throwing, which is also what the
 * real `Headers.get` does, so a test that omits a header exercises the headerless fallback.
 */
function answerWith(status: number, body: unknown, headers: Record<string, string> = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name: string) => headers[name] ?? null },
    json: async () => body,
  } as unknown as Response;
}

/** The panel the failed read renders, found by its heading so a test never guesses at a selector. */
function panelFor(heading: RegExp): HTMLElement {
  return screen.getByRole("heading", { name: heading }).closest("div.rounded-xl") as HTMLElement;
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

    const panel = panelFor(/Waiting on a database migration/i);
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

/**
 * The half of PR #43 that was left undone: the frontend.
 *
 * The server now tells a missing table, a missing credential and a broken builder apart by status
 * (503 / 424 / 500) and by `X-Error-Code`. This page did not, and so it told all three the same
 * way: `shadowUnavailable` tested the `detail` for `supabase/migrations/`, and a 424 body has no
 * path in it -- it says "this is not a migration" -- so the one state that is a person setting two
 * environment variables rendered as a red "The shadow timeline could not be read". That is the
 * undiagnosable outcome the 424 was introduced to end, and it survived the PR because the client
 * was never changed.
 *
 * The obligations, in the order they matter:
 *
 *  1. 424 is an operator step. Amber, a heading that says what is waiting, and the server's
 *     sentence naming both variables and where they go.
 *  2. 503 is still a migration, byte for byte. There was already a test for it and there still is.
 *  3. 500 is still a fault and still red. Three facts, three presentations; collapsing the third
 *     into either of the first two would be the same defect in the other direction.
 *  4. The classification reads the status and the header. Every test in the last block pairs a
 *     status with prose arguing for the OTHER answer, so a component that went back to matching on
 *     the message fails rather than passing quietly.
 */
describe("a 424: the table is fine and an environment variable is not set", () => {
  const CREDENTIAL_HEADERS = { "X-Error-Code": "missing_credentials" };

  it("renders the operator step, not the fault panel, and names both variables", async () => {
    await renderPage(answerWith(424, { detail: CREDENTIAL_SENTENCE }, CREDENTIAL_HEADERS));

    // The heading says what is being waited on, in the same voice as the migration one, because it
    // is the same kind of fact: a person has a step to take on this deployment.
    expect(
      screen.getByRole("heading", { name: /Waiting on environment variables/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Only an operator can finish this/i)).toBeInTheDocument();

    // Not the fault panel. Not by title, and not by colour: a red frame here is what told a reader
    // the product was broken when the only thing wrong was two unset variables.
    expect(screen.queryByText(/could not be read/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/API unavailable/i)).not.toBeInTheDocument();
    const panel = panelFor(/Waiting on environment variables/i);
    expect(panel.className).toMatch(/amber/);
    expect(panel.className).not.toMatch(/rose/);

    // What is missing and what to do. The two variables, the file to put them in, and the
    // `environment:` block that has to name them too -- `compose.yml` will not pass them through
    // otherwise, and an operator who sets the variables and redeploys would be back here again.
    expect(screen.getByText(/ALPACA_API_KEY/)).toBeInTheDocument();
    expect(screen.getByText(/ALPACA_SECRET_KEY/)).toBeInTheDocument();
    expect(screen.getByText(/vps-stack\/compose\.yml/)).toBeInTheDocument();
    expect(screen.getByText(/environment: block/)).toBeInTheDocument();
  });

  it("says this is not a migration, because applying one would fix nothing", async () => {
    // The server's sentence carries it and so does this. An operator who has just applied
    // 20260415090000 and is still seeing red needs to be told the next step is a different act, and
    // "the database is fine" is the sentence that stops them applying the file they just applied.
    await renderPage(answerWith(424, { detail: CREDENTIAL_SENTENCE }, CREDENTIAL_HEADERS));

    expect(screen.getByText(/database is fine -- this is not a migration/i)).toBeInTheDocument();
    expect(screen.queryByText(/Waiting on a database migration/i)).not.toBeInTheDocument();
  });

  it("prints no figure and no figure-shaped zero, exactly as the migration panel does not", async () => {
    await renderPage(answerWith(424, { detail: CREDENTIAL_SENTENCE }, CREDENTIAL_HEADERS));

    for (const label of ["Considered Trades", "Hit Rate", "Brier Score", "Virtual PnL", "Dead Zone"]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
    // The blunt form. The server's instruction contains no digits, so "no digits anywhere on the
    // panel" is exact and catches a `0.00h` freshness line or a stray `424` printed as a figure.
    expect((panelFor(/Waiting on environment variables/i).textContent ?? "").match(/[0-9]+/g) ?? [])
      .toEqual([]);
  });

  it("still tells a visitor who wanted the scoreboard where it is", async () => {
    // The 503 panel links to /scoreboard and so does this one. The collision is about the page, not
    // about why the read failed.
    await renderPage(answerWith(424, { detail: CREDENTIAL_SENTENCE }, CREDENTIAL_HEADERS));

    const link = screen.getByRole("link", { name: /Open the Engine Scoreboard/i });
    expect(link).toHaveAttribute("href", "/scoreboard");
  });

  it("reads the status alone when the proxy drops the X-Error-Code header", async () => {
    // A gateway that does not forward custom headers is an ordinary thing. The page must not depend
    // on a header surviving the network to know that a 424 is a person setting variables.
    await renderPage(answerWith(424, { detail: CREDENTIAL_SENTENCE }));

    expect(
      screen.getByRole("heading", { name: /Waiting on environment variables/i }),
    ).toBeInTheDocument();
  });
});

describe("the three failed reads, side by side", () => {
  it("gives each status its own heading and its own frame, and collapses no two of them", async () => {
    // All three rendered in one test on purpose. The failure mode here is a COLLAPSE -- two statuses
    // sharing a presentation is exactly what made 503 and 424 indistinguishable before this change,
    // and a test that checks them one at a time would pass on a classifier that had merged them.
    const seen: { heading: string; frame: string; body: string }[] = [];

    for (const [status, detail, code, heading] of [
      [503, MIGRATION_SENTENCE, "missing_table", /Waiting on a database migration/i],
      [424, CREDENTIAL_SENTENCE, "missing_credentials", /Waiting on environment variables/i],
      [500, BUG_SENTENCE, "internal_error", /could not be read/i],
    ] as const) {
      await renderPage(answerWith(status, { detail }, { "X-Error-Code": code }));
      const panel = panelFor(heading);
      seen.push({
        heading: screen.getByRole("heading", { name: heading }).textContent ?? "",
        frame: panel.className,
        body: panel.textContent ?? "",
      });
      cleanup();
    }

    // Three distinct headings, and no heading reused: the reader can tell which step they have.
    expect(new Set(seen.map((panel) => panel.heading)).size).toBe(3);

    // Two amber operator steps and one red fault, and the red one is the 500 alone. A 424 in red
    // is the defect; a 500 in amber would be the same defect pointed the other way, because it
    // would tell a reader an operator step exists for a bug in this code.
    expect(seen[0].frame).toMatch(/amber/);
    expect(seen[0].frame).not.toMatch(/rose/);
    expect(seen[1].frame).toMatch(/amber/);
    expect(seen[1].frame).not.toMatch(/rose/);
    expect(seen[2].frame).toMatch(/rose/);
    expect(seen[2].frame).not.toMatch(/amber/);

    // Each panel carries its own server sentence and nobody else's. A 424 panel that quoted a
    // migration path would send an operator to apply a file, and a 500 panel that quoted a
    // variable name would send one to go and set it.
    expect(seen[0].body).toContain("20260415090000_signal_events_unification.sql");
    expect(seen[0].body).not.toContain("ALPACA");
    expect(seen[1].body).toContain("ALPACA_API_KEY");
    expect(seen[1].body).toContain("ALPACA_SECRET_KEY");
    expect(seen[1].body).not.toContain(".sql");
    expect(seen[2].body).toContain(BUG_SENTENCE);
    expect(seen[2].body).not.toMatch(/ALPACA|\.sql/);
  });

  it("keeps the migration 503 rendering exactly as it did", async () => {
    // Not "still renders a migration notice" but the same notice: the same heading, the same four
    // sentences, and the server's sentence quoted verbatim. This state was correct before this
    // change and had a test; the only way to be sure it survived is to assert all of it.
    await renderPage(
      answerWith(503, { detail: MIGRATION_SENTENCE }, { "X-Error-Code": "missing_table" }),
    );

    expect(screen.getByRole("heading", { name: /Waiting on a database migration/i })).toBeInTheDocument();
    expect(screen.getByText(/Only an operator can finish this/i)).toBeInTheDocument();
    expect(screen.getByText(MIGRATION_SENTENCE)).toBeInTheDocument();
    expect(screen.queryByText(/could not be read/i)).not.toBeInTheDocument();
  });

  it("keeps a 500 rendering as a fault, in red, and not as a step anyone can take", async () => {
    await renderPage(answerWith(500, { detail: BUG_SENTENCE }, { "X-Error-Code": "internal_error" }));

    expect(screen.getByRole("heading", { name: /could not be read/i })).toBeInTheDocument();
    const panel = panelFor(/could not be read/i);
    expect(panel.className).toMatch(/rose/);
    expect(panel.className).not.toMatch(/amber/);
    // The exception text and nothing that sends an operator off to apply a file or set a variable.
    expect(panel.textContent).toContain(BUG_SENTENCE);
    expect(panel.textContent).not.toMatch(/ALPACA/);
    expect(panel.textContent).not.toMatch(/\.sql/);
  });
});

/**
 * The obligation that keeps PR #43 from being undone on the client: `detail` is OUTPUT.
 *
 * Every test here pairs a status with prose that argues for the OTHER classification. A neutral
 * detail would pass under both a status-based classifier and a prose-based one, so these pairings
 * are the whole test: a `ShadowBacktester` that went back to matching on the message text fails all
 * of them. The mutation notes in the report are the proof these have been seen to fail.
 */
describe("the page classifies on the status, not on the message", () => {
  it("calls a 424 an operator step when its detail names nothing but a dependency", async () => {
    // A prose matcher finds no variable name here and reports a fault. The status says 424, and
    // 424 on this endpoint means one thing.
    await renderPage(
      answerWith(424, { detail: "upstream dependency did not answer" }, { "X-Error-Code": "missing_credentials" }),
    );

    expect(
      screen.getByRole("heading", { name: /Waiting on environment variables/i }),
    ).toBeInTheDocument();
  });

  it("keeps a 500 a fault when its detail is the credential sentence word for word", async () => {
    // The sharpest of these, and the exact defect PR #43 described: a 500 whose body says "Missing
    // Alpaca API credentials" sent a reader to set environment variables when the code was broken.
    // Same sentence, status 424 above renders an operator step and status 500 here renders a fault.
    await renderPage(
      answerWith(500, { detail: CREDENTIAL_SENTENCE }, { "X-Error-Code": "internal_error" }),
    );

    expect(screen.getByRole("heading", { name: /could not be read/i })).toBeInTheDocument();
    expect(screen.queryByText(/Waiting on environment variables/i)).not.toBeInTheDocument();
  });

  it("keeps a 500 a fault when its detail is the migration sentence word for word", async () => {
    await renderPage(answerWith(500, { detail: MIGRATION_SENTENCE }));

    expect(screen.getByRole("heading", { name: /could not be read/i })).toBeInTheDocument();
    expect(screen.queryByText(/Waiting on a database migration/i)).not.toBeInTheDocument();
  });

  it("calls a 424 an operator step when its detail names a migration", async () => {
    // The status beats the prose in the other direction as well. A 424 whose body happens to carry
    // a migration path is still a credential problem, and "apply this file" is a step that will not
    // fix it -- which is how an operator ends up applying migrations twice.
    await renderPage(
      answerWith(424, { detail: MIGRATION_SENTENCE }, { "X-Error-Code": "missing_credentials" }),
    );

    expect(
      screen.getByRole("heading", { name: /Waiting on environment variables/i }),
    ).toBeInTheDocument();
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
