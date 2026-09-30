"""Shared plumbing for forecasters whose targets are Kalshi markets (v2 spec §5, §10 baselines).

A Kalshi-linked target is one market ticker, prefixed `kalshi:`. It is registered and frozen only
inside `FREEZE_LEAD` of the market close, so every forecaster (and the market mid it is compared
with) is frozen at the same horizon instead of whenever the market happened to be listed. It
settles on Kalshi's own result, exactly like `tradehub.settlement` settles `predictions`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from tradehub.data.kalshi_live import LiveMarket
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.settlement import SETTLED, parse_market_result

FREEZE_LEAD = timedelta(hours=24)
TARGET_PREFIX = "kalshi:"
SETTLEMENT_SOURCE = "kalshi:market_result"


def kalshi_target(ticker: str) -> str:
    return f"{TARGET_PREFIX}{ticker}"


def ticker_of(target: str) -> str:
    if not target.startswith(TARGET_PREFIX):
        raise ValueError(f"not a Kalshi target: {target!r}")
    return target[len(TARGET_PREFIX):]


def quote_mid(lm: LiveMarket) -> float | None:
    """Mid of the top of book; None when either side is empty (same rule as the scan's `_mid`)."""
    if lm.quote.yes_bid is None or lm.quote.yes_ask is None:
        return None
    return (lm.quote.yes_bid + lm.quote.yes_ask) / 2.0


def quote_payload(lm: LiveMarket) -> dict[str, float | None]:
    """The frozen top of book, recorded in every market-linked forecast so its edge can be netted of costs."""
    return {"yes_bid": lm.quote.yes_bid, "yes_ask": lm.quote.yes_ask}


def in_freeze_window(lm: LiveMarket, now: datetime, lead: timedelta = FREEZE_LEAD) -> bool:
    return now < lm.market.close_time <= now + lead


def entry_for(lm: LiveMarket, family: str, cadence: str) -> CalendarEntry:
    return CalendarEntry(kalshi_target(lm.market.ticker), family, cadence, lm.market.close_time, market_linked=True)


def settle_on_kalshi(target: str, fetch_market: Callable[[str], Any]) -> Settlement | None:
    """Kalshi's final yes/no, or None while it is open. A voided market never settles (None forever)."""
    disposition, outcome = parse_market_result(fetch_market(ticker_of(target)))
    if disposition != SETTLED or outcome is None:
        return None
    return Settlement(target, outcome, SETTLEMENT_SOURCE)


class KalshiImplied:
    """The market pseudo-forecaster: freezes the Kalshi mid as its probability.

    It is the baseline the model forecasters are graded against, shown beside them on the journal.
    Its BSS against the market is 0 by construction, so it can never be promoted; that is intended.
    """

    version = "v1"

    def __init__(self, family: str, series: tuple[str, ...], cadence: str, live, fetch_market: Callable[[str], Any],
                 *, keep: Callable[[LiveMarket], bool] = lambda lm: True):
        self.name = f"kalshi_implied_{family}"
        self.family, self.series, self.cadence = family, series, cadence
        self._live, self._fetch_market, self._keep = live, fetch_market, keep
        self._open: dict[str, LiveMarket] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): lm for s in self.series for lm in self._live.open_markets(s)
                      if in_freeze_window(lm, now) and self._keep(lm)}
        return [entry_for(lm, self.family, self.cadence) for lm in self._open.values()]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        mid = quote_mid(lm) if lm else None
        if mid is None:
            return None
        return Forecast(self.name, self.version, entry.target, mid, market_prob=mid,
                        payload=quote_payload(lm))

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)
