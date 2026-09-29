"""S&P 500 next-session direction: the target the sentiment meter (§6) and the quant (§7) share.

Target, exactly: `spx:<t>:up` is 1 iff the S&P 500 close on session t (FRED `SP500`) is strictly
above the previous session's close; an unchanged close is not up. t is the first NYSE session whose
08:00 CT freeze is still ahead. Settlement source is FRED `SP500` rather than Stooq SPY: Stooq now
serves a JavaScript proof-of-work wall to scripts, and the journal does not bypass bot checks.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

from tradehub.data.fred_daily import fetch_fred_daily
from tradehub.journal.contract import CalendarEntry, Settlement
from tradehub.journal.nyse import is_session, next_session

CT = ZoneInfo("America/Chicago")
FREEZE_TIME_CT = time(8, 0)
# Frozen on the morning of t (05:00-08:00 CT), after FRED has the previous close: a 24h lead would
# freeze on the morning of t-1 and every forecast would be a day stale.
FREEZE_LEAD = timedelta(hours=3)
SPX_SERIES = "SP500"
HISTORY_DAYS = 3700  # FRED licenses about ten years of SP500
CLIMATOLOGY_SESSIONS = 1260  # five years of sessions
CLIMATOLOGY_BOUNDS = (0.02, 0.98)
SETTLEMENT_SOURCE = "fred:SP500"


def spx_target(day: date) -> str:
    return f"spx:{day.isoformat()}:up"


def target_day(target: str) -> date:
    return date.fromisoformat(target.split(":")[1])


def freeze_at(day: date) -> datetime:
    return datetime.combine(day, FREEZE_TIME_CT, CT)


def next_target_day(now: datetime) -> date | None:
    """The session whose freeze is the next one ahead, if that freeze is within FREEZE_LEAD."""
    day = next_session(now.astimezone(CT).date())
    if freeze_at(day) <= now:
        day = next_session(day + timedelta(days=1))
    return day if freeze_at(day) - now <= FREEZE_LEAD else None


def up_outcome(closes: Mapping[date, float], day: date) -> int | None:
    if day not in closes:
        return None
    earlier = [d for d in closes if d < day]
    return int(closes[day] > closes[max(earlier)]) if earlier else None


def climatology_up(closes: Mapping[date, float], before: date) -> float | None:
    days = sorted(d for d in closes if d < before)[-(CLIMATOLOGY_SESSIONS + 1):]
    if len(days) < 253:
        return None
    ups = [closes[b] > closes[a] for a, b in pairwise(days)]
    lo, hi = CLIMATOLOGY_BOUNDS
    return min(hi, max(lo, sum(ups) / len(ups)))


class SpxCloses:
    """FRED SP500 closes, fetched at most once per hourly run and shared by every SPX forecaster."""

    def __init__(self, fetch: Callable[..., Mapping[date, float]] = fetch_fred_daily):
        self._fetch = fetch
        self._hour: datetime | None = None
        self._closes: Mapping[date, float] = {}

    def get(self, now: datetime) -> Mapping[date, float]:
        hour = now.astimezone(CT).replace(minute=0, second=0, microsecond=0)
        if self._hour != hour:
            self._closes = self._fetch(SPX_SERIES, hour.date() - timedelta(days=HISTORY_DAYS))
            self._hour = hour
        return self._closes


def spx_entry(now: datetime, closes: SpxCloses, family: str) -> list[CalendarEntry]:
    day = next_target_day(now)
    if day is None:
        return []
    return [CalendarEntry(spx_target(day), family, "daily", freeze_at(day),
                          climatology_prob=climatology_up(closes.get(now), day))]


def settle_spx(target: str, now: datetime, closes: SpxCloses) -> Settlement | None:
    day = target_day(target)
    outcome = up_outcome(closes.get(now), day) if is_session(day) else None
    if outcome is None:
        return None
    return Settlement(target, outcome, SETTLEMENT_SOURCE, realized_value=closes.get(now)[day])
