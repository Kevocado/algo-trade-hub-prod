import { describe, expect, it } from "vitest";

import { describePortfolio, portfolioHeadline } from "./portfolioTruth";

/**
 * The War Room header read `kalshi_portfolio` (empty) and `portfolio_metrics` (a stale row of
 * zeros from 2026-03-24) straight from Supabase in the browser, and rendered the result as
 * "LIVE BALANCE $0.00". A confident $0.00 reads as a flat book. This product places no orders
 * (spec section 6), so the header has to say that instead of implying a balance.
 */
describe("portfolioHeadline", () => {
  it("says no orders are placed instead of rendering a zero balance", () => {
    const zero = { total_value: 0, daily_pnl: 0, cash_balance: 0, suggest_only: true };

    expect(portfolioHeadline(zero)).toEqual({
      label: "Suggest-only",
      value: "No orders placed",
      tone: "muted",
    });
  });

  it("shows real figures when the product ever does keep a book", () => {
    const book = { total_value: 1234.5, daily_pnl: -12.25, cash_balance: 900, suggest_only: false };

    expect(portfolioHeadline(book)).toEqual({
      label: "Live Balance",
      value: "$1,234.50",
      tone: "default",
    });
  });

  it("treats a missing payload as unknown rather than as zero", () => {
    expect(portfolioHeadline(null).value).not.toMatch(/\$0\.00/);
    expect(portfolioHeadline(null).tone).toBe("muted");
  });
});

describe("describePortfolio", () => {
  it("names the reason a figure is absent instead of rendering a bare dash", () => {
    const copy = describePortfolio({ suggest_only: true, total_paper_trades: 0 });

    expect(copy).toMatchObject({ headline: expect.stringContaining("no orders") });
  });

  it("does not describe an empty ledger as a losing or winning record", () => {
    const copy = describePortfolio({ suggest_only: true, total_paper_trades: 0 });

    expect(copy.body).not.toMatch(/win|loss|lose|profit/i);
  });
});
