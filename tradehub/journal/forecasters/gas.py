"""Kalshi daily AAA gasoline (KXAAAGASD), graded against the market and a persistence baseline.

The market settles on AAA's daily national average regular price, one day's change at a time. The model
(`gas`, `gas-v2`) is the gas engine's regression of the day-over-day AAA change on the lagged RBOB
change, with the train/serve skew fixed: both fit and inference read the RBOB window at the decision
time (the market close minus the engine lead), not at the previous day's AAA print. Beside it the
journal grades the Kalshi mid on the same contract (`KalshiImplied`) and a persistence baseline
(`baseline_persistence_gas`): the previous AAA print as the level, with the sigma of past daily changes.

ponytail: this is a measurement, not an edge hunt. The legacy engine is 4x behind the market on settled
contracts; the journal records whether that holds at a consistent lead and against persistence. A
negative result here is a complete answer.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from tradehub.core.kalshi_feed import fetch_market
from tradehub.data.rbob import front_month_roll_dates, rbob_closes
from tradehub.engines.gas import (
    GAS_DECISION_LEAD,
    GAS_SERIES,
    MIN_GAS_SIGMA,
    GasModel,
    aaa_daily_changes,
    fit_gas_model,
    gas_prob,
    gas_training_pairs,
    rbob_change,
)
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.forecasters.baselines import PERSISTENCE, baseline_name
from tradehub.journal.kalshi_linked import (
    KalshiImplied,
    entry_for,
    in_freeze_window,
    kalshi_target,
    quote_mid,
    quote_payload,
    settle_on_kalshi,
)
from tradehub.markets import KalshiMarket, event_date

FAMILY = "gas"
SERIES = GAS_SERIES
VERSION = "v2"
# Kalshi's last trading time is 11:59 PM ET the day before the reference day and the AAA print lands
# ~11:06Z, so freezing in the 2h before close is after the print and before the settle.
LEAD = GAS_DECISION_LEAD
MIN_TRAIN = 30


def target_day(market: KalshiMarket) -> date:
    return event_date(market.event_ticker)


class GasInputs:
    """The AAA prints (Kalshi's own settled values) and RBOB closes, loaded once per run.

    The journal runs hourly and the AAA print for a day lands mid-morning, so a cache that outlives a
    run would freeze the next day's market off a print that is not out yet (horizon 2 instead of 1).
    The cache is therefore keyed on `now`: one load per run, never reused across runs.
    """

    def __init__(self, live, *, rbob_fn: Callable[[], list] = rbob_closes):
        self._live, self._rbob_fn = live, rbob_fn
        self._now: datetime | None = None
        self._aaa: list = []
        self._rbob: list = []

    def _refresh(self, now: datetime) -> None:
        if now == self._now:
            return
        self._now = now
        self._aaa = [o for o in self._live.settled_values(SERIES) if o.published_at <= now]
        self._rbob = self._rbob_fn()

    def aaa(self, now: datetime) -> list:
        self._refresh(now)
        return self._aaa

    def rbob(self, now: datetime) -> list:
        self._refresh(now)
        return self._rbob

    def roll_dates(self, aaa: list, now: datetime) -> list[date]:
        return front_month_roll_dates(min(event_date(o.name) for o in aaa), now.date())


class _GasBase:
    cadence = "daily"

    def __init__(self, live, fetch: Callable[[str], Any], inputs: GasInputs):
        self._live, self._fetch_market, self._inputs = live, fetch, inputs
        self._open: dict[str, Any] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): lm for lm in self._live.open_markets(SERIES)
                      if in_freeze_window(lm, now, LEAD)}
        return [entry_for(lm, self.name, self.cadence) for lm in self._open.values()]

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


class GasAaa(_GasBase):
    name, version = FAMILY, VERSION

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        aaa = self._inputs.aaa(now)
        if len(aaa) < MIN_TRAIN:
            return None
        day = target_day(lm.market)
        last = max(aaa, key=lambda o: event_date(o.name))
        horizon = (day - event_date(last.name)).days
        if horizon < 1:
            return None
        rbob = self._inputs.rbob(now)
        roll_dates = self._inputs.roll_dates(aaa, now)
        model = fit_gas_model(
            [(x, y) for x, y, published in gas_training_pairs(aaa, rbob, roll_dates=roll_dates, lead=LEAD)
             if published <= now],
            aaa=aaa,
        )
        x = rbob_change(rbob, now, roll_dates=roll_dates)
        return Forecast(self.name, self.version, entry.target,
                        gas_prob(lm.market, last.value, horizon, x, model),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "last_aaa": last.value,
                                 "last_aaa_event": last.name, "horizon_days": horizon,
                                 "rbob_change": x, "alpha": model.alpha, "beta": model.beta,
                                 "sigma": model.sigma})


class GasPersistence(_GasBase):
    version = "v1"

    def __init__(self, live, fetch, inputs):
        super().__init__(live, fetch, inputs)
        self.name = baseline_name(PERSISTENCE, FAMILY)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        aaa = self._inputs.aaa(now)
        if len(aaa) < MIN_TRAIN:
            return None
        day = target_day(lm.market)
        last = max(aaa, key=lambda o: event_date(o.name))
        horizon = (day - event_date(last.name)).days
        if horizon < 1:
            return None
        sigma = max(MIN_GAS_SIGMA, statistics.stdev(aaa_daily_changes(aaa)))
        return Forecast(self.name, self.version, entry.target,
                        gas_prob(lm.market, last.value, horizon, None, GasModel(0.0, 0.0, sigma)),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "last_aaa": last.value,
                                 "horizon_days": horizon, "sigma": sigma,
                                 "basis": "last AAA print as the level, sigma of past daily changes"})


def build_gas(live, fetch: Callable[[str], Any] = fetch_market, inputs: GasInputs | None = None) -> list:
    inputs = inputs or GasInputs(live)
    return [GasAaa(live, fetch, inputs),
            KalshiImplied(FAMILY, (SERIES,), "daily", live, fetch, lead=LEAD),
            GasPersistence(live, fetch, inputs)]
