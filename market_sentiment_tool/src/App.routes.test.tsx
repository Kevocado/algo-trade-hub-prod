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
 * The `/shadow-scoreboard`, `/models` and `/shadow` routes are load-bearing, so they are pinned.
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
 * path="/shadow-scoreboard" element={<Scoreboard />} />` to render anything, and a duplicated route
 * table passes when the real one loses a route -- which is exactly the deletion this file exists
 * to catch. So the real `BrowserRouter` is used and the path is set on the history before render,
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
});

describe("the sidebar link and the route agree", () => {
  it("resolves /shadow-scoreboard to the engine scoreboard", async () => {
    await renderAppAt("/shadow-scoreboard");

    // The h1 is rendered only once the read resolves, so this is the page and not its loading shell.
    expect(screen.getByRole("heading", { name: "Engine scoreboard", level: 1 })).toBeInTheDocument();
    // And the link that gets a reader there is present, and points at that same path. The label
    // matters as much as the href: the owner approved this page as "the shadow scoreboard", and a
    // nav list reading "Scoreboard" is what made "Shadow" mean this page to him and sent him to
    // /shadow instead.
    const link = screen.getByRole("link", { name: /shadow scoreboard/i });
    expect(link).toHaveAttribute("href", "/shadow-scoreboard");
  });

  it("still resolves the old /scoreboard path, to the same page", async () => {
    // The permanent redirect. A rename with no redirect 404s every bookmark and every link the
    // moment the owner makes one, and this is the cheap moment to add the redirect.
    await renderAppAt("/scoreboard");

    expect(heading()).toBeInTheDocument();
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
    expect(screen.getByRole("link", { name: /shadow scoreboard/i })).toBeInTheDocument();
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

    expect(screen.getByRole("link", { name: /open the shadow scoreboard/i })).toHaveAttribute(
      "href",
      "/shadow-scoreboard",
    );
  });

  it("renders neither page on a path with no route", async () => {
    await renderAppAt("/no-such-route");

    expect(cryptoHeading()).toBeNull();
    expect(heading()).toBeNull();
    expect(screen.getByRole("link", { name: /crypto shadow/i })).toBeInTheDocument();
  });
});
