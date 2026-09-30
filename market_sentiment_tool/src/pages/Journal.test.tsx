import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import Journal from "@/pages/Journal";
import type { JournalFeed, JournalResponse, JournalScore } from "@/lib/journal";

vi.mock("@/hooks/useQuarantine", () => ({ useQuarantine: () => ({ data: null, loading: false, error: null }) }));

function score(over: Partial<JournalScore> = {}): JournalScore {
  return {
    forecaster: "cpi_nowcast",
    forecaster_version: "cpi-v1",
    cadence: "monthly",
    baseline: "market",
    n_targets: 12,
    n_settled: 10,
    brier: 0.0712,
    brier_baseline: 0.0683,
    bss: -0.0425,
    reliability: [{ bucket: "60-70", n: 10, predicted: 0.65, observed: 0.5 }],
    murphy: {},
    calibration_ready: false,
    gate_status: "SHADOW",
    gate_reasons: ["only 10 settled targets, need 50 (monthly)"],
    computed_at: "2026-10-01T13:00:00+00:00",
    ...over,
  };
}

const journal: JournalResponse = {
  as_of: "2026-10-01T13:00:00+00:00",
  forecasters: [
    score(),
    score({ forecaster: "kalshi_implied_cpi", forecaster_version: "v1", brier: 0.0683, bss: 0 }),
    score({ forecaster: "fomc_mapped", forecaster_version: "fomc-mapped-v1", cadence: "meeting", brier: null,
            bss: null, n_settled: 0, reliability: [], gate_reasons: ["no baseline to compare against"] }),
  ],
  headline: { forecasters: 3, calibrated: 0, settled_calibrated: 0, promoted: 0 },
};

const feed: JournalFeed = {
  forecaster: "cpi_nowcast",
  forecaster_version: "cpi-v1",
  generated_at: "2026-10-01T13:00:00+00:00",
  forecasts: [{ target: "kalshi:KXCPI-26SEP-T0.3", probability: 0.52, market_prob: null,
                frozen_at: "2026-10-14T12:05:00+00:00", rebuilt: false, source_hash: "h" }],
  calibration: [],
  gate_status: "SHADOW",
  provisional: true,
};

function stubFetch() {
  const fn = vi.fn((url: string) => {
    const body = url.includes("/api/journal/feed") ? feed : journal;
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("Journal", () => {
  it("renders the server headline and a losing forecaster as losing, beside its market", async () => {
    stubFetch();
    render(<Journal />);
    expect(await screen.findByLabelText("Headline")).toHaveTextContent("0 of 3 forecasters calibrated");
    const tile = screen.getByText("cpi_nowcast@cpi-v1").closest("article")!;
    expect(within(tile).getByText("Brier skill -0.043 vs the Kalshi market")).toBeInTheDocument();
    expect(within(tile).getByText("Kalshi-implied (kalshi_implied_cpi@v1)")).toBeInTheDocument();
    expect(within(tile).getByText("provisional")).toBeInTheDocument();
    expect(within(tile).getAllByText(/^After fees and spread: no quoted prices recorded yet/).length).toBeGreaterThan(0);
    expect(within(tile).getByText("only 10 settled targets, need 50 (monthly)")).toBeInTheDocument();
    expect(within(tile).getByText(/overconfident by 15.0pp/)).toBeInTheDocument();
  });

  it("says unscored in words and labels the FOMC model experimental", async () => {
    stubFetch();
    render(<Journal />);
    const tile = (await screen.findByText("fomc_mapped@fomc-mapped-v1")).closest("article")!;
    expect(within(tile).getByText("experimental")).toBeInTheDocument();
    expect(within(tile).getByLabelText("Brier fomc_mapped@fomc-mapped-v1")).toHaveTextContent("not scored yet");
    expect(within(tile).queryByText("0.0000")).toBeNull();
  });

  it("loads a forecaster's frozen forecasts on demand and never shows a missing price as a number", async () => {
    const fetchFn = stubFetch();
    render(<Journal />);
    const tile = (await screen.findByText("cpi_nowcast@cpi-v1")).closest("article")!;
    fireEvent.click(within(tile).getByText("Show frozen forecasts"));
    await waitFor(() => expect(within(tile).getByText("kalshi:KXCPI-26SEP-T0.3")).toBeInTheDocument());
    expect(within(tile).getByText("no market price")).toBeInTheDocument();
    expect(fetchFn.mock.calls.some(([u]) => String(u).includes("forecaster=cpi_nowcast&version=cpi-v1"))).toBe(true);
  });

  it("shows the API's error instead of an empty ledger", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({
      ok: false, status: 503, json: () => Promise.resolve({ detail: "journal_scores is missing: apply 20260428000014" }),
    })));
    render(<Journal />);
    expect(await screen.findByText(/apply 20260428000014/)).toBeInTheDocument();
  });
});
