import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import { isSuggestOnly, type PortfolioBook } from "@/lib/portfolioTruth";

/**
 * The War Room's money read, through the hub's own API.
 *
 * It used to query `kalshi_portfolio` and `portfolio_metrics` directly from the browser with the
 * publishable Supabase key and subscribe to a realtime channel. That put the database in the
 * browser's data path — the key shipped in the bundle, RLS had to be opened to the anon role for it
 * to read anything at all, and the sidebar rendered "LIVE BALANCE $0.00" from an empty table plus a
 * row of zeros last touched in March. One data path, server-side, and the API says what the product
 * is instead of implying a balance.
 */
export interface PortfolioBook_ extends PortfolioBook {
  suggest_only: boolean;
}

function fromSummary(body: Record<string, unknown>): PortfolioBook_ {
  const cents = body.total_pnl_cents;
  return {
    total_value: typeof cents === "number" ? cents / 100 : null,
    daily_pnl: typeof body.daily_pnl === "number" ? body.daily_pnl : null,
    cash_balance: typeof body.cash_balance === "number" ? body.cash_balance : null,
    // An older payload without the flag reads as suggest-only: claiming a live book we cannot
    // evidence is the worse error.
    suggest_only: isSuggestOnly(body as PortfolioBook),
  };
}

export interface PaperPosition {
  // The paper_trades ledger's own columns, not an ad-hoc JSON blob's shape: the old fields
  // (position, average_price, current_price, total_traded) never existed in any migration.
  engine?: string | null;
  ticker?: string | null;
  action?: string | null;
  side?: string | null;
  contracts?: number | null;
  avg_cost_cents?: number | null;
  exit_price_cents?: number | null;
  pnl_cents?: number | null;
  edge_pct?: number | null;
  model_prob?: number | null;
  status?: string | null;
}

export function usePortfolio() {
  const [portfolio, setPortfolio] = useState<PortfolioBook_ | null>(null);
  const [positions, setPositions] = useState<PaperPosition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch(buildApiUrl("/api/pnl_summary"));
        if (!response.ok) throw new Error(`Request failed with status ${response.status}`);
        const body = await response.json();
        if (!cancelled) {
          setPortfolio(fromSummary(body));
          setError(null);
        }
        // Positions come from the API too, not from a browser-side table read. Empty is the honest
        // answer for a suggest-only product, and `suggest_only` says why.
        const positionsResponse = await fetch(buildApiUrl("/api/positions"));
        if (positionsResponse.ok && !cancelled) {
          setPositions((await positionsResponse.json()) as PaperPosition[]);
        }
      } catch (err) {
        // A failed read is `null`, never a zero. Zero is a claim.
        if (!cancelled) {
          setPortfolio(null);
          setError(err instanceof Error ? err.message : "Unknown error");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return { portfolio, positions, loading, error };
}

export function usePortfolioMetrics() {
  const [metrics, setMetrics] = useState<PortfolioBook_ | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch(buildApiUrl("/api/pnl_summary"));
        if (!response.ok) throw new Error(`Request failed with status ${response.status}`);
        const body = await response.json();
        if (!cancelled) setMetrics(fromSummary(body));
      } catch {
        if (!cancelled) setMetrics(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return { metrics, loading };
}
