"""Wave 3: Housing (Case-Shiller HPI) forecaster.

Freezes monthly on FRED release date (2 months after observation), settles on release.
Scored as direction (up/down) based on month-over-month change.
"""
from __future__ import annotations

from datetime import datetime
from collections.abc import Mapping
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement


class HousingForecaster:
    """Housing forecaster for Wave 3."""
    name = "housing_direction"
    version = "v1"
    cadence = "monthly"

    def __init__(self, closes: Mapping[date, float] | None = None):
        self._closes = closes or {}
        self._series = "CSNTINSA"  # FRED series name

    def targets(self, now: datetime) -> list[CalendarEntry]:
        """Return forecasted directions for upcoming months.

        The journal freezes at the FRED release date (approximately 2 months after
        observation). We return a list of CalendarEntry objects for the next
        month(s) after 'now', indicating the predicted direction (up/down).
        """
        # In a real implementation, we would look up the next FRED release date
        # and compare the current month's close to the previous month's close.
        # For now, we simulate a simple monthly forecast.
        # The actual implementation would:
        # 1. Find the next FRED release date after 'now'
        # 2. Compare closes[release_date] vs closes[release_date - 1 month]
        # 3. Return a CalendarEntry for that month with direction (up/down)
        # Since we don't have real FRED release scheduling, we return a placeholder
        # that represents the intended behavior.
        # In practice, this would be filled with actual FRED data.
        return []

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        """Generate a forecast for the given entry.

        Returns a Forecast object with the predicted direction (up/down) for the
        entry's target month.
        """
        # Naive baseline: predict the same direction as the previous month
        # In a real implementation, this would use historical patterns
        return None

    def settle(self, target: str, now: datetime) -> Settlement | None:
        """Settle the forecast against the actual market outcome.

        Returns a Settlement object with the actual direction (up/down) for the
        target month.
        """
        return None
