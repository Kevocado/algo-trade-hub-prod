import json
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
        def merged_candles(self, ticker, start, end, *, series_ticker, market_settled_at=None):
            calls.append(ticker)
            close = datetime(2026, 9, 4, 12, 29, tzinfo=timezone.utc)
            early = 0.80 if ticker.endswith("T0") else 0.30
            return [Candle(close - timedelta(hours=1, minutes=5), early - 0.02, early + 0.02, 1.0),
                    Candle(close, early + 0.08, early + 0.12, 1.0)]

    ladder_1h, ladder_close = event_ladders(Client(), markets, 1000.0, 1000.0)
    assert calls == ["KXPAYROLLS-26AUG-T0", "KXPAYROLLS-26AUG-T100000"]
    assert ladder_1h == [(0.5, pytest.approx(0.80)), (100.5, pytest.approx(0.30))]
    assert ladder_close == [(0.5, pytest.approx(0.90)), (100.5, pytest.approx(0.40))]


# ── the tier bug: a settled market's candles live in /historical, not /series ──
#
# `event_ladders` asked for candles without `market_settled_at`, which tells
# `merged_candles` the market is still live, so it built the live-tier path:
#
#   404 .../series/PROLLS/markets/PROLLS-23MAR-T0/candlesticks?...
#
# Every market that settled before `/historical/cutoff`'s `market_settled_ts` is in the other tier.

class _FakeGet:
    """Serves canned JSON per path and records every (path, params) call, so a test can assert which
    TIER a request went to. Local rather than imported from the kalshi_history tests."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, params=None):
        from tradehub.backtest import kalshi_history as kh
        path = url.replace(kh.KALSHI_PUBLIC_BASE, "")
        self.calls.append((path, dict(params or {})))
        pages = self.routes[path]
        return pages.pop(0) if isinstance(pages, list) else pages


CUTOFF = {"market_settled_ts": "2024-01-01T00:00:00Z", "trades_created_ts": "2024-01-01T00:00:00Z"}


def _candle_at(moment, mid):
    return {
        "end_period_ts": int(moment.timestamp()),
        "open_interest": "10.00",
        "price": {"close": None, "high": None, "low": None, "mean": None, "open": None, "previous": None},
        "volume": "1.00",
        "yes_ask": {"close": f"{mid + 0.01:.4f}", "high": None, "low": None, "open": None},
        "yes_bid": {"close": f"{mid - 0.01:.4f}", "high": None, "low": None, "open": None},
    }


def _legacy_market(ticker="PROLLS-23MAR-T0", settlement="2023-04-07T12:00:00Z"):
    """A legacy `PROLLS-*` market: no strike fields (the ticker's -T<k> is the floor), settled long
    before the cutoff."""
    return labor_market({
        "ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0], "open_time": "2023-03-01T00:00:00Z",
        "close_time": "2023-04-07T12:29:00Z", "title": "payrolls", "settlement_ts": settlement,
    })


def test_a_pre_cutoff_settled_market_reads_the_historical_tier_not_the_live_series():
    """The regression, pinned at the URL: a market that settled before the cutoff must be read from
    /historical/markets/{ticker}/candlesticks. The live path 404s for exactly these markets."""
    from tradehub.backtest import kalshi_history as kh
    from tradehub.scripts.build_jobs_scorecard import CANDLE_LOOKBACK, event_ladders
    from tradehub.engines.labor import decision_time, pre_release_time

    market = _legacy_market()
    first, last = decision_time(market), pre_release_time(market)
    routes = {
        "/historical/cutoff": CUTOFF,
        f"/historical/markets/{market.ticker}/candlesticks": {"candlesticks": [
            _candle_at(first - timedelta(minutes=30), 0.60), _candle_at(last, 0.70)]},
    }
    get = _FakeGet(routes)
    client = kh.KalshiHistoryClient(get_json=get)

    ladder_1h, ladder_close = event_ladders(client, [market], 1000.0, 1000.0)

    paths = [path for path, _ in get.calls]
    assert f"/historical/markets/{market.ticker}/candlesticks" in paths, paths
    assert not [p for p in paths if p.startswith("/series/")], f"a settled market hit the live tier: {paths}"
    assert ladder_1h and ladder_close, "the historical candles were not read"
    start, end = get.calls[-1][1]["start_ts"], get.calls[-1][1]["end_ts"]
    assert start == int((first - CANDLE_LOOKBACK).timestamp()) and end == int(last.timestamp())


def test_an_open_market_still_reads_the_live_tier():
    """The fix must not over-correct: an open market has no settlement time, so it belongs in the
    live tier, and `merged_candles` says so when `market_settled_at` is None."""
    from tradehub.backtest import kalshi_history as kh
    from tradehub.scripts.build_jobs_scorecard import event_ladders
    from tradehub.engines.labor import decision_time, pre_release_time

    market = labor_market({"ticker": "KXPAYROLLS-26AUG-T0", "event_ticker": "KXPAYROLLS-26AUG",
                           "strike_type": "greater", "floor_strike": 0, "open_time": "2026-08-01T00:00:00Z",
                           "close_time": "2026-09-04T12:29:00Z", "title": "jobs"})
    assert market.settlement_ts is None
    first, last = decision_time(market), pre_release_time(market)
    get = _FakeGet({
        "/historical/cutoff": CUTOFF,
        f"/series/{market.series_ticker}/markets/{market.ticker}/candlesticks": {"candlesticks": [
            _candle_at(first - timedelta(minutes=30), 0.60), _candle_at(last, 0.70)]},
    })

    event_ladders(kh.KalshiHistoryClient(get_json=get), [market], 1000.0, 1000.0)

    assert [p for p, _ in get.calls if p.startswith("/series/")], "an open market was sent to /historical"


def test_a_market_whose_candles_404_leaves_the_other_strikes_in_the_ladder(caplog):
    """One missing strike must cost one strike, not the whole event."""
    ok = labor_market({"ticker": "KXPAYROLLS-26AUG-T100000", "event_ticker": "KXPAYROLLS-26AUG",
                       "strike_type": "greater", "floor_strike": 100000, "open_time": "2026-08-01T00:00:00Z",
                       "close_time": "2026-09-04T12:29:00Z", "title": "jobs", "settlement_ts": None})
    gone = labor_market({"ticker": "KXPAYROLLS-26AUG-T0", "event_ticker": "KXPAYROLLS-26AUG",
                         "strike_type": "greater", "floor_strike": 0, "open_time": "2026-08-01T00:00:00Z",
                         "close_time": "2026-09-04T12:29:00Z", "title": "jobs", "settlement_ts": None})
    close = datetime(2026, 9, 4, 12, 29, tzinfo=timezone.utc)

    class Client:
        def merged_candles(self, ticker, start, end, *, series_ticker, market_settled_at=None):
            if ticker.endswith("T0"):
                raise RuntimeError("404 Client Error: for url: /series/.../candlesticks")
            return [Candle(close - timedelta(hours=1, minutes=5), 0.28, 0.32, 1.0), Candle(close, 0.38, 0.42, 1.0)]

    with caplog.at_level("WARNING"):
        ladder_1h, _ = event_ladders(Client(), [gone, ok], 1000.0, 1000.0)

    assert ladder_1h == [(100.5, pytest.approx(0.30))], ladder_1h
    assert any("KXPAYROLLS-26AUG" in r.getMessage() for r in caplog.records), caplog.text


def test_an_empty_candle_response_is_a_warning_not_a_silent_gap(caplog):
    empty = labor_market({"ticker": "KXPAYROLLS-26AUG-T0", "event_ticker": "KXPAYROLLS-26AUG",
                          "strike_type": "greater", "floor_strike": 0, "open_time": "2026-08-01T00:00:00Z",
                          "close_time": "2026-09-04T12:29:00Z", "title": "jobs", "settlement_ts": None})

    class Client:
        def merged_candles(self, ticker, start, end, *, series_ticker, market_settled_at=None):
            return []

    with caplog.at_level("WARNING"):
        ladder_1h, ladder_close = event_ladders(Client(), [empty], 1000.0, 1000.0)

    assert ladder_1h == [] and ladder_close == []
    assert any("KXPAYROLLS-26AUG" in r.getMessage() for r in caplog.records), caplog.text


# ── one bad market must not cost the whole build ──────────────────────────────


def _raw_markets():
    """Raw Kalshi market payloads per series, as `/historical/markets` and `/markets` return them.

    Real `group_events` runs on these, so the event/reference-month mapping is exercised rather than
    stubbed: 26JUN -> 2026-06-01 and so on.
    """
    plan = (("KXPAYROLLS", "26JUN", "2026-07-02T12:29:00Z", (0, 100000)),
            ("KXPAYROLLS", "26JUL", "2026-08-07T12:29:00Z", (0, 100000)),
            ("KXU3", "26JUL", "2026-08-07T12:29:00Z", (4.0, 4.1)))
    out: dict[str, list[dict]] = {}
    for series, tag, close, floors in plan:
        out.setdefault(series, []).extend(
            {"ticker": f"{series}-{tag}-T{floor:g}", "event_ticker": f"{series}-{tag}", "series_ticker": series,
             "strike_type": "greater", "floor_strike": floor, "cap_strike": None,
             "open_time": "2026-01-01T00:00:00Z", "close_time": close, "title": "jobs", "settlement_ts": None}
            for floor in floors)
    return out


def _series_client(raw_markets, *, fail=None):
    """A KalshiHistoryClient stand-in that serves `raw_markets` and a two-point ladder per market.

    Candle times come from the requested window (`end` is the market's pre-release moment), so every
    market gets quotes at ITS OWN decision and close times rather than one shared wall clock.

    `fail(ticker)` returns True to stage a 404 for that market.
    """
    class Client:
        def settled_markets(self, series):
            return list(raw_markets.get(series, []))

        def open_markets(self, series):
            return []

        def merged_candles(self, ticker, start, end, *, series_ticker, market_settled_at=None):
            if fail is not None and fail(ticker):
                raise RuntimeError("404 Client Error: for url: /series/.../candlesticks")
            return [Candle(end - timedelta(hours=2), 0.28, 0.32, 1.0), Candle(end, 0.38, 0.42, 1.0)]

    return Client()


def _install_fake_labor(monkeypatch, mod):
    """Stub the ALFRED/model half of `build_rows`; the Kalshi ladder is what these tests exercise."""
    from tradehub.data.labor_inputs import LaborInputs
    from tradehub.engines.labor import EstimatePath

    empty = LaborInputs(payems={}, unrate={}, adp={}, icsa={}, ccsa={}, hires={}, openings={})
    monkeypatch.setattr(mod, "load_labor_inputs", lambda **kw: empty)
    monkeypatch.setattr(mod, "payroll_nowcasts", lambda *a, **k: {})
    monkeypatch.setattr(mod, "estimate_path", lambda *a, **k: EstimatePath())
    return EstimatePath


def test_a_404_on_one_event_still_writes_every_other_row(monkeypatch, caplog):
    from tradehub.scripts import build_jobs_scorecard as mod

    raws = _raw_markets()
    _install_fake_labor(monkeypatch, mod)
    client = _series_client(raws, fail=lambda t: "26JUN" in t)

    with caplog.at_level("WARNING"):
        rows, stats = mod.build_rows(client, since=date(2026, 1, 1), today=date(2026, 9, 25), cache_dir=None)

    assert {(r["series"], r["reference_month"]) for r in rows} == {
        ("payrolls", "2026-06-01"), ("payrolls", "2026-07-01"), ("unemployment", "2026-07-01")}
    june = next(r for r in rows if r["reference_month"] == "2026-06-01")
    assert june["kalshi_ladder_1h"] == [] and june["kalshi_mean_1h"] is None
    # The nowcast half of the June row is still recorded: a missing ladder must not lose the print.
    july = next(r for r in rows if r["reference_month"] == "2026-07-01" and r["series"] == "payrolls")
    assert july["kalshi_ladder_1h"], "a healthy event lost its ladder"
    assert stats["rows"] == 3 and stats["rows_skipped"] == 1, stats
    assert any("KXPAYROLLS-26JUN" in r.getMessage() for r in caplog.records), caplog.text


def test_the_counts_distinguish_a_full_ladder_from_a_partial_one(monkeypatch):
    from tradehub.scripts import build_jobs_scorecard as mod

    raws = _raw_markets()
    _install_fake_labor(monkeypatch, mod)
    client = _series_client(raws, fail=lambda t: t.endswith("-T100000") or t.endswith("-T4.1"))

    _rows, stats = mod.build_rows(client, since=date(2026, 1, 1), today=date(2026, 9, 25), cache_dir=None)

    assert stats["rows"] == 3
    assert stats["rows_with_full_ladder"] == 0, "a partial ladder was counted as full"
    assert stats["rows_skipped"] == 0, "a partial ladder is not a skipped row"


def test_exit_code_is_non_zero_only_when_every_row_failed():
    from tradehub.scripts.build_jobs_scorecard import scorecard_exit_code

    assert scorecard_exit_code({"rows": 3, "rows_skipped": 1}) == 0
    assert scorecard_exit_code({"rows": 3, "rows_skipped": 3}) == 1
    assert scorecard_exit_code({"rows": 0, "rows_skipped": 0}) == 0, "an empty run is not a failure"


def test_main_reports_the_counts_and_dry_run_writes_nothing(monkeypatch, capsys):
    from tradehub.scripts import build_jobs_scorecard as mod

    raws = _raw_markets()
    _install_fake_labor(monkeypatch, mod)
    client = _series_client(raws)
    monkeypatch.setattr(mod, "KalshiHistoryClient", lambda **kw: client)

    def explode(*a, **k):
        raise AssertionError("--dry-run wrote to Supabase")

    monkeypatch.setattr(mod, "upsert_scorecard", explode)

    assert mod.main(["--since", "2026-01", "--dry-run"]) == 0
    printed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert printed["rows"] == 3 and printed["rows_with_full_ladder"] == 3, printed
    assert printed["written"] == 0 and printed["rows_skipped"] == 0, printed


# ── idempotence ───────────────────────────────────────────────────────────────


def test_the_upsert_is_idempotent_on_series_and_reference_month(monkeypatch):
    """Re-running the builder must produce the SAME keys, including for a row whose ladder came back
    empty -- otherwise a partial run would insert a second row for the same release."""
    from tradehub.scripts import build_jobs_scorecard as mod

    raws = _raw_markets()
    _install_fake_labor(monkeypatch, mod)
    keys = []
    payloads = []
    for _ in range(2):
        client = _series_client(raws, fail=lambda t: "26JUN" in t)
        rows, _stats = mod.build_rows(client, since=date(2026, 1, 1), today=date(2026, 9, 25), cache_dir=None)
        keys.append([(r["series"], r["reference_month"]) for r in rows])
        payloads.append([{k: v for k, v in r.items() if k != "updated_at"} for r in rows])

    assert keys[0] == keys[1], keys
    assert payloads[0] == payloads[1], "a second run produced different row content"
    assert len(set(keys[0])) == len(keys[0]), f"duplicate (series, reference_month) keys: {keys[0]}"
