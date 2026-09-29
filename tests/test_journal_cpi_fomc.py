import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from journal_fakes import FakeJournalDB

from tradehub.data.cleveland_fed import parse_nowcast_month
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.journal.forecasters.cpi import CpiForecaster
from tradehub.journal.forecasters.fomc import FomcMapped, hold_probability, is_hold_market
from tradehub.journal.kalshi_linked import KalshiImplied, settle_on_kalshi
from tradehub.journal.runner import run_journal
from tradehub.markets import parse_cpi_market, parse_market

PAYLOAD = json.loads((Path(__file__).parent / "fixtures" / "cleveland_nowcast_month_trimmed.json").read_text("utf-8"))
NOW = datetime(2026, 9, 11, 12, 5, tzinfo=UTC)  # 08:05 EDT on the Aug-2026 release morning
PARAMS = {"train_months": 24.0, "use_bias": 0.0}


def _cpi(series, strike, close="2026-09-11T12:25:00Z", bid=0.30, ask=0.34):
    event = f"{series}-26AUG"
    market = parse_cpi_market({"ticker": f"{event}-T{strike}", "event_ticker": event, "strike_type": "greater",
                               "floor_strike": strike, "open_time": "2026-07-23T21:00:00Z", "close_time": close,
                               "title": f"{series} {strike}"})
    return LiveMarket(market, Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=50.0, yes_ask_size=50.0))


def _fed(suffix, close="2026-09-11T18:59:00Z", bid=0.90, ask=0.94):
    event = "KXFEDDECISION-26SEP"
    market = parse_market({"ticker": f"{event}-{suffix}", "event_ticker": event, "strike_type": "custom",
                           "open_time": "2026-06-01T00:00:00Z", "close_time": close, "title": suffix})
    return LiveMarket(market, Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=10.0, yes_ask_size=10.0))


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def _nowcast(kind):
    return parse_nowcast_month(PAYLOAD, kind)


def _result(result):
    return lambda ticker: {"market": {"ticker": ticker, "status": "finalized", "result": result}}


def test_cpi_forecaster_reproduces_the_scan_probability_and_freezes_the_market_mid():
    live = FakeLive([_cpi("KXCPI", 0.3), _cpi("KXCPICORE", 0.2)])
    fc = CpiForecaster("KXCPI", live, _result("yes"), nowcast_fn=_nowcast, params=PARAMS)
    [entry] = fc.targets(NOW)
    assert entry.target == "kalshi:KXCPI-26AUG-T0.3" and entry.market_linked and entry.cadence == "monthly"
    forecast = fc.forecast(entry, NOW)
    assert (fc.name, fc.version) == ("cpi_nowcast", "cpi-v1")
    assert forecast.probability == pytest.approx(0.5244, abs=1e-4)  # same number test_scan_cpi pins
    assert forecast.market_prob == pytest.approx(0.32)
    assert forecast.payload["nowcast_obs"] == "CPI:2026-08@2026-09-10"


def test_only_markets_inside_the_freeze_lead_are_targets():
    live = FakeLive([_cpi("KXCPI", 0.3, close="2026-10-11T12:25:00Z"),  # a month out: not yet
                     _cpi("KXCPI", 0.4, close="2026-09-11T12:00:00Z")])  # already closed
    assert CpiForecaster("KXCPI", live, _result("yes"), nowcast_fn=_nowcast, params=PARAMS).targets(NOW) == []


def test_kalshi_settlement_only_on_a_final_yes_or_no():
    assert settle_on_kalshi("kalshi:X", _result("yes")).outcome == 1
    assert settle_on_kalshi("kalshi:X", _result("no")).outcome == 0
    assert settle_on_kalshi("kalshi:X", _result(None)) is None  # voided: never settles
    assert settle_on_kalshi("kalshi:X", lambda t: {"market": {"status": "open"}}) is None


def test_hold_probability_is_the_prior_at_target_and_falls_away_from_it():
    assert hold_probability(2.0 / 12) == pytest.approx(0.70)
    assert hold_probability(2.4 / 12) == pytest.approx(0.70)  # inside the band
    assert hold_probability(4.5 / 12) < hold_probability(3.5 / 12) < 0.70
    assert hold_probability(-1.0 / 12) < 0.70


def test_fomc_targets_only_the_hold_market():
    live = FakeLive([_fed("H0"), _fed("C25"), _fed("H25")])
    fc = FomcMapped(live, _result("yes"), nowcast_fn=_nowcast)
    [entry] = fc.targets(NOW)
    assert entry.target == "kalshi:KXFEDDECISION-26SEP-H0" and entry.cadence == "meeting"
    forecast = fc.forecast(entry, NOW)
    assert 0.0 < forecast.probability < 1.0 and forecast.payload["experimental"] is True
    assert forecast.market_prob == pytest.approx(0.92)
    assert is_hold_market(_fed("H0")) and not is_hold_market(_fed("C25"))


def test_cpi_and_its_pseudo_forecaster_run_end_to_end_and_settle_on_kalshi():
    clock = [NOW]
    db = FakeJournalDB(lambda: clock[0])
    live = FakeLive([_cpi("KXCPI", 0.3), _cpi("KXCPI", 0.4)])
    fcs = [CpiForecaster("KXCPI", live, _result("yes"), nowcast_fn=_nowcast, params=PARAMS),
           KalshiImplied("cpi", ("KXCPI",), "monthly", live, _result("yes"))]
    out = run_journal(db, fcs, clock[0])
    assert out["forecasters"]["cpi_nowcast@cpi-v1"]["frozen"] == 2
    assert out["forecasters"]["kalshi_implied_cpi@v1"]["frozen"] == 2
    clock[0] = NOW + timedelta(hours=2)
    live.markets = []  # closed markets are no longer listed; settlement must not depend on them
    out = run_journal(db, fcs, clock[0])
    assert out["forecasters"]["cpi_nowcast@cpi-v1"]["settled"] == 2
    cards = {r["forecaster"]: r for r in db.tables["journal_scores"]}
    assert cards["kalshi_implied_cpi"]["bss"] == pytest.approx(0.0)  # the market vs itself
    assert cards["cpi_nowcast"]["baseline"] == "market" and cards["cpi_nowcast"]["gate_status"] == "SHADOW"


def test_the_registry_builds_without_network():
    from tradehub.journal.registry import FORECASTERS

    keys = {(f.name, f.version) for f in FORECASTERS}
    assert {("cpi_nowcast", "cpi-v1"), ("cpi_nowcast", "cpi-core-v1"), ("fomc_mapped", "fomc-mapped-v1"),
            ("kalshi_implied_cpi", "v1"), ("kalshi_implied_fomc", "v1")} <= keys
    assert len(keys) == len(FORECASTERS), "(name, version) must be unique: it is the journal key"
