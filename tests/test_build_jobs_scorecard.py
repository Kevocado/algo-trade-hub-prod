from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from tradehub.backtest.kalshi_history import Candle
from tradehub.data.alfred_vintages import parse_alfred_csv
from tradehub.engines.labor import labor_market
from tradehub.scripts.build_jobs_scorecard import event_ladders, group_events, u3_baseline

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "labor"


def test_group_events_keeps_ended_months_since_start():
    raws = [{"ticker": f"KXU3-{tag}-T4.1", "event_ticker": f"KXU3-{tag}", "open_time": "2026-01-01T00:00:00Z",
             "close_time": "2026-10-02T12:29:00Z", "title": "u3"} for tag in ("26JUL", "26AUG", "26SEP")]
    raws.append({"ticker": "U3-22JUL-T4.3", "event_ticker": "U3-22JUL", "open_time": "2022-07-01T00:00:00Z",
                 "close_time": "2022-08-05T12:25:00Z", "title": "u3"})
    grouped = group_events(raws, since=date(2026, 8, 1), today=date(2026, 9, 25))
    assert list(grouped) == [date(2026, 8, 1)]
    assert grouped[date(2026, 8, 1)][0].floor_strike == pytest.approx(4.1)


def test_u3_baseline_is_last_known_rate():
    unrate = parse_alfred_csv((FIXTURES / "unrate_2026.csv").read_text(encoding="utf-8"))
    snap = u3_baseline(unrate, date(2026, 8, 1))
    assert snap.mu == 4.1 and snap.sigma == pytest.approx(0.2)  # too little history: default spread
    assert snap.engine_version == "u3-naive-v0"
    assert u3_baseline(unrate, date(2026, 1, 1)) is None


def test_event_ladders_one_request_per_strike_both_moments():
    markets = [labor_market({"ticker": f"KXPAYROLLS-26AUG-T{k}", "event_ticker": "KXPAYROLLS-26AUG",
                             "strike_type": "greater", "floor_strike": k, "open_time": "2026-08-01T00:00:00Z",
                             "close_time": "2026-09-04T12:29:00Z", "title": "jobs"}) for k in (0, 100000)]
    calls = []

    class Client:
        def merged_candles(self, ticker, start, end, *, series_ticker):
            calls.append(ticker)
            close = datetime(2026, 9, 4, 12, 29, tzinfo=timezone.utc)
            early = 0.80 if ticker.endswith("T0") else 0.30
            return [Candle(close - timedelta(hours=1, minutes=5), early - 0.02, early + 0.02, 1.0),
                    Candle(close, early + 0.08, early + 0.12, 1.0)]

    ladder_1h, ladder_close = event_ladders(Client(), markets, 1000.0, 1000.0)
    assert calls == ["KXPAYROLLS-26AUG-T0", "KXPAYROLLS-26AUG-T100000"]
    assert ladder_1h == [(0.5, pytest.approx(0.80)), (100.5, pytest.approx(0.30))]
    assert ladder_close == [(0.5, pytest.approx(0.90)), (100.5, pytest.approx(0.40))]
