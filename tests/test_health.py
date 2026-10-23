"""Tests for the read-only health report (timers, per-family freeze, order-book age).

The module under test is pure: it turns already-fetched timestamps and counts into a report, so every
rule here is testable without a database, a network, or a filesystem.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tradehub.health import (
    FROZEN_WINDOW_HOURS,
    STALE_AFTER_HOURS,
    TIMERS,
    UNTRACKED_TIMERS,
    build_health_report,
    expected_daily,
    timer_status,
)

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


def _ago(**kwargs) -> datetime:
    return NOW - timedelta(**kwargs)


def test_a_timer_that_just_succeeded_is_ok():
    assert timer_status(_ago(minutes=5), NOW) == "ok"
    assert timer_status(_ago(hours=1, minutes=59), NOW) == "ok"


def test_a_timer_past_the_stale_window_is_stale_not_ok():
    assert timer_status(_ago(hours=STALE_AFTER_HOURS), NOW) == "stale"
    assert timer_status(_ago(hours=STALE_AFTER_HOURS, minutes=1), NOW) == "stale"


def test_a_timer_that_never_succeeded_is_never_not_stale():
    assert timer_status(None, NOW) == "never"


def test_only_daily_and_hourly_cadences_are_expected_to_freeze_every_day():
    assert expected_daily("daily") is True
    assert expected_daily("hourly") is True
    assert expected_daily("monthly") is False
    assert expected_daily("meeting") is False


def _report(**overrides):
    base = dict(
        timers={
            "scan": _ago(minutes=10),
            "settle": _ago(minutes=20),
            "journal": _ago(minutes=30),
            "orderbooks": _ago(minutes=40),
        },
        frozen_by_family={"weather_high": 20, "cpi_nowcast": 3},
        cadences={"weather_high": "daily", "cpi_nowcast": "monthly"},
        orderbook_age_seconds=600.0,
        now=NOW,
    )
    base.update(overrides)
    return build_health_report(**base)


def test_a_healthy_system_reports_ok_and_no_problems():
    report = _report()
    assert report["status"] == "ok"
    assert report["problems"] == []
    assert set(report["timers"]) == {"scan", "settle", "journal", "orderbooks"}
    assert report["families"]["weather_high"]["frozen_24h"] == 20
    assert report["families"]["cpi_nowcast"]["frozen_24h"] == 3


def test_a_stale_timer_degrades_the_report_and_names_the_timer():
    report = _report(timers={"scan": _ago(hours=6), "settle": _ago(minutes=20),
                             "journal": _ago(minutes=30), "orderbooks": _ago(minutes=40)})
    assert report["status"] == "degraded"
    assert report["timers"]["scan"]["status"] == "stale"
    assert any("scan" in p for p in report["problems"])


def test_a_daily_family_that_froze_nothing_in_24h_is_a_problem_but_a_monthly_one_is_not():
    report = _report(frozen_by_family={"weather_high": 0, "cpi_nowcast": 0})
    assert report["families"]["weather_high"]["silent"] is True
    assert report["families"]["cpi_nowcast"]["silent"] is False
    assert any("weather_high" in p for p in report["problems"])
    assert not any("cpi_nowcast" in p for p in report["problems"])
    assert report["status"] == "degraded"


def test_a_missing_orderbook_file_is_a_problem_not_a_zero():
    report = _report(orderbook_age_seconds=None)
    assert report["orderbook"]["newest_file_age_seconds"] is None
    assert report["orderbook"]["status"] == "missing"
    assert report["status"] == "degraded"


def test_a_stale_orderbook_is_a_problem():
    report = _report(orderbook_age_seconds=3600.0 * 5)
    assert report["orderbook"]["status"] == "stale"


def test_the_report_carries_the_frozen_window_and_generated_at():
    report = _report()
    assert report["generated_at"] == NOW.isoformat()
    assert report["frozen_window_hours"] == FROZEN_WINDOW_HOURS


def test_a_registry_family_missing_from_the_counts_read_froze_zero_and_is_silent():
    # The count read succeeded and held no row for weather_low: that is a measurement of zero.
    report = _report(frozen_by_family={"weather_high": 5},
                     cadences={"weather_high": "daily", "weather_low": "daily"})
    assert report["families"]["weather_low"]["frozen_24h"] == 0
    assert report["families"]["weather_low"]["silent"] is True
    assert any("weather_low" in p for p in report["problems"])


def test_an_unreadable_count_read_is_unknown_not_zero_and_never_silent():
    # `None` means the query FAILED. Reporting 0 here would raise a false "froze nothing" alert on a
    # database outage, which is the exact failure this distinction exists to prevent.
    report = _report(frozen_by_family=None, cadences={"weather_high": "daily"})
    assert report["families"]["weather_high"]["frozen_24h"] is None
    assert report["families"]["weather_high"]["silent"] is False
    assert not any("froze nothing" in p for p in report["problems"])


def test_the_orderbooks_timer_uses_its_own_longer_window():
    # A file written 2h ago is fine for a 3hly recorder but would be stale on a 2h timer. The order-book
    # entry must agree with the order-book block, not with the other three timers.
    report = _report(timers={"scan": _ago(minutes=5), "settle": _ago(minutes=5),
                             "journal": _ago(minutes=5), "orderbooks": _ago(hours=2)})
    assert report["timers"]["orderbooks"]["status"] == "ok"
    assert report["orderbook"]["status"] == "ok"


def test_a_non_datetime_latest_value_is_treated_as_unknown():
    from tradehub.health import _latest

    class Q:
        def __init__(self, value):
            self.value = value

        def select(self, *a, **k):
            return self

        def order(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def execute(self):
            return type("R", (), {"data": [{"c": self.value}]})()

    class S:
        def __init__(self, value):
            self.value = value

        def table(self, name):
            return Q(self.value)

    assert _latest(S("not-a-timestamp"), "t", "c") is None
    assert _latest(S("2026-10-17T11:00:00Z"), "t", "c") == _ago(hours=1)


# ─── timers with no marker are untracked, not broken ──────────────────────────
# `scan` and `settle` run hourly and write no record that the *job* ran. `scanner_runs` exists but
# `start_run`/`complete_run` are never called, so it stays empty; `predictions.settled_at` is only
# written when a contract actually settles, so it records "last time something settled". Reading
# either as a last-success marker reported both timers "never" while they were running fine, which
# made the whole page "degraded" on a healthy system -- a false alarm on the page whose only job is
# to be trusted about faults.


def test_only_scan_and_settle_lacking_markers_still_reports_ok():
    """The reported bug, as a test: untracked timers must not degrade a healthy system."""
    report = _report(timers={"scan": None, "settle": None,
                             "journal": _ago(minutes=10), "orderbooks": _ago(minutes=20)},
                    untracked=UNTRACKED_TIMERS)
    assert report["status"] == "ok"
    assert report["problems"] == []
    assert report["timers"]["journal"]["status"] == "ok"
    assert report["timers"]["orderbooks"]["status"] == "ok"


def test_an_untracked_timer_says_not_tracked_and_never_never():
    """Three different facts, three different words: fresh, stale/never, and not measured at all."""
    report = _report(timers={"scan": None, "settle": None,
                             "journal": _ago(minutes=10), "orderbooks": _ago(minutes=20)},
                    untracked=UNTRACKED_TIMERS)
    for name in ("scan", "settle"):
        assert report["timers"][name]["status"] == "not_tracked"
        assert report["timers"][name]["tracked"] is False
        # Unmeasured is not a measurement: no timestamp and no age, exactly like a missing order book.
        assert report["timers"][name]["last_success"] is None
        assert report["timers"][name]["age_seconds"] is None
    assert "never" not in {t["status"] for t in report["timers"].values()}


def test_a_tracked_timer_that_really_never_ran_is_still_never_and_still_degrades():
    """The anti-regression half. Dropping a timer from UNTRACKED must not silence a real fault, and a
    read that fails must not read as "untracked" -- that would turn a loud failure into a quiet gap."""
    report = _report(timers={"scan": None, "settle": None, "journal": None, "orderbooks": _ago(minutes=20)})
    assert report["timers"]["journal"]["status"] == "never"
    assert report["timers"]["journal"]["tracked"] is True
    assert report["status"] == "degraded"
    assert any("timer journal is never" in p for p in report["problems"])


def test_untracked_is_opt_in_so_the_pure_function_defaults_to_tracking_everything():
    """`build_health_report` called without `untracked` treats every timer as measured. If the caller
    forgets to pass it, the failure is a loud "never", never a silent hole."""
    report = _report(timers={"scan": None, "settle": None, "journal": _ago(minutes=10),
                             "orderbooks": _ago(minutes=20)}, untracked=None)
    assert report["timers"]["scan"]["status"] == "never"
    assert report["status"] == "degraded"


def test_untracked_timers_are_still_listed_on_the_report():
    """They are excluded from the fault count, never hidden: the gap stays visible on the page."""
    report = _report(timers={"scan": None, "settle": None,
                             "journal": _ago(minutes=10), "orderbooks": _ago(minutes=20)},
                     untracked=UNTRACKED_TIMERS)
    assert set(report["timers"]) == {"scan", "settle", "journal", "orderbooks"}
    assert report["untracked_timers"] == ["scan", "settle"]
    assert report["tracked_timer_count"] == 2


def test_untracked_does_not_mask_a_fault_in_a_tracked_timer():
    report = _report(timers={"scan": None, "settle": None,
                             "journal": _ago(hours=6), "orderbooks": _ago(minutes=20)},
                     untracked=UNTRACKED_TIMERS)
    assert report["status"] == "degraded"
    assert any("timer journal is stale" in p for p in report["problems"])
    # And the untracked pair contributed nothing to that verdict.
    assert not any(p.startswith("timer scan") or p.startswith("timer settle") for p in report["problems"])


def test_the_untracked_set_is_exactly_the_two_jobs_with_no_marker():
    """Pin the policy, because it is fail-safe in the dangerous direction.

    Widening UNTRACKED_TIMERS silences a real timer: adding `journal` here would make a journal that
    never ran read as "not tracked" and the page would report `ok` on a system whose journal is dead.
    That is the exact false-negative this whole change exists to avoid, so the set is pinned to the
    two jobs whose absence of a marker is a documented fact about their code, and `journal` and
    `orderbooks` stay tracked.
    """
    assert UNTRACKED_TIMERS == {"scan", "settle"}
    assert UNTRACKED_TIMERS < set(TIMERS)
    assert {"journal", "orderbooks"} & UNTRACKED_TIMERS == set()


# ─── sports calendar: daily families only expected to freeze when calendar has targets ───────

def test_a_daily_non_sports_family_with_calendar_entries_and_zero_frozen_is_silent():
    """A daily family (weather, gas, ercot, etc.) that has calendar targets in the window but froze
    nothing is still a problem. This is the regression guard: the fix for sports must not silence
    real daily families that actually should freeze every day."""
    # The calendar read returns targets with cutoffs inside [now-24h, now+24h] for this family
    calendar_by_family = {
        "weather_high": [
            {"target": "KXHIGHNY-26OCT17-75", "family": "weather_high", "cadence": "daily",
             "cutoff_at": "2026-10-17T05:30:00+00:00", "market_linked": True},
        ],
    }
    # Build the report with calendar data
    from tradehub.health import build_health_report
    report = build_health_report(
        timers={"scan": _ago(minutes=10), "settle": _ago(minutes=20),
                "journal": _ago(minutes=30), "orderbooks": _ago(minutes=40)},
        frozen_by_family={"weather_high": 0},
        cadences={"weather_high": "daily"},
        orderbook_age_seconds=600.0,
        now=NOW,
        calendar_by_family=calendar_by_family,
    )
    fam = report["families"]["weather_high"]
    assert fam["frozen_24h"] == 0
    assert fam["expected_daily"] is True
    assert fam["silent"] is True
    assert fam.get("reason") is None  # no reason, it's genuinely silent
    assert any("weather_high" in p for p in report["problems"])


def test_a_daily_sports_family_with_no_calendar_entries_in_window_is_not_silent():
    """A daily sports family (sports_nfl, sports_nfl_spread, etc.) with NO calendar entries whose
    cutoff falls in [now-24h, now+24h] is NOT expected to freeze. It should report expected_daily=False,
    silent=False, with reason='no_game_window', and NOT add a problem line."""
    # Calendar returns empty for sports_nfl because no NFL games have cutoffs in the window
    calendar_by_family = {
        "sports_nfl": [],  # no targets with cutoffs in the window
    }
    from tradehub.health import build_health_report
    report = build_health_report(
        timers={"scan": _ago(minutes=10), "settle": _ago(minutes=20),
                "journal": _ago(minutes=30), "orderbooks": _ago(minutes=40)},
        frozen_by_family={"sports_nfl": 0},
        cadences={"sports_nfl": "daily"},
        orderbook_age_seconds=600.0,
        now=NOW,
        calendar_by_family=calendar_by_family,
    )
    fam = report["families"]["sports_nfl"]
    assert fam["frozen_24h"] == 0
    assert fam["expected_daily"] is False  # not expected when no games
    assert fam["silent"] is False
    assert fam.get("reason") == "no_game_window"
    # No problem should be added
    assert not any("sports_nfl" in p for p in report["problems"])


def test_a_daily_sports_family_with_calendar_entries_in_window_and_zero_frozen_is_silent():
    """If a sports family DOES have calendar entries in the window (game day) but froze nothing,
    it IS a problem - same as weather/gas."""
    calendar_by_family = {
        "sports_nfl": [
            {"target": "KXNFLGAME-26OCT17PHIKC-PHI", "family": "sports_nfl", "cadence": "daily",
             "cutoff_at": "2026-10-17T17:00:00+00:00", "market_linked": True},
        ],
    }
    from tradehub.health import build_health_report
    report = build_health_report(
        timers={"scan": _ago(minutes=10), "settle": _ago(minutes=20),
                "journal": _ago(minutes=30), "orderbooks": _ago(minutes=40)},
        frozen_by_family={"sports_nfl": 0},
        cadences={"sports_nfl": "daily"},
        orderbook_age_seconds=600.0,
        now=NOW,
        calendar_by_family=calendar_by_family,
    )
    fam = report["families"]["sports_nfl"]
    assert fam["frozen_24h"] == 0
    assert fam["expected_daily"] is True
    assert fam["silent"] is True
    assert fam.get("reason") is None
    assert any("sports_nfl" in p for p in report["problems"])


def test_calendar_read_failure_falls_back_to_cadence_based_expected_daily():
    """If the calendar read fails (returns None), fall back to old behavior: daily cadence means
    expected_daily=True, and zero frozen => silent=True."""
    from tradehub.health import build_health_report
    report = build_health_report(
        timers={"scan": _ago(minutes=10), "settle": _ago(minutes=20),
                "journal": _ago(minutes=30), "orderbooks": _ago(minutes=40)},
        frozen_by_family={"sports_nfl": 0},
        cadences={"sports_nfl": "daily"},
        orderbook_age_seconds=600.0,
        now=NOW,
        calendar_by_family=None,  # calendar read failed
    )
    fam = report["families"]["sports_nfl"]
    assert fam["expected_daily"] is True
    assert fam["silent"] is True
    assert any("sports_nfl" in p for p in report["problems"])


def test_a_daily_non_sports_family_with_no_calendar_entries_is_still_silent():
    """If a weather family's calendar writer stops, the empty calendar is the failure, not a day off."""
    report = build_health_report(
        timers={"scan": _ago(minutes=10), "settle": _ago(minutes=20),
                "journal": _ago(minutes=30), "orderbooks": _ago(minutes=40)},
        frozen_by_family={"weather_high": 0},
        cadences={"weather_high": "daily"},
        orderbook_age_seconds=600.0,
        now=NOW,
        calendar_by_family={"weather_high": []},
    )
    fam = report["families"]["weather_high"]
    assert fam["expected_daily"] is True and fam["silent"] is True
    assert any("weather_high" in p for p in report["problems"])


def test_only_sports_families_are_game_driven():
    from tradehub.health import is_game_driven

    assert is_game_driven("sports_nfl_spread_cal") and is_game_driven("sports_cfb")
    assert not any(is_game_driven(f) for f in ("weather_high", "gas_aaa", "ercot_peak", "eurusd", "gold"))


def test_the_calendar_read_asks_the_database_for_the_window_only():
    """1,871 calendar rows today and ~60 more a day: the health call must not page the whole table."""
    from tradehub.health import _fetch_calendar_by_family

    seen: list[tuple[str, str, str]] = []

    class Query:
        def select(self, *_):
            return self

        def gte(self, col, val):
            seen.append(("gte", col, val))
            return self

        def lte(self, col, val):
            seen.append(("lte", col, val))
            return self

        def order(self, *_):
            return self

        def range(self, *_):
            return self

        def execute(self):
            class R:
                data = [{"family": "sports_nfl", "cutoff_at": "2026-10-17T20:00:00+00:00"}]

            return R()

    class Supa:
        def table(self, name):
            assert name == "journal_calendars"
            return Query()

    out = _fetch_calendar_by_family(Supa(), NOW)
    assert out == {"sports_nfl": [{"family": "sports_nfl", "cutoff_at": "2026-10-17T20:00:00+00:00"}]}
    lo = (NOW - timedelta(hours=FROZEN_WINDOW_HOURS)).isoformat()
    hi = (NOW + timedelta(hours=FROZEN_WINDOW_HOURS)).isoformat()
    assert seen == [("gte", "cutoff_at", lo), ("lte", "cutoff_at", hi)]


def test_a_calendar_cutoff_that_is_already_a_datetime_counts_as_in_the_window():
    report = build_health_report(
        timers={"scan": _ago(minutes=10), "settle": _ago(minutes=20),
                "journal": _ago(minutes=30), "orderbooks": _ago(minutes=40)},
        frozen_by_family={"sports_nfl": 0},
        cadences={"sports_nfl": "daily"},
        orderbook_age_seconds=600.0,
        now=NOW,
        calendar_by_family={"sports_nfl": [{"cutoff_at": _ago(hours=3)}]},
    )
    fam = report["families"]["sports_nfl"]
    assert fam["expected_daily"] is True and fam["silent"] is True
