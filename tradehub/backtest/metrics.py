"""Per-fill P&L and prediction rows shaped for tradehub.track_record."""

from __future__ import annotations

from typing import Any

from tradehub.backtest.fills import Fill
from tradehub.backtest.kalshi_history import Candle
from tradehub.settlement import brier_score


def fill_pnl(fill: Fill, result: str) -> float:
    payout = 1.0 if fill.side == result else 0.0
    return (payout - fill.price) * fill.contracts - fill.fee


def max_drawdown(pnls: list[float]) -> float:
    peak = cum = 0.0
    worst = 0.0
    for pnl in pnls:
        cum += pnl
        peak = max(peak, cum)
        worst = max(worst, peak - cum)
    return worst


def market_mid(candle: Candle | None) -> float | None:
    if candle is None or candle.yes_bid is None or candle.yes_ask is None:
        return None
    return (candle.yes_bid + candle.yes_ask) / 2.0


def prediction_row(our_prob: float, market_prob: float | None, result: str) -> dict[str, Any]:
    outcome = 1 if result == "yes" else 0
    return {
        "our_prob": our_prob,
        "market_prob": market_prob,
        "result": result,
        "brier": brier_score(our_prob, outcome),
        "market_brier": None if market_prob is None else brier_score(market_prob, outcome),
        "status": "SETTLED",
    }
