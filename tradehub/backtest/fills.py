"""Conservative Kalshi fill model: taker at the visible ask, maker only on a printed trade."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from shared.kalshi_fees import kalshi_fee_cents
from tradehub.backtest.kalshi_history import Candle, Trade
from tradehub.backtest.pit import Decision
from tradehub.edges import MIN_TAKER_PRICE, best_side


@dataclass(frozen=True)
class Fill:
    market_ticker: str
    side: str
    price: float
    contracts: int
    fee: float
    filled_at: datetime
    maker: bool


def quote_at(candles: list[Candle], at: datetime) -> Candle | None:
    """Last candle that ended at or before `at` with both quotes present."""
    visible = [c for c in candles if c.end_ts <= at and c.yes_bid is not None and c.yes_ask is not None]
    return visible[-1] if visible else None


def _fee_dollars(price: float, contracts: int, maker: bool) -> float:
    return kalshi_fee_cents(price * 100.0, contracts=contracts, maker=maker) / 100.0


def taker_fill(decision: Decision, candles: list[Candle], *, contracts: int = 1, min_edge_pct: float = 0.0) -> Fill | None:
    quote = quote_at(candles, decision.decided_at)
    if quote is None:
        return None
    side, price, edge = best_side(
        decision.our_prob,
        quote.yes_ask,
        1.0 - quote.yes_bid,
        maker=False,
        contracts=contracts,
    )
    if edge <= 0 or edge < min_edge_pct or price < MIN_TAKER_PRICE:
        return None
    return Fill(decision.market_ticker, side, price, contracts, _fee_dollars(price, contracts, False),
                decision.decided_at, maker=False)


def maker_fill(
    decision: Decision,
    candles: list[Candle],
    trades: list[Trade],
    close_time: datetime,
    *,
    contracts: int = 1,
    min_edge_pct: float = 0.0,
) -> Fill | None:
    quote = quote_at(candles, decision.decided_at)
    if quote is None:
        return None
    side, limit, edge = best_side(
        decision.our_prob,
        quote.yes_bid,
        1.0 - quote.yes_ask,
        maker=True,
        contracts=contracts,
    )
    if edge <= 0 or edge < min_edge_pct or not 0.0 < limit < 1.0:
        return None
    qualifying_count = 0.0
    qualifying_trades = sorted(
        trades,
        key=lambda trade: (trade.created_at, trade.taker_side, trade.yes_price, trade.no_price, trade.count),
    )
    for trade in qualifying_trades:
        if trade.is_block_trade or trade.count <= 0 or not decision.decided_at < trade.created_at <= close_time:
            continue
        qualifies = (
            side == "yes" and trade.taker_side == "no" and trade.yes_price <= limit
        ) or (
            side == "no" and trade.taker_side == "yes" and trade.no_price <= limit
        )
        if not qualifies:
            continue
        qualifying_count += trade.count
        if qualifying_count >= contracts:
            return Fill(
                decision.market_ticker,
                side,
                limit,
                contracts,
                _fee_dollars(limit, contracts, True),
                trade.created_at,
                maker=True,
            )
    return None
