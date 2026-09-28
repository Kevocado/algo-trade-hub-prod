import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import CpiDisplay from "@/pages/CpiDisplay";
import type { CpiDisplayResponse, CpiDisplayRow } from "@/lib/cpiDisplay";

/**
 * The four obligations, as they land on the page.
 *
 * The endpoint makes four claims about itself that a page can silently drop, and dropping one
 * reinstates exactly the defect it was added to prevent:
 *
 *   1. `gate_checked: false` -- the gate was NEVER checked. Rendered as a bare "SHADOW" the page
 *      would be saying a gate was consulted and returned a verdict, i.e. that a refuted engine is
 *      PENDING. That is a live opportunity in everything but name.
 *   2. `truncated` -- a bounded read that renders as a complete one is a claim about the data.
 *   3. `withheld_count` / `withheld_reason` -- a row with no market mid, counted over the whole
 *      read, with the reason shown.
 *   4. `comparable` -- and the rule underneath: a figure the response does not carry is rendered as
 *      words, never as 0, 0.0, or a dash standing in for one.
 *
 * Plus a fifth, which is obligation 4's INVERSE and was missed: `default_error_model`. A row whose
 * probability came out of the engine's hardcoded fallback sigma is not missing a figure, so none of
 * the rules above catches it -- it is a DEFAULTED figure, rendered in the exact shape of a measured
 * one. That is the same failure the page exists to prevent, from the other direction.
 */

const row = (extra: Partial<CpiDisplayRow> = {}): CpiDisplayRow => ({
  market_ticker: "KXCPI-26SEP09-3.0",
  our_prob: 0.55,
  market_prob: 0.52,
  edge_pct: null,
  nowcast: 0.39,
  nowcast_obs: "CLEVELAND-2026-09",
  sigma: 0.15,
  n_train: 24,
  default_error_model: false,
  default_error_model_reason: null,
  hours_to_close: 6.5,
  as_of: "2026-09-27T12:00:00+00:00",
  status: "OPEN",
  comparable: true,
  withheld_reason: null,
  gate_status: "SHADOW",
  gate_checked: false,
  ...extra,
});

const payload = (extra: Partial<CpiDisplayResponse> = {}): CpiDisplayResponse => ({
  as_of: "2026-09-27T13:00:00+00:00",
  mode: "display",
  engine: "cpi_nowcast",
  suggest_only: true,
  reason: "Not an edge engine. CPI is shown for context only.",
  edge_pct: null,
  gate_status: "SHADOW",
  gate_checked: false,
  gate_checked_reason: "No gate was consulted and none is expected.",
  row_order: "as_of desc",
  rows: [row()],
  total: 1,
  truncated: false,
  withheld_count: 0,
  limit: 50,
  offset: 0,
  ...extra,
});

function stubFetch(body: unknown, ok = true, status = 200) {
  const spy = vi.fn().mockResolvedValue({
    ok,
    status,
    json: async () => body,
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => vi.unstubAllGlobals());

describe("CpiDisplay", () => {
  it("asks for the display endpoint, scoped and paged", async () => {
    const spy = stubFetch(payload());
    render(<CpiDisplay />);
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(String(spy.mock.calls[0][0])).toContain("/api/cpi-display");
  });

  it("labels the mode in the header rather than leaving the page title to imply a board", async () => {
    stubFetch(payload());
    render(<CpiDisplay />);
    expect(await screen.findByText("mode: display")).toBeTruthy();
    expect(screen.getByText(/display only/i)).toBeTruthy();
    // The heading states it once and the endpoint's `reason` states it again, so the claim is made
    // before the numbers and is not dependent on a reader parsing prose.
    expect(screen.getAllByText(/not an edge engine/i).length).toBeGreaterThan(0);
  });

  it("prints the endpoint's reason above the table, not only inside rows", async () => {
    stubFetch(payload());
    const { container } = render(<CpiDisplay />);
    await screen.findByText("mode: display");
    expect(container.textContent).toContain("Not an edge engine. CPI is shown for context only.");
  });

  it("shows the nowcast in its own units, not as a probability", async () => {
    stubFetch(payload());
    render(<CpiDisplay />);
    // 0.39 is +0.39% month-over-month. Rendered as a probability it reads "39.0%", which
    // overstates the print a hundredfold and still typechecks.
    expect(await screen.findByText("+0.39% MoM")).toBeTruthy();
    expect(screen.queryByText("39.0% MoM")).toBeNull();
  });

  // ── obligation 1: the gate was never checked ───────────────────────────────
  it("says the gate was never checked, and does not render the gate value as a verdict", async () => {
    stubFetch(payload());
    const { container } = render(<CpiDisplay />);

    expect(await screen.findByText(/never checked/i)).toBeTruthy();
    // The three renderings that would turn a refuted engine back into a pending one.
    expect(container.textContent).not.toMatch(/\bSHADOW\b/);
    expect(container.textContent).not.toMatch(/not passed the promotion gate/i);
    expect(container.textContent).not.toMatch(/has not passed .* yet/i);
    // ...and the one thing that makes the distinction real: the API's own reason travels.
    expect(container.textContent).toContain("No gate was consulted and none is expected.");
  });

  it("does not use the shared GateBadge, whose tooltip says 'not passed the gate yet'", async () => {
    // A SHADOW badge is the pending reading, word for word. Reusing it here would undo the whole
    // point of `gate_checked`.
    stubFetch(payload());
    const { container } = render(<CpiDisplay />);
    await screen.findByText(/never checked/i);
    expect(container.textContent).not.toMatch(/tracked, not trade-worthy/i);
  });

  // ── obligation 2: truncation ───────────────────────────────────────────────
  it("says nothing about truncation when the read was complete", async () => {
    stubFetch(payload());
    const { container } = render(<CpiDisplay />);
    await screen.findByText(/never checked/i);
    expect(container.textContent).not.toMatch(/truncat/i);
  });

  it("says the list is truncated when it is, instead of reading as complete", async () => {
    stubFetch(payload({ truncated: true, total: 200, rows: [row()], limit: 1 }));
    render(<CpiDisplay />);

    expect(await screen.findByText(/^Truncated\./)).toBeTruthy();
    expect(screen.getByText(/not the whole set/i)).toBeTruthy();
  });

  it("does not call a truncated total a count", async () => {
    stubFetch(payload({ truncated: true, total: 200 }));
    render(<CpiDisplay />);
    await screen.findByText(/^Truncated\./);
    expect(screen.getByText(/at least 200 rows read/)).toBeTruthy();
  });

  // ── obligation 3: withheld rows and their reasons ───────────────────────────
  it("reports the withheld count over the whole read, not the page", async () => {
    // The withheld row is on page 2. A page-derived count would say "nothing withheld" here.
    stubFetch(payload({ rows: [row()], withheld_count: 1, total: 2, limit: 1, offset: 0 }));
    render(<CpiDisplay />);

    expect(await screen.findByText(/1 of the read has no market mid/)).toBeTruthy();
  });

  it("prints the endpoint's withheld_reason on a row with no market mid", async () => {
    const reason =
      "No market mid was recorded for this release, so there is no market probability to set the " +
      "nowcast against. A missing mid is not a market mid of zero.";
    stubFetch(
      payload({
        rows: [row({ comparable: false, market_prob: null, withheld_reason: reason })],
        withheld_count: 1,
      }),
    );
    render(<CpiDisplay />);

    // The reason is what makes the withheld row a disclosure rather than a blank cell, so it has to
    // be on screen in the endpoint's own words. Matched on content: it is rendered inside the row's
    // " · "-joined note, not as a standalone element.
    await screen.findByText("mode: display");
    expect(document.body.textContent).toContain(reason);
  });

  it("still shows a withheld row rather than dropping it", async () => {
    stubFetch(
      payload({
        rows: [row({ comparable: false, market_prob: null, withheld_reason: "no mid recorded" })],
        withheld_count: 1,
      }),
    );
    render(<CpiDisplay />);

    // An engine that loses stays visible. The row is withheld from the COMPARISON, not the page.
    expect(await screen.findByText("KXCPI-26SEP09-3.0")).toBeTruthy();
    expect(screen.getByText("+0.39% MoM")).toBeTruthy();
  });

  // ── obligation 4: no number the response does not carry ─────────────────────
  it("renders a missing market mid in words, never as 0, 0.0 or a dash standing in for one", async () => {
    stubFetch(
      payload({
        rows: [row({ comparable: false, market_prob: null, withheld_reason: "no mid recorded" })],
        withheld_count: 1,
      }),
    );
    render(<CpiDisplay />);

    expect(await screen.findByText(/no market mid recorded/i)).toBeTruthy();
    // The fabricated value this must never become, in any of its forms.
    expect(screen.queryByText("0.0%")).toBeNull();
    expect(screen.queryByText("0%")).toBeNull();
    expect(screen.queryByText(/^0\.0$/)).toBeNull();
  });

  it("renders a missing model probability in words too", async () => {
    stubFetch(payload({ rows: [row({ our_prob: null })] }));
    render(<CpiDisplay />);
    expect(await screen.findByText(/no model probability was recorded/i)).toBeTruthy();
    expect(screen.queryByText("0.0%")).toBeNull();
  });

  it("renders a genuine zero, because a measured zero is not the same as a missing figure", async () => {
    stubFetch(payload({ rows: [row({ our_prob: 0, market_prob: 0, nowcast: 0 })] }));
    render(<CpiDisplay />);
    await screen.findByText(/never checked/i);
    // 0.0% appears twice (model and market mid) and +0.00% MoM once.
    expect(screen.getAllByText("0.0%")).toHaveLength(2);
    expect(screen.getByText("+0.00% MoM")).toBeTruthy();
  });

  it("shows the row's own timestamp and state, so a settled row cannot read as live", async () => {
    stubFetch(payload({ rows: [row({ status: "SETTLED" })] }));
    render(<CpiDisplay />);
    expect(await screen.findByText("SETTLED")).toBeTruthy();
    // Twice on purpose: the Ledger column and the row's own note, so the state travels with the
    // reasoning rather than only sitting in a column a reader may skip.
    expect(screen.getAllByText(/2026-09-27 12:00Z/).length).toBeGreaterThan(0);
  });

  it("shows no edge figure anywhere, because there is not one", async () => {
    stubFetch(payload());
    const { container } = render(<CpiDisplay />);
    await screen.findByText(/never checked/i);
    expect(container.textContent).not.toMatch(/\d+(\.\d+)?\s*%\s*(edge|pp advantage)/i);
    expect(container.textContent).not.toMatch(/execute trade/i);
  });

  it("states that this product places no orders", async () => {
    stubFetch(payload());
    render(<CpiDisplay />);
    expect(await screen.findByText(/places no orders/i)).toBeTruthy();
  });

  // ── the states a page can get wrong ────────────────────────────────────────
  it("renders an empty ledger as an empty board, and says an empty board is expected", async () => {
    stubFetch(payload({ rows: [], total: 0, withheld_count: 0 }));
    render(<CpiDisplay />);
    expect(await screen.findByText(/between prints is expected/i)).toBeTruthy();
  });

  it("renders a failed read as a failure, never as an empty board", async () => {
    // "Not measured" and "measured, and there is nothing there" are different facts. The endpoint
    // returns a 503 rather than an empty list precisely so the page can keep them apart.
    stubFetch({ detail: "Could not find the table 'public.predictions'" }, false, 503);
    render(<CpiDisplay />);

    expect(await screen.findByText(/unavailable/i)).toBeTruthy();
    expect(screen.getByText(/public\.predictions/)).toBeTruthy();
    expect(screen.queryByText(/between prints is expected/i)).toBeNull();
    expect(screen.queryByText(/No CPI markets in the ledger/i)).toBeNull();
  });

  // ── obligation 5: a DEFAULTED error model is not a fitted one ───────────────
  it("renders n_train, so a sigma is never a number of unknown origin", async () => {
    stubFetch(payload());
    const { container } = render(<CpiDisplay />);
    await screen.findByText("+0.39% MoM");

    expect(container.textContent).toContain("24 pairs");
  });

  it("says the error model is a DEFAULT when the engine used its fallback sigma", async () => {
    // `fit_cpi_error` returns a hardcoded DEFAULT_CPI_ERROR below CPI_MIN_TRAIN pairs, so
    // `our_prob` came out of a constant. This is the INVERSE of the rule the rest of this file
    // enforces -- a figure that was not measured, presented in the shape of one that was -- and it
    // used to be indistinguishable from a fit on the same page.
    const reason =
      "The error model is the default, not a fit: fewer than 12 nowcast/print pairs were " +
      "available, so the 0.15pp sigma is the constant the engine falls back to rather than " +
      "something measured. This row's probability comes from that default.";
    stubFetch(
      payload({
        rows: [
          row({ n_train: 3, sigma: 0.15, default_error_model: true, default_error_model_reason: reason }),
        ],
      }),
    );
    render(<CpiDisplay />);

    expect(await screen.findByText(/default, not fitted · 3 pairs/)).toBeTruthy();
    expect(document.body.textContent).toContain(reason);
  });

  it("does not label a fitted row as a default, even when the fit lands on the default's sigma", async () => {
    // The flag has to come from n_train, not from `sigma === 0.15` -- the default's own value is
    // one a fit can also return, so branching on it would mislabel fitted rows and be a coin flip
    // on the rest.
    stubFetch(payload({ rows: [row({ n_train: 40, sigma: 0.15, default_error_model: false })] }));
    render(<CpiDisplay />);

    // Twice on purpose: the Nowcast cell as a figure, and the row's own note so the provenance
    // travels with the reasoning rather than only sitting in a column a reader may skip.
    expect((await screen.findAllByText(/fitted on 40 pairs/)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/default, not fitted/)).toBeNull();
  });

  it("claims neither a fit nor a default when n_train was not recorded", async () => {
    // Three-valued. An absent count is not evidence that the model was fitted, so the row says the
    // count is unknown rather than defaulting the reader to a conclusion in either direction.
    stubFetch(
      payload({
        rows: [
          row({ n_train: null, default_error_model: null, default_error_model_reason: null }),
        ],
      }),
    );
    render(<CpiDisplay />);

    expect(await screen.findByText(/not recorded/i)).toBeTruthy();
    expect(screen.getByText(/training-set size not recorded/i)).toBeTruthy();
    expect(screen.queryByText(/fitted on/)).toBeNull();
    expect(screen.queryByText(/default, not fitted/)).toBeNull();
  });
});
