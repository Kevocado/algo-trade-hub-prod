from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from tradehub.data.alfred_vintages import parse_alfred_csv
from tradehub.engines.labor import (
    add_months,
    decision_time,
    estimate_path,
    first_prints,
    greater_threshold,
    labor_market,
    month_end,
    parse_expiration_value,
    payroll_prob,
    pre_release_time,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "labor"
PAYEMS = parse_alfred_csv((FIXTURES / "payems_2024_2025.csv").read_text(encoding="utf-8"))
UNRATE = parse_alfred_csv((FIXTURES / "unrate_2026.csv").read_text(encoding="utf-8"))


def _raw(ticker, floor="missing", close="2026-09-04T12:29:00Z"):
    raw = {"ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0], "open_time": "2026-08-01T00:00:00Z",
           "close_time": close, "title": ticker}
    if floor != "missing":
        raw.update({"strike_type": "greater", "floor_strike": floor})
    return raw


def test_months():
    assert add_months(date(2025, 12, 1), 1) == date(2026, 1, 1)
    assert add_months(date(2026, 1, 1), -13) == date(2024, 12, 1)
    assert month_end(date(2024, 2, 1)) == date(2024, 2, 29)


def test_labor_market_reads_strike_from_ticker_when_fields_missing():
    old = labor_market(_raw("KXPAYROLLS-25JAN-T256000"))
    assert (old.strike_type, old.floor_strike) == ("greater", 256000.0)
    u3 = labor_market(_raw("U3-22JUL-T4.3"))
    assert u3.floor_strike == pytest.approx(4.3) and u3.series_ticker == "U3"
    assert labor_market(_raw("KXPAYROLLS-26AUG-T150000", floor=150000)).floor_strike == 150000.0


@pytest.mark.parametrize("floor, resolution, cut", [
    (200000, 1000.0, 200500.0),    # "above 200,000": a 200,000 print is NO
    (199999, 1000.0, 199500.0),    # "200,000 or above": a 200,000 print is YES
    (-100001, 1000.0, -100500.0),
    (4.1, 0.1, 4.15),              # KXU3-26AUG-T4.1 settled NO at 4.1
    (4.099999, 0.1, 4.15),         # float-stored 4.1 (KXU3-25FEB-T4.1 settled NO at 4.1)
])
def test_greater_threshold(floor, resolution, cut):
    assert greater_threshold(floor, resolution) == pytest.approx(cut)


def test_payroll_prob_uses_thousands():
    market = labor_market(_raw("KXPAYROLLS-26AUG-T150000", floor=150000))
    assert payroll_prob(market, mu_k=150.5, sigma_k=50.0) == pytest.approx(0.5)
    assert payroll_prob(market, mu_k=400.0, sigma_k=50.0) > 0.99


@pytest.mark.parametrize("raw, value", [("162000", 162000.0), ("119,000", 119000.0), ("-23000", -23000.0),
                                        ("4.10", 4.1), ("4.4%", 4.4), ("", None), (None, None)])
def test_parse_expiration_value(raw, value):
    assert parse_expiration_value(raw) == value


def test_first_prints_from_recorded_vintages():
    prints = first_prints(PAYEMS)
    # Kalshi settled KXPAYROLLS-24DEC at 256,000, -25JAN at 143,000, -25FEB at 151,000.
    assert prints == {date(2024, 11, 1): pytest.approx(227.0), date(2024, 12, 1): 256.0,
                      date(2025, 1, 1): 143.0, date(2025, 2, 1): 151.0}
    assert first_prints(UNRATE, change=False) == {date(2026, 6, 1): 4.2, date(2026, 7, 1): 4.1, date(2026, 8, 1): 4.1}


def test_estimate_path_dec_2024_first_second_third_benchmark():
    path = estimate_path(PAYEMS, date(2024, 12, 1))
    assert (path.first, path.first_vintage) == (256.0, date(2025, 1, 31))
    assert (path.second, path.second_vintage) == (307.0, date(2025, 2, 28))
    assert (path.third, path.third_vintage) == (323.0, date(2025, 3, 31))
    assert (path.benchmark, path.benchmark_vintage) == (307.0, date(2025, 2, 28))
    assert (path.latest, path.latest_vintage) == (323.0, date(2025, 3, 31))


def test_estimate_path_unknown_when_oldest_vintage_already_revised():
    assert estimate_path(PAYEMS, date(2024, 10, 1)).first is None


def test_decision_and_pre_release_times():
    normal = labor_market(_raw("KXPAYROLLS-26AUG-T0", floor=0, close="2026-09-04T12:29:00Z"))
    assert decision_time(normal) == datetime(2026, 9, 4, 11, 29, tzinfo=timezone.utc)
    assert pre_release_time(normal) == normal.close_time
    late = labor_market(_raw("KXPAYROLLS-26JAN-T0", floor=0, close="2026-02-11T15:00:00Z"))  # closed after 8:30 ET
    assert decision_time(late) == datetime(2026, 2, 11, 12, 30, tzinfo=timezone.utc)
    assert pre_release_time(late) == datetime(2026, 2, 11, 13, 29, tzinfo=timezone.utc)
