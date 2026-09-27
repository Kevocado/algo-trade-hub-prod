import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";

import Scoreboard from "@/pages/Scoreboard";
import type { ScoreboardResponse, ScoreboardRow } from "@/lib/scoreboard";

/**
 * The three obligations the review left, none of which the code alone enforces.
 *
 * 1. `rows_not_comparable` is rendered BESIDE the headline, or the headline is not rendered. The
 *    headline is a claim about ENGINES; that count is about ROWS. "No engine beats the market on
 *    Brier." next to an unrendered `rows_not_comparable: 2` is incomplete, and only the rendering
 *    puts the caveat in front of a reader.
 * 2. A losing engine is never dropped and never softened. This page exists to show losses, so
 *    there is no hide-losers affordance and no collapse of the losing tail.
 * 3. `HEADLINE_NOT_COMPARABLE` is honoured as its own case: no claim about the market at all.
 *
 * These are asserted against rendered output rather than against a returned object, because a
 * function that returns the right pair and a component that renders one of them is the failure.
 */

function gasRow(over: Partial<ScoreboardRow> = {}): ScoreboardRow {
  return {
    engine: "gas",
    engine_version: "gas-v1",
    mode: "taker",
    date_from: "2026-06-01T00:00:00+00:00",
    date_to: "2026-09-20T00:00:00+00:00",
    created_at: "2026-09-20T00:00:00+00:00",
    n_decisions: 1982,
    n_fills: 274,
    n_settled: 42,
    brier_ours: 0.1148,
    brier_market: 0.02676,
    brier_ratio: 4.29,
    market_verdict: "behind",
    pnl_after_fees: -3.84,
    max_drawdown: 7.06,
    gate_status: "SHADOW",
    promotion_status: "SHADOW",
    gate_reasons: ["only 42 settled contracts, need 200 (daily)"],
    settled_distance: {
      n_settled: 42,
      required: 200,
      required_source: "gate",
      remaining: 158,
      met: false,
      pct: 21.0,
      floor: 100,
      floor_remaining: 58,
      floor_met: false,
      floor_pct: 42.0,
    },
    ...over,
  };
}

function response(over: Partial<ScoreboardResponse> = {}): ScoreboardResponse {
  const rows = [gasRow()];
  return {
    as_of: "2026-09-27T00:00:00+00:00",
    runs_read: 1,
    rows,
    engines: 1,
    promotion_lookup_failed: false,
    rows_total: 1,
    rows_behind_market: 1,
    rows_ahead_of_market: 0,
    rows_level_with_market: 0,
    rows_not_comparable: 0,
    any_beats_market: false,
    headline: "No engine beats the market on Brier.",
    headline_kind: "behind",
    caveat: null,
    ...over,
  };
}

function mockScoreboard(handler: () => { ok: boolean; status: number; body?: unknown }) {
  const spy = vi.fn(async () => {
    const { ok, status, body } = handler();
    return { ok, status, json: async () => body ?? {} } as Response;
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

async function renderWith(payload: ScoreboardResponse) {
  mockScoreboard(() => ({ ok: true, status: 200, body: payload }));
  const rendered = render(<Scoreboard />);
  await waitFor(() => expect(screen.getByText(/rows ·/)).toBeInTheDocument());
  return rendered;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("obligation 1: the headline never travels without the count that qualifies it", () => {
  it("renders the caveat in the same block as the headline", async () => {
    const caveat =
      "2 of 5 rows could not be compared: no market Brier was recorded for them, so the headline " +
      "does not rest on those rows.";
    await renderWith(
      response({
        rows: [gasRow()],
        rows_total: 5,
        rows_behind_market: 3,
        rows_not_comparable: 2,
        caveat,
      }),
    );

    const headline = screen.getByText("No engine beats the market on Brier.");
    // Same block, not merely the same page: a caveat two sections down is a caveat nobody reads.
    expect(headline.closest("div")).toHaveTextContent(caveat);
    expect(screen.getByText(/2 of 5 rows could not be compared/)).toBeInTheDocument();
  });

  it("names all four buckets, so a partly-comparable board says so in the summary", async () => {
    await renderWith(
      response({ rows_total: 3, rows_behind_market: 1, rows_not_comparable: 2, caveat: "2 of 3 rows" }),
    );

    const summary = screen.getByText(/rows ·/);
    expect(summary).toHaveTextContent("1 behind the market");
    expect(summary).toHaveTextContent("2 not comparable");
  });
});

describe("obligation 2: a losing engine is never dropped and never softened", () => {
  const losers = [
    gasRow(),
    gasRow({ engine: "weather", engine_version: "weather-v1", brier_ratio: 1.2787,
             brier_ours: 0.1242, brier_market: 0.09713, pnl_after_fees: -11.2,
             market_verdict: "behind" }),
    gasRow({ engine: "labor_nowcast", engine_version: "labor-v1", brier_ratio: 1.0802,
             brier_ours: 0.1792, brier_market: 0.1659, pnl_after_fees: -2.05,
             market_verdict: "behind" }),
  ];

  it("renders every engine, including the worst one", async () => {
    await renderWith(response({ rows: losers, rows_total: 3, engines: 3, rows_behind_market: 3 }));

    for (const engine of ["gas", "weather", "labor_nowcast"]) {
      expect(screen.getByRole("rowheader", { name: new RegExp(engine) })).toBeInTheDocument();
    }
    // The body of the table holds exactly the three rows and no summary row about the best of them.
    const bodyRows = within(screen.getByRole("table")).getAllByRole("row");
    expect(bodyRows).toHaveLength(4); // header + 3
  });

  it("offers no control that could remove a row from the board", async () => {
    const { container } = await renderWith(
      response({ rows: losers, rows_total: 3, engines: 3, rows_behind_market: 3 }),
    );

    // A select, a checkbox or a text input is how a "hide losers" affordance arrives. There is no
    // such control, and this fails the moment one is added.
    expect(container.querySelectorAll("select, input, button")).toHaveLength(0);
  });

  it("states each engine's loss in numbers and in the multiple, not in an adjective", async () => {
    await renderWith(response({ rows: losers, rows_total: 3, engines: 3, rows_behind_market: 3 }));

    const gas = screen.getByRole("rowheader", { name: /gas/ }).closest("tr") as HTMLElement;
    expect(gas).toHaveTextContent("4.3x the market's Brier — behind");
    expect(gas).toHaveTextContent("-$3.84");
    expect(gas).toHaveTextContent("0.11480");
    expect(gas).toHaveTextContent("0.02676");
    // The whole board's text, checked for the vocabulary of softening.
    expect(document.body.textContent).not.toMatch(/close to|competitive|nearly par|almost/i);
  });
});

describe("obligation 3: HEADLINE_NOT_COMPARABLE is its own case", () => {
  it("says the comparison could not be made and makes no claim about the market", async () => {
    const unmeasured = gasRow({
      engine: "weather",
      engine_version: "weather-v1",
      mode: "maker",
      brier_market: null,
      brier_ratio: null,
      market_verdict: "not_comparable",
      gate_reasons: ["no market Brier recorded; gate cannot be evaluated"],
    });
    await renderWith(
      response({
        rows: [unmeasured],
        rows_total: 1,
        rows_behind_market: 0,
        rows_not_comparable: 1,
        any_beats_market: false,
        headline:
          "No engine run could be compared: no market Brier was recorded at decision time.",
        headline_kind: "not_comparable",
        caveat:
          "1 of 1 rows could not be compared: no market Brier was recorded for them, so the " +
          "headline does not rest on those rows.",
      }),
    );

    expect(
      screen.getByText("No engine run could be compared: no market Brier was recorded at decision time."),
    ).toBeInTheDocument();
    // The engine is still on the page, with its numbers, and says the comparison was not made.
    expect(screen.getByRole("rowheader", { name: /weather/ })).toBeInTheDocument();
    const row = screen.getByRole("rowheader", { name: /weather/ }).closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("Not measured");
    expect(row).toHaveTextContent("—"); // the market Brier is a dash, not 0.00000
    expect(row).not.toHaveTextContent("0.00000");
  });
});

describe("the two bars, both visible and both attributable", () => {
  it("labels each bar so a reader can tell which one a verdict was made against", async () => {
    await renderWith(response());

    const row = screen.getByRole("rowheader", { name: /gas/ }).closest("tr") as HTMLElement;
    expect(within(row).getByText("Own gate")).toBeInTheDocument();
    expect(within(row).getByText("Reviewer's settled floor")).toBeInTheDocument();
    expect(row).toHaveTextContent("42 of 200 settled — 158 more needed");
    expect(row).toHaveTextContent("42 of 100 settled — 58 more needed");
  });

  it("does not report a cleared monthly engine as failing the reviewer's floor", async () => {
    // 70 settled, gate named no bar (so it met its own unstateable 50), reviewer's floor is 100.
    await renderWith(
      response({
        rows: [
          gasRow({
            engine: "labor_nowcast",
            n_settled: 70,
            gate_reasons: ["model Brier 0.2 is not below market Brier 0.1"],
            settled_distance: {
              n_settled: 70,
              required: null,
              required_source: "engine",
              remaining: 0,
              met: true,
              pct: null,
              floor: 100,
              floor_remaining: 30,
              floor_met: false,
              floor_pct: 70.0,
            },
          }),
        ],
        rows_total: 1,
        rows_behind_market: 1,
      }),
    );

    const row = screen.getByRole("rowheader", { name: /labor_nowcast/ }).closest("tr") as HTMLElement;
    // Two different verdicts, visibly attributed to two different bars.
    expect(within(row).getAllByText("Met")).toHaveLength(1);
    expect(within(row).getByText("Not met")).toBeInTheDocument();
    expect(row).toHaveTextContent("the gate named no bar");
    expect(row).toHaveTextContent("70 of 100 settled — 30 more needed");
    // And never the collapsed "70/100, unmet" verdict against a bar that was never the engine's.
    expect(row).not.toHaveTextContent("70 of 100 settled — met");
  });

  it("renders an unmeasured gate as not measured, never as met and never as unmet", async () => {
    await renderWith(
      response({
        rows: [
          gasRow({
            settled_distance: {
              n_settled: null as unknown as number,
              required: null,
              required_source: "unknown",
              remaining: null,
              met: null,
              pct: null,
              floor: null,
              floor_remaining: null,
              floor_met: null,
              floor_pct: null,
            },
          }),
        ],
      }),
    );

    const row = screen.getByRole("rowheader", { name: /gas/ }).closest("tr") as HTMLElement;
    expect(within(row).getAllByText("Not measured")).toHaveLength(2);
    expect(within(row).queryByText("Met")).not.toBeInTheDocument();
    expect(within(row).queryByText("Not met")).not.toBeInTheDocument();
  });
});

describe("the two gates are two things, and are not merged", () => {
  it("shows the run's own backtest gate beside the shared promotion verdict", async () => {
    await renderWith(
      response({ rows: [gasRow({ gate_status: "PROMOTED", promotion_status: "SHADOW" })] }),
    );

    const row = screen.getByRole("rowheader", { name: /gas/ }).closest("tr") as HTMLElement;
    // The backtest gate passed...
    expect(row).toHaveTextContent("Backtest gate passed");
    // ...and the engine is still not promoted, because the track record does not say so.
    expect(row).toHaveTextContent("Shadow");
    // The partial gate is never labelled "Promoted".
    expect(row).not.toHaveTextContent("Promoted");
  });

  it("announces an unreadable promotion lookup rather than showing unverified verdicts as fact", async () => {
    await renderWith(response({ promotion_lookup_failed: true }));

    expect(screen.getByText(/promotion.*could not be read|unverified/i)).toBeInTheDocument();
  });
});

describe("empty, loading and failed reads", () => {
  it("says nothing has been recorded yet when the board is empty", async () => {
    // No `renderWith` here: the empty board has no table to wait for, and that is the point.
    mockScoreboard(() => ({
      ok: true,
      status: 200,
      body: response({
        rows: [],
        engines: 0,
        runs_read: 0,
        rows_total: 0,
        rows_behind_market: 0,
        headline: "No backtest runs are recorded yet, so no engine has a record to show.",
        headline_kind: "no_runs",
      }),
    }));

    render(<Scoreboard />);

    await waitFor(() =>
      expect(
        screen.getByText("No backtest runs are recorded yet, so no engine has a record to show."),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows the failure the API reported, and no board", async () => {
    mockScoreboard(() => ({
      ok: false,
      status: 503,
      body: { detail: "table 'backtest_runs' is not in the database. Apply 20260416000004_backtest_runs.sql and redeploy." },
    }));

    render(<Scoreboard />);

    await waitFor(() => expect(screen.getByText(/20260416000004_backtest_runs\.sql/)).toBeInTheDocument());
    // The migration name comes from the API, which owns that mapping; the page does not repeat it.
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("does not claim a verdict while the read is still in flight", async () => {
    // A fetch that never settles, so the assertion is genuinely about the in-flight state and no
    // state update lands after the test ends (which React reports as an act() warning).
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<Scoreboard />);

    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    expect(screen.queryByText("No engine beats the market on Brier.")).not.toBeInTheDocument();
    // No verdict, and no numbers yet either -- an empty shell is not a finding.
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
