"""RBOB gasoline futures (front month) daily closes as point-in-time observations."""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tradehub.backtest.pit import Observation

RBOB_SYMBOL = "RB=F"
_SETTLE_TZ = ZoneInfo("America/New_York")


def _default_history() -> Any:
    import yfinance as yf

    return yf.Ticker(RBOB_SYMBOL).history(period="2y", interval="1d")


def rbob_closes(history_fn: Callable[[], Any] = _default_history) -> list[Observation]:
    frame = history_fn()
    out = []
    for stamp, close in frame["Close"].items():
        day = stamp.date()
        published = datetime.combine(day, time(18, 0), _SETTLE_TZ).astimezone(timezone.utc)
        out.append(Observation(f"RBOB:{day.isoformat()}", float(close), published))
    return sorted(out, key=lambda o: o.published_at)
