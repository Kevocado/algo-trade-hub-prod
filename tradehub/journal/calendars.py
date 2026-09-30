"""Session calendars for the daily-direction families (v2 spec §8: each family states its own).

- NYSE sessions (`tradehub.journal.nyse`): S&P 500, VIX (CBOE follows NYSE), gold via the GLD ETF.
- TARGET business days: EUR/USD, because the ECB publishes one reference rate per TARGET day. They
  are weekdays except New Year's Day, Good Friday, Easter Monday, 1 May, 25 and 26 December.
"""

from __future__ import annotations

from datetime import date, timedelta

from tradehub.journal.nyse import _easter, is_session


def is_target_day(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    easter = _easter(day.year)
    closed = {date(day.year, 1, 1), easter - timedelta(days=2), easter + timedelta(days=1),
              date(day.year, 5, 1), date(day.year, 12, 25), date(day.year, 12, 26)}
    return day not in closed


__all__ = ["is_session", "is_target_day"]
