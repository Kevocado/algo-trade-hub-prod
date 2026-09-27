import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import { usePortfolio } from "@/hooks/usePortfolio";
import { moneyMetric, portfolioHeadline } from "@/lib/portfolioTruth";

/**
 * Item 4 of the #20 review: confirm the page degrades gracefully when
 * `20260416000011_war_room_tables.sql` has not been applied.
 *
 * Without that migration `paper_trades` does not exist, so `/api/pnl_summary` and `/api/positions`
 * return 503 — deliberately, naming the migration rather than returning an empty book that would read
 * as "you are flat". The consequence for this page is the thing worth pinning: a failed read has to
 * render as **unknown**, exactly as a null field does. If it rendered as a zero, applying the
 * migration would be the only thing standing between the product and a false claim, and the failure
 * mode would be invisible until someone checked.
 *
 * The 503 body deliberately says `table 'paper_trades' is not in the database. Apply ...` — so the
 * hook's error is the actionable one, and the page shows a dash rather than a number.
 */
const MIGRATION_503 = {
  detail:
    "table 'paper_trades' is not in the database. Apply " +
    "market_sentiment_tool/supabase/migrations/20260416000011_war_room_tables.sql and redeploy.",
};

function mockFetch(handler: (url: string) => { ok: boolean; status: number; body?: unknown }) {
  const spy = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const { ok, status, body } = handler(url);
    return {
      ok,
      status,
      json: async () => body ?? {},
    } as Response;
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("usePortfolio when the paper_trades migration is not applied", () => {
  it("treats a 503 as unknown rather than as a zero balance", async () => {
    mockFetch(() => ({ ok: false, status: 503, body: MIGRATION_503 }));

    const { result } = renderHook(() => usePortfolio());
    await waitFor(() => expect(result.current.loading).toBe(false));

    // null, not a zero-initialised book. A zero here is a claim the API never made.
    expect(result.current.portfolio).toBeNull();
    expect(result.current.error).toBeTruthy();
  });

  it("renders the same unknown treatment a null field would get", async () => {
    mockFetch(() => ({ ok: false, status: 503, body: MIGRATION_503 }));

    const { result } = renderHook(() => usePortfolio());
    await waitFor(() => expect(result.current.loading).toBe(false));

    // The header and every money card go through these, so this is the whole visible consequence.
    expect(portfolioHeadline(result.current.portfolio)).toEqual({
      label: "Suggest-only",
      value: "No orders placed",
      tone: "muted",
    });
    for (const value of [undefined, null]) {
      const metric = moneyMetric(value, result.current.portfolio);
      expect(metric.known).toBe(false);
      expect(metric.value).toBe("—");
    }
  });

  it("keeps the positions table on its honest empty state rather than a fabricated one", async () => {
    mockFetch(() => ({ ok: false, status: 503, body: MIGRATION_503 }));

    const { result } = renderHook(() => usePortfolio());
    await waitFor(() => expect(result.current.loading).toBe(false));

    // Home renders a fixed "This product places no orders" row when this is empty, so an empty list
    // is a true statement. A list built from a failed read would not be.
    expect(result.current.positions).toEqual([]);
  });

  it("surfaces the migration name from the API rather than a generic failure", async () => {
    mockFetch(() => ({ ok: false, status: 503, body: MIGRATION_503 }));

    const { result } = renderHook(() => usePortfolio());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toContain("20260416000011_war_room_tables.sql");
  });
});

describe("usePortfolio when the API is reachable", () => {
  it("reads suggest-only from the payload and does not invent figures the API omitted", async () => {
    mockFetch((url) =>
      url.includes("/api/pnl_summary")
        ? {
            ok: true,
            status: 200,
            body: {
              total_paper_trades: 0, winning_trades: 0, win_rate_pct: 0,
              total_pnl_cents: 0, avg_edge_pct: 0, largest_win_cents: 0, largest_loss_cents: 0,
              as_of: "2026-09-27T00:00:00Z", suggest_only: true,
              // daily_pnl and cash_balance are absent, as they are in the real PnLSummary.
            },
          }
        : { ok: true, status: 200, body: [] },
    );

    const { result } = renderHook(() => usePortfolio());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.portfolio?.suggest_only).toBe(true);
    expect(result.current.error).toBeNull();
    // A total_pnl_cents of 0 must not become a $0.00 "live equity" figure.
    expect(moneyMetric(result.current.portfolio?.total_value, result.current.portfolio).value).toBe("—");
    expect(result.current.positions).toEqual([]);
  });
});
