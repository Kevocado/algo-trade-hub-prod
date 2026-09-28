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
