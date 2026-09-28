import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";

import Models from "@/pages/Models";
import type { Catalogue, CatalogueEntry, ModelsResponse } from "@/lib/models";
import type { ScoreboardRow } from "@/lib/scoreboard";

/**
 * The page that answers "what are the models and what are they doing", and the four obligations
 * that are not the code's to enforce.
 *
 * The fixture is the product's REAL state as of this writing, not a flattering one: three engines
 * measured and all three losing, four engines with no backtest run at all. That is the point of
 * the fixture. A board where everything has been measured would not exercise the failure this page
 * exists to prevent, which is an engine quietly missing.
 *
 * 1. **Every engine appears.** `/api/scoreboard` reduces `backtest_runs`, so an un-backtested engine
 *    is ABSENT from it, and an absent engine reads as "this engine has nothing to show" — a claim
 *    about the engine that nobody made. Removing the catalogue join from this page would still
 *    render a complete-looking table of three.
 * 2. **A losing engine is stated as losing, with its multiple.** Gas at 4.29x is not close, and a
 *    reader told otherwise cannot judge the engine.
 * 3. **The two bars are two bars.** The engine's own stated bar (200 daily, 50 monthly) and the
 *    reviewer's flat floor (100) are different numbers; rendering one of them, or averaging them,
 *    is a verdict against a bar the engine never had.
 * 4. **No affordance can remove a row.** No filter, no sort, no collapsed tail.
 *
 * These are asserted against RENDERED output rather than against a returned object, because a
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

/** Weather: 1.28x behind, 672 settled, so it has MET both of its bars. */
function weatherRow(over: Partial<ScoreboardRow> = {}): ScoreboardRow {
  return gasRow({
    engine: "weather",
    engine_version: "weather-v1",
    brier_ours: 0.1242,
    brier_market: 0.09713,
    brier_ratio: 1.2787,
    n_settled: 672,
    gate_reasons: ["only 672 settled contracts, need 200 (daily)"],
    settled_distance: {
      n_settled: 672,
      required: 200,
      required_source: "gate",
      remaining: 0,
      met: true,
      pct: 100.0,
      floor: 100,
      floor_remaining: 0,
      floor_met: true,
      floor_pct: 100.0,
    },
    ...over,
  });
}

/** Labor: a MONTHLY engine at 70 settled. It met its own unstateable 50 bar; the floor is 100. */
const laborRow = gasRow({
  engine: "labor_nowcast",
  engine_version: "labor-v1",
  brier_ours: 0.1792,
  brier_market: 0.1659,
  brier_ratio: 1.0802,
  n_settled: 70,
  gate_reasons: ["model Brier 0.1792 is not below market Brier 0.1659"],
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
});

const MEASURED: CatalogueEntry[] = [
  {
    engine: "gas",
    label: "Gasoline — AAA US average, day over day",
    claim: "Whether the AAA US average gasoline price will finish the day above or below a strike, on KXAAAGASD.",
    claim_note: "",
    in_catalogue: true,
    cadence: "daily",
    measured: true,
    measured_rows: 1,
    status: "behind",
    worst_brier_ratio: 4.29,
    rows: [gasRow()],
  },
  {
    engine: "weather",
    label: "Daily high temperature — Chicago, New York, Miami",
    claim: "Whether a city's daily high reaches a strike, on KXHIGHCHI, KXHIGHNY and KXHIGHMIA.",
    claim_note: "",
    in_catalogue: true,
    cadence: "daily",
    measured: true,
    measured_rows: 1,
    status: "behind",
    worst_brier_ratio: 1.2787,
    rows: [weatherRow()],
  },
  {
    engine: "cpi_nowcast",
    label: "CPI — first print, month over month (headline and core)",
    claim: "Whether the BLS first print of month-over-month CPI is more than a strike above the contract, on KXCPI.",
    claim_note: "",
    in_catalogue: true,
    cadence: "monthly",
    measured: false,
    measured_rows: 0,
    status: "not_measured",
    worst_brier_ratio: null,
    rows: [],
  },
  {
    engine: "labor_nowcast",
    label: "Non-farm payrolls — BLS first print",
    claim: "Whether the BLS first print of the change in non-farm payrolls is above a strike, on KXPAYROLLS.",
    claim_note: "",
    in_catalogue: true,
    cadence: "monthly",
    measured: true,
    measured_rows: 1,
    status: "behind",
    worst_brier_ratio: 1.0802,
    rows: [laborRow],
  },
  {
    engine: "crypto",
    label: "Crypto — BTC and ETH, next hourly close",
    claim: "Whether an asset's next hourly close resolves YES against a fixed threshold.",
    claim_note: "",
    in_catalogue: true,
    cadence: "daily",
    measured: false,
    measured_rows: 0,
    status: "not_measured",
    worst_brier_ratio: null,
    rows: [],
  },
  {
    engine: "sports_nfl",
    label: "NFL game markets — winner, spread, total",
    claim: "The probability that one side of an NFL market resolves as claimed, for winner, spread and total.",
    claim_note: "",
    in_catalogue: true,
    cadence: "daily",
    measured: false,
    measured_rows: 0,
    status: "not_measured",
    worst_brier_ratio: null,
    rows: [],
  },
  {
    engine: "sports_cfb",
    label: "College football game markets — winner, spread, total",
    claim: "The probability that one side of a college-football market resolves as claimed.",
    claim_note: "",
    in_catalogue: true,
    cadence: "daily",
    measured: false,
    measured_rows: 0,
    status: "not_measured",
    worst_brier_ratio: null,
    rows: [],
  },
];

function catalogueOf(entries: CatalogueEntry[]): Catalogue {
  const measured = entries.filter((e) => e.measured).length;
  return {
    engines_total: entries.length,
    engines_measured: measured,
    engines_not_measured: entries.length - measured,
    engines_unlisted: entries.filter((e) => !e.in_catalogue).length,
    entries,
  };
}

function response(over: Partial<ModelsResponse> = {}): ModelsResponse {
  const rows = MEASURED.flatMap((e) => e.rows);
  return {
    as_of: "2026-09-27T00:00:00+00:00",
    runs_read: 9,
    rows,
    engines: 3,
    promotion_lookup_failed: false,
    rows_total: 3,
    rows_behind_market: 3,
    rows_ahead_of_market: 0,
    rows_level_with_market: 0,
    rows_not_comparable: 0,
    any_beats_market: false,
    headline: "No engine beats the market on Brier.",
    headline_kind: "behind",
    caveat: null,
    catalogue: catalogueOf(MEASURED),
    ...over,
  };
}

function stub(handler: () => { ok: boolean; status: number; body?: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      const { ok, status, body } = handler();
      return { ok, status, json: async () => body ?? {} } as Response;
    }),
  );
}

async function renderWith(payload: ModelsResponse) {
  stub(() => ({ ok: true, status: 200, body: payload }));
  const rendered = render(<Models />);
  // `engine` because the counts line agrees its noun with the count and reads "7 engines".
  await waitFor(() => expect(screen.getByText(/engines? ·/)).toBeInTheDocument());
  return rendered;
}

function rowFor(engine: string): HTMLElement {
  return screen.getByRole("rowheader", { name: new RegExp(engine) }).closest("tr") as HTMLElement;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("obligation 1: every engine appears, measured or not", () => {
  it("renders all seven, including the four with no backtest run", async () => {
    await renderWith(response());

    for (const engine of ["gas", "weather", "cpi_nowcast", "labor_nowcast", "crypto", "sports_nfl", "sports_cfb"]) {
      expect(screen.getByRole("rowheader", { name: new RegExp(engine) })).toBeInTheDocument();
    }
    // Header plus seven engines. A page that dropped the unmeasured tail would render four and
    // look complete, which is the whole failure.
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(8);
  });

  it("says an unmeasured engine is not measured, in words, and prints no figure for it", async () => {
    await renderWith(response());

    const crypto = rowFor("crypto");
    expect(within(crypto).getByText("Not measured")).toBeInTheDocument();
    expect(crypto).toHaveTextContent("No backtest run is recorded for this engine");
    // No figure at all — not a 0, not a 0.00x, and not even a dash standing in for one. The
    // strongest form of "absent is not zero" is that there is nothing in the cell to misread.
    expect(crypto.textContent).not.toMatch(/0\.00x|0x the market|—x|0\.00000/);
    // "Not measured" is not the same sentence as "no bars to state": a bar needs a count, and
    // there is no count, so neither bar is drawn and neither is reported as met or unmet.
    expect(crypto).toHaveTextContent("No bars to state");
    expect(crypto).toHaveTextContent("No gate verdict");
    expect(within(crypto).queryByText("Met")).not.toBeInTheDocument();
    expect(within(crypto).queryByText("Not met")).not.toBeInTheDocument();
  });

  it("still states the claim for an engine nothing has been measured on", async () => {
    // A claim is not a measurement. Losing the claim on the unmeasured engines would answer the
    // owner's question for the three engines they can already see and not the other four.
    await renderWith(response());

    expect(rowFor("cpi_nowcast")).toHaveTextContent("KXCPI");
    expect(rowFor("crypto")).toHaveTextContent("next hourly close");
    expect(rowFor("sports_cfb")).toHaveTextContent("college-football market");
  });

  it("says how much of the product has never been measured, in the summary", async () => {
    await renderWith(response());

    const summary = screen.getByText(/engines? ·/);
    expect(summary).toHaveTextContent("7 engines");
    expect(summary).toHaveTextContent("3 measured");
    expect(summary).toHaveTextContent("4 not measured");
  });

  it("labels the two counts, because both of them are called engines", async () => {
    // "7 engines" and "3 engines" a line apart, counting different sets, is the right-number-
    // wrong-label defect arrived at through layout. Each count says what it counts.
    const { container } = await renderWith(response());

    const block = container.querySelector("table")?.previousElementSibling as HTMLElement;
    expect(within(block).getByText(/^Engines —/)).toBeInTheDocument();
    expect(within(block).getByText(/^Backtest rows —/)).toBeInTheDocument();
    // The headline stays a claim about engines, and the caveat stays beside it.
    expect(within(block).getByText("No engine beats the market on Brier.")).toBeInTheDocument();
  });

  it("still renders an engine with no catalogue entry, and says the catalogue is behind", async () => {
    const undeclared = { ...MEASURED[0], engine: "fx_carry", label: "fx_carry", claim: null,
      claim_note: "Not described. No entry in the engine catalogue.", in_catalogue: false };
    const entries = [...MEASURED, undeclared];
    await renderWith(response({ catalogue: catalogueOf(entries) }));

    const row = rowFor("fx_carry");
    expect(row).toHaveTextContent("Not described");
    // It is still measured, because the run is real evidence, and the run is still on the row.
    expect(row).toHaveTextContent("4.29x");
    expect(screen.getByText(/engines? ·/)).toHaveTextContent("1 not in the catalogue");
  });
});

describe("obligation 2: a losing engine is stated as losing, with its multiple", () => {
  it("shows gas at 4.29x the market's Brier, and calls it behind", async () => {
    await renderWith(response());

    const gas = rowFor("gas");
    expect(within(gas).getByText("Behind the market")).toBeInTheDocument();
    expect(within(gas).getByText("4.29x")).toBeInTheDocument();
    // Ours beside the market's, in the precision the column stores.
    expect(gas).toHaveTextContent("0.11480 ours · 0.02676 market");
    expect(gas).toHaveTextContent("4.29x the market's Brier — behind");
  });

  it("names the worst of an engine's runs when it has more than one, and shows the rest anyway", async () => {
    const twoModes = { ...MEASURED[1], measured_rows: 2, worst_brier_ratio: 1.2787,
      rows: [weatherRow(), weatherRow({ mode: "maker", brier_ours: 0.1112, brier_market: 0.0993,
        brier_ratio: 1.1199 })] };
    const entries = MEASURED.map((e) => (e.engine === "weather" ? twoModes : e));
    await renderWith(response({ catalogue: catalogueOf(entries) }));

    const weather = rowFor("weather");
    // The summary is built from the WORST row, and says so, rather than quietly leading with
    // the better one.
    expect(weather).toHaveTextContent("worst of 2 runs");
    expect(weather).toHaveTextContent("1.28x");
    // And the better row is still on the page, so the worst is a summary and not a filter.
    expect(weather).toHaveTextContent("1.12x the market's Brier — behind");
  });

  it("uses the board's own headline and never a summary that names only the best engine", async () => {
    await renderWith(response());

    expect(screen.getByText("No engine beats the market on Brier.")).toBeInTheDocument();
    const summaryBlock = screen.getByText("No engine beats the market on Brier.").closest("div");
    // A summary naming one engine is a summary about the other six, and it is the summary a
    // reader reads first.
    expect(summaryBlock?.textContent).not.toMatch(/gas|weather|labor|cpi|crypto|sports/);
  });

  it("never softens a deficit anywhere on the page", async () => {
    await renderWith(response());

    expect(document.body.textContent).not.toMatch(/close to|competitive|nearly par|almost/i);
  });

  it("reports a run with no market Brier as not comparable, and dashes the market's figure", async () => {
    const uncompared = { ...MEASURED[1], status: "not_comparable" as const, worst_brier_ratio: null,
      rows: [weatherRow({ brier_market: null, brier_ratio: null, market_verdict: "not_comparable" as const })] };
    const entries = MEASURED.map((e) => (e.engine === "weather" ? uncompared : e));
    await renderWith(response({ catalogue: catalogueOf(entries) }));

    const weather = rowFor("weather");
    expect(within(weather).getByText("Not comparable")).toBeInTheDocument();
    expect(weather).toHaveTextContent("0.12420 ours · — market");
    expect(weather).not.toHaveTextContent("0.00000 market");
    // A run exists, so the bars do: this is NOT the "no bars to state" case.
    expect(weather).toHaveTextContent("Own gate");
  });
});

describe("obligation 3: the two bars are two bars", () => {
  it("labels each bar and prints both numbers for gas", async () => {
    await renderWith(response());

    const gas = rowFor("gas");
    expect(within(gas).getByText("Own gate")).toBeInTheDocument();
    expect(within(gas).getByText("Reviewer's settled floor")).toBeInTheDocument();
    expect(gas).toHaveTextContent("42 of 200 settled — 158 more needed");
    expect(gas).toHaveTextContent("42 of 100 settled — 58 more needed");
  });

  it("does not report a cleared monthly engine as failing the reviewer's floor", async () => {
    // 70 settled against the engine's own unstateable 50: MET. The floor is 100 and is unmet.
    // Collapsing the two into one number is the failure — and "70 of 100, unmet" is exactly what
    // that collapse prints.
    await renderWith(response());

    const labor = rowFor("labor_nowcast");
    expect(within(labor).getAllByText("Met")).toHaveLength(1);
    expect(within(labor).getByText("Not met")).toBeInTheDocument();
    expect(labor).toHaveTextContent("the gate named no bar");
    expect(labor).toHaveTextContent("70 of 100 settled — 30 more needed");
    expect(labor).not.toHaveTextContent("70 of 100 settled — met");
    // And the engine's own bar is never restated as the floor's number.
    expect(labor).not.toHaveTextContent("70 of 50");
  });

  it("shows an engine that has met both bars as having met both, not as one merged number", async () => {
    await renderWith(response());

    const weather = rowFor("weather");
    expect(within(weather).getAllByText("Met")).toHaveLength(2);
    expect(within(weather).queryByText("Not met")).not.toBeInTheDocument();
    expect(weather).toHaveTextContent("672 of 200 settled — met");
    expect(weather).toHaveTextContent("672 of 100 settled — met");
  });
});

describe("obligation 4: nothing can remove a row from the board", () => {
  it("offers no control that could hide, sort or collapse anything", async () => {
    const { container } = await renderWith(response());

    // A select, a checkbox or a button is how a "hide losers" affordance arrives.
    expect(container.querySelectorAll("select, input, button")).toHaveLength(0);
    // And no <details>, which is how a collapsing tail arrives.
    expect(container.querySelectorAll("details")).toHaveLength(0);
  });

  it("keeps the two gates as two things on a measured engine", async () => {
    await renderWith(
      response({
        catalogue: catalogueOf(
          MEASURED.map((e) =>
            e.engine === "gas" ? { ...e, rows: [gasRow({ gate_status: "PROMOTED" })] } : e,
          ),
        ),
      }),
    );

    const gas = rowFor("gas");
    // The backtest gate passed...
    expect(gas).toHaveTextContent("Backtest gate passed");
    // ...and the engine is still not promoted, because the track record does not say so.
    expect(gas).toHaveTextContent("Shadow");
    expect(gas).not.toHaveTextContent("Promoted");
    // The scope, in visible text, for the same reason the scoreboard states it in visible text.
    expect(within(gas).getByText("for gas · gas-v1")).toBeInTheDocument();
  });
});

describe("loading, failed and empty reads", () => {
  it("does not claim a verdict while the read is still in flight", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<Models />);

    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    expect(screen.queryByText("No engine beats the market on Brier.")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows the failure the API reported, and no table", async () => {
    stub(() => ({
      ok: false,
      status: 503,
      body: { detail: "table 'backtest_runs' is not in the database. Apply 20260416000004_backtest_runs.sql and redeploy." },
    }));

    render(<Models />);

    await waitFor(() => expect(screen.getByText(/20260416000004_backtest_runs\.sql/)).toBeInTheDocument());
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("says the catalogue came back empty rather than rendering an empty table", async () => {
    // An empty table on this page reads as "nothing to report about the models", which is the
    // exact claim this page must never make: the engines exist whether or not anyone measured them.
    await renderWith(response({ catalogue: catalogueOf([]) }));

    expect(screen.getByText(/engine catalogue came back empty/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("survives a response with no catalogue key at all, from an older API", async () => {
    // The hub deploys the API and the SPA together, but a browser can hold the old bundle against
    // the new API. A crash would be a worse answer than a page that says the join is missing —
    // and "0 engines" would be the worst answer of all, because it is a claim the product is empty.
    const { catalogue: _dropped, ...withoutCatalogue } = response();
    stub(() => ({ ok: true, status: 200, body: withoutCatalogue }));

    render(<Models />);

    expect(
      await screen.findByText(/engine catalogue came back empty/i),
    ).toBeInTheDocument();
    expect(document.body.textContent).toMatch(/engine counts not in the response/i);
    expect(document.body.textContent).not.toMatch(/\b0 engines\b/);
  });
});
