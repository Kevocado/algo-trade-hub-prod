"""FOMC decision, experimental (v2 spec §5, ruling Q5): P(the Fed holds) mapped from the CPI nowcast.

There is no FOMC model. This is a small fixed mapping, published so the journal can show whether it
beats the Kalshi pseudo-forecaster it ships beside (it is expected not to; it is the first candidate
for `retired`). Target: the "Fed maintains rate" market (`KXFEDDECISION-<meeting>-H0`) of each meeting.

Mapping (constants fixed a priori, never tuned on journal outcomes):
    annualized core CPI  a = latest core nowcast (m/m %) x 12
    logit P(hold) = logit(HOLD_PRIOR) - SLOPE x max(0, |a - TARGET| - BAND)
Inflation near target -> the base-rate hold probability; far from target in either direction ->
more likely to move. Labor is not an input in v1: the payroll nowcast only exists in the few days
between a reference month's end and its release, which rarely brackets a meeting.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime
from typing import Any

from tradehub.data.cleveland_fed import fetch_nowcast_history
from tradehub.data.kalshi_live import LiveMarket
from tradehub.engines.cpi import latest_nowcast
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.kalshi_linked import entry_for, in_freeze_window, kalshi_target, quote_mid, settle_on_kalshi

FOMC_SERIES = "KXFEDDECISION"
HOLD_SUFFIX = "-H0"
HOLD_PRIOR = 0.70  # share of scheduled FOMC meetings with no change, order of magnitude since 1994
INFLATION_TARGET = 2.0
BAND = 0.5  # pp of annualized core inflation treated as "at target"
SLOPE = 1.0  # logit units per pp outside the band


def is_hold_market(lm: LiveMarket) -> bool:
    return lm.market.series_ticker == FOMC_SERIES and lm.market.ticker.endswith(HOLD_SUFFIX)


def hold_probability(core_mom_pct: float) -> float:
    annualized = core_mom_pct * 12.0
    gap = max(0.0, abs(annualized - INFLATION_TARGET) - BAND)
    logit = math.log(HOLD_PRIOR / (1.0 - HOLD_PRIOR)) - SLOPE * gap
    return 1.0 / (1.0 + math.exp(-logit))


def latest_core_nowcast(history: dict, now: datetime):
    """The newest core-CPI nowcast known at `now`, across all months."""
    known = [obs for month in history.values() if (obs := latest_nowcast(month, now)) is not None]
    return max(known, key=lambda o: o.published_at) if known else None


class FomcMapped:
    name = "fomc_mapped"
    version = "fomc-mapped-v1"
    cadence = "meeting"

    def __init__(self, live, fetch_market: Callable[[str], Any], *,
                 nowcast_fn: Callable[[str], dict] = fetch_nowcast_history):
        self._live, self._fetch_market, self._nowcast_fn = live, fetch_market, nowcast_fn
        self._open: dict[str, LiveMarket] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): lm for lm in self._live.open_markets(FOMC_SERIES)
                      if is_hold_market(lm) and in_freeze_window(lm, now)}
        return [entry_for(lm, "fomc", self.cadence) for lm in self._open.values()]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        core = latest_core_nowcast(self._nowcast_fn("core"), now) if lm else None
        if core is None:
            return None
        return Forecast(self.name, self.version, entry.target, hold_probability(core.value),
                        market_prob=quote_mid(lm),
                        payload={"core_nowcast": core.value, "core_obs": core.name, "experimental": True,
                                 "hold_prior": HOLD_PRIOR, "slope": SLOPE, "band": BAND})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)
