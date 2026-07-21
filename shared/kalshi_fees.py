"""
kalshi_fees.py — Kalshi's exact fee formula, shared across sports engines.

Per the current published fee schedule (kalshi.com/docs/kalshi-fee-schedule.pdf):
    taker_fee_dollars = ceil(0.07 * contracts * P * (1 - P) * 100) / 100
    maker_fee_dollars = ceil(0.25 * (0.07 * contracts * P * (1 - P) * 100)) / 100
where P is price expressed as a probability in [0, 1] (a 45c contract is
P=0.45). Fee peaks at the 50c price point (1.75% of notional) and shrinks
toward the extremes.

Each Kalshi contract has $1 notional, so a fee expressed in cents is
numerically the same as a fee expressed in percentage points of edge on a
single contract — that lets net_edge_pct() subtract fee cents directly
from a model-vs-market edge expressed in percentage points.
"""
from __future__ import annotations

import math

TAKER_RATE = 0.07
MAKER_SHARE = 0.25


def kalshi_fee_cents(price_cents: float, *, contracts: int = 1, maker: bool = False) -> float:
    """
    Returns the total fee, in cents, for trading `contracts` contracts at
    `price_cents` (e.g. 45.0 for a 45c YES contract).
    """
    if contracts <= 0:
        return 0.0
    probability = max(min(price_cents / 100.0, 1.0), 0.0)
    raw_taker_cents = TAKER_RATE * contracts * probability * (1.0 - probability) * 100.0
    if maker:
        return math.ceil(MAKER_SHARE * raw_taker_cents * 100) / 100.0
    return math.ceil(raw_taker_cents * 100) / 100.0


def net_edge_pct(model_prob_pct: float, kalshi_price_cents: float, *, contracts: int = 1, maker: bool = False) -> float:
    """
    Edge in percentage points after subtracting Kalshi's per-contract fee.
    The fee always works against the position, regardless of direction.
    """
    gross_edge_pct = model_prob_pct - kalshi_price_cents
    fee_cents_total = kalshi_fee_cents(kalshi_price_cents, contracts=contracts, maker=maker)
    fee_pct_per_contract = fee_cents_total / contracts
    if gross_edge_pct >= 0:
        return gross_edge_pct - fee_pct_per_contract
    return gross_edge_pct + fee_pct_per_contract
