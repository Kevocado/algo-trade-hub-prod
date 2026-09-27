import { describe, expect, it } from "vitest";

import { moneyMetric, type PortfolioBook } from "./portfolioTruth";

/**
 * `$0.00` is still invented on the War Room's home page.
 *
 * `PnLSummary` carries no `daily_pnl` and no `cash_balance`, so `metrics?.daily_pnl ?? 0` is not a
 * measured zero — it is a missing number rendered as a confident one, under headings that then claim
 * "Live equity" and "Real-time profit/loss for the current 24h cycle". This product places no orders
 * (spec section 6), so all three of those figures are unknown, not zero.
 *
 * The distinction that matters: a zero is a measurement that can be acted on. `null` is the absence of
 * one. Rendering the second as the first is the exact defect the sidebar fix addressed, one page over.
 */
const SUGGEST_ONLY: PortfolioBook = { suggest_only: true };
const REAL_BOOK: PortfolioBook = { suggest_only: false };

describe("moneyMetric", () => {
  it("renders a dash, not a zero, when the product keeps no book", () => {
    const m = moneyMetric(undefined, SUGGEST_ONLY);

    expect(m.value).toBe("—");
    expect(m.known).toBe(false);
    expect(m.value).not.toMatch(/\$0\.00/);
  });

  it("renders a dash when a single figure is null, even in a real book", () => {
    // cash_balance is null while total_value is known: one missing number must not blank the rest.
    expect(moneyMetric(null, REAL_BOOK).known).toBe(false);
    expect(moneyMetric(1234.5, REAL_BOOK).known).toBe(true);
  });

  it("says why the figure is unknown", () => {
    expect(moneyMetric(undefined, SUGGEST_ONLY).note).toMatch(/no orders/i);
    expect(moneyMetric(null, REAL_BOOK).note).toMatch(/not reported/i);
  });

  it("formats a real figure", () => {
    expect(moneyMetric(1234.5, REAL_BOOK).value).toBe("$1,234.50");
  });

  it("signs a positive P&L but never produces a double sign", () => {
    expect(moneyMetric(12, REAL_BOOK, { signed: true }).value).toBe("+$12.00");
    expect(moneyMetric(0, REAL_BOOK, { signed: true }).value).toBe("$0.00");
  });

  it("keeps a negative P&L negative rather than writing +-$12.00", () => {
    // The page's own expression was `{isPnLPositive ? '+' : ''}${...}`, so a negative
    // dailyPnL rendered as "$-12.00". Formatting must own the sign, not the caller.
    expect(moneyMetric(-12, REAL_BOOK, { signed: true }).value).toBe("-$12.00");
  });

  it("treats a missing book the same as a suggest-only one", () => {
    expect(moneyMetric(undefined, null).known).toBe(false);
    expect(moneyMetric(undefined, undefined).value).toBe("—");
  });
});
