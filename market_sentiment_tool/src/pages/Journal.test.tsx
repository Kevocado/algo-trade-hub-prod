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

// The real 2026-10-02 replay rows, trimmed to the fields the table reads. `by_year` is not invented:
// gold's pooled skill is positive while its most recent year is clearly negative, and a reader shown
// only the pooled number cannot see that. `brier_diff`/`brier_diff_se` are the gap between our squared
// error and the climatology's on the same session, with the standard error of that gap: -0.000119 against
// an SE of 0.0022 is 0.05 standard errors, which is the whole reason the interval is printed at all.
const backtests = { as_of: "x", counted: false, backtests: [
  { forecaster: "gold_direction", forecaster_version: "gold-wf-v1", date_from: "2023-10-02",
    date_to: "2026-10-01", n: 753, bss: 0.000482, brier: 0.246852, brier_baseline: 0.246971,
    brier_diff: -0.000119, brier_diff_se: 0.0022,
    by_year: { "2023": { n: 63, bss: 0.003971 }, "2024": { n: 252, bss: 0.003995 },
               "2025": { n: 250, bss: 0.010636 }, "2026": { n: 188, bss: -0.018619 } },
    created_at: "2026-10-02T15:00:56.328768+00:00" },
  { forecaster: "eurusd_direction", forecaster_version: "eurusd-wf-v1", date_from: "2023-10-02",
    date_to: "2026-10-01", n: 766, bss: 0.000557, brier: 0.249885, brier_baseline: 0.250024,
    brier_diff: -0.000139, brier_diff_se: 0.0021,
    by_year: { "2023": { n: 63, bss: -0.008608 }, "2024": { n: 256, bss: -0.002479 },
               "2025": { n: 255, bss: -0.004821 }, "2026": { n: 192, bss: 0.014861 } },
    created_at: "2026-10-02T15:00:56.328768+00:00" },
] };

function stubFetch(replays: unknown = backtests) {
  const fn = vi.fn((url: string) => {
    const body = url.includes("/api/journal/feed") ? feed : url.includes("/api/scoreboard") ? scoreboard
      : url.includes("/api/journal/backtests") ? replays : journal;
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
    const replay = await screen.findByLabelText("Daily models replayed over history");
    expect(within(replay).getByText("Gold tomorrow")).toBeInTheDocument();
    expect(within(replay).getByText("753")).toBeInTheDocument();
  });

  it("never renders a skill as a signed bare zero, however small", async () => {
    // Gold's live pooled skill is +0.000482. `toFixed(3)` renders that "+0.000", which reads as
    // exactly zero skill when the number is positive and measured -- the same thing `skillText` on
    // /journal refuses to do for null. And a small negative would render "-0.000".
    stubFetch();
    render(<Journal />);
    await screen.findByLabelText("Totals");
    const summary = screen.getByText("Past backtests (not counted)");
    const details = summary.closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    const replay = await screen.findByLabelText("Daily models replayed over history");
    // Every signed figure the table prints, pooled and per-year: none may be a bare zero.
    const cells = [...replay.querySelectorAll("td")].map((td) => td.textContent ?? "");
    const signed = cells.flatMap((c) => c.match(/[+-]\d+\.\d+/g) ?? []);
    expect(signed.length).toBeGreaterThan(8);
    for (const text of signed) expect(Number(text)).not.toBe(0);
    // gold pools to +0.000482, so it must not print the three-place form
    expect(cells.some((c) => c.includes("+0.0005") || c.includes("+0.00048"))).toBe(true);
  });

  it("shows the year split, because a pooled number hides a sign flip", async () => {
    // EUR/USD pools to +0.001 while three of its four years are negative. The replay was split by
    // year for exactly this reason; a reader shown only the pooled row cannot see it.
    stubFetch();
    render(<Journal />);
    await screen.findByLabelText("Totals");
    const summary = screen.getByText("Past backtests (not counted)");
    const details = summary.closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    const replay = await screen.findByLabelText("Daily models replayed over history");
    const text = replay.textContent ?? "";
    // gold: pooled positive, most recent year clearly negative -- the sign flip the split exists for
    expect(text).toContain("2026 -0.019");
    // EUR/USD: pools positive, three of four years negative
    expect(text).toContain("2025 -0.005");
    expect(text).toContain("2023 -0.009");
    expect(replay.querySelectorAll("tbody tr")).toHaveLength(4);   // 2 models + 1 year row each
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

  it("says so when the replay cannot be read, instead of showing nothing", async () => {
    // `.catch(() => setReplays([]))` plus `length > 0` made a 500, a network error and an unapplied
    // migration all render exactly like "no replays have ever run". The reader cannot tell absence of
    // evidence from absence of the table.
    // The scoreboard body must still resolve or the component throws on `data.rows` and the section
    // never mounts -- which is how a missing replay table can look like an unrelated crash.
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (String(url).includes("/api/journal/backtests")) {
        return Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({ detail: "journal_backtests is missing" }) });
      }
      if (String(url).includes("/api/scoreboard")) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(scoreboard) });
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(journal) });
    }));
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (String(url).includes("/api/journal/backtests")) {
        return Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({ detail: "journal_backtests is missing" }) });
      }
      if (String(url).includes("/api/scoreboard")) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(scoreboard) });
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(journal) });
    }));
    render(<Journal />);
    await screen.findByLabelText("Totals");
    const summary = screen.getByText("Past backtests (not counted)");
    const details = summary.closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect(await screen.findByText(/Daily-model replays unavailable: journal_backtests is missing/)).toBeInTheDocument();
  });

  it("shows the effect size in Brier points, so the skill number can be judged", async () => {
    // Skill +0.010 is 1.1 standard errors over 775 sessions -- a coin flip that reads as a result.
    // The Brier pair beside it makes the size of the difference visible without any statistics:
    // 0.24533 against a 0.24779 climatology baseline.
    stubFetch();
    render(<Journal />);
    await screen.findByLabelText("Totals");
    const summary = screen.getByText("Past backtests (not counted)");
    const details = summary.closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    const replay = await screen.findByLabelText("Daily models replayed over history");
    expect(replay.textContent).toContain("0.2469 vs 0.2470");   // gold, rounded Brier pair
  });

  it("prints the gap and its standard error, because a bare number reads as a result", async () => {
    // The audit that produced this: over ~760 sessions every replayed skill sits within 0.01 of
    // climatology and VIX's +0.0099 is 1.1 standard errors. `-0.0001 ± 0.0022` says the same thing in one
    // line -- and it is on the Brier gap, not on the skill, because the standard error of a difference is
    // measurable and the standard error of a ratio is not this number.
    stubFetch();
    render(<Journal />);
    await screen.findByLabelText("Totals");
    const summary = screen.getByText("Past backtests (not counted)");
    const details = summary.closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    const replay = await screen.findByLabelText("Daily models replayed over history");
    const gold = replay.textContent ?? "";
    expect(gold).toContain("0.2469 vs 0.2470 (-0.0001 ± 0.0022)");
    // and EUR/USD's, so the interval is not one hand-typed row's decoration
    expect(gold).toContain("0.2499 vs 0.2500 (-0.0001 ± 0.0021)");
    // the gap is small enough to vanish at three places, and must not print a signed zero
    expect(gold).not.toContain("-0.0000");
  });

  it("omits the interval entirely when the migration has not been applied", async () => {
    // `brier_diff_se: null` is what /api/journal/backtests serves while migration 017 is unapplied. The
    // Brier pair is still true, so it stays; the interval is not measured, so it is not printed -- and
    // certainly not printed as `± 0`, which would claim a precision nobody measured.
    stubFetch({ as_of: "x", counted: false, backtests: [
      { forecaster: "gold_direction", forecaster_version: "gold-wf-v1", date_from: "2023-10-02",
        date_to: "2026-10-01", n: 753, bss: 0.000482, brier: 0.246852, brier_baseline: 0.246971,
        brier_diff: -0.000119, brier_diff_se: null,
        by_year: { "2026": { n: 188, bss: -0.018619 } }, created_at: "2026-10-02T15:00:56.328768+00:00" },
    ] });
    render(<Journal />);
    await screen.findByLabelText("Totals");
    const summary = screen.getByText("Past backtests (not counted)");
    const details = summary.closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    const replay = await screen.findByLabelText("Daily models replayed over history");
    const cells = [...replay.querySelectorAll("td")].map((td) => td.textContent ?? "");

    expect(cells.some((c) => c.includes("0.2469 vs 0.2470"))).toBe(true);   // the pair survives
    expect(replay.textContent).not.toContain("±");                          // the interval does not
    expect(replay.textContent).not.toContain("-0.0001");
    expect(cells.some((c) => c.includes("± 0"))).toBe(false);               // never a fake zero
  });

  it("dates the replays, because a re-run silently replaces the numbers", async () => {
    stubFetch();
    render(<Journal />);
    await screen.findByLabelText("Totals");
    const summary = screen.getByText("Past backtests (not counted)");
    const details = summary.closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    const replay = await screen.findByLabelText("Daily models replayed over history");
    expect(replay.textContent).toContain("replayed");
  });
