import { describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import { useMarketEdges } from "@/hooks/useMarketEdges";
import { DISPLAY_ONLY_REASON, EDGES_READ_LIMIT } from "@/lib/displayOnlyEngines";

/**
 * The read half of Ruling 1, and the reason this task is not one line.
 *
 * `scan_cpi` no longer writes CPI edges, and the historical rows are not deleted by a migration --
 * they are kept while their markets are open, and `remove_closed_cpi_edges` deletes each one on the
 * first hourly scan after `expires_at`. So there are rows to stand a filter on, for as long as their
 * markets are open. `useMarketEdges` is the single read every page in this product goes through, so
 * it is the only place a standing rule can hold. It must therefore stop handing those rows to a
 * caller as opportunities, and it must hand them over WITH the reason rather than dropping them: a
 * row that is read and then silently omitted is indistinguishable from there having been no rows,
 * and a reader seeing the MACRO tab go quiet would conclude the engine was retired rather than
 * relabelled.
 *
 * The second half of this file is the FAILED read. A swallowed Supabase error used to leave both
 * buckets empty, which renders as "nothing was withheld" -- the one claim a reader must not be able
 * to infer from a read that never happened.
 *
 * These test the HOOK, not just the pure partition function, because the hook is what the ruling is
 * actually about -- and because a pure-function test would still pass if the hook stopped calling it.
 */

const cpiEdge = (id = "cpi-1") => ({
  id,
  market_id: "KXCPI-26SEP09-T0.3",
  edge_type: "MACRO",
  engine: "cpi_nowcast",
  engine_version: "cpi-v1",
  gate_status: "SHADOW",
  market_prob: 0.32,
  our_prob: 0.52,
  edge_pct: 20.0,
  discovered_at: "2026-09-27T12:00:00Z",
  raw_payload: {},
});

const laborEdge = {
  id: "labor-1",
  market_id: "KXPAYROLLS-26OCT-T0.1",
  edge_type: "MACRO",
  engine: "labor_nowcast",
  engine_version: "labor-v1",
  gate_status: "SHADOW",
  market_prob: 0.4,
  our_prob: 0.5,
  edge_pct: 10.0,
  discovered_at: "2026-09-27T12:00:00Z",
  raw_payload: {},
};

// `@/lib/supabase` calls createClient() at module scope, which throws without a URL, so the mock
// has to be hoisted above the hook's import rather than installed inside a helper. `READ` is a
// mutable binding the tests reassign before rendering: it decides what the stubbed query resolves
// to, which is how a failure and an over-cap read are both driven from here.
const READ: { current: { rows: unknown[]; error: unknown } } = {
  current: { rows: [], error: null },
};
const LIMIT = vi.hoisted(() => ({ asked: 0 }));

vi.mock("@/lib/supabase", () => {
  const channel = { on: vi.fn().mockReturnThis(), subscribe: vi.fn().mockReturnThis() };
  return {
    supabase: {
      from: vi.fn(() => ({
        select: vi.fn().mockReturnThis(),
        order: vi.fn().mockReturnThis(),
        limit: vi.fn((n: number) => {
          LIMIT.asked = n;
          return Promise.resolve(
            READ.current.error
              ? { data: null, error: READ.current.error }
              : { data: READ.current.rows, error: null },
          );
        }),
      })),
      channel: vi.fn(() => channel),
      removeChannel: vi.fn(),
    },
  };
});

// No afterEach restore here on purpose. `restoreAllMocks` also resets the hoisted module factory's
// spies, and `channel` is then undefined for the next test -- the hook calls `.subscribe()` on it
// during the effect, which is how the real-time subscription is set up. READ and LIMIT are the only
// per-test state, and renderWith reassigns them.

/** Render the hook against a stubbed Supabase read of `rows`. */
function renderWith(rows: unknown[]) {
  READ.current = { rows, error: null };
  return renderHook(() => useMarketEdges());
}

/** Render the hook against a read that fails. */
function renderWithFailure(message: string) {
  READ.current = { rows: [], error: Object.assign(new Error(message), {}) };
  return renderHook(() => useMarketEdges());
}

describe("useMarketEdges — CPI is no longer presented as an edge", () => {
  it("does not hand a cpi_nowcast row to a caller as an opportunity", async () => {
    const { result } = renderWith([cpiEdge()]);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.edges).toEqual([]);
    expect(result.current.edges.some((e) => e.engine === "cpi_nowcast")).toBe(false);
  });

  it("still hands over the row, labelled, rather than dropping it", async () => {
    const { result } = renderWith([cpiEdge()]);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.withheld).toHaveLength(1);
    expect(result.current.withheld[0].engine).toBe("cpi_nowcast");
    expect(result.current.withheld[0].reason).toBe(DISPLAY_ONLY_REASON.cpi_nowcast);
    // The row itself is passed through untouched, so the recorded numbers stay auditable and the
    // display view can still show the nowcast context from the ledger.
    expect(result.current.withheld[0].edge.market_id).toBe("KXCPI-26SEP09-T0.3");
  });

  it("conserves every row across the two buckets, so nothing vanishes silently", async () => {
    // If the hook ever returned only `edges`, this would look identical to a table with no CPI
    // rows. The count is the thing that distinguishes "withheld and labelled" from "missing".
    const { result } = renderWith([cpiEdge("a"), cpiEdge("b"), laborEdge]);
    await waitFor(() => expect(result.current.loading).toBe(false));

    const read = 3;
    expect(result.current.edges.length + result.current.withheld.length).toBe(read);
    expect(result.current.edges).toHaveLength(1);
    expect(result.current.edges[0].engine).toBe("labor_nowcast");
  });

  it("leaves the other MACRO engine alone: labor is separately ruled and still gated", async () => {
    const { result } = renderWith([laborEdge]);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.edges).toHaveLength(1);
    expect(result.current.withheld).toEqual([]);
  });

  it("reports no error on a successful read", async () => {
    const { result } = renderWith([cpiEdge()]);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeNull();
  });
});

/**
 * A failed read used to be swallowed into `console.error`, leaving `edges: []` and `withheld: []`.
 * Those two empty buckets render as "no opportunities" and "nothing was withheld" respectively --
 * which is the exact "a row that never existed vs. one I could not see" ambiguity the withholding
 * rule was built to remove, reintroduced one layer up.
 */
describe("useMarketEdges — a failed read is a fact, not an empty result", () => {
  it("surfaces the failure instead of returning two empty buckets", async () => {
    const { result } = renderWithFailure("Could not find the table 'public.kalshi_edges'");
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toMatch(/kalshi_edges/);
  });

  it("empties both buckets, so a count from a previous read is not attributed to this one", async () => {
    // A stale successful read left standing next to a fresh failure would be worse than either: the
    // page would render yesterday's numbers as if they were current.
    const { result } = renderWithFailure("boom");
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.edges).toEqual([]);
    expect(result.current.withheld).toEqual([]);
    expect(result.current.truncated).toBe(false);
  });

  it("still clears loading, so a page does not spin for ever on a failure", async () => {
    const { result } = renderWithFailure("boom");
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.loading).toBe(false);
  });
});

/**
 * `.limit(100)` with no `truncated` flag, so the notice's "(N rows)" was a claim about the table
 * when it is a count of the newest 100 rows read. `/api/cpi-display` already solved this by asking
 * for one row more than it needs and treating the extra as the answer.
 */
describe("useMarketEdges — the read is bounded, and says so", () => {
  it("asks for one row more than the limit, so 'there are more' is established not guessed", async () => {
    renderWith([cpiEdge()]);
    await waitFor(() => expect(LIMIT.asked).toBeGreaterThan(0));

    expect(LIMIT.asked).toBe(EDGES_READ_LIMIT + 1);
  });

  it("keeps at most the limit and reports truncation when the sentinel row arrives", async () => {
    const over = [...Array(EDGES_READ_LIMIT + 1).keys()].map((i) => ({
      ...laborEdge,
      id: `e-${i}`,
    }));

    const { result } = renderWith(over);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.edges).toHaveLength(EDGES_READ_LIMIT);
    expect(result.current.truncated).toBe(true);
  });

  it("reports no truncation on a read that filled exactly the limit", async () => {
    // The boundary. A "did I fill the cap?" check written the obvious way is wrong here, and the
    // same boundary is already pinned for the API endpoint's own `truncated`.
    const exact = [...Array(EDGES_READ_LIMIT).keys()].map((i) => ({ ...laborEdge, id: `e-${i}` }));

    const { result } = renderWith(exact);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.edges).toHaveLength(EDGES_READ_LIMIT);
    expect(result.current.truncated).toBe(false);
  });

  it("does not leak the sentinel row into either bucket", async () => {
    const over = [...Array(EDGES_READ_LIMIT + 1).keys()].map((i) => ({ ...laborEdge, id: `e-${i}` }));

    const { result } = renderWith(over);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.edges.some((e) => e.id === `e-${EDGES_READ_LIMIT}`)).toBe(false);
  });
});

/**
 * The three numbers this hook used to invent.
 *
 * `useMarketEdges` normalised `our_prob`, `market_prob` and `edge_pct` with `?? 0`, so a row that
 * recorded neither the column nor a `raw_payload` fallback was handed to every page as a model
 * probability of exactly zero and an edge of exactly 0.0%. Both are specific, confident and false,
 * and both are read as measurements by every consumer: `PredictionLab`'s EdgeCard prints
 * `{edge_pct}% EDGE` and the War Room prints `+{edge_pct}%`. An unmeasured edge reading as 0.0% is
 * "we looked and there is nothing here", which is the single most misleading thing a display can
 * say about a number it does not have -- the same class as the `$0.00` the War Room used to print
 * for a portfolio it had never measured, one screen over.
 *
 * The rule under all of these: a missing figure is `null` in the data and a dash on screen, and a
 * MEASURED zero is a number and is printed as one. Those two cases must never share an expression,
 * which is why the fallback here is a plain `null` rather than another conditional.
 */
describe("useMarketEdges — a figure it did not measure is null, never 0", () => {
  const bare = (id: string, extra: Record<string, unknown> = {}) => ({
    id,
    market_id: `KXCPI-26SEP09-T${id}.3`,
    edge_type: "MACRO",
    engine: "labor_nowcast",
    engine_version: "labor-v1",
    gate_status: "SHADOW",
    discovered_at: "2026-09-27T12:00:00Z",
    raw_payload: {},
    ...extra,
  });

  it("leaves all three null when the row recorded none of them", async () => {
    const { result } = renderWith([bare("1")]);
    await waitFor(() => expect(result.current.loading).toBe(false));

    const row = result.current.edges[0];
    expect(row.our_prob).toBeNull();
    expect(row.market_prob).toBeNull();
    expect(row.edge_pct).toBeNull();
  });

  it("does not turn an absent edge into an edge of zero", async () => {
    // The single most damaging of the three, so it gets its own line: `0.0%` on a card reading
    // "0.0% EDGE" is a measurement, and the reader is entitled to act on a measurement.
    const { result } = renderWith([bare("1", { our_prob: 0.5, market_prob: 0.48 })]);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.edges[0].edge_pct).toBeNull();
  });

  it("does not turn an absent model probability into a model that rates the outcome at zero", async () => {
    const { result } = renderWith([bare("1", { market_prob: 0.48, edge_pct: 4 })]);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.edges[0].our_prob).toBeNull();
    // 0.0 would be a PREDICTION. A reader is entitled to act on a prediction.
    expect(result.current.edges[0].our_prob).not.toBe(0);
  });

  it("still falls back to raw_payload when there is something to fall back to", async () => {
    // The fallback is not the defect; the `0` it degraded into was. `my_prob`/`yes_ask` are percent,
    // `edge` is already in the columns' unit, and the two conversions must not be confused.
    const { result } = renderWith([
      bare("1", { raw_payload: { my_prob: 52, yes_ask: 48, edge: 4 } }),
    ]);
    await waitFor(() => expect(result.current.loading).toBe(false));

    const row = result.current.edges[0];
    expect(row.our_prob).toBeCloseTo(0.52);
    expect(row.market_prob).toBeCloseTo(0.48);
    expect(row.edge_pct).toBe(4);
  });

  it("prefers the column over the payload", async () => {
    const { result } = renderWith([
      bare("1", { our_prob: 0.51, raw_payload: { my_prob: 99 } }),
    ]);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.edges[0].our_prob).toBe(0.51);
  });

  it("keeps a measured zero a number, because zero is a measurement and null is not", async () => {
    // The two must never share an expression. The old truthiness test on the payload fallback sent
    // a recorded `my_prob: 0` down the "no value" branch, so a real zero and a missing figure were
    // indistinguishable -- which is how a `?? 0` gets added in the first place.
    const { result } = renderWith([
      bare("1", { our_prob: 0, market_prob: 0, edge_pct: 0 }),
    ]);
    await waitFor(() => expect(result.current.loading).toBe(false));

    const row = result.current.edges[0];
    expect(row.our_prob).toBe(0);
    expect(row.market_prob).toBe(0);
    expect(row.edge_pct).toBe(0);
  });

  it("keeps a measured zero in raw_payload a number too", async () => {
    const { result } = renderWith([bare("1", { raw_payload: { my_prob: 0 } })]);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.edges[0].our_prob).toBe(0);
  });

  it("leaves a non-numeric figure absent rather than coercing it", async () => {
    // `Number.isFinite` on purpose: NaN and Infinity are numbers to `typeof` and are not figures.
    const { result } = renderWith([
      bare("1", { our_prob: Number.NaN, market_prob: Number.POSITIVE_INFINITY, edge_pct: "4" }),
    ]);
    await waitFor(() => expect(result.current.loading).toBe(false));

    const row = result.current.edges[0];
    expect(row.our_prob).toBeNull();
    expect(row.market_prob).toBeNull();
    expect(row.edge_pct).toBeNull();
  });

  it("withholds a figure in the same way whether the row is an edge or a display-only one", async () => {
    // The partition runs on the normalised rows, so a null has to survive being split. A row that
    // recorded nothing is still a row, and the withholding bucket still counts it.
    const { result } = renderWith([{ ...bare("1"), engine: "cpi_nowcast" }]);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.withheld).toHaveLength(1);
    expect(result.current.withheld[0].edge.edge_pct).toBeNull();
    expect(result.current.withheld[0].edge.our_prob).toBeNull();
  });
});
