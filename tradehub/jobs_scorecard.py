"""Jobs Scorecard rows (pure): nowcast vs Kalshi-implied vs first print vs revisions, per release.

One row per (series, reference_month). Payroll values are in thousands of
jobs (Kalshi strikes are converted); unemployment values are in percent.
The Kalshi ladders are isotonic-fixed usable mids (see tradehub.engines.ladder)
one hour before the release and at the last pre-release quote.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from tradehub.engines.labor import EstimatePath
from tradehub.engines.ladder import (
    Ladder,
    implied_mean,
    implied_median,
    ladder_brier,
    ladder_crps,
    normal_ladder,
)

JOBS_SCORECARD_TABLE = "jobs_scorecard"
SERIES_PAYROLLS = "payrolls"
SERIES_UNEMPLOYMENT = "unemployment"


@dataclass(frozen=True)
class NowcastSnapshot:
    mu: float
    sigma: float
    engine_version: str
    features: Mapping[str, float]


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None or not math.isfinite(value) else round(value, digits)


def _day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _ladder_json(ladder: Ladder) -> list[list[float]]:
    return [[round(cut, 4), round(prob, 4)] for cut, prob in ladder]


def scorecard_row(
    *,
    series: str,
    month: date,
    event_ticker: str | None,
    release: date | None,
    close_time: datetime | None,
    ladder_1h: Ladder,
    ladder_close: Ladder,
    nowcast: NowcastSnapshot | None,
    path: EstimatePath,
) -> dict[str, Any]:
    """Assemble one jobs_scorecard row; scores are filled once the first print exists."""
    first = path.first
    row: dict[str, Any] = {
        "series": series,
        "reference_month": month.isoformat(),
        "kalshi_event": event_ticker,
        "release_date": _day(release),
        "kalshi_close_ts": None if close_time is None else close_time.isoformat(),
        "nowcast_mu": None if nowcast is None else _round(nowcast.mu),
        "nowcast_sigma": None if nowcast is None else _round(nowcast.sigma),
        "engine_version": None if nowcast is None else nowcast.engine_version,
        "nowcast_features": {} if nowcast is None else {k: _round(float(v)) for k, v in nowcast.features.items()},
        "kalshi_ladder_1h": _ladder_json(ladder_1h),
        "kalshi_ladder_close": _ladder_json(ladder_close),
        "kalshi_mean_1h": _round(implied_mean(ladder_1h)) if len(ladder_1h) >= 2 else None,
        "kalshi_median_1h": _round(implied_median(ladder_1h)) if len(ladder_1h) >= 2 else None,
        "kalshi_mean_close": _round(implied_mean(ladder_close)) if len(ladder_close) >= 2 else None,
        "first_print": _round(first),
        "first_print_vintage": _day(path.first_vintage),
        "rev2": _round(path.second),
        "rev2_vintage": _day(path.second_vintage),
        "rev3": _round(path.third),
        "rev3_vintage": _day(path.third_vintage),
        "benchmark": _round(path.benchmark),
        "benchmark_vintage": _day(path.benchmark_vintage),
        "latest": _round(path.latest),
        "latest_vintage": _day(path.latest_vintage),
        "n_strikes": len(ladder_1h),
        "nowcast_abs_err": None,
        "kalshi_abs_err": None,
        "nowcast_brier": None,
        "kalshi_brier": None,
        "nowcast_crps": None,
        "kalshi_crps": None,
    }
    if first is None:
        return row
    if nowcast is not None:
        row["nowcast_abs_err"] = _round(abs(nowcast.mu - first))
    if row["kalshi_mean_1h"] is not None:
        row["kalshi_abs_err"] = _round(abs(row["kalshi_mean_1h"] - first))
    if ladder_1h:
        row["kalshi_brier"] = _round(ladder_brier(ladder_1h, first))
        row["kalshi_crps"] = _round(ladder_crps(ladder_1h, first))
        if nowcast is not None:
            ours = normal_ladder([cut for cut, _ in ladder_1h], nowcast.mu, nowcast.sigma)
            row["nowcast_brier"] = _round(ladder_brier(ours, first))
            row["nowcast_crps"] = _round(ladder_crps(ours, first))
    return row


def upsert_scorecard(supa, rows: list[dict[str, Any]], now: datetime) -> int:
    """Idempotent write keyed on (series, reference_month), stamping updated_at; returns rows sent."""
    if rows:
        stamped = [{**row, "updated_at": now.isoformat()} for row in rows]
        supa.table(JOBS_SCORECARD_TABLE).upsert(stamped, on_conflict="series,reference_month").execute()
    return len(rows)
