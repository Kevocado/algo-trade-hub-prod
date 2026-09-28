import { describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import { useMarketEdges } from "@/hooks/useMarketEdges";
import { DISPLAY_ONLY_REASON } from "@/lib/displayOnlyEngines";

/**
 * The read half of Ruling 1, and the reason this task is not one line.
 *
 * `scan_cpi` no longer writes CPI edges, but the rows already in `kalshi_edges` are NOT deleted --
 * no migration, per the ruling. They stay, and `useMarketEdges` is the single read every page in
 * this product goes through, so it is the only place a standing rule can hold. It must therefore
 * stop handing those rows to a caller as opportunities, and it must hand them over WITH the reason
 * rather than dropping them: a row that is read and then silently omitted is indistinguishable from
 * there having been no rows, and a reader seeing the MACRO tab go quiet would conclude the engine
 * was retired rather than relabelled.
 *
 * This tests the HOOK, not just the pure partition function, because the hook is what the ruling is
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
// has to be hoisted above the hook's import rather than installed inside a helper. `ROWS` is a
// mutable binding the tests reassign before rendering.
const ROWS: { current: unknown[] } = { current: [] };

vi.mock("@/lib/supabase", () => {
  const channel = { on: vi.fn().mockReturnThis(), subscribe: vi.fn().mockReturnThis() };
  return {
    supabase: {
      from: vi.fn(() => ({
        select: vi.fn().mockReturnThis(),
        order: vi.fn().mockReturnThis(),
        limit: vi.fn().mockResolvedValue({ data: ROWS.current, error: null }),
      })),
      channel: vi.fn(() => channel),
      removeChannel: vi.fn(),
    },
  };
});

// No afterEach restore here on purpose. `restoreAllMocks` also resets the hoisted module factory's
// spies, and `channel` is then undefined for the next test -- the hook calls `.subscribe()` on it
// during the effect, which is how the real-time subscription is set up. ROWS is the only per-test
// state, and renderWith reassigns it.

/** Render the hook against a stubbed Supabase read of `rows`. */
function renderWith(rows: unknown[]) {
  ROWS.current = rows;
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
});
