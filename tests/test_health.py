"""Tests for the read-only health report (timers, per-family freeze, order-book age).

The module under test is pure: it turns already-fetched timestamps and counts into a report, so every
rule here is testable without a database, a network, or a filesystem.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tradehub.health import (
    FROZEN_WINDOW_HOURS,
    STALE_AFTER_HOURS,
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
