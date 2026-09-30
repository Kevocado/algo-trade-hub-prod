import random
from datetime import UTC, date, datetime, timedelta

from journal_fakes import FakeJournalDB

from tradehub.data.frankfurter import parse_rates
from tradehub.data.yahoo_chart import parse_chart
from tradehub.journal.calendars import is_target_day
from tradehub.journal.daily import DailyCloses, DailySource, closed_only, next_target_day, settle_daily
from tradehub.journal.forecasters.daily_direction import DirectionForecaster, eurusd_source, gold_source, vix_source
from tradehub.journal.nyse import is_session
from tradehub.journal.runner import run_journal
from tradehub.models.spy_direction.model import ArtifactStore


def _series(is_open, n=900, seed=5, start=date(2023, 1, 2)):
    rng, level, out, day = random.Random(seed), 100.0, {}, start
    while len(out) < n:
        if is_open(day):
            level *= 1.0 + rng.gauss(0.0002, 0.006)
            out[day] = level
        day += timedelta(days=1)
    return out


def test_target_calendar_skips_ecb_holidays_and_weekends():
    assert not is_target_day(date(2026, 4, 3))   # Good Friday
    assert not is_target_day(date(2026, 4, 6))   # Easter Monday
    assert not is_target_day(date(2026, 5, 1)) and not is_target_day(date(2026, 12, 26))
    assert is_target_day(date(2026, 9, 30)) and not is_target_day(date(2026, 10, 3))
    assert is_target_day(date(2026, 7, 3)) and not is_session(date(2026, 7, 3))  # the calendars differ


def test_frankfurter_and_yahoo_payloads_parse_to_date_keyed_closes():
    rates = parse_rates({"rates": {"2026-09-28": {"USD": 1.1378}, "2026-09-29": {"USD": 1.1355}}})
    assert rates == {date(2026, 9, 28): 1.1378, date(2026, 9, 29): 1.1355}
    payload = {"chart": {"result": [{
        "meta": {"exchangeTimezoneName": "America/New_York"},
        "timestamp": [1790688600, 1790775000, 1790861400],  # 13:30 UTC = 09:30 EDT
        "indicators": {"quote": [{"close": [382.89, None, 383.6]}], "adjclose": [{"adjclose": [1, 2, 3]}]},
    }]}}
    closes, tz = parse_chart(payload)
    assert tz == "America/New_York" and len(closes) == 2 and 382.89 in closes.values()
    assert 1.0 not in closes.values()  # raw close, never adjclose


def test_a_bar_dated_today_is_never_a_close():
    now = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)  # 11:00 EDT: today's GLD bar is intraday
    closes = {date(2026, 9, 30): 380.0, date(2026, 10, 1): 383.0}
    assert closed_only(closes, "America/New_York", now) == {date(2026, 9, 30): 380.0}
    same_evening = datetime(2026, 10, 2, 3, 0, tzinfo=UTC)  # 23:00 EDT on Oct 1: still "today"
    assert date(2026, 10, 1) not in closed_only(closes, "America/New_York", same_evening)
    next_day = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)  # 01:00 EDT on Oct 2: Oct 1 is over
    assert date(2026, 10, 1) in closed_only(closes, "America/New_York", next_day)


def test_the_target_follows_each_familys_own_calendar():
    friday = datetime(2026, 7, 3, 11, 0, tzinfo=UTC)  # 06:00 CDT on the US holiday
    assert next_target_day(friday, is_target_day) == date(2026, 7, 3)  # ECB still publishes
    assert next_target_day(friday, is_session) is None  # NYSE is shut and Monday's freeze is far off


def test_eurusd_freezes_before_the_fix_and_settles_on_the_ecb_rate(tmp_path):
    rates = _series(is_target_day)
    last = max(rates)
    day = last + timedelta(days=1)
    while not is_target_day(day):
        day += timedelta(days=1)
    rates[day] = rates[last] * 1.01  # the fix that will print on the target day
    published = {d: v for d, v in rates.items() if d < day}
    clock = [datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=11)]  # 06:00 CDT
    source = DailySource("eurusd", "ecb:EURUSD", lambda start: (dict(published), "Europe/Berlin"), is_target_day)
    fc = DirectionForecaster(DailyCloses(source), "eurusd_direction", "eurusd-wf-v1",
                             ArtifactStore(tmp_path, "eurusd_direction"))
    db = FakeJournalDB(lambda: clock[0])
    out = run_journal(db, [fc], clock[0])
    assert out["forecasters"]["eurusd_direction@eurusd-wf-v1"]["frozen"] == 1
    [row] = db.tables["journal_forecasts"]
    assert row["target"] == f"eurusd:{day.isoformat()}:up" and row["payload"]["source"] == "ecb:EURUSD"
    published[day] = rates[day]
    clock[0] = datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC) + timedelta(hours=11)
    out = run_journal(db, [fc], clock[0])
    assert out["forecasters"]["eurusd_direction@eurusd-wf-v1"]["settled"] == 1
    assert db.tables["journal_settlements"][0]["outcome"] == 1


def test_settle_waits_for_the_close_and_ignores_a_non_session():
    source = DailySource("vix", "fred:VIXCLS", lambda s: ({date(2026, 9, 29): 18.0}, "America/New_York"), is_session)
    closes = DailyCloses(source)
    now = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
    assert settle_daily("vix:2026-09-30:up", now, closes) is None  # FRED has not posted the 30th
    assert settle_daily("vix:2026-10-03:up", now, closes) is None  # a Saturday is not a session


def test_each_family_has_its_own_artifact_namespace_and_stale_data_is_a_gap(tmp_path):
    closes = _series(is_session)
    last = max(closes)
    source = DailySource("vix", "fred:VIXCLS", lambda s: (dict(closes), "America/New_York"), is_session)
    fc = DirectionForecaster(DailyCloses(source), "vix_direction", "vix-wf-v1", ArtifactStore(tmp_path, "vix_direction"))
    now = datetime.combine(last + timedelta(days=1), datetime.min.time(), UTC) + timedelta(hours=11)
    artifact, digest = fc.model_for(last + timedelta(days=1), now)
    assert (tmp_path / "vix_direction").is_dir() and not (tmp_path / "spy_direction").exists()
    assert artifact.train_end < (last + timedelta(days=1)).replace(day=1).isoformat() and len(digest) == 64
    from tradehub.journal.contract import CalendarEntry
    far = last + timedelta(days=30)
    assert fc.forecast(CalendarEntry(f"vix:{far.isoformat()}:up", "vix", "daily", now + timedelta(days=30)), now) is None


def test_the_registry_runs_wave_2_with_unique_keys_and_no_network():
    from tradehub.journal.registry import FORECASTERS

    keys = [(f.name, f.version) for f in FORECASTERS]
    assert {("vix_direction", "vix-wf-v1"), ("gold_direction", "gold-wf-v1"),
            ("eurusd_direction", "eurusd-wf-v1")} <= set(keys)
    assert len(set(keys)) == len(keys)
    assert vix_source().family == "vix" and gold_source().source == "yahoo:GLD" and eurusd_source().family == "eurusd"


def test_yahoo_requests_identify_the_journal_not_a_browser(monkeypatch):
    from tradehub.data import yahoo_chart

    seen = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(headers=headers, timeout=timeout)
        return Resp()

    monkeypatch.setattr(yahoo_chart.requests, "get", fake_get)
    assert yahoo_chart.default_get_json("https://x", {}) == {"ok": True}
    assert seen["headers"]["User-Agent"].startswith("tradehub-journal/") and "Mozilla" not in seen["headers"]["User-Agent"]
