"""Tests for the ERCOT daily peak-demand forecaster and its data sources.

Data facts verified live on 2026-10-16: Kalshi's KXTXERCOTPEAKD settles on the highest value in the
TOTAL column of ERCOT's daily "Actual System Load by Forecast Zone" report (one keyless HTML table per
operating day). The yearly Native_Load archive is a different series and is not used. The event
ticker's date is the settlement day, one after the operating day the report describes.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from journal_fakes import FakeJournalDB

from tradehub.data.ercot import load_peaks, parse_daily_peak
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.journal.forecasters.ercot import (
    MIN_LEAD,
    SERIES,
    VERSION,
    ErcotClimatology,
    ErcotPeak,
    build_ercot,
    fit,
    operating_day,
    prob_for,
)
from tradehub.journal.runner import run_journal
from tradehub.markets import parse_market

CLOSE = datetime(2026, 10, 17, 4, 55, tzinfo=UTC)  # 23:55 CDT on operating day 2026-10-16
NOW = CLOSE - timedelta(hours=20)
DAY = date(2026, 10, 16)  # the operating day the market forecasts


def _lm(ticker, floor, bid=0.40, ask=0.44, close=CLOSE):
    event = ticker.rsplit("-", 1)[0]
    raw = {"ticker": ticker, "event_ticker": event, "strike_type": "greater", "floor_strike": floor,
           "cap_strike": None, "open_time": "2026-10-16T04:55:00Z", "close_time": close.isoformat(),
           "title": ticker}
    return LiveMarket(parse_market(raw), Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=5.0, yes_ask_size=5.0))


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def _history(n=60, temp=None, peak=None):
    """A synthetic history of (peak, max-temp F) with a known linear relationship by default."""
    out = {}
    for i in range(n):
        day = date(2026, 8, 1) + timedelta(days=i)
        t = temp(i) if temp else 70.0 + (i % 10)
        out[day] = (peak(i, t) if peak else 15000.0 + 600.0 * t, t)
    return out


class Inputs:
    """A fake ErcotInputs: `history()` returns past (peak, temp) pairs, `temp()` the target's feature."""

    def __init__(self, history, target_temp):
        self._history, self._target_temp, self.calls = history, target_temp, []

    def history(self, day, now):
        self.calls.append(("history", day))
        return {d: v for d, v in self._history.items() if d < day}

    def peaks(self, first, last):
        return {d: v[0] for d, v in self._history.items() if first <= d <= last}

    def temp(self, day, now):
        self.calls.append(("temp", day))
        return self._target_temp


ZONE_HTML = """
<html><body><table class="tableStyle">
<tr><th>Oper Day</th><th>Hour Ending</th><th>NORTH</th><th>SOUTH</th><th>WEST</th><th>HOUSTON</th><th>TOTAL</th></tr>
<tr><td>07/04/2025</td><td>1500</td><td>22967.11</td><td>16167.16</td><td>10364.11</td><td>18045.46</td><td>67543.84</td></tr>
<tr><td>07/04/2025</td><td>1600</td><td>23096.73</td><td>16332.09</td><td>10527.08</td><td>18036.24</td><td>67992.13</td></tr>
<tr><td>07/04/2025</td><td>1700</td><td>22707.41</td><td>16491.71</td><td>10525.71</td><td>17876.69</td><td>67601.52</td></tr>
</table></body></html>
"""


def test_the_peak_is_the_total_column_not_a_zone_or_a_sum():
    assert parse_daily_peak(ZONE_HTML) == pytest.approx(67992.13)
    # hour 1600 sums its four zone cells to 67992.13 here, but hour 1500's zones do not sum to its TOTAL,
    # so a parser that summed zones or read a wrong column would disagree with the max TOTAL above.
    assert parse_daily_peak("<table></table>") is None
    assert parse_daily_peak("not html at all") is None


def test_a_duplicated_fall_back_hour_does_not_break_the_peak():
    html = ZONE_HTML.replace("<tr><td>07/04/2025</td><td>1700</td>",
                             '<tr><td>07/04/2025</td><td>0200\n*</td>')
    assert parse_daily_peak(html) == pytest.approx(67992.13)


def test_a_cached_in_progress_operating_day_is_dropped(tmp_path):
    # ERCOT serves a partial report for the day in progress; a peak read from it is not the day's peak.
    (tmp_path / "peaks.json").write_text('{"2026-10-14": 70000.0, "2026-10-15": 12345.0}')
    got = load_peaks(date(2026, 10, 14), date(2026, 10, 15), get_text=lambda *_a, **_k: "",
                     cache_dir=tmp_path, today=date(2026, 10, 15))
    assert got == {date(2026, 10, 14): 70000.0}


def test_the_operating_day_is_the_day_before_the_settlement_date():
    assert operating_day(_lm("KXTXERCOTPEAKD-26OCT17-T54000", 54000).market) == date(2026, 10, 16)
    assert operating_day(_lm("KXTXERCOTPEAKD-26OCT06-T69000", 69000).market) == date(2026, 10, 5)


def test_the_fit_recovers_the_known_load_relationship():
    hist = _history()
    beta, sigma = fit([(d, peak, t) for d, (peak, t) in hist.items()])
    mu = prob_for(_lm("KXTXERCOTPEAKD-26OCT17-T69000", 69000).market, 90.0, DAY, beta, sigma)
    assert 0.40 < mu < 0.60   # the truth is 15000 + 600*90 = 69000, exactly on the 69000 strike
    assert sigma == pytest.approx(1.0)  # no residual noise -> the floor, never zero


def test_the_probability_is_monotone_decreasing_in_the_strike():
    hist = _history()
    beta, sigma = fit([(d, peak, t) for d, (peak, t) in hist.items()])
    probs = [prob_for(_lm(f"KXTXERCOTPEAKD-26OCT17-T{n}", n).market, 90.0, DAY, beta, sigma)
             for n in range(66000, 73000, 500)]
    assert probs == sorted(probs, reverse=True)
    assert probs[0] > 0.5 > probs[-1]


def test_the_forecaster_freezes_inside_24h_and_never_uses_the_target_month():
    live = FakeLive([_lm("KXTXERCOTPEAKD-26OCT17-T69000", 69000),
                     _lm("KXTXERCOTPEAKD-26OCT18-T69000", 69000, close=CLOSE + timedelta(days=1))])
    inputs = Inputs(_history(), target_temp=90.0)
    fc = ErcotPeak(live, lambda t: {"market": {"ticker": t, "status": "finalized", "result": "yes"}}, inputs)
    [entry] = fc.targets(NOW)          # only the market closing in 20h is a target
    f = fc.forecast(entry, NOW)
    assert (fc.name, fc.version, fc.cadence) == ("ercot_peak", VERSION, "daily")
    assert f.probability == pytest.approx(0.5, abs=0.05) and f.market_prob == pytest.approx(0.42)
    assert f.payload["operating_day"] == "2026-10-16" and f.payload["yes_bid"] == 0.40
    # corrupt every day from the target month onward: a monthly refit must ignore them all
    inputs._history.update({DAY + timedelta(days=k): (9.9e9, 9.9e9) for k in range(15)})
    assert fc.forecast(entry, NOW).probability == pytest.approx(f.probability)


def test_a_market_part_way_through_its_operating_day_is_not_forecast():
    live = FakeLive([_lm("KXTXERCOTPEAKD-26OCT17-T69000", 69000)])
    for cls in (ErcotPeak, ErcotClimatology):
        fc = cls(live, lambda t: None, Inputs(_history(), 90.0))
        assert fc.targets(CLOSE - timedelta(hours=21)) and fc.targets(CLOSE - timedelta(hours=19)) == []


def test_the_climatology_baseline_is_the_same_weekday_over_the_past_four_weeks():
    # Oct 16 2026 is a Friday; the four prior Fridays are Sep 18, 25 and Oct 2, 9.
    hist = {date(2026, 10, 9): (75000.0, 80.0), date(2026, 10, 2): (60000.0, 80.0),
            date(2026, 9, 25): (65000.0, 80.0), date(2026, 9, 18): (70000.0, 80.0),
            date(2026, 10, 8): (99999.0, 80.0)}   # a Thursday: not the same weekday, not used
    live = FakeLive([_lm("KXTXERCOTPEAKD-26OCT17-T65000", 65000)])
    fc = ErcotClimatology(live, lambda t: None, Inputs(hist, 90.0))
    [entry] = fc.targets(NOW)
    assert fc.name == "baseline_climatology_ercot_peak"
    # peaks above 65000 among the four Fridays: 70000 and 75000 -> (2 + 0.5) / (4 + 1)
    assert fc.forecast(entry, NOW).probability == pytest.approx(0.5)
    assert fc.forecast(entry, NOW).payload["n_weeks"] == 4


def test_a_market_with_too_little_history_is_a_gap_not_a_guess():
    live = FakeLive([_lm("KXTXERCOTPEAKD-26OCT17-T69000", 69000)])
    inputs = Inputs({d: v for d, v in _history().items() if d < date(2026, 8, 5)}, 90.0)
    assert ErcotPeak(live, lambda t: None, inputs).forecast(
        ErcotPeak(live, lambda t: None, inputs).targets(NOW)[0], NOW) is None


def _final(result):
    return lambda ticker: {"market": {"ticker": ticker, "status": "finalized", "result": result}}


def test_end_to_end_the_model_baseline_and_market_are_scored_on_the_same_contracts():
    clock = [NOW]
    db = FakeJournalDB(lambda: clock[0])
    live = FakeLive([_lm("KXTXERCOTPEAKD-26OCT17-T69000", 69000),
                     _lm("KXTXERCOTPEAKD-26OCT17-T70000", 70000)])
    fcs = build_ercot(live, _final("no"), Inputs(_history(), 90.0))
    run_journal(db, fcs, clock[0])
    clock[0] = CLOSE + timedelta(hours=1)
    out = run_journal(db, fcs, clock[0])
    assert not out["failures"]
    cards = {r["forecaster"]: r for r in db.tables["journal_scores"]}
    assert cards["ercot_peak"]["n_settled"] == 2 and cards["ercot_peak"]["baseline"] == "market"
    assert cards["baseline_climatology_ercot_peak"]["n_settled"] == 2
    assert cards["kalshi_implied_ercot_peak"]["bss"] == pytest.approx(0.0)


def test_the_registry_runs_the_ercot_family_with_unique_keys():
    from tradehub.journal.registry import FORECASTERS

    keys = [(f.name, f.version) for f in FORECASTERS]
    for name in ("ercot_peak", "kalshi_implied_ercot_peak", "baseline_climatology_ercot_peak"):
        assert any(k[0] == name for k in keys), name
    assert len(set(keys)) == len(keys)
    assert MIN_LEAD == timedelta(hours=20) and SERIES == "KXTXERCOTPEAKD"
