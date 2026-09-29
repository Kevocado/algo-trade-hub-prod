from datetime import UTC, date, datetime, timedelta

from journal_fakes import FakeJournalDB

from tradehub.data.gdelt import parse_tone_timeline
from tradehub.journal.forecasters.sentiment import Component, SentimentMeter, component, meter
from tradehub.journal.nyse import holidays, is_session, next_session
from tradehub.journal.runner import run_journal
from tradehub.journal.spx import SpxCloses, climatology_up, next_target_day, up_outcome

CT_0700 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)  # Thu 07:00 CDT, before the 08:00 freeze


def _weekdays(start: date, n: int) -> list[date]:
    out, day = [], start
    while len(out) < n:
        if is_session(day):
            out.append(day)
        day += timedelta(days=1)
    return out


def _closes(days, step=1.0):
    return {d: 5000.0 + step * i * (1 if i % 2 else -0.5) for i, d in enumerate(days)}


def test_nyse_rules_match_the_published_2026_and_2027_calendars():
    assert holidays(2026) == {date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
                              date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
                              date(2026, 11, 26), date(2026, 12, 25)}
    assert date(2027, 3, 26) in holidays(2027) and date(2027, 12, 24) in holidays(2027)
    assert date(2027, 12, 31) not in holidays(2027)  # New Year 2028 is a Saturday: not observed on Friday
    assert next_session(date(2026, 11, 26)) == date(2026, 11, 27)


def test_the_target_is_the_next_session_whose_freeze_is_still_ahead():
    assert next_target_day(CT_0700) == date(2026, 10, 1)
    assert next_target_day(CT_0700 - timedelta(hours=3)) is None  # 04:00 CT: outside the 3h lead
    assert next_target_day(CT_0700 + timedelta(hours=2)) is None  # past today's freeze; tomorrow's is 23h out
    assert next_target_day(datetime(2026, 10, 2, 11, 0, tzinfo=UTC)) == date(2026, 10, 2)
    assert next_target_day(datetime(2026, 10, 4, 14, 0, tzinfo=UTC)) is None  # Sunday
    assert next_target_day(datetime(2026, 10, 5, 11, 30, tzinfo=UTC)) == date(2026, 10, 5)


def test_up_means_strictly_above_the_previous_session_close():
    closes = {date(2026, 9, 30): 100.0, date(2026, 10, 1): 100.0, date(2026, 10, 2): 101.0}
    assert up_outcome(closes, date(2026, 10, 1)) == 0  # unchanged is not up
    assert up_outcome(closes, date(2026, 10, 2)) == 1
    assert up_outcome(closes, date(2026, 10, 5)) is None  # no close yet


def test_climatology_is_the_trailing_up_share_and_needs_a_year():
    days = _weekdays(date(2024, 1, 2), 400)
    closes = {d: float(i) for i, d in enumerate(days)}  # always up
    assert climatology_up(closes, days[-1]) == 0.98
    assert climatology_up(dict(list(closes.items())[:100]), days[-1]) is None


def test_component_uses_only_values_before_the_day_and_flags_staleness():
    days = _weekdays(date(2025, 1, 2), 300)
    series = {d: 20.0 + (i % 5) for i, d in enumerate(days)}
    series[days[-1]] = 40.0  # a spike ON the target day must not be visible
    part = component("VIXCLS", series, days[-1], 252)
    assert part.observed == days[-2].isoformat() and abs(part.z) < 3
    later = component("VIXCLS", series, days[-1] + timedelta(days=10), 252)
    assert later.stale is True


def test_meter_needs_a_fresh_fred_component_and_renormalises_weights():
    fear = Component("VIXCLS", 35.0, "2026-09-30", 3.0, False)
    tone = Component("gdelt_tone", 1.0, "2026-09-30", 3.0, False)
    assert meter([tone]) is None  # GDELT alone is not enough
    score, prob = meter([fear])
    assert score == -100.0 and prob < 0.53
    score, _ = meter([fear, tone])
    assert score == -33.3  # (0.4 x -3 + 0.2 x +3) / 0.6 = -1 z -> -33.3 on the display scale


def test_gdelt_parser_reads_the_average_tone_series():
    payload = {"timeline": [{"series": "Average Tone", "data": [{"date": "20260705T000000Z", "value": 0.18}]}]}
    assert parse_tone_timeline(payload) == {date(2026, 7, 5): 0.18}


def test_meter_freezes_before_the_open_and_settles_on_the_close():
    days = _weekdays(date(2025, 6, 2), 340)
    closes = _closes(days + [date(2026, 10, 1)])
    fred = {name: {d: 20.0 + (i % 7) for i, d in enumerate(days)} for name in ("VIXCLS", "BAMLH0A0HYM2")}
    spx = SpxCloses(fetch=lambda series, start: {d: v for d, v in closes.items() if d < clock[0].date()})
    fc = SentimentMeter(spx, fred=lambda name, start: fred[name], tone=lambda: (_ for _ in ()).throw(OSError("429")))
    clock = [CT_0700]
    db = FakeJournalDB(lambda: clock[0])
    out = run_journal(db, [fc], clock[0])
    assert out["forecasters"]["sentiment_meter@meter-v1"]["frozen"] == 1
    [row] = db.tables["journal_forecasts"]
    assert row["target"] == "spx:2026-10-01:up" and row["payload"]["missing"] == ["gdelt_tone: OSError"]
    assert db.tables["journal_calendars"][0]["climatology_prob"] is not None
    clock[0] = datetime(2026, 10, 2, 13, 0, tzinfo=UTC)  # next morning: FRED has Oct 1's close
    out = run_journal(db, [fc], clock[0])
    assert out["forecasters"]["sentiment_meter@meter-v1"]["settled"] == 1
    assert db.tables["journal_scores"][0]["baseline"] == "climatology"




def test_the_registry_runs_the_meter():
    from tradehub.journal.registry import FORECASTERS

    assert ("sentiment_meter", "meter-v1") in {(f.name, f.version) for f in FORECASTERS}
