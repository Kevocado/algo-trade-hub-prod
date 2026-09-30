"""CPI m/m through the journal (v2 spec §5): the existing nowcast engine, no model changes.

Same math as `tradehub.scripts.scan.scan_cpi` (Cleveland Fed nowcast, `Normal(nowcast + bias, sigma)`
fit at the decision horizon, KXCPI/KXCPICORE bucket mapping) and the same `engine_version`s, so the
journal grades the engine the site already shows. Headline and core are separate forecasters because
they are separate track records.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from tradehub.data.cleveland_fed import fetch_nowcast_history
from tradehub.data.kalshi_live import LiveMarket
from tradehub.engine_config import load_engine_config
from tradehub.engines.cpi import CPI_TARGETS, CPI_TRAIN_MONTHS, cpi_prob, fit_cpi_error, latest_nowcast, training_pairs
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.kalshi_linked import (
    entry_for,
    in_freeze_window,
    kalshi_target,
    quote_mid,
    quote_payload,
    settle_on_kalshi,
)
from tradehub.markets import event_month

CPI_ENGINE = "cpi_nowcast"


class CpiForecaster:
    name = CPI_ENGINE
    cadence = "monthly"

    def __init__(self, series: str, live, fetch_market: Callable[[str], Any], *,
                 nowcast_fn: Callable[[str], dict] = fetch_nowcast_history, params: dict[str, float] | None = None):
        self.kind, self.version = CPI_TARGETS[series]
        self.series = series
        self._live, self._fetch_market, self._nowcast_fn = live, fetch_market, nowcast_fn
        params = params if params is not None else load_engine_config(CPI_ENGINE).params
        self._window = int(params.get("train_months", CPI_TRAIN_MONTHS))
        self._use_bias = bool(params.get("use_bias", 0.0))
        self._open: dict[str, LiveMarket] = {}
        self._history: dict | None = None

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): lm for lm in self._live.open_markets(self.series)
                      if in_freeze_window(lm, now)}
        self._history = None  # refetched lazily, once per run, only if something needs forecasting
        return [entry_for(lm, "cpi", self.cadence) for lm in self._open.values()]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        if self._history is None:
            self._history = self._nowcast_fn(self.kind)
        nowcast = latest_nowcast(self._history.get(event_month(lm.market.event_ticker)), now)
        horizon = lm.market.close_time - now
        if nowcast is None:
            return None
        pairs = training_pairs(self._history, now, horizon)[-self._window:]
        model = fit_cpi_error(pairs, window=self._window, use_bias=self._use_bias)
        return Forecast(self.name, self.version, entry.target, cpi_prob(lm.market, nowcast.value, model),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "nowcast": nowcast.value, "nowcast_obs": nowcast.name,
                                 "bias": model.bias,
                                 "sigma": model.sigma, "n_train": len(pairs),
                                 "hours_to_close": round(horizon.total_seconds() / 3600.0, 2)})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)
