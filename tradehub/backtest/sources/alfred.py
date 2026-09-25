"""ALFRED (FRED archival) vintages: macro values exactly as they were known at a past date."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable

from tradehub.backtest.http import default_get_json
from tradehub.backtest.pit import Observation

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"


class AlfredSource:
    def __init__(self, series_id: str, api_key: str, get_json: Callable[..., Any] = default_get_json):
        self.series_id = series_id
        self._api_key = api_key
        self._get_json = get_json

    def latest_as_of(self, as_of: datetime) -> Observation | None:
        """Newest value knowable at `as_of`.

        ALFRED vintages are day-granular but releases land intraday (e.g. 8:30 ET),
        so we read the previous day's vintage and treat each vintage as available
        only from the start of the day after it began.
        """
        vintage_day = (as_of.astimezone(timezone.utc).date() - timedelta(days=1)).isoformat()
        data = self._get_json(FRED_OBSERVATIONS_URL, {
            "series_id": self.series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "realtime_start": vintage_day,
            "realtime_end": vintage_day,
            "sort_order": "desc",
            "limit": 50,
        })
        for obs in data.get("observations") or []:
            if obs.get("value") in (None, "", "."):
                continue
            began = datetime.combine(datetime.fromisoformat(obs["realtime_start"]).date(), time(0), timezone.utc)
            return Observation(
                name=f"{self.series_id}:{obs['date']}",
                value=float(obs["value"]),
                published_at=began + timedelta(days=1),
            )
        return None
