import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import Journal from "@/pages/Journal";
import type { JournalFeed, JournalResponse, JournalScore } from "@/lib/journal";
import { copyWords } from "@/test/copyWords";

function score(over: Partial<JournalScore> = {}): JournalScore {
  return {
    forecaster: "spy_quant", forecaster_version: "spy-wf-v1", cadence: "daily", baseline: "climatology", n_targets: 2,
    n_settled: 1, brier: 0.311, brier_baseline: 0.2836, bss: -0.0966,
    reliability: [{ bucket: "50-60", n: 1, predicted: 0.558, observed: 0 }], murphy: {}, calibration_ready: false,
    gate_status: "SHADOW", gate_reasons: ["only 1 settled targets, need 200 (daily)"], computed_at: "2026-10-01T13:00:00+00:00", ...over,
  };
}

const waiting = (forecaster: string, version: string, over: Partial<JournalScore> = {}) =>
  score({ forecaster, forecaster_version: version, n_settled: 0, n_targets: 0, brier: null, bss: null, baseline: "none",
          reliability: [], gate_reasons: [], ...over });

const journal: JournalResponse = {
  as_of: "2026-10-01T13:00:00+00:00",
  forecasters: [
    score(),
    score({ forecaster: "sentiment_meter", forecaster_version: "meter-v1", brier: 0.277, bss: 0.0234 }),
    waiting("cpi_nowcast", "cpi-v1", { cadence: "monthly" }),
    waiting("cpi_nowcast", "cpi-core-v1", { cadence: "monthly" }),
    waiting("kalshi_implied_cpi", "v1", { cadence: "monthly" }),
    waiting("housing_direction", "housing-wf-v1", { cadence: "monthly" }),
  ],
  headline: { forecasters: 6, calibrated: 0, settled_calibrated: 0, promoted: 0 },
};

const feed: JournalFeed = {
  forecaster: "spy_quant", forecaster_version: "spy-wf-v1", generated_at: "2026-10-01T13:00:00+00:00",
  forecasts: [{ target: "spx:2026-09-30:up", probability: 0.558, market_prob: null, frozen_at: "2026-09-30T10:17:00+00:00", rebuilt: false, source_hash: "h" }],
  calibration: [], gate_status: "SHADOW", provisional: true,
};

const scoreboard = { as_of: "x", runs_read: 1, engines: 1, rows: [{ engine: "cpi_nowcast", engine_version: "cpi-v1", mode: "taker",
  date_from: "2025-01-01T00:00:00+00:00", date_to: "2026-06-30T00:00:00+00:00", n_decisions: 412, brier_ours: 0.0712, brier_market: 0.0683 }] };

function stubFetch() {
  const fn = vi.fn((url: string) => {
    const body = url.includes("/api/journal/feed") ? feed : url.includes("/api/scoreboard") ? scoreboard : journal;
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("Journal", () => {
  it("leads with three numbers and only the forecasters that have results", async () => {
    stubFetch();
    render(<Journal />);
    const totals = await screen.findByLabelText("Totals");
    expect(within(totals).getByText("forecasts locked in").previousSibling).toHaveTextContent("4");
    expect(within(totals).getByText("scored so far").previousSibling).toHaveTextContent("2");
    expect(within(totals).getByText("promoted").previousSibling).toHaveTextContent("0");
    const results = screen.getByLabelText("Results");
    expect(within(results).getByText("S&P 500 tomorrow: model")).toBeInTheDocument();
    expect(within(results).getByText("-0.10")).toBeInTheDocument();
    expect(within(results).getAllByText("Too early").length).toBe(2);
  });

  it("lists forecasters with nothing scored as short chips, in plain words, with the baseline folded away", async () => {
    stubFetch();
    render(<Journal />);
    const list = await screen.findByLabelText("Waiting");
    expect(within(list).getByText("Inflation (CPI)")).toBeInTheDocument();
    expect(within(list).getByText("Core inflation (CPI)")).toBeInTheDocument();
    expect(within(list).getByText("US home prices")).toBeInTheDocument();
    expect(within(list).queryByText(/kalshi_implied/i)).toBeNull();
  });

  it("opens a forecaster's calibration and locked-in forecasts only on request", async () => {
    stubFetch();
    render(<Journal />);
    fireEvent.click(await screen.findByRole("button", { name: "S&P 500 tomorrow: model" }));
    expect(await screen.findByLabelText("Calibration spy_quant@spy-wf-v1")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("spx:2026-09-30:up")).toBeInTheDocument());
  });

  it("loads past backtests only when asked, and says they are not counted", async () => {
    const fetchFn = stubFetch();
    render(<Journal />);
    await screen.findByLabelText("Totals");
    expect(fetchFn.mock.calls.some(([u]) => String(u).includes("/api/scoreboard"))).toBe(false);
    const summary = screen.getByText("Past backtests (not counted)");
    const details = summary.closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect(await screen.findByText("cpi_nowcast · cpi-v1 · taker")).toBeInTheDocument();
  });

  it("stays inside its word budget", async () => {
    stubFetch();
    const { container } = render(<Journal />);
    await screen.findByLabelText("Totals");
    expect(copyWords(container)).toBeLessThanOrEqual(45);
  });

  it("shows the API's error instead of an empty ledger", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({ detail: "journal_scores is missing: apply 20260428000014" }) })));
    render(<Journal />);
    expect(await screen.findByText(/apply 20260428000014/)).toBeInTheDocument();
  });
});
