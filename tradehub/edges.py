"""Edge layer: after-fee edge vs executable quotes, maker-first, no taker longshots (spec §4.3)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Quote:
    yes_bid: float | None
    yes_ask: float | None
    yes_bid_size: float
    yes_ask_size: float
