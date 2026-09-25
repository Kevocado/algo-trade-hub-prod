"""RBOB gasoline futures (front month) daily closes as point-in-time observations."""

from __future__ import annotations

import calendar
import inspect
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tradehub.backtest.pit import Observation

RBOB_SYMBOL = "RB=F"
_SETTLE_TZ = ZoneInfo("America/New_York")
_FUTURES_MONTH_CODES = "FGHJKMNQUVXZ"


def _last_business_day(year: int, month: int) -> date:
    day = date(year, month, calendar.monthrange(year, month)[1])
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def front_month_roll_dates(start: date, end: date) -> list[date]:
    """Return NYMEX RBOB roll dates: month-end business days before delivery."""
    if end < start:
        raise ValueError(f"end must not precede start, got {end!r} < {start!r}")
    rolls = []
    year = start.year
    month = start.month
    while True:
        roll = _last_business_day(year, month)
        if roll > end:
            break
        if roll >= start:
            rolls.append(roll)
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return rolls


def _front_contract(day: date) -> str:
    """Infer the next calendar month's delivery contract."""
    delivery_year = day.year
    delivery_month = day.month + 1
    if delivery_month == 13:
        delivery_month = 1
        delivery_year += 1
    code = _FUTURES_MONTH_CODES[delivery_month - 1]
    return f"RB{code}{delivery_year % 100:02d}.NYM"


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
