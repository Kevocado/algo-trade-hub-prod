import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import Cpi from "@/pages/Cpi";
import type { JournalFeed, JournalResponse, JournalScore } from "@/lib/journal";
import { copyWords } from "@/test/copyWords";

function score(over: Partial<JournalScore> = {}): JournalScore {
  return {
    forecaster: "cpi_nowcast", forecaster_version: "cpi-v1", cadence: "monthly", baseline: "market", n_targets: 0,
    n_settled: 0, brier: null, brier_baseline: null, bss: null, reliability: [], murphy: {}, calibration_ready: false,
    gate_status: "SHADOW", gate_reasons: [], computed_at: "2026-10-01T13:00:00+00:00", ...over,
  };
}

function serve(forecasters: JournalScore[], feed: Partial<JournalFeed> = {}) {
  const journal: JournalResponse = {
    as_of: "x", forecasters, headline: { forecasters: forecasters.length, calibrated: 0, frozen_calibrated: 0, settled_calibrated: 0, promoted: 0, market_skill: null },
  };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const body = String(url).includes("/api/journal/feed")
      ? { forecaster: "cpi_nowcast", forecaster_version: "cpi-v1", generated_at: "x", forecasts: [], calibration: [], gate_status: "SHADOW", provisional: true, ...feed }
      : journal;
    return { ok: true, json: async () => body } as Response;
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("/cpi", () => {
  it("shows only the CPI forecasters, plainly named, and says when nothing is locked in", async () => {
    serve([
      score(), score({ forecaster_version: "cpi-core-v1" }), score({ forecaster: "kalshi_implied_cpi", forecaster_version: "v1" }),
      score({ forecaster: "spy_quant", forecaster_version: "spy-wf-v1", cadence: "daily" }),
    ]);
    const { container } = render(<Cpi />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Inflation (CPI)", level: 1 })).toBeTruthy());
    expect(screen.getByRole("heading", { name: "Core inflation (CPI)" })).toBeTruthy();
    expect(screen.queryByText(/S&P/)).toBeNull();
    expect(screen.getByText(/Nothing locked in yet/)).toBeTruthy();
    expect(copyWords(container)).toBeLessThanOrEqual(45);
  });

  it("shows a scored forecast as a number with a verdict, and a missing score as a dash, never zero", async () => {
    serve([score({ n_targets: 30, n_settled: 30, brier: 0.09, brier_baseline: 0.07, bss: -0.2 }),
           score({ forecaster_version: "cpi-core-v1", n_targets: 2 })]);
    render(<Cpi />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Inflation (CPI)", level: 2 })).toBeTruthy());
    expect(screen.getAllByText("Behind").length).toBeGreaterThan(0);
    expect(screen.getByText("-0.20")).toBeTruthy();
  });

  it("says the page is unavailable when the journal cannot be read", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 503, json: async () => ({ detail: "down" }) }) as Response));
    render(<Cpi />);
    await waitFor(() => expect(screen.getByText(/CPI forecasts unavailable: down/)).toBeTruthy());
  });
});