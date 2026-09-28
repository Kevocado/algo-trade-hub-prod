import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";

import App from "@/App";
import type { ModelsResponse } from "@/lib/models";
import type { ShadowPerformanceResponse } from "@/lib/shadowPerformance";

// `src/lib/supabase.ts` builds a real client at import time and THROWS when the publishable key is
// absent, so importing `App` -- which pulls in `Home` and `PredictionLab` -> `useMarketEdges` --
// fails before a single assertion runs. The stub is a stand-in for a credential this test does not
// need: neither route rendered here reads a Supabase table directly (the API does), so nothing
// calls it. Setting a fake URL instead would be worse: it would let a test that means to prove
// reachability quietly exercise a real network path.
vi.mock("@/lib/supabase", () => ({ supabase: {} }));

/**
 * A mount counter for the Scoreboard component, so a redirect loop is observable.
 *
 * A `Navigate` that points at itself renders the page over and over, and in jsdom that does not
 * throw and does not fail an assertion -- it just never settles, which reads as a passing test with
 * a slightly odd warning. Counting mounts turns "it settles" into something assertable: `<Navigate>`
 * replaces itself in the tree, so a correct redirect renders Scoreboard exactly once, and a loop
 * renders it many times.
 *
 * The mock wraps the real component rather than replacing it, so the heading this file asserts on
 * is still the real page's, and `App.tsx`'s route table is still the only one in play.
 */
let scoreboardRenders = 0;
vi.mock("@/pages/Scoreboard", async () => {
  const actual = await vi.importActual<typeof import("@/pages/Scoreboard")>("@/pages/Scoreboard");
  const Counting = (props: Record<string, unknown>) => {
    scoreboardRenders += 1;
    return <actual.default {...props} />;
  };
  return { ...actual, default: Counting };
});

/**
 * The `/scoreboard`, `/models` and `/shadow` routes are load-bearing, so they are pinned.
 *
 * These pages are unreachability-sensitive. `/models` exists because the owner of the product
 * could not work out what the site was for, and a page nobody can reach does not answer that for
 * anybody. The other two are the pair that collided on 2026-09-28, when a visitor went to `/shadow`
 * for the scoreboard and got a 503 from a crypto backtester instead. For those two, "it renders"
 * is not the same claim as "it is reachable at the name a person would type", so the nav label and
 * the href are asserted together with the route. All three still exist, still import, still pass
 * their own tests, and are simply never seen if their route is deleted — and nothing else in this
 * suite renders `App`.
 *
 * The route table is NOT re-declared here. A `MemoryRouter` test would have to repeat `<Route
 * path="/scoreboard" element={<Scoreboard />} />` to render anything, and a duplicated route table
 * passes when the real one loses a route -- which is exactly the deletion this file exists to
 * catch. So the real `BrowserRouter` is used and the path is set on the history before render,
 * which makes the only route table in play `App.tsx`'s own.
 */
const EMPTY_BOARD: ModelsResponse = {
  as_of: "2026-09-27T00:00:00+00:00",
  runs_read: 0,
  rows: [],
  engines: 0,
  promotion_lookup_failed: false,
  rows_total: 0,
  rows_behind_market: 0,
  rows_ahead_of_market: 0,
  rows_level_with_market: 0,
  rows_not_comparable: 0,
  any_beats_market: false,
  headline: "No backtest runs are recorded yet, so no engine has a record to show.",
  headline_kind: "no_runs",
  caveat: null,
  // Every engine the product has, and none of them measured. A board with no catalogue at all would
  // render the "the catalogue came back empty" notice, which is a different page and would make
  // this assertion about the wrong thing.
  catalogue: {
    engines_total: 1,
    engines_measured: 0,
    engines_not_measured: 1,
    engines_unlisted: 0,
    entries: [
      {
        engine: "gas",
        label: "Gasoline — AAA US average, day over day",
        claim: "Whether the AAA US average gasoline price will finish the day above or below a strike.",
        claim_note: "",
        in_catalogue: true,
        cadence: "daily",
        measured: false,
        measured_rows: 0,
        status: "not_measured",
        worst_brier_ratio: null,
        rows: [],
      },
    ],
  },
};

function heading(): HTMLElement | null {
  return screen.queryByRole("heading", { name: "Engine scoreboard", level: 1 });
}

/** The crypto page's h1. A separate query so the shadow describe can assert its absence without
 *  caring what the scoreboard is called. */
function cryptoHeading(): HTMLElement | null {
  return screen.queryByRole("heading", { name: /Crypto Shadow Timeline/i, level: 1 });
}

/** A read that succeeded and found nothing, which is what `/api/shadow-performance` sends whenever
 *  the table is readable but the window is empty. */
const EMPTY_SHADOW: ShadowPerformanceResponse = {
  domain: "crypto",
  hours: 24,
  generated_at: "2026-09-28T00:00:00Z",
  thresholds: {},
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
};

/** Only `/api/scoreboard` matters here. The sidebar's book read is stubbed too, because `App` mounts
 * it on every route and an unstubbed read would be a real network call from a unit test. */
function stubApi() {
  const answers: Record<string, unknown> = {
    "/api/scoreboard": EMPTY_BOARD,
    "/api/shadow-performance": EMPTY_SHADOW,
    "/api/pnl_summary": { total_pnl_cents: 0, suggest_only: true },
    "/api/positions": [],
  };
  const spy = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const key = Object.keys(answers).find((path) => url.includes(path));
    return { ok: true, status: 200, json: async () => answers[key ?? ""] ?? {} } as Response;
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

/** Render on a settled tree: every stubbed read resolves inside `act`, so nothing lands after the
 * assertions (which would be React's act() warning, and a flake waiting for a slower machine). */
async function renderAppAt(path: string) {
  stubApi();
  window.history.pushState({}, "", path);
  await act(async () => {
    render(<App />);
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.history.pushState({}, "", "/");
  // Reset the redirect-loop counter between tests. Without this, an earlier test's mount count
  // would be carried into a later `toBe(1)` and the guard would stop guarding.
  scoreboardRenders = 0;
});

describe("the sidebar link and the route agree", () => {
  it("resolves /scoreboard to the engine scoreboard", async () => {
    await renderAppAt("/scoreboard");

    // The h1 is rendered only once the read resolves, so this is the page and not its loading shell.
    expect(heading()).toBeInTheDocument();
    // And the link that gets a reader there is present, and points at that same path.
    expect(screen.getByRole("link", { name: /engine scoreboard/i })).toHaveAttribute(
      "href",
      "/scoreboard",
    );
  });

  it("resolves /models to the models page", async () => {
    // The page that answers "what are the models and what are they doing". A page nobody can
    // reach answers it for nobody, and it would keep passing its own nineteen tests after the
    // route was deleted -- so the route and the nav entry are pinned together here.
    await renderAppAt("/models");

    expect(screen.getByRole("heading", { name: "Models", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /models/i })).toHaveAttribute("href", "/models");
  });

  it("renders no models page on a path with no route", async () => {
    // The control. Without it the test above would also pass if the page rendered unconditionally
    // -- a bug the deletion it guards against and a missing guard both look like.
    await renderAppAt("/no-such-route");

    expect(screen.queryByRole("heading", { name: "Models", level: 1 })).not.toBeInTheDocument();
    // The shell still renders, so the absence is the route's doing and not a crashed tree.
    expect(screen.getByRole("link", { name: /models/i })).toBeInTheDocument();
  });

  it("renders no scoreboard on a path with no route", async () => {
    // The control. Without it, the test above would also pass if the page were rendered
    // unconditionally -- a bug the deletion it guards against and a missing guard both look like.
    await renderAppAt("/no-such-route");

    expect(heading()).toBeNull();
    // The shell still renders, so the absence is the route's doing and not a crashed tree.
    expect(screen.getByRole("link", { name: /engine scoreboard/i })).toBeInTheDocument();
  });
});

/**
 * `/shadow-scoreboard` is a redirect, not a second route for the same component.
 *
 * This is the interesting failure in the whole change, and it is invisible from the page. A
 * `Navigate` that points at its own path, or at a path that redirects back to it, produces a
 * redirect loop: the router navigates forever and the reader sees a blank shell, while every other
 * assertion in this file still passes because the sidebar renders. So three things are checked,
 * and the middle one is the one that catches it:
 *
 *   1. The redirect LANDS ON THE CANONICAL COMPONENT -- the h1 is on screen. A redirect that
 *      renders nothing would otherwise satisfy "the path changed" and pass.
 *   2. The final path is `/scoreboard`. A loop does not settle here, and a redirect to some third
 *      path would also fail.
 *   3. The Scoreboard component is rendered ONCE. `<Navigate>` swaps itself out of the tree rather
 *      than nesting, so a correct redirect never re-enters; a loop renders it over and over. The
 *      spy is what makes that observable, because a loop in a jsdom test does not throw -- it just
 *      stops settling.
 *
 * The spy is on the MODULE, not on a re-declared route. `App.tsx`'s own route table is still the
 * only one in play; the mock replaces the component it points at, not the routing.
 */
describe("the /shadow-scoreboard redirect lands on the canonical route", () => {
  it("renders the engine scoreboard itself, not a blank shell", async () => {
    await renderAppAt("/shadow-scoreboard");

    // The load-bearing assertion. A redirect to a path with no route, or to a route whose element
    // is another redirect, renders nothing here and this fails.
    expect(heading()).toBeInTheDocument();
  });

  it("settles on /scoreboard rather than re-entering itself", async () => {
    await renderAppAt("/shadow-scoreboard");

    expect(window.location.pathname).toBe("/scoreboard");
    // And the loop guard: a self-referential Navigate would keep remounting this component.
    expect(scoreboardRenders).toBe(1);
  });

  it("is a redirect and not a second route serving the same component", async () => {
    // The duplication risk, pinned. Two `<Route>`s both pointing at `<Scoreboard />` would make
    // both paths render the page, which is the ambiguity this rename exists to remove -- and it
    // would be invisible to every other test here. What distinguishes them: at the alias the
    // Scoreboard is NOT what the route table selected; the router swapped in a Navigate and then
    // routed again. So exactly one Scoreboard render, and the path has moved on.
    await renderAppAt("/shadow-scoreboard");

    expect(scoreboardRenders).toBe(1);
    expect(heading()).toBeInTheDocument();
  });
});

/**
 * The collision, pinned at both ends.
 *
 * `/shadow` sent a visitor to the wrong page on 2026-09-28, and it did so for two reasons that a
 * test of the page alone cannot see: the route was reachable and looked like a scoreboard, and the
 * nav entry beside it was labelled with the word the scoreboard was known by. So both are asserted
 * here, and so is the thing that must NOT be true -- that `/shadow` renders the scoreboard. A
 * redirect from one to the other would pass every other test in this file while quietly replacing
 * a crypto backtester with an engine scoreboard, and that is the one substitution this product
 * keeps refusing to make quietly.
 */
describe("the two pages that share the word 'shadow'", () => {
  it("resolves /shadow to the crypto timeline, not to the scoreboard", async () => {
    await renderAppAt("/shadow");

    expect(cryptoHeading()).toBeInTheDocument();
    expect(heading()).toBeNull();
  });

  it("labels the /shadow nav entry with its domain, so 'Shadow' alone names nothing", async () => {
    // The nav entry used to read plain "Shadow", directly above "Scoreboard". That is the sentence
    // a reader parses as two halves of one thing. Asserted on the /shadow route rather than on "/"
    // because the sidebar mounts on every route and "/" additionally mounts Home, which opens a
    // realtime Supabase channel this file's stub is not a client for.
    await renderAppAt("/shadow");

    const link = screen.getByRole("link", { name: /crypto shadow/i });
    expect(link).toHaveAttribute("href", "/shadow");
    // And nothing in the nav is called plain "Shadow" any more, which is the claim itself.
    expect(screen.queryByRole("link", { name: /^shadow$/i })).not.toBeInTheDocument();
  });

  it("sends a visitor who lands on /shadow to the scoreboard, on the page itself", async () => {
    // The collision's other half, and the part a rename cannot do. The owner already has the wrong
    // page open, and the read here is the one thing most likely to be broken, so the correction
    // has to be in this page's own header rather than only in the nav he has to go looking for.
    await renderAppAt("/shadow");

    expect(screen.getByRole("link", { name: /open the engine scoreboard/i })).toHaveAttribute(
      "href",
      "/scoreboard",
    );
  });

  it("renders neither page on a path with no route", async () => {
    await renderAppAt("/no-such-route");

    expect(cryptoHeading()).toBeNull();
    expect(heading()).toBeNull();
    expect(screen.getByRole("link", { name: /crypto shadow/i })).toBeInTheDocument();
  });
});
