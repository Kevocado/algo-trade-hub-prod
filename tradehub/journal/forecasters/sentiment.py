"""Sentiment meter v1 (v2 spec §6): a daily composite for next-session S&P 500 direction.

Components (each z-scored against its own trailing history, clipped to +/-3):
    VIXCLS        FRED, required-class  weight 0.4  sign -1 (fear)
    BAMLH0A0HYM2  FRED, required-class  weight 0.4  sign -1 (credit stress)
    GDELT tone    optional              weight 0.2  sign +1
Only values observed strictly before the target day are used. A component whose newest value is
older than STALE_DAYS is dropped and flagged. Weights renormalise over the components present; the
meter needs at least one FRED component or it records a gap.

Not in v1, with reasons (spec's weakest-dependency rule): CNN Fear & Greed answers scripts with HTTP
418; Stooq breadth sits behind a JavaScript proof-of-work wall; no free put/call endpoint was found
with evidence of free access. They are listed so their absence is a decision, not an oversight.

Output: `score` in [-100, 100] for display; probability = logistic(logit(PRIOR_UP) + SLOPE x s) with
s the weighted z in [-3, 3]. The constants are a documented prior, not a fit: v1 is `provisional`
throughout. A calibrated mapping ships as a new version (`meter-v2`) fitted only on meter-v1's
settled history, so no version is ever re-fit on the period it is scored on.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from tradehub.data.fred_daily import fetch_fred_daily
from tradehub.data.gdelt import fetch_market_tone
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.spx import SpxCloses, settle_spx, spx_entry, target_day

# name -> (weight, sign, trailing window in observations, required-class)
COMPONENTS = {
    "VIXCLS": (0.4, -1.0, 252, True),
    "BAMLH0A0HYM2": (0.4, -1.0, 252, True),
    "gdelt_tone": (0.2, 1.0, 60, False),  # the DOC API only reaches back ~3 months
}
Z_CLIP = 3.0
STALE_DAYS = 5
PRIOR_UP = 0.53  # long-run share of S&P 500 up sessions
SLOPE = 0.10  # logit units per unit of weighted z: a deliberately weak prior
FRED_LOOKBACK_DAYS = 500


@dataclass(frozen=True)
class Component:
    name: str
    value: float
    observed: str
    z: float
    stale: bool


def component(name: str, series: Mapping[date, float], day: date, window: int) -> Component | None:
    known = sorted(d for d in series if d < day)
    if len(known) < window + 1:
        return None
    latest = known[-1]
    history = [series[d] for d in known[-window - 1:-1]]
    spread = statistics.pstdev(history)
    if spread == 0:
        return None
    z = max(-Z_CLIP, min(Z_CLIP, (series[latest] - statistics.fmean(history)) / spread))
    return Component(name, series[latest], latest.isoformat(), z, (day - latest).days > STALE_DAYS)


def meter(parts: list[Component]) -> tuple[float, float] | None:
    """(score in [-100, 100], P(up)) from the fresh components, or None without a fresh FRED one."""
    fresh = [c for c in parts if not c.stale]
    if not any(COMPONENTS[c.name][3] for c in fresh):
        return None
    weight = sum(COMPONENTS[c.name][0] for c in fresh)
    s = sum(COMPONENTS[c.name][0] * COMPONENTS[c.name][1] * c.z for c in fresh) / weight
    logit = math.log(PRIOR_UP / (1.0 - PRIOR_UP)) + SLOPE * s
    return round(100.0 * s / Z_CLIP, 1), 1.0 / (1.0 + math.exp(-logit))


class SentimentMeter:
    name = "sentiment_meter"
    version = "meter-v1"
    cadence = "daily"

    def __init__(self, closes: SpxCloses, *, fred: Callable[..., Mapping[date, float]] = fetch_fred_daily,
                 tone: Callable[[], Mapping[date, float]] = fetch_market_tone):
        self._closes, self._fred, self._tone = closes, fred, tone

    def targets(self, now: datetime) -> list[CalendarEntry]:
        return spx_entry(now, self._closes, "spx")

    def _series(self, name: str, day: date) -> Mapping[date, float]:
        if name == "gdelt_tone":
            return self._tone()
        return self._fred(name, day - timedelta(days=FRED_LOOKBACK_DAYS))

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        day = target_day(entry.target)
        parts, missing = [], []
        for name, (_, _, window, _) in COMPONENTS.items():
            try:
                part = component(name, self._series(name, day), day, window)
            except Exception as exc:  # noqa: BLE001 - a source failing is recorded, not fatal
                missing.append(f"{name}: {type(exc).__name__}")
                continue
            if part is None:
                missing.append(name)
            else:
                parts.append(part)
        result = meter(parts)
        if result is None:
            return None
        score, prob = result
        return Forecast(self.name, self.version, entry.target, prob,
                        payload={"score": score, "provisional": True, "components": [asdict(c) for c in parts],
                                 "missing": missing})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_spx(target, now, self._closes)
