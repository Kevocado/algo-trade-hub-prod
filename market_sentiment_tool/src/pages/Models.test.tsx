import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import Models from "@/pages/Models";
import type { CatalogueEntry, ModelsResponse } from "@/lib/models";
import type { ScoreboardRow } from "@/lib/scoreboard";
import { copyWords } from "@/test/copyWords";

/**
 * The obligations that outlive the redesign: every engine appears (measured, unmeasured and retired),
 * a losing engine is stated as losing WITH its multiple, an unmeasured engine is a word and never a 0,
 * and no affordance can remove a row. Plus the copy budget.
 */

const row: ScoreboardRow = {
  engine: "gas", engine_version: "gas-v1", mode: "taker", date_from: "2026-06-01T00:00:00+00:00", date_to: "2026-09-20T00:00:00+00:00",
  created_at: "2026-09-20T00:00:00+00:00", n_decisions: 1982, n_fills: 400, n_settled: 3328, brier_ours: 0.119, brier_market: 0.0296,
  brier_ratio: 4.02, market_verdict: "behind", pnl_after_fees: -10, max_drawdown: 5, gate_status: "shadow", promotion_status: "SHADOW",
  gate_reasons: [], settled_distance: null,
};

const entry = (over: Partial<CatalogueEntry>): CatalogueEntry => ({
  engine: "x", label: "X engine", claim: "Predicts X.", claim_note: "", in_catalogue: true, cadence: "daily", measured: false,
  measured_rows: 0, status: "not_measured", worst_brier_ratio: null, rows: [], ...over,
});

const BODY: ModelsResponse = {
  as_of: "2026-10-01T00:00:00+00:00", runs_read: 1, rows: [row], engines: 1, promotion_lookup_failed: false, rows_total: 1,
  rows_behind_market: 1, rows_ahead_of_market: 0, rows_level_with_market: 0, rows_not_comparable: 0, any_beats_market: false,
  headline: "h", headline_kind: "all_behind", caveat: null,
  catalogue: {
    engines_total: 3, engines_measured: 1, engines_not_measured: 2, engines_unlisted: 0, engines_retired: 1,
    entries: [
      entry({ engine: "gas", label: "Gasoline", measured: true, measured_rows: 1, status: "behind", worst_brier_ratio: 4.02, rows: [row] }),
      entry({ engine: "labor_nowcast", label: "Non-farm payrolls", cadence: "monthly" }),
      entry({ engine: "old", label: "Old engine", status: "retired", claim: null, claim_note: "Retired: deleted",
             retired: { removed: "2026-10-15", reason: "deleted", replaced_by: "gas" } }),
    ],
  },
} as unknown as ModelsResponse;

function stub(body: unknown = BODY, ok = true) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok, status: ok ? 200 : 503, json: () => Promise.resolve(body) })));
}

afterEach(() => vi.unstubAllGlobals());

describe("Models", () => {
  it("lists every engine, measured or not, retired included, and says losing in words with the multiple", async () => {
    stub();
    render(<Models />);
    const gas = (await screen.findByText("Gasoline")).closest("tr")!;
    expect(within(gas).getByText("Behind")).toBeInTheDocument();
    expect(within(gas).getByText("4.0x")).toBeInTheDocument();
    expect(within(gas).getByText("1,982")).toBeInTheDocument();
    const payroll = screen.getByText("Non-farm payrolls").closest("tr")!;
    expect(within(payroll).getByText("Not tested")).toBeInTheDocument();
    expect(within(payroll).queryByText(/0\.0x|^0$/)).toBeNull(); // an untested engine is a dash, never a zero
    expect(screen.getByText("Old engine").closest("tr")).toHaveTextContent("Retired");
  });

  it("headlines three counts without a paragraph", async () => {
    stub();
    render(<Models />);
    const totals = await screen.findByLabelText("Totals");
    expect(within(totals).getByText("beating the market").previousSibling).toHaveTextContent("0");
    expect(within(totals).getByText("behind the market").previousSibling).toHaveTextContent("1");
    expect(within(totals).getByText("not tested yet").previousSibling).toHaveTextContent("2");
  });

  it("opens the claim, the backtest and both settled bars only on request", async () => {
    stub();
    render(<Models />);
    expect(screen.queryByText("Own gate")).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Gasoline" }));
    expect(screen.getByText("Predicts X.")).toBeInTheDocument();
    expect(screen.getByText("Own gate")).toBeInTheDocument();
    expect(screen.getByText("Reviewer's settled floor")).toBeInTheDocument(); // two bars, never merged
  });

  it("stays inside its word budget", async () => {
    stub();
    const { container } = render(<Models />);
    await screen.findByText("Gasoline");
    expect(copyWords(container)).toBeLessThanOrEqual(45);
  });

  it("shows the API's error, and a missing catalogue as a fault rather than an empty table", async () => {
    stub({ detail: "backtest_runs is missing" }, false);
    const { unmount } = render(<Models />);
    expect(await screen.findByText(/backtest_runs is missing/)).toBeInTheDocument();
    unmount();
    stub({ ...BODY, catalogue: { ...BODY.catalogue, entries: [] } });
    render(<Models />);
    expect(await screen.findByText("The model list did not arrive.")).toBeInTheDocument();
  });
});
