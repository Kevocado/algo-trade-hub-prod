import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Home from "@/pages/Home";
import type { Standings } from "@/lib/homeTruth";

const BEATS: Standings = {
  best: {
    forecaster: "gas",
    version: "gas-v2",
    baseline: "market",
    cadence: "daily",
    gap: -0.03,
    se: 0.005,
    n: 760,
    n_settled: 1982,
    bss: 0.045,
    verdict: "beats",
    date_from: "2026-06-01",
    date_to: "2026-09-20",
  },
  worst: {
    forecaster: "ercot_peak",
    version: "v1",
    baseline: "climatology",
    cadence: "daily",
    gap: 0.02,
    se: 0.004,
    n: 500,
    n_settled: 300,
    bss: -0.01,
    verdict: "loses to",
    date_from: "2026-06-01",
    date_to: "2026-09-20",
  },
  n_settled: 2282,
  n_replayed: 2,
  forecasters: 9,
  market_linked: ["gas"],
  distinct_se: 2,
  verdict: "gas beats the Kalshi price by -0.030 ± 0.005 over 760 replayed sessions.",
};

const NO_SIGNAL: Standings = {
  ...BEATS,
  best: { ...BEATS.best!, gap: -0.01, se: 0.009, verdict: "indistinguishable" },
  worst: { ...BEATS.worst!, gap: 0.01, se: 0.009, verdict: "indistinguishable" },
  verdict:
    "No forecaster beats the Kalshi price after costs. Best is AAA gasoline prices at -0.010 ± 0.009 over 760 replayed sessions, inside the noise.",
};

const EMPTY: Standings = {
  best: null,
  worst: null,
  n_settled: 0,
  n_replayed: 0,
  forecasters: 0,
  market_linked: [],
  distinct_se: 2,
  verdict: "No forecaster has settled results yet, so there is nothing to compare against the Kalshi price.",
};

function mockJournal(standings: Standings | null) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: async () => ({ status: "ok", forecasters: [], headline: {}, standings }),
  });
}

const renderHome = () =>
  render(
    <MemoryRouter>
      <Home />
    </MemoryRouter>,
  );

describe("front page", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("leads with the server's verdict sentence and the headline numbers", async () => {
    vi.stubGlobal("fetch", mockJournal(BEATS));
    renderHome();
    await waitFor(() => expect(screen.getByText(/gas beats the Kalshi price/)).toBeTruthy());
    expect(screen.getByText("2282")).toBeTruthy(); // settled
    expect(screen.getByText("9")).toBeTruthy(); // forecasters
    expect(screen.getAllByText("AAA gasoline prices").length).toBe(2); // stat card and leaderboard row
    // The gap travels with its interval, on the page, in the same figure.
    expect(screen.getAllByText(/−0\.030 ± 0\.005/).length).toBeGreaterThan(0);
  });

  it("renders the honest common case as no signal, not as a win", async () => {
    vi.stubGlobal("fetch", mockJournal(NO_SIGNAL));
    renderHome();
    await waitFor(() => expect(screen.getByText(/No forecaster beats the Kalshi price/)).toBeTruthy());
    expect(screen.getAllByText("No signal").length).toBe(2);
    expect(screen.queryByText("Beats")).toBeNull();
  });

  it("renders dashes rather than zeroes when nothing has been measured", async () => {
    vi.stubGlobal("fetch", mockJournal(EMPTY));
    renderHome();
    await waitFor(() => expect(screen.getByText(/No forecaster has settled results/)).toBeTruthy());
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2); // best and worst names
    // No "Best"/"Worst" rows at all, because there is no measurement to put in them.
    expect(screen.queryByText("Both ends of the leaderboard")).toBeNull();
  });

  it("states the bar a gap has to clear, so a small number is not read as a result", async () => {
    vi.stubGlobal("fetch", mockJournal(NO_SIGNAL));
    renderHome();
    await waitFor(() => expect(screen.getByText(/clears 2 standard errors/)).toBeTruthy());
  });

  it("links only to pages that exist", async () => {
    vi.stubGlobal("fetch", mockJournal(BEATS));
    renderHome();
    await waitFor(() => expect(screen.getByText("Go deeper")).toBeTruthy());
    for (const path of ["/journal", "/models", "/sports", "/health"]) {
      expect(screen.getByText("Go deeper").closest("section")?.querySelector(`a[href="${path}"]`)).toBeTruthy();
    }
    expect(document.querySelector('a[href="/weather"]')).toBeNull();
  });

  it("reports an absent standings payload as an error, not an empty page", async () => {
    vi.stubGlobal("fetch", mockJournal(null));
    renderHome();
    await waitFor(() => expect(screen.getByText(/has no journal standings/)).toBeTruthy());
  });

  it("reports the status when a non-JSON response comes back", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        headers: { get: () => "text/html" },
        json: async () => ({}),
      }),
    );
    renderHome();
    await waitFor(() => expect(screen.getByText(/status 503/)).toBeTruthy());
  });
});