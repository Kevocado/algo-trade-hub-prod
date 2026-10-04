"""Daily-direction plumbing for any family (v2 spec §8), generalising `spx.py` over calendar and source.

Target, exactly (same as the S&P): `<family>:<t>:up` is 1 iff the close of session t is strictly above
the previous session's close; unchanged is not up. t is the first session (in the family's calendar)
whose 08:00 CT freeze is still ahead, frozen inside `FREEZE_LEAD` of it. A close is usable only once
its exchange-local date is over (`closed_only`): a bar for "today" may be an intraday price, and
settling on it would grade a forecast against a number that later moves.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tradehub.journal.contract import CalendarEntry, Settlement
from tradehub.journal.spx import CT, FREEZE_LEAD, HISTORY_DAYS, climatology_up, freeze_at, up_outcome

Fetch = Callable[[date], tuple[Mapping[date, float], str]]  # start -> (closes, exchange tz name)


@dataclass(frozen=True)
class DailySource:
    family: str
    source: str  # settlement source label, e.g. "fred:VIXCLS"
    fetch: Fetch
    is_session: Callable[[date], bool]


def daily_target(family: str, day: date) -> str:
    return f"{family}:{day.isoformat()}:up"


def target_day(target: str) -> date:
    return date.fromisoformat(target.split(":")[1])


def next_session(day: date, is_session: Callable[[date], bool]) -> date:
    while not is_session(day):
        day += timedelta(days=1)
    return day


def previous_session(day: date, is_session: Callable[[date], bool]) -> date:
    """The session STRICTLY before `day`. Its own walk, because `next_session` walks forward from its
    argument and so returns `day` itself -- the target, whose close has not printed yet."""
    day -= timedelta(days=1)
    while not is_session(day):
        day -= timedelta(days=1)
    return day


def next_target_day(now: datetime, is_session: Callable[[date], bool]) -> date | None:
    day = next_session(now.astimezone(CT).date(), is_session)
    if freeze_at(day) <= now:
        day = next_session(day + timedelta(days=1), is_session)
    return day if freeze_at(day) - now <= FREEZE_LEAD else None


def closed_only(closes: Mapping[date, float], tz_name: str, now: datetime) -> dict[date, float]:
    """Drop bars dated today or later in the exchange's own time zone."""
    today = now.astimezone(ZoneInfo(tz_name)).date()
    return {d: v for d, v in closes.items() if d < today}


class DailyCloses:
    """One family's closes, fetched at most once per hourly run and shared by its forecasters."""

    def __init__(self, source: DailySource):
        self.source = source
        self._hour: datetime | None = None
        self._closes: dict[date, float] = {}

    def get(self, now: datetime) -> dict[date, float]:
        hour = now.astimezone(CT).replace(minute=0, second=0, microsecond=0)
        if self._hour != hour:
            closes, tz_name = self.source.fetch(hour.date() - timedelta(days=HISTORY_DAYS))
            self._closes = closed_only(closes, tz_name, now)
            self._hour = hour
        return self._closes


def daily_entry(now: datetime, closes: DailyCloses) -> list[CalendarEntry]:
    day = next_target_day(now, closes.source.is_session)
    if day is None:
        return []
    return [CalendarEntry(daily_target(closes.source.family, day), closes.source.family, "daily", freeze_at(day),
                          climatology_prob=climatology_up(closes.get(now), day))]


def settle_daily(target: str, now: datetime, closes: DailyCloses) -> Settlement | None:
    day = target_day(target)
    data = closes.get(now)
    outcome = up_outcome(data, day) if closes.source.is_session(day) else None
    if outcome is None:
        return None
    return Settlement(target, outcome, closes.source.source, realized_value=data[day])
