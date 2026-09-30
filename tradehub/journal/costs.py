"""What trading a frozen forecast would have cost (v2 spec §10, §12).

The journal's headline edge is model probability minus the market mid, which is gross of both the
Kalshi taker fee and the half-spread paid to cross the book. Promotion needs the edge *net* of those
costs, so this module replays each settled, market-linked forecast as a one-contract taker trade:
buy the side with the larger after-fee edge at its visible ask, only when that edge is positive and the
price clears the no-longshot floor (`edges.MIN_TAKER_PRICE`), and settle it at 0 or 100 cents. It uses
the same `best_side` and `kalshi_fee_cents` as the live edge layer, so the two cannot disagree.
"""

from __future__ import annotations

from typing import Any

from shared.kalshi_fees import kalshi_fee_cents
from tradehub.edges import MIN_TAKER_PRICE, best_side


def frozen_quote(payload: dict[str, Any] | None) -> tuple[float, float] | None:
    """(yes_bid, yes_ask) in dollars from a forecast payload, or None when either side was not recorded."""
    bid, ask = (payload or {}).get("yes_bid"), (payload or {}).get("yes_ask")
    if bid is None or ask is None or not 0.0 <= float(bid) <= float(ask) <= 1.0:
        return None
    return float(bid), float(ask)


def simulated_trade(our_prob: float, yes_bid: float, yes_ask: float, outcome: int) -> dict[str, float] | None:
    """The one-contract taker trade the forecast would have made, or None when it would not trade."""
    side, price, edge_pct = best_side(our_prob, yes_ask, round(1.0 - yes_bid, 4), maker=False)
    if edge_pct <= 0 or price < MIN_TAKER_PRICE:
        return None
    won = outcome == 1 if side == "yes" else outcome == 0
    fee = kalshi_fee_cents(price * 100.0)
    gross = (100.0 if won else 0.0) - price * 100.0
    return {"gross_cents": gross, "fee_cents": fee, "net_cents": gross - fee}


def cost_summary(pairs: list[dict[str, Any]]) -> dict[str, float | int]:
    """Totals over settled forecasts: how many carried a quote, how many would have traded, and the P&L."""
    quoted = traded = 0
    gross = fees = 0.0
    for row in pairs:
        quote = frozen_quote(row.get("payload"))
        if quote is None:
            continue
        quoted += 1
        trade = simulated_trade(float(row["probability"]), quote[0], quote[1], int(row["outcome"]))
        if trade is None:
            continue
        traded += 1
        gross += trade["gross_cents"]
        fees += trade["fee_cents"]
    return {"n_quoted": quoted, "n_traded": traded, "gross_pnl_cents": round(gross, 2),
            "fees_cents": round(fees, 2), "net_pnl_cents": round(gross - fees, 2)}
