"""Walk-forward replay of a daily-direction model over history (plan 16): context, never counted.

The live journal needs 200 settled days before a daily model can pass its gate, which is most of a year
of waiting. This replays the same model over years that already happened, so there is an honest
out-of-sample answer today: for each session, the model is refit the way the journal refits it (once a
month, on sessions strictly before that month), predicts the session from closes strictly before it, and
is graded against the usual climatology rate on that session.

A replay is never a journal row. It is stored apart (`journal_backtests`), shown labelled "backtest, not
counted", and has no path into `journal_forecasts`, `journal_scores` or any gate: history cannot be frozen
before the fact, and the hindsight in choosing the model is real even when the fit is clean.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any, Protocol

from tradehub.journal.spx import climatology_up
from tradehub.models.spy_direction.features import features_for, training_set
from tradehub.models.spy_direction.model import fit


class Predictor(Protocol):
    def predict(self, row: dict[str, float]) -> float: ...


def _skill(brier: float | None, base: float | None) -> float | None:
    return None if brier is None or not base else 1.0 - brier / base


def _summary(rows: list[tuple[float, float, int]]) -> dict[str, Any]:
    """rows: (probability, climatology, outcome)."""
    if not rows:
        return {"n": 0, "brier": None, "brier_baseline": None, "bss": None, "up_rate": None}
    n = len(rows)
    brier = sum((p - y) ** 2 for p, _c, y in rows) / n
    base = sum((c - y) ** 2 for _p, c, y in rows) / n
    return {"n": n, "brier": round(brier, 6), "brier_baseline": round(base, 6),
            "bss": round(_skill(brier, base), 6) if base else None, "up_rate": round(sum(y for *_r, y in rows) / n, 6)}


def replay(closes: Mapping[date, float], *, start: date, end: date,
           fit_fn: Callable[..., Predictor] = fit) -> dict[str, Any]:
    ordered = sorted(closes)
    previous = dict(zip(ordered[1:], ordered[:-1], strict=True))
    models: dict[tuple[int, int], Predictor] = {}
    rows: list[tuple[float, float, int]] = []
    by_year: dict[str, list[tuple[float, float, int]]] = defaultdict(list)
    for day in ordered:
        if not start <= day <= end or day not in previous:
            continue
        found, clim = features_for(closes, day), climatology_up(closes, day)
        if found is None or clim is None:
            continue
        month = (day.year, day.month)
        if month not in models:
            x, y, used = training_set(closes, before=day.replace(day=1))
            models[month] = fit_fn(x, y, used)
        probability = models[month].predict(found[0])
        outcome = int(closes[day] > closes[previous[day]])
        rows.append((probability, clim, outcome))
        by_year[str(day.year)].append((probability, clim, outcome))
    return {**_summary(rows), "date_from": start.isoformat(), "date_to": end.isoformat(),
            "by_year": {year: _summary(group) for year, group in sorted(by_year.items())}}