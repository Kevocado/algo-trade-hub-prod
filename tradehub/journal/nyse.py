"""NYSE full-day closures by rule (v2 spec §6: no freeze on non-session days).

Rules: New Year's Day (Saturday -> not observed; Sunday -> Monday), MLK Day, Washington's Birthday,
Good Friday, Memorial Day, Juneteenth (from 2022), Independence Day, Labor Day, Thanksgiving,
Christmas (Saturday -> Friday, Sunday -> Monday). Unscheduled closures (e.g. a national day of
mourning) are not predictable; such a day simply never settles, because it has no close.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


def _easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = (h + ell - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    return day - timedelta(days=1) if day.weekday() == 5 else day + timedelta(days=1) if day.weekday() == 6 else day


@lru_cache(maxsize=64)
def holidays(year: int) -> frozenset[date]:
    out = {
        _nth_weekday(year, 1, 0, 3), _nth_weekday(year, 2, 0, 3), _easter(year) - timedelta(days=2),
        _last_weekday(year, 5, 0), _observed(date(year, 7, 4)), _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4), _observed(date(year, 12, 25)),
    }
    new_year = date(year, 1, 1)
    if new_year.weekday() != 5:
        out.add(_observed(new_year))
    if year >= 2022:
        out.add(_observed(date(year, 6, 19)))
    return frozenset(out)


def is_session(day: date) -> bool:
    return day.weekday() < 5 and day not in holidays(day.year)


def next_session(day: date) -> date:
    """`day` itself if it is a session, else the next one."""
    while not is_session(day):
        day += timedelta(days=1)
    return day
