"""Tests for the Kalshi daily AAA gasoline forecaster (`gas`, `gas-v2`).

Data facts: Kalshi's KXAAAGASD settles on AAA's daily national average regular price, and its event
ticker's date is the reference day the price describes (the close is 11:59 PM ET the day before). The
AAA print for a day lands ~11:06Z that day, so the 2h freeze window is after the print and before the
settle. The model is the gas engine's regression of the day-over-day AAA change on the lagged RBOB
change, fit and applied at the same decision time.
"""

import statistics
from datetime import UTC, date, datetime, timedelta

import pytest
from journal_fakes import FakeJournalDB

from tradehub.data.kalshi_live import LiveMarket
from tradehub.backtest.pit import Observation
from tradehub.edges import Quote
from tradehub.engines.gas import GAS_RESOLUTION, GasModel, gas_prob
from tradehub.journal.forecasters.gas import (
    LEAD,
    MIN_TRAIN,
    SERIES,
    VERSION,
    GasAaa,
    GasInputs,
    GasPersistence,
    build_gas,
)
from tradehub.journal.runner import run_journal
from tradehub.markets import event_date, parse_market

CLOSE = datetime(2026, 10, 17, 3, 59, tzinfo=UTC)  # 23:59 EDT on Oct 16
NOW = CLOSE - timedelta(hours=1, minutes=50)        # 2026-10-17T02:09Z, inside the 2h window
DAY = date(2026, 10, 17)                            # the reference day the market settles on


def _lm(ticker, floor, bid=0.40, ask=0.44, close=CLOSE):
    event = ticker.rsplit("-", 1)[0]
    raw = {"ticker": ticker, "event_ticker": event, "strike_type": "greater", "floor_strike": floor,
           "cap_strike": None, "open_time": "2026-10-16T04:00:00Z", "close_time": close.isoformat(),
           "title": ticker}
    return LiveMarket(parse_market(raw), Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=5.0, yes_ask_size=5.0))


class FakeLive:
    def __init__(self, markets, aaa=None):
        self.markets = markets
        self.aaa = _aaa() if aaa is None else aaa

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]

    def settled_values(self, series):
        return self.aaa


def _aaa(n=77):
    out = []
    for i in range(n):
        day = date(2026, 8, 1) + timedelta(days=i)
        out.append(
            Observation(f"KXAAAGASD-{day.strftime('%y%b%d').upper()}", 4.0 + i * 0.001 + (0.01 if i % 2 else -0.01),
                        datetime(day.year, day.month, day.day, 12, tzinfo=UTC))
        )
    return out


def _rbob(n=20):
    return [Observation(f"RBOB:RBV26.NYM:2026-09-{day:02d}", 3.0 + i * 0.01,
                       datetime(2026, 9, day, 22, tzinfo=UTC)) for i, day in enumerate(range(1, n + 1))]


def _inputs(live):
    return GasInputs(live, rbob_fn=lambda: _rbob())


def test_the_forecaster_freezes_only_inside_the_two_hour_window():
    live = FakeLive([_lm("KXAAAGASD-26OCT17-4.5000", 4.50)])
    fc = GasAaa(live, lambda t: None, _inputs(live))

    assert fc.targets(NOW)
    assert fc.targets(CLOSE - timedelta(hours=2, minutes=1)) == []  # not yet in the window
    assert fc.targets(CLOSE - timedelta(hours=3)) == []
    assert fc.targets(CLOSE + timedelta(hours=1)) == []            # already closed


def test_the_model_forecasts_one_day_ahead_at_the_frozen_lead():
    live = FakeLive([_lm("KXAAAGASD-26OCT17-4.5000", 4.50)])
    fc = GasAaa(live, lambda t: None, _inputs(live))
    [entry] = fc.targets(NOW)
    f = fc.forecast(entry, NOW)

    assert (fc.name, fc.version, fc.cadence) == ("gas", VERSION, "daily")
    assert f.market_prob == pytest.approx(0.42)
    assert f.payload["horizon_days"] == 1
    assert f.payload["last_aaa_event"] == "KXAAAGASD-26OCT16"
    assert f.payload["yes_bid"] == 0.40
    assert 0.0 <= f.probability <= 1.0


def test_the_persistence_baseline_is_the_last_print_with_past_daily_sigma():
    live = FakeLive([_lm("KXAAAGASD-26OCT17-4.5000", 4.50)])
    fc = GasPersistence(live, lambda t: None, _inputs(live))
    [entry] = fc.targets(NOW)
    f = fc.forecast(entry, NOW)

    assert fc.name == "baseline_persistence_gas"
    aaa = _aaa()
    ordered = sorted(aaa, key=lambda o: event_date(o.name))
    changes = [b.value - a.value for a, b in zip(ordered, ordered[1:])]
    sigma = max(0.002, statistics.stdev(changes))
    last = max(aaa, key=lambda o: event_date(o.name))
    assert f.probability == pytest.approx(gas_prob(live.markets[0].market, last.value, 1, None, GasModel(0.0, 0.0, sigma)))
    assert f.payload["sigma"] == pytest.approx(sigma)


def test_too_little_history_is_a_gap_not_a_guess():
    live = FakeLive([_lm("KXAAAGASD-26OCT17-4.5000", 4.50)], aaa=_aaa(MIN_TRAIN - 1))
    fc = GasAaa(live, lambda t: None, _inputs(live))
    [entry] = fc.targets(NOW)
    assert fc.forecast(entry, NOW) is None
    assert GasPersistence(live, lambda t: None, _inputs(live)).forecast(entry, NOW) is None


def _final(result):
    return lambda ticker: {"market": {"ticker": ticker, "status": "finalized", "result": result}}


def test_end_to_end_the_model_baseline_and_market_are_scored_on_the_same_contracts():
    clock = [NOW]
    db = FakeJournalDB(lambda: clock[0])
    live = FakeLive([_lm("KXAAAGASD-26OCT17-4.5000", 4.50),
                     _lm("KXAAAGASD-26OCT17-4.5100", 4.51)])
    inputs = _inputs(live)
    fcs = build_gas(live, _final("no"), inputs)
    run_journal(db, fcs, clock[0])
    clock[0] = CLOSE + timedelta(hours=1)
    out = run_journal(db, fcs, clock[0])

    assert not out["failures"]
    cards = {r["forecaster"]: r for r in db.tables["journal_scores"]}
    assert cards["gas"]["n_settled"] == 2 and cards["gas"]["baseline"] == "market"
    assert cards["baseline_persistence_gas"]["n_settled"] == 2
    assert cards["kalshi_implied_gas"]["bss"] == pytest.approx(0.0)


def test_the_registry_runs_the_gas_family_with_unique_keys():
    from tradehub.journal.registry import FORECASTERS

    keys = [(f.name, f.version) for f in FORECASTERS]
    for name in ("gas", "kalshi_implied_gas", "baseline_persistence_gas"):
        assert any(k[0] == name for k in keys), name
    assert len(set(keys)) == len(keys)
    assert LEAD == timedelta(hours=2) and SERIES == "KXAAAGASD" and GAS_RESOLUTION == 0.0001
