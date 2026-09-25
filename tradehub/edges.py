"""Edge layer: after-fee edge vs executable quotes, maker-first, no taker longshots (spec §4.3)."""

from __future__ import annotations

from dataclasses import dataclass

from shared.kalshi_fees import net_edge_pct

MIN_TAKER_PRICE = 0.10


@dataclass(frozen=True)
class Quote:
    yes_bid: float | None
    yes_ask: float | None
    yes_bid_size: float
    yes_ask_size: float


@dataclass(frozen=True)
class EdgeSuggestion:
    market_ticker: str
    side: str
    entry_price: float
    maker: bool
    net_edge_pct: float
    our_prob: float
    market_prob: float | None


def best_side(
    our_prob: float, yes_price: float, no_price: float, *, maker: bool, contracts: int = 1
) -> tuple[str, float, float]:
    """(side, price, net edge in pct points) for whichever of YES/NO has the larger after-fee edge."""
    yes_edge = net_edge_pct(our_prob * 100.0, yes_price * 100.0, contracts=contracts, maker=maker)
    no_edge = net_edge_pct((1.0 - our_prob) * 100.0, no_price * 100.0, contracts=contracts, maker=maker)
    if yes_edge >= no_edge:
        return "yes", yes_price, yes_edge
    return "no", no_price, no_edge


def evaluate_edge(
    market_ticker: str, our_prob: float, quote: Quote, *, min_edge_pct: float, prefer_maker: bool = True
) -> EdgeSuggestion | None:
    if quote.yes_bid is None or quote.yes_ask is None:
        return None
    mid = (quote.yes_bid + quote.yes_ask) / 2.0
    if prefer_maker:
        side, limit, edge = best_side(our_prob, quote.yes_bid, round(1.0 - quote.yes_ask, 4), maker=True)
        if edge > 0 and edge >= min_edge_pct and 0.0 < limit < 1.0:
            return EdgeSuggestion(market_ticker, side, limit, True, edge, our_prob, mid)
    side, price, edge = best_side(our_prob, quote.yes_ask, round(1.0 - quote.yes_bid, 4), maker=False)
    if edge > 0 and edge >= min_edge_pct and price >= MIN_TAKER_PRICE:
        return EdgeSuggestion(market_ticker, side, price, False, edge, our_prob, mid)
    return None
