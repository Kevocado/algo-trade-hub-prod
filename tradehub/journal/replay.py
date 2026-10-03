"""Walk-forward replay of a daily-direction model over history (plan 16): context, never counted.

The live journal needs 200 settled days before a daily model can pass its gate, which is most of a year
of waiting. This replays the same model over years that already happened, so there is an honest
out-of-sample answer today: for each session, the model is refit the way the journal refits it (once a
month, on sessions strictly before that month), predicts the session from closes strictly before it, and
is graded against the usual climatology rate on that session.

A replay is never a journal row. It is stored apart (`journal_backtests`), shown labelled "backtest, not
counted", and has no path into `journal_forecasts`, `journal_scores` or any gate: history cannot be frozen
before the fact, and the hindsight in choosing the model is real even when the fit is clean.

`is_target` is the live forecaster's own calendar predicate -- NYSE sessions for SPX, VIX and gold, TARGET
days for EUR/USD, as `DailySource.is_session` already carries it. Scoring every date a feed happens to
publish instead is not a replay of the live journal: VIXCLS carries a print forward across market holidays,
and ungated that graded 21 days the market was shut, against 754 real sessions. A replay whose sessions are
not the journal's sessions measures something else.

`date_from`/`date_to` report the sessions actually scored, not the arithmetic window asked for: the window
is derived by subtracting days from the run date, so it can start or end on a Saturday, and it is the only
provenance a reader has for a number the page says is not counted.

An audit of the first replays found all four models within ±0.01 of climatology over ~760 sessions, with
the best of them about 1.1 standard errors from zero -- indistinguishable from noise, printed as `+0.010`.
A number with no interval reads as a result, so every summary also carries `brier_diff` (our squared error
minus the climatology's, session by session) and `brier_diff_se` (its standard error). "Better or worse
than the usual rate by X ± SE, over N sessions" is a claim a reader can check; a bare skill is not.
"""

from __future__ import annotations

import math
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


def _paired_se(gaps: list[float]) -> float | None:
    """The standard error of the mean per-session gap, `sample_sd(gaps) / sqrt(n)`.

    The gap is taken on the SAME session for both scores -- `(p_i - y_i)^2 - (c_i - y_i)^2` -- and not by
    differencing the two averages afterwards. That is the whole reason this statistic exists: the
    session-to-session swing in a squared error is enormous (a miss near 0.5 costs 0.25, a confident
    correct call 0.0001) and it is almost all shared, because both scores are graded on the same
    outcome. Pairing cancels it, leaving the spread of the part that is actually about skill.

    `None` below two sessions, never 0. A sample standard deviation needs `n - 1` in the denominator, and
    a single observation has no spread: reporting 0 there would claim perfect precision from one session,
    which is the failure this number was added to stop.
    """
    if len(gaps) < 2:
        return None
    mean = sum(gaps) / len(gaps)
    variance = sum((g - mean) ** 2 for g in gaps) / (len(gaps) - 1)
    return math.sqrt(variance) / math.sqrt(len(gaps))


def _summary(rows: list[tuple[float, float, int]]) -> dict[str, Any]:
    """rows: (probability, climatology, outcome)."""
    if not rows:
        return {"n": 0, "brier": None, "brier_baseline": None, "bss": None, "up_rate": None,
                "brier_diff": None, "brier_diff_se": None}
    n = len(rows)
    brier = sum((p - y) ** 2 for p, _c, y in rows) / n
    base = sum((c - y) ** 2 for _p, c, y in rows) / n
    gaps = [(p - y) ** 2 - (c - y) ** 2 for p, c, y in rows]
    se = _paired_se(gaps)
    # `bss` stays a bare ratio on purpose. Its standard error is not `brier_diff_se`: a delta-method
    # approximation of SE(bss) exists and is easy to write, but publishing one here would print a
    # number nobody measured as though it were the same kind of thing as the interval beside it. A
    # reader who wants skill with an interval divides the gap by the baseline -- `bss` is
    # `-brier_diff / brier_baseline`, by definition -- and the gap's own interval bounds it.
    return {"n": n, "brier": round(brier, 6), "brier_baseline": round(base, 6),
            "bss": round(_skill(brier, base), 6) if base else None, "up_rate": round(sum(y for *_r, y in rows) / n, 6),
            "brier_diff": round(sum(gaps) / n, 6), "brier_diff_se": None if se is None else round(se, 6)}


def replay(closes: Mapping[date, float], *, start: date, end: date,
           fit_fn: Callable[..., Predictor] = fit,
           is_target: Callable[[date], bool] | None = None) -> dict[str, Any]:
    ordered = sorted(closes)
    previous = dict(zip(ordered[1:], ordered[:-1], strict=True))
    models: dict[tuple[int, int], Predictor] = {}
    rows: list[tuple[float, float, int]] = []
    by_year: dict[str, list[tuple[float, float, int]]] = defaultdict(list)
    for day in ordered:
        if not start <= day <= end or day not in previous:
            continue
        if is_target is not None and not is_target(day):
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
    scored = [day for day in ordered if (start <= day <= end) and day in previous
              and (is_target is None or is_target(day))]
    return {**_summary(rows),
            "date_from": (scored[0].isoformat() if scored else start.isoformat()),
            "date_to": (scored[-1].isoformat() if scored else end.isoformat()),
            "by_year": {year: _summary(group) for year, group in sorted(by_year.items())}}