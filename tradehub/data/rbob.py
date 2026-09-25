"""RBOB gasoline futures (front month) daily closes as point-in-time observations."""

from __future__ import annotations

import inspect
from datetime import date, datetime, time, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tradehub.backtest.pit import Observation

RBOB_SYMBOL = "RB=F"
_SETTLE_TZ = ZoneInfo("America/New_York")
_MONTH_CODES = "FGHJKMNQUVXZ"


def _front_contract(day: date) -> str:
    """Return the expected front delivery contract for a calendar date.

    RBOB's front contract rolls at the calendar-month boundary (the prior
    delivery month stops trading at the end of its last business day). The
    contract code is carried in the observation name so mixed-contract windows
    can be rejected without guessing from price jumps.
    """
    year = day.year + (1 if day.month == 12 else 0)
    month = 1 if day.month == 12 else day.month + 1
    return f"RB{_MONTH_CODES[month - 1]}{year % 100:02d}.NYM"


def _default_history(start: date | None = None, end: date | None = None) -> Any:
    import yfinance as yf

    kwargs: dict[str, Any] = {"interval": "1d", "auto_adjust": False}
    if start is None and end is None:
        kwargs["period"] = "2y"
    else:
        if start is not None:
            kwargs["start"] = start.isoformat()
        if end is not None:
            kwargs["end"] = end.isoformat()
    return yf.Ticker(RBOB_SYMBOL).history(**kwargs)


def _call_history(history_fn: Callable[..., Any], start: date | None, end: date | None) -> Any:
    try:
        parameters = inspect.signature(history_fn).parameters.values()
    except (TypeError, ValueError):
        return history_fn()
    names = {parameter.name for parameter in parameters}
    accepts_kwargs = any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters)
    if accepts_kwargs or {"start", "end"}.issubset(names):
        return history_fn(start=start, end=end)
    return history_fn()


def rbob_closes(
    start: date | None = None,
    end: date | None = None,
    *,
    history_fn: Callable[..., Any] = _default_history,
) -> list[Observation]:
    frame = _call_history(history_fn, start, end)
    if frame is None or "Close" not in frame:
        return []
    contract_column = next(
        (column for column in ("Contract", "contract", "Contract Month") if column in frame),
        None,
    )
    contracts = frame[contract_column] if contract_column is not None else None
    out = []
    for stamp, close in frame["Close"].items():
        if close is None or close != close:  # NaN check without requiring pandas.
            continue
        day = stamp.date()
        if start is not None and day < start:
            continue
        if end is not None and day >= end:
            continue
        contract = None
        if contracts is not None:
            try:
                contract = contracts.loc[stamp]
            except (AttributeError, KeyError, TypeError):
                contract = None
        if contract is None or str(contract).lower() in {"", "nan", "none"}:
            contract = _front_contract(day)
        published = datetime.combine(day, time(18, 0), _SETTLE_TZ).astimezone(timezone.utc)
        out.append(Observation(f"RBOB:{contract}:{day.isoformat()}", float(close), published))
    return sorted(out, key=lambda observation: observation.published_at)
