"""A FRED daily series as it stands now (current vintage), via the keyed API the VPS can reach.

The live journal freezes at a moment and reads the current vintage at that moment, so everything it
sees was, by construction, published before the freeze. Callers still filter observation dates
strictly before the target day, which is the same rule a replay must apply.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date

from tradehub.data.alfred_vintages import (
    FRED_API_KEY_ENV,
    FRED_SERIES_OBSERVATIONS,
    Vintage,
    default_get_text,
    parse_fred_observations_json,
)


def fetch_fred_daily(series_id: str, start: date, *, get_text: Callable[..., str] = default_get_text,
                     api_key: str | None = None, deadline: float | None = None) -> Vintage:
    key = (api_key if api_key is not None else os.getenv(FRED_API_KEY_ENV, "")).strip()
    if not key:
        raise RuntimeError(f"{FRED_API_KEY_ENV} is not set; the journal's daily series need the keyed FRED API")
    params = {"series_id": series_id, "observation_start": start.isoformat(), "file_type": "json", "api_key": key}
    extra = {} if deadline is None else {"deadline": deadline}
    return parse_fred_observations_json(get_text(FRED_SERIES_OBSERVATIONS, params, secret=key, **extra))
