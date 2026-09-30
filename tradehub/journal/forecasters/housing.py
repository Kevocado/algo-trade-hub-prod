"""Wave 3: Housing (Case-Shiller HPI) forecaster.

Freezes monthly on FRED release date (2 months after observation), settles on release.
Scored as direction (up/down) based on month-over-month change.
"""
from __future__ import annotations

import pytz
from collections.abc import Mapping
from datetime import datetime, date
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement

CT = pytz.timezone("America/Chicago")
UTC = pytz.UTC


class HousingForecaster:
    """Housing forecaster for Wave 3."""
    name = "housing_direction"
    version = "v1"
    cadence = "monthly"

    def __init__(self, case_shiller: Mapping[date, float] | None = None):
        self._case_shiller = case_shiller or {}
        self._series = "CSNTINSA"  # FRED series name

    def targets(self, now: datetime) -> list[CalendarEntry]:
        """Return forecasted directions for upcoming months.

        The journal freezes at the FRED release date (approximately 2 months after
        observation). We return a list of CalendarEntry objects for the next
        month(s) after 'now', indicating the predicted direction (up/down).
        """
        # In a real implementation, we would:
        # 1. Find the next FRED release date after 'now'
        # 2. Compare case_shiller[release_date] vs case_shiller[release_date - 1 month]
        # 3. Return a CalendarEntry for that month with direction (up/down)
        # Since we don't have real FRED release scheduling, we simulate the behavior
        # by looking for recent data and predicting the direction.
        
        # This is a simplified version - in production we would integrate with FRED
        # release calendar and use actual Case-Shiller data
        today = date.today()
        # Look for the most recent data point we have
        available_dates = sorted(d for d in self._case_shiller.keys() if d <= today)
        if len(available_dates) < 2:
            # Not enough data to make a forecast
            return []
        
        # Use the two most recent months to determine trend
        recent_date = available_dates[-1]
        prior_date = available_dates[-2] if len(available_dates) >= 2 else None
        
        if prior_date and self._case_shiller[recent_date] and self._case_shiller[prior_date]:
            # Simple trend: if recent > prior, predict up; else down
            direction = "up" if self._case_shiller[recent_date] > self._case_shiller[prior_date] else "down"
            
            # Create a target for the next month (this is simplified)
            # In reality, we would look up the actual FRED release schedule
            # Approximate next month (not exact but works for demo)
            if recent_date.month == 12:
                next_month = date(recent_date.year + 1, 1, 1)
            else:
                next_month = date(recent_date.year, recent_date.month + 1, 1)
            
            # The freeze would be approximately 2 months before this
            # For now, we return a target with the next month as the settlement date
            target_id = f"cs:{next_month.isoformat()}:up"
            cutoff = datetime.combine(next_month, datetime.min.time(), CT)
            return [CalendarEntry(target_id, "housing", "monthly", cutoff)]
        
        return []

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        """Generate a forecast for the given entry.

        Returns a Forecast object with the predicted direction (up/down) for the
        entry's target month.
        """
        # Extract the target date from the target ID (cs:YYYY-MM-DD:up)
        target_str = entry.target
        if not target_str.startswith("cs:") or not target_str.endswith(":up"):
            return None
        
        try:
            target_date_str = target_str.split(":")[1]
            target_date = date.fromisoformat(target_date_str)
        except (IndexError, ValueError):
            return None
        
        # We only forecast if the target date is in the future
        if target_date <= date.today():
            return None
        
        # Simple baseline: predict the same direction as last known change
        available_dates = sorted(d for d in self._case_shiller.keys() if d < target_date)
        if len(available_dates) < 2:
            return None
        
        recent_date = available_dates[-1]
        prior_date = available_dates[-2] if len(available_dates) >= 2 else None
        
        if prior_date and self._case_shiller[recent_date] is not None and self._case_shiller[prior_date] is not None:
            # Simple persistence: predict the same direction as last change
            last_change_up = self._case_shiller[recent_date] > self._case_shiller[prior_date]
            predicted_prob = 0.6 if last_change_up else 0.4  # Slight bias toward persistence
            
            return Forecast(
                self.name, 
                self.version, 
                entry.target, 
                predicted_prob,
                payload={
                    "baseline": "persistence", 
                    "provisional": True,
                    "last_known": {
                        "date": recent_date.isoformat(),
                        "value": self._case_shiller[recent_date],
                        "prior_date": prior_date.isoformat() if prior_date else None,
                        "prior_value": self._case_shiller[prior_date] if prior_date else None
                    }
                }
            )
        
        return None

    def settle(self, target: str, now: datetime) -> Settlement | None:
        """Settle the forecast against the actual market outcome.

        Returns a Settlement object with the actual direction (up/down) for the
        target month.
        """
        # Extract the target date from the target ID (cs:YYYY-MM-DD:up)
        if not target.startswith("cs:") or not target.endswith(":up"):
            return None
        
        try:
            target_date_str = target.split(":")[1]
            target_date = date.fromisoformat(target_date_str)
        except (IndexError, ValueError):
            return None
        
        # We can only settle if the target date is in the past or present
        if target_date > date.today():
            return None  # Not yet settled
        
        # Get the actual Case-Shiller values for the target month and prior month
        available_dates = sorted(d for d in self._case_shiller.keys() if d <= target_date)
        if len(available_dates) < 2:
            return None  # Not enough data to determine direction
        
        recent_date = available_dates[-1]
        prior_date = available_dates[-2] if len(available_dates) >= 2 else None
        
        if prior_date and self._case_shiller[recent_date] is not None and self._case_shiller[prior_date] is not None:
            # Determine actual direction: up if recent > prior, else down
            actual_up = self._case_shiller[recent_date] > self._case_shiller[prior_date]
            
            return Settlement(
                target,
                1 if actual_up else 0,
                f"fred:{self._series}",
                realized_value=self._case_shiller[recent_date]
            )
        
        return None