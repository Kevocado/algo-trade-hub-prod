"""Point-in-time replay of the sentiment meter (v2 spec §6).

Spec §6: "The backtest must apply the same rule via FRED `realtime_start` vintages, or it is scoring
information the live meter never had." The live meter reads FRED's CURRENT vintage at its 08:00 CT
freeze, so everything it saw was published before the freeze by construction. A replay over history has
to earn the same property, and the only way to earn it is to ask ALFRED what the series said on the
forecast's own date.

The fixture below is built so the two readings are far apart, because a no-leak test whose two sides
agree proves nothing: FRED restates the observations from `RESTATED_FROM` upward by +30, and the
restatement only entered ALFRED after the scored window closed. So every vintage inside the window
says 12-ish and only today's vintage says 42-ish.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from tradehub.journal.forecasters.sentiment import component, meter
from tradehub.journal.meter_replay import GONE, meter_on, read_vintages, replay_meter
from tradehub.journal.nyse import is_session, next_session
from tradehub.journal.replay import summary
from tradehub.journal.spx import SPX_SERIES, climatology_up, up_outcome

SESSIONS_START = date(2024, 1, 2)
N = 400
RESTATED_FROM_INDEX = 120  # observations from here up were restated, after the window closed
RESTATEMENT = 30.0  # the size of it: the series' whole range is 1.0
TODAY = date(2026, 1, 5)


def _sessions(n=N):
    out, day = [], SESSIONS_START
    while len(out) < n:
        if is_session(day):
            out.append(day)
        day += timedelta(days=1)
    return out


DAYS = _sessions()
FIRST_VINTAGE = DAYS[0]
WINDOW = (DAYS[253], DAYS[-2])
SCORED = [d for d in DAYS if WINDOW[0] <= d <= WINDOW[1]]
BASE = {name: {d: 12.0 + (i % 5) * 0.25 for i, d in enumerate(DAYS)}
        for name in ("VIXCLS", "BAMLH0A0HYM2")}
BASE["BAMLH0A0HYM2"] = {d: 3.0 + (i % 7) * 0.2 for i, d in enumerate(DAYS)}
CLOSES = {d: 5000.0 + 9.0 * i + (30.0 if i % 3 else -30.0) for i, d in enumerate(DAYS)}
SCORE_DAY = DAYS[300]  # inside the window: 300 prior observations, so both components resolve


def _published(series_id: str, obs: date, vintage: date) -> float:
    """What FRED said about observation `obs` in the vintage dated `vintage`."""
    if series_id == SPX_SERIES:
        return CLOSES[obs]
    value = BASE[series_id][obs]
    return value + RESTATEMENT if obs >= DAYS[RESTATED_FROM_INDEX] and vintage > WINDOW[1] else value


def vintage(series_id: str, as_of: date) -> dict[date, float]:
    return {d: _published(series_id, d, as_of) for d in DAYS if d < as_of}


def fetcher(*, point_in_time: bool = True, missing: tuple[date, ...] = ()):
    """A `fetch_vintages` stand-in, recording what it was asked for.

    `point_in_time=False` answers every date with TODAY's vintage instead of that date's own. That is
    the leak: it is what a current-vintage reader looks like from the inside.
    """
    calls: list[tuple[str, tuple[date, ...]]] = []

    def fetch(series_id, vintages, **_kwargs):
        dates = sorted(vintages)
        calls.append((series_id, tuple(dates)))
        return {v: vintage(series_id, v if point_in_time else TODAY) for v in dates if v not in missing}

    return fetch, calls


# ── The no-leak property ─────────────────────────────────────────────────────


def test_a_forecast_uses_its_own_dates_vintage_and_not_todays_restatement():
    """The one assertion this whole change exists for.

    Both readings are computed here, from the same `SentimentMeter` primitives, so the difference is the
    vintage and nothing else. The values are far apart on purpose: the as-of-day VIXCLS sits near 12.5
    and today's restatement lifts the same observations to near 42.5.
    """
    day = SCORE_DAY
    as_of_day, as_of_today = vintage("VIXCLS", day), vintage("VIXCLS", TODAY)
    assert max(as_of_day.values()) < 14.0
    assert max(as_of_today.values()) > 40.0, "the fixture no longer discriminates"

    pit = meter_on(day, read_vintages([day], fetch=fetcher()[0]))
    leaked = meter_on(day, read_vintages([day], fetch=fetcher(point_in_time=False)[0]))

    def hand(as_of: date) -> float:
        parts = [component(name, vintage(name, as_of), day, 252) for name in ("VIXCLS", "BAMLH0A0HYM2")]
        return meter(parts)[1]

    assert pit[0] == pytest.approx(hand(day))
    assert leaked[0] == pytest.approx(hand(TODAY))
    assert pit[0] != pytest.approx(leaked[0], abs=1e-6), "the two readings agree, so nothing is proved"
    # The root quantity, spelled out: the z-score each reading gives the same observation. Measured on
    # this fixture as +1.4156 vs +0.6753 on VIXCLS and +1.0000 vs +0.6679 on BAMLH0A0HYM2.
    for name in ("VIXCLS", "BAMLH0A0HYM2"):
        zs = [component(name, vintage(name, as_of), day, 252).z for as_of in (day, TODAY)]
        assert abs(zs[0] - zs[1]) > 0.3, (name, zs)
    # ... and what survives the meter's deliberately flat logistic (SLOPE = 0.10): 0.4998 against 0.5132.
    assert abs(pit[0] - leaked[0]) > 0.01, (pit[0], leaked[0])


def test_the_whole_replay_changes_when_the_current_vintage_is_used_instead_of_the_vintage():
    """Same property at the level the CLI reports it: the graded numbers depend on which vintage was read.

    Without this the single-day assertion above could still pass while the replay loop quietly used the
    current vintage for every day but the one tested.
    """
    honest = replay_meter(SCORED, read_vintages(SCORED, fetch=fetcher()[0]))
    leaked = replay_meter(SCORED, read_vintages(SCORED, fetch=fetcher(point_in_time=False)[0]))

    assert honest["n"] == leaked["n"] == len(SCORED) > 100
    assert honest["brier"] != pytest.approx(leaked["brier"], abs=1e-6)
    assert honest["bss"] != pytest.approx(leaked["bss"], abs=1e-6)
    assert honest["brier_diff"] != pytest.approx(leaked["brier_diff"], abs=1e-6)
    assert (honest["by_year"] != leaked["by_year"])
    # Measured on this fixture: brier 0.255499 honest against 0.258508 leaked, bss -0.036440 against
    # -0.043384. Neither reading is a result -- both are worse than the usual up-rate -- and that is
    # exactly the point: the number on the page changes with the vintage, so it cannot be quoted
    # without saying which one it is.


def test_the_reader_asks_for_the_forecast_days_own_vintage_and_never_for_todays():
    """Provenance, so a future refactor cannot get the values right by accident.

    Components are read at the forecast day's own vintage (the 08:00 CT freeze morning). SP500 is read
    one day later, because that is the first vintage that can contain the day's own close -- and it is
    the vintage `settle_spx` reads on the settlement morning.
    """
    _fetch, calls = fetcher()
    read_vintages(SCORED, fetch=_fetch)

    by_series = dict(calls)
    assert list(by_series) == ["VIXCLS", "BAMLH0A0HYM2", SPX_SERIES], "one batched call per series"
    for name in ("VIXCLS", "BAMLH0A0HYM2"):
        assert by_series[name] == tuple(SCORED), name
    assert by_series[SPX_SERIES] == tuple(d + timedelta(days=1) for d in SCORED)
    assert TODAY not in {d for dates in calls for d in dates}, "a current-vintage read crept in"


# ── Honest degradation: a gap is a gap, never a substituted value ─────────────


def test_a_day_with_no_vintage_produces_no_row_and_never_a_current_vintage_value(monkeypatch):
    """One missing vintage drops one day. The alternative -- reading today's vintage to fill it -- is the
    leak, so it is pinned shut from both sides: the day produces no row, and no current-vintage reader
    is reachable even if one is wired in."""
    from tradehub.data import fred_daily

    monkeypatch.setattr(fred_daily, "fetch_fred_daily",
                        lambda *a, **k: pytest.fail("a current-vintage read reached the meter replay"))

    withheld = (SCORED[0],)
    result = replay_meter(SCORED, read_vintages(SCORED, fetch=fetcher(missing=withheld)[0]))

    assert result["n"] == len(SCORED) - len(withheld) > 100
    assert result["date_from"] == SCORED[1].isoformat(), "the dropped day is still in the reported window"
    assert result["gaps"]["VIXCLS"] == len(withheld)


def test_a_run_with_no_vintages_at_all_reports_the_gap_and_writes_nothing(monkeypatch):
    """FRED_API_KEY unset and the keyless ALFRED path unreachable: there is no honest number, and the
    replay must say so rather than quietly produce a current-vintage one."""
    from tradehub.data import fred_daily

    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(fred_daily, "fetch_fred_daily",
                        lambda *a, **k: pytest.fail("a current-vintage read reached the meter replay"))

    result = replay_meter(SCORED, read_vintages(SCORED, fetch=lambda series, days, **k: {}))

    assert result["n"] == 0
    assert result["brier"] is None and result["bss"] is None and result["up_rate"] is None
    assert result["gaps"] == {"VIXCLS": len(SCORED), "BAMLH0A0HYM2": len(SCORED), SPX_SERIES: len(SCORED)}


def test_gdelt_tone_is_never_read_because_it_has_no_vintage_archive():
    """The optional component is dropped, and the drop is named. GDELT serves a rolling ~3 months and
    re-serves today's tone for a past date, so reading it point-in-time is not possible -- and reading
    it any other way is the leak. `meter()` renormalises over the components present, so the replay
    grades meter-v1's FRED-only configuration."""
    assert GONE == "gdelt_tone"
    result = replay_meter(SCORED, read_vintages(SCORED, fetch=fetcher()[0]))

    assert result["n"] == len(SCORED)
    assert result["components_dropped"] == [GONE]
    assert result["gaps"].get(GONE) is None, "a dropped component is not a gap: it was never asked for"
    # the FRED-only probability, computed from the same primitives, is what got graded
    day = SCORE_DAY
    parts = [component(name, vintage(name, day), day, 252) for name in ("VIXCLS", "BAMLH0A0HYM2")]
    assert meter_on(day, read_vintages([day], fetch=fetcher()[0]))[0] == pytest.approx(meter(parts)[1])


# ── Graded exactly as the journal grades it ──────────────────────────────────


def closes_up(day: date) -> int:
    closes = vintage(SPX_SERIES, day + timedelta(days=1))
    return up_outcome(closes, day)


def test_the_replay_is_graded_on_the_journals_own_up_rate_and_climatology():
    """Same primitives as `spx.settle_spx` and the same summary as the four models already in the table:
    up-rate, Brier, Brier against climatology, BSS and the paired gap with its standard error. Rebuilt
    here from `climatology_up`/`up_outcome` rather than read back from the result, so it is a check."""
    got = replay_meter(SCORED, read_vintages(SCORED, fetch=fetcher()[0]))

    rows = []
    for day in SCORED:
        pit = meter_on(day, read_vintages([day], fetch=fetcher()[0]))
        closes = vintage(SPX_SERIES, day + timedelta(days=1))
        rows.append((pit[0], climatology_up(closes, day), up_outcome(closes, day)))
    expected = summary(rows)

    assert got["n"] == expected["n"] == len(SCORED)
    for key in ("brier", "brier_baseline", "bss", "up_rate", "brier_diff", "brier_diff_se"):
        assert got[key] == pytest.approx(expected[key], abs=1e-6), key
    assert got["up_rate"] == pytest.approx(sum(closes_up(day) for day in SCORED) / len(SCORED))
    assert 0.4 < got["up_rate"] < 0.9, got["up_rate"]
    assert sum(v["n"] for v in got["by_year"].values()) == got["n"]


def test_the_reported_window_is_the_sessions_actually_scored():
    """`date_from`/`date_to` are the sessions that produced a row, not the days asked for.

    The first session AFTER the fixture ends is appended: it is a session the gate accepts, and the
    fixture holds no close for it, so it cannot be scored. Without a trailing unscoreable day the two
    rules are indistinguishable and an echo-the-window bug would pass.
    """
    beyond = next_session(DAYS[-1] + timedelta(days=1))  # `next_session(d)` returns d itself if it is one
    asked = [*SCORED, beyond]
    assert beyond not in SCORED and is_session(beyond)
    result = replay_meter(asked, read_vintages(asked, fetch=fetcher()[0]))

    assert result["n"] == len(SCORED)
    assert result["gaps"] == {SPX_SERIES: 1}, "the unscoreable day is reported as a gap, not hidden"
    assert result["date_from"] == SCORED[0].isoformat()
    assert result["date_to"] == SCORED[-1].isoformat()
    assert result["date_to"] == DAYS[-2].isoformat()
    assert result["date_to"] < beyond.isoformat()


def test_days_that_are_not_sessions_are_never_scored():
    """SCORED happens to be all sessions, so stating the rule on it would be vacuous. This states it on a
    list that is NOT: a Saturday, the Sunday after it, and the 2025-01-09 day of mourning the live
    journal already excludes (`is_session` is False for all three) must be skipped, not graded."""
    saturday = next(d for d in (SCORED[0] + timedelta(days=i) for i in range(60))
                    if d.weekday() == 5 and SCORED[0] < d <= SCORED[-1])
    spaced = sorted([*SCORED, saturday, saturday + timedelta(days=1), date(2025, 1, 9)])

    assert len(spaced) == len(SCORED) + 3
    assert [d for d in spaced if not is_session(d)] == [saturday, saturday + timedelta(days=1),
                                                        date(2025, 1, 9)]

    result = replay_meter(spaced, read_vintages(spaced, fetch=fetcher()[0]))
    assert result["n"] == len(SCORED)
    assert result["n"] == sum(1 for d in spaced if is_session(d))
    assert result["gaps"] == {}


def test_a_window_without_enough_history_scores_nothing_rather_than_guessing():
    short = DAYS[:100]
    result = replay_meter(short, read_vintages(short, fetch=fetcher()[0]))
    assert result["n"] == 0 and result["brier"] is None and result["bss"] is None


# ── The CLI wiring ───────────────────────────────────────────────────────────


def test_the_cli_replays_the_meter_alongside_the_four_and_reports_it_as_a_fifth(monkeypatch):
    from tradehub.scripts import backtest_daily as bd

    def fake_replay(closes, *, start, end, is_target=None):
        return {"n": 1, "brier": 0.25, "brier_baseline": 0.25, "bss": 0.0, "up_rate": 0.5,
                "brier_diff": 0.0, "brier_diff_se": None, "date_from": "a", "date_to": "b", "by_year": {}}

    def meter_replay(now, years, **_kwargs):
        return {"forecaster": "sentiment_meter", "forecaster_version": "meter-v1", "n": 7, "brier": 0.24,
                "brier_baseline": 0.25, "bss": 0.04, "brier_diff": -0.01, "brier_diff_se": 0.002,
                "up_rate": 0.53, "date_from": "c", "date_to": "d", "by_year": {}, "gaps": {}}

    monkeypatch.setattr(bd, "replay", fake_replay)
    monkeypatch.setattr(bd, "SOURCES", {("a", "a-v1"): lambda start: ({date(2020, 1, 2): 1.0}, "UTC")})

    now = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    out = bd.run(now, 1, meter=meter_replay)

    assert [r["forecaster"] for r in out] == ["a", "sentiment_meter"]
    assert out[1]["n"] == 7 and out[1]["forecaster_version"] == "meter-v1"


def test_main_hands_run_a_meter_replay(monkeypatch):
    """The wiring itself, since `run`'s `meter` argument is optional and a caller that forgot it would
    leave the meter's row off the page without failing anything."""
    from tradehub.scripts import backtest_daily as bd

    seen: dict[str, Any] = {}
    monkeypatch.setattr(bd, "load_local_env", lambda: None)
    monkeypatch.setattr(bd, "run", lambda now, years, **kw: seen.update(kw) or [])

    assert bd.main(["--years", "2", "--dry-run"]) == 0
    assert seen.get("meter") is bd.replay_meter_window


def test_a_meter_replay_that_cannot_be_point_in_time_is_reported_as_an_error_not_a_row():
    from tradehub.scripts import backtest_daily as bd

    def broken(now, years, **_kwargs):
        raise RuntimeError("FRED_API_KEY is not set and alfredgraph is unreachable")

    out = bd.run(datetime(2026, 1, 5, 12, 0, tzinfo=UTC), 1, calendars={}, meter=broken)

    assert [r["forecaster"] for r in out] == ["sentiment_meter"]
    assert out[0]["forecaster_version"] == "meter-v1"
    assert "FRED_API_KEY is not set" in out[0]["error"]
    assert bd.record(_NoWrite(), out, NOW) == 0


class _NoWrite:
    def table(self, name):
        raise AssertionError(f"a result with no row must not be written to {name}")


NOW = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)


def test_the_meter_row_is_written_to_journal_backtests_and_nowhere_else():
    """The one write this CLI is allowed to make. `record` builds its row key by key, so an extra key on
    the result -- the gap report -- is dropped rather than sent to a table that has no column for it."""
    from tradehub.scripts import backtest_daily as bd

    class Supa:
        def __init__(self):
            self.rows = []
            self.names = []

        def table(self, name):
            self.names.append(name)
            return self

        def insert(self, rows):
            self.rows = rows
            return self

        def execute(self):
            return self

    # a replay that really did hit gaps, so `gaps` is not empty and the assertions below have teeth
    withheld = (SCORED[3], SCORED[9])
    result = replay_meter(SCORED, read_vintages(SCORED, fetch=fetcher(missing=withheld)[0]))
    assert result["gaps"] == {"BAMLH0A0HYM2": len(withheld), SPX_SERIES: len(withheld),
                              "VIXCLS": len(withheld)}

    row = {"forecaster": "sentiment_meter", "forecaster_version": "meter-v1", **result}
    supa = Supa()

    assert bd.record(supa, [row], NOW) == 1
    assert supa.names == ["journal_backtests"]
    assert set(supa.rows[0]) == {"forecaster", "forecaster_version", "date_from", "date_to", "n", "brier",
                                 "brier_baseline", "bss", "brier_diff", "brier_diff_se", "by_year", "created_at"}
    assert not ({"gaps", "VIXCLS", "BAMLH0A0HYM2", "components_dropped"} & set(supa.rows[0])), (
        "a key with no column is an insert PostgREST refuses")


def test_the_meter_replay_never_names_a_journal_table_and_never_reaches_for_one():
    """Context, never evidence. Pinned as two absences: no current-vintage reader (the fallback that
    would reintroduce the leak) and no database client of any kind (the only way a not-counted number
    could reach a counted table)."""
    from pathlib import Path

    import tradehub.journal.meter_replay as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "fetch_fred_daily" not in source, "a current-vintage read is reachable from the meter replay"
    assert "supabase" not in source.lower()
    assert not [name for name in vars(module) if name in ("get_client", "get_supabase")]


def test_the_window_helper_fetches_only_the_sessions_in_the_window_and_labels_the_forecaster():
    from tradehub.scripts import backtest_daily as bd

    _fetch, calls = fetcher()
    now = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    today = now.date()
    out = bd.replay_meter_window(now, 1, fetch=_fetch, today=today)

    end = today - timedelta(days=1)
    start = end - timedelta(days=365)
    span = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    # NYSE sessions, minus any whose settlement vintage cannot exist yet (`fetch_vintages` drops
    # `v >= today`, so asking for one would report a gap that is really an artefact of the arithmetic).
    sessions = [d for d in span if is_session(d) and d + timedelta(days=1) < today]

    asked = dict(calls)
    assert list(asked) == ["VIXCLS", "BAMLH0A0HYM2", SPX_SERIES], "one batched call per series"
    assert asked["VIXCLS"] == asked["BAMLH0A0HYM2"] == tuple(sessions)
    assert asked[SPX_SERIES] == tuple(d + timedelta(days=1) for d in sessions)
    assert not [d for d in span if not is_session(d) and d in {x for dates in calls for x in dates}]

    assert out["forecaster"] == "sentiment_meter" and out["forecaster_version"] == "meter-v1"
    assert 0 < out["n"] <= len(sessions)
    assert out["date_to"] <= sessions[-1].isoformat()


def test_a_series_fred_does_not_know_raises_rather_than_reading_as_an_empty_vintage():
    """`fetch_vintages` distinguishes a typo'd id from a pre-history vintage on purpose. A replay that
    swallowed that would quietly score a series of nothing as though it were a gap."""
    from tradehub.data.alfred_vintages import SeriesNotFound

    def fetch(series_id, vintages, **_kwargs):
        if series_id == "BAMLH0A0HYM2":
            raise SeriesNotFound("FRED has no series 'BAMLH0A0HYM2'; the id is wrong, not the vintage")
        return {v: vintage(series_id, v) for v in sorted(vintages)}

    from tradehub.scripts import backtest_daily as bd

    with pytest.raises(SeriesNotFound):
        bd.replay_meter_window(datetime(2026, 1, 5, 12, 0, tzinfo=UTC), 1, fetch=fetch, today=date(2026, 1, 5))


def test_the_first_vintage_asked_for_is_never_today_or_later():
    """`fetch_vintages` drops `v >= today`, so asking would return nothing at all and the run would
    report a gap that is really a bug in the window arithmetic.

    `today` is a SATURDAY on purpose. With a weekday `today`, `now - 1 day` is the Sunday before it and
    the session gate already drops the day whose settlement vintage would land on `today`, so the trim
    would never be exercised and this test would pass vacuously.
    """
    _fetch, calls = fetcher()
    from tradehub.scripts import backtest_daily as bd

    today = date(2026, 1, 3)  # Sat: Fri 2026-01-02 is a session, and its settlement vintage IS today
    assert is_session(today - timedelta(days=1)) and not is_session(today)

    bd.replay_meter_window(datetime(2026, 1, 3, 12, 0, tzinfo=UTC), 1, fetch=_fetch, today=today)

    freezes = dict(calls)["VIXCLS"]
    asked = {d for _s, dates in calls for d in dates}
    assert asked, "nothing was asked for"
    # Fri 2026-01-02 is a session, and its settlement vintage is `today` itself -- so it is not asked for,
    # and the last freeze asked for is the session before it.
    assert freezes[-1] == date(2025, 12, 31), freezes[-1]
    assert max(asked) == date(2026, 1, 1), f"the last settlement vintage asked for was {max(asked)}"
    assert max(asked) < today, "a vintage that cannot exist yet was requested"


def test_the_fixture_really_has_a_restatement_to_find():
    """Guards the guard: if the two readings ever coincided, every no-leak assertion above would pass
    vacuously. Asserted on the raw fixture, not on the module."""
    day = SCORE_DAY
    assert vintage("VIXCLS", day)[DAYS[299]] == pytest.approx(12.0 + (299 % 5) * 0.25)
    assert vintage("VIXCLS", TODAY)[DAYS[299]] == pytest.approx(12.0 + (299 % 5) * 0.25 + RESTATEMENT)
    assert vintage("BAMLH0A0HYM2", day)[DAYS[299]] != vintage("BAMLH0A0HYM2", TODAY)[DAYS[299]]
    assert component("VIXCLS", vintage("VIXCLS", day), day, 252).z != pytest.approx(
        component("VIXCLS", vintage("VIXCLS", TODAY), day, 252).z, abs=0.1)


def test_the_forecaster_keys_match_the_live_journal_exactly():
    """The row is grouped by `(forecaster, forecaster_version)` on the page and in the endpoint, so a
    typo would file the replay under a key no card exists for."""
    from tradehub.journal.forecasters.sentiment import SentimentMeter

    assert (SentimentMeter.name, SentimentMeter.version) == ("sentiment_meter", "meter-v1")
    result = replay_meter(SCORED, read_vintages(SCORED, fetch=fetcher()[0]))
    assert (result["forecaster"], result["forecaster_version"]) == ("sentiment_meter", "meter-v1")