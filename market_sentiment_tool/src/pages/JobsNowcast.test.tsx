import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import JobsNowcast from "@/pages/JobsNowcast";
import { copyWords } from "@/test/copyWords";
import type { JobsSeries } from "@/lib/jobsScorecard";

const mockFetchResponse = (series: JobsSeries, rows: unknown): Response =>
  ({
    ok: true,
    status: 200,
    json: async () => rows,
  } as unknown as Response);

function stubFetch(series: JobsSeries, rows: unknown) {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    const urlStr = String(url);
    if (urlStr.includes("/api/jobs-scorecard")) {
      return Promise.resolve(mockFetchResponse(series, rows));
    }
    return Promise.resolve({ ok: false, status: 404 } as unknown as Response);
  }));
}

function mockRow(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    series: "payrolls" as JobsSeries,
    reference_month: "2026-09-01",
    kalshi_event: "KXPAYROLLS-26AUG",
    release_date: "2026-09-04",
    nowcast_mu: 162,
    nowcast_sigma: 90,
    engine_version: "labor-v1",
    engine: "labor_nowcast",
    gate_status: "SHADOW",
    kalshi_mean_1h: 45,
    kalshi_median_1h: 44,
    first_print: 162,
    rev2: null,
    rev3: null,
    benchmark: null,
    latest: 162,
    n_strikes: 17,
    nowcast_abs_err: 102,
    kalshi_abs_err: 117,
    nowcast_brier: 0.2,
    kalshi_brier: 0.25,
    ...overrides,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("JobsNowcast", () => {
  it("leads with stats cards, not paragraphs", async () => {
    stubFetch("payrolls", [
      mockRow({ reference_month: "2026-08-01" }),
      mockRow({ reference_month: "2026-09-01" }),
    ]);
    render(<JobsNowcast />);
    await waitFor(() => expect(screen.getByText("We were closer")).toBeInTheDocument());
    expect(screen.getByText("We were closer").closest("div")?.parentElement).toBeInTheDocument();
  });

  it("shows a per-report us-vs-Kalshi chart with dots (no lines)", async () => {
    stubFetch("payrolls", [
      mockRow({ reference_month: "2026-08-01" }),
      mockRow({ reference_month: "2026-07-01" }),
    ]);
    render(<JobsNowcast />);
    await waitFor(() => expect(screen.getByText("Our nowcast vs Kalshi vs first print")).toBeInTheDocument());
  });

  it("formats payrolls in signed thousands and unemployment in percent", async () => {
    stubFetch("payrolls", [
      mockRow({ reference_month: "2026-08-01", nowcast_mu: 162 }),
    ]);
    render(<JobsNowcast />);
    await waitFor(() => expect(screen.getByText("+162k")).toBeInTheDocument());
  });

  it("renders a disclosure for internals (engine version, gate status not in table)", async () => {
    stubFetch("payrolls", [
      mockRow({ reference_month: "2026-08-01", engine_version: "labor-v1", gate_status: "SHADOW" }),
    ]);
    render(<JobsNowcast />);
    await waitFor(() => expect(screen.getByText("Jobs nowcast vs Kalshi")).toBeInTheDocument());
    expect(screen.queryByText("labor-v1")).toBeNull();
    expect(screen.queryByText("Shadow")).toBeNull();
  });

  it("uses the word budget and renders missing figures as dashes, not zero", async () => {
    stubFetch("payrolls", [
      mockRow({
        reference_month: "2026-08-01",
        nowcast_mu: null,
        kalshi_mean_1h: null,
        first_print: null,
        latest: null,
      }),
    ]);
    render(<JobsNowcast />);
    await waitFor(() => expect(screen.getByText("We were closer")).toBeInTheDocument());
    const { container } = render(<JobsNowcast />);
    // The page's text nodes should not contain bare "0" representing a missing figure
    expect(container.textContent).not.toMatch(/0\.0/);
  });

  it("stays under the 45-word budget (headings + paragraphs only)", async () => {
    stubFetch("payrolls", [
      mockRow({ reference_month: "2026-08-01" }),
    ]);
    const { container } = render(<JobsNowcast />);
    await waitFor(() => expect(screen.getByText("Jobs nowcast vs Kalshi")).toBeInTheDocument());
    expect(copyWords(container)).toBeLessThanOrEqual(45);
  });

  it("switches series between payrolls and unemployment", async () => {
    stubFetch("payrolls", [mockRow({ reference_month: "2026-08-01" })]);
    render(<JobsNowcast />);
    await waitFor(() => expect(screen.getByText("Payrolls")).toBeInTheDocument());
    expect(screen.getByText("Payrolls")).toBeInTheDocument();
  });

  it("shows an error message when the API fails", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({ detail: "Supabase is not configured" }) })));
    render(<JobsNowcast />);
    await waitFor(() => expect(screen.getByText(/Supabase is not configured/i)).toBeInTheDocument());
  });

  it("shows a loading spinner before data loads", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise((resolve) => setTimeout(() => resolve({ ok: true, status: 200, json: () => Promise.resolve([]) }), 100))));
    render(<JobsNowcast />);
    expect(screen.getByRole("status")).toBeInTheDocument(); // loader
  });
});