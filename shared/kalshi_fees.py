"""
kalshi_fees.py — Kalshi's exact fee formula, shared across sports engines.

Kalshi's published general fee schedule rounds the total fee for an order
up to the next cent. With P expressed as a probability in [0, 1] and C as
the number of contracts:
    taker fee = round_up(0.07 * C * P * (1 - P)) dollars
    maker fee = round_up(0.0175 * C * P * (1 - P)) dollars
The maker rate is 25% of the taker rate for the markets that charge maker
fees. This helper returns cents, so it rounds the calculated cent amount
once, after applying the contract count.

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
    Returns the total fee, in whole cents, for trading `contracts` contracts
    at `price_cents` (e.g. 45.0 for a 45c YES contract).
    """
    if contracts <= 0:
        return 0.0
    probability = max(min(price_cents / 100.0, 1.0), 0.0)
    raw_taker_cents = TAKER_RATE * contracts * probability * (1.0 - probability) * 100.0
    raw_cents = raw_taker_cents * MAKER_SHARE if maker else raw_taker_cents
    return float(math.ceil(raw_cents))


def net_edge_pct(model_prob_pct: float, kalshi_price_cents: float, *, contracts: int = 1, maker: bool = False) -> float:
    """
    Edge in percentage points after subtracting Kalshi's per-contract fee.
    The fee always works against the position, regardless of direction.
    """
    gross_edge_pct = model_prob_pct - kalshi_price_cents
    fee_cents_total = kalshi_fee_cents(kalshi_price_cents, contracts=contracts, maker=maker)
    fee_pct_per_contract = fee_cents_total / contracts
    return gross_edge_pct - fee_pct_per_contract
