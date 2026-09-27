/**
 * What the War Room is allowed to claim about money.
 *
 * The header used to read `kalshi_portfolio` and `portfolio_metrics` directly from Supabase in the
 * browser and render the result as "LIVE BALANCE $0.00" — a confident zero that reads as a flat
 * book. This product places no orders (spec section 6), and the tables it was reading are empty or
 * stale, so the honest thing is to say what the product is rather than render a number nobody can
 * act on. Everything here is pure so it can be tested without a browser or a network.
 */

export interface PortfolioBook {
  total_value?: number | null;
  daily_pnl?: number | null;
  cash_balance?: number | null;
  /** From the API's PnLSummary. Absent means an older payload, which we treat as suggest-only. */
  suggest_only?: boolean;
}

export interface Headline {
  label: string;
  value: string;
  tone: "default" | "muted";
}

function money(value: number): string {
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** True unless the payload positively says this product keeps a real book. */
export function isSuggestOnly(book: PortfolioBook | null | undefined): boolean {
  if (!book) return true;
  return book.suggest_only !== false;
}

export function portfolioHeadline(book: PortfolioBook | null | undefined): Headline {
  if (isSuggestOnly(book)) {
    // Not "$0.00": a zero balance is a claim, and this one was false.
    return { label: "Suggest-only", value: "No orders placed", tone: "muted" };
  }
  const total = book?.total_value;
  if (typeof total !== "number" || !Number.isFinite(total)) {
    return { label: "Live Balance", value: "Unavailable", tone: "muted" };
  }
  return { label: "Live Balance", value: money(total), tone: "default" };
}

export interface PortfolioCopy {
  headline: string;
  body: string;
}

/**
 * The sentence under the headline. Its job is to stop the reader interpreting an empty ledger as a
 * result, so it must never contain a win/loss word when nothing has been traded.
 */
export function describePortfolio(summary: {
  suggest_only?: boolean;
  total_paper_trades?: number;
  winning_trades?: number;
} | null | undefined): PortfolioCopy {
  if (isSuggestOnly(summary) || !summary?.total_paper_trades) {
    return {
      headline: "This product places no orders",
      body:
        "Every number on this site is a suggestion with the reasoning behind it. " +
        "An engine is only promoted once its settled results beat the market after fees.",
    };
  }
  const { winning_trades = 0, total_paper_trades: total = 0 } = summary;
  const pct = total ? Math.round((winning_trades / total) * 100) : 0;
  return {
    headline: `${winning_trades} of ${total} correct`,
    body: "Paper record only. No order has been placed with real money.",
  };
}
