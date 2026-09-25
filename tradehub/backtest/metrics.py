"""Per-fill P&L and prediction rows shaped for tradehub.track_record."""

from __future__ import annotations

import math
from typing import Any

from tradehub.backtest.fills import Fill
from tradehub.backtest.kalshi_history import Candle
from tradehub.settlement import brier_score

LOG_LOSS_EPSILON = 1e-15


def _binary_outcome(outcome: str | int) -> int:
    if outcome in ("yes", 1, True):
        return 1
    if outcome in ("no", 0, False):
        return 0
    raise ValueError(f"outcome must be yes/no or 1/0, got {outcome!r}")


def log_loss(prob: float, outcome: str | int) -> float:
    """Binary log loss with probabilities clipped away from zero and one."""
    y = _binary_outcome(outcome)
    probability = float(prob) if y else 1.0 - float(prob)
    clipped = min(max(probability, LOG_LOSS_EPSILON), 1.0 - LOG_LOSS_EPSILON)
    return -math.log(clipped)


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
    outcome = _binary_outcome(result)
    return {
        "our_prob": our_prob,
        "market_prob": market_prob,
        "result": result,
        "brier": brier_score(our_prob, outcome),
        "market_brier": None if market_prob is None else brier_score(market_prob, outcome),
        "log_loss": log_loss(our_prob, outcome),
        "status": "SETTLED",
    }
