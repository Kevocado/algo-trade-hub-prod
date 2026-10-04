"""Point-in-time replay of the sentiment meter (v2 spec §6): every input as it stood on the forecast's
own date, or the day is a gap.

Spec §6 is why this file exists: "The backtest must apply the same rule via FRED `realtime_start`
vintages, or it is scoring information the live meter never had." The live meter reads FRED's CURRENT
vintage at its 08:00 CT freeze, so by construction everything it saw was published before the freeze. A
replay over history has to earn the same property, and the only way to earn it is to ask ALFRED what the
series said on the forecast's own date -- which is `alfred_vintages.fetch_vintages`, already this repo's
vintage reader (one HTTP client, the keyless alfredgraph CSV or the keyed API) and the one the labor
engine uses. There is no second FRED client here and no current-vintage reader to fall back on.

**There is no fallback, deliberately.** A missing vintage produces no row and a counted gap. Filling it
from today's vintage is precisely the leak this module exists to close, and a backtest that quietly does
it is worse than no backtest, because its number looks real.

Which vintage, per input:

  * VIXCLS, BAMLH0A0HYM2 -- the vintage dated the forecast day. These are the forecast's inputs, and the
    freeze is at 08:00 CT that morning.
  * SP500 -- the vintage dated one day later, the first that can contain the day's own close. It carries
    the label and the climatology baseline, which is what `settle_spx` reads on the settlement morning;
    `climatology_up` and `up_outcome` keep their own `d < day` filters, so nothing dated on or after the
    day reaches the forecast.
  * gdelt_tone -- not read, and named in `components_dropped`. GDELT's DOC API has no vintage archive:
    a rolling ~3 months that re-serves today's tone for a past date. There is no point-in-time read of it
    to make, so the replay grades meter-v1's FRED-only configuration -- which `meter()` already supports,
    since it renormalises the weights over the components present. A recorded drop, never a substitute.

Graded by `replay.summary` -- the same up-rate, Brier, Brier-vs-climatology, BSS and paired gap with its
standard error as the four replays already in the table -- against `spx.climatology_up`, the journal's own
baseline. A not-counted result: it lands in `journal_backtests` and this module holds no database client
at all, so it has no route to a counted table.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from tradehub.data.alfred_vintages import Vintage, fetch_vintages
from tradehub.journal.forecasters.sentiment import COMPONENTS, Component, component, meter
from tradehub.journal.nyse import is_session
from tradehub.journal.replay import summary
from tradehub.journal.spx import SPX_SERIES, climatology_up, up_outcome

FORECASTER = "sentiment_meter"
VERSION = "meter-v1"
# The one component with no vintage archive, named rather than silently omitted so the reader of a replay
# row knows the meter's optional 0.2 weight was not applied.
GONE = "gdelt_tone"
FRED_COMPONENTS = {name: spec for name, spec in COMPONENTS.items() if name != GONE}
# The first vintage that can contain a day's own close, and so the one the settlement reads.
SETTLEMENT_LAG = timedelta(days=1)


@dataclass(frozen=True)
class MeterVintages:
    """Every input the replay needs, each at the vintage it is read at.

    `components` is {series: {forecast day: that day's vintage}}; `closes` is {settlement day: SP500 as
    published that day}. An absent key means no vintage was available -- a gap, never a value read from
    some other date.
    """

    components: Mapping[str, Mapping[date, Vintage]]
    closes: Mapping[date, Vintage]


def read_vintages(
    days: Sequence[date],
    *,
    fetch: Callable[..., Mapping[date, Vintage]] = fetch_vintages,
    cache_dir: Any | None = None,
    today: date | None = None,
    deadline: float | None = None,
) -> MeterVintages:
    """The inputs for `days`, read at the vintage each is read at.

    One batched call per series, because batching is what `fetch_vintages` already does: 12 vintage
    columns per request on the keyless path, one paced request per uncached vintage on the keyed one,
    with every past vintage cached on disk afterwards. A `SeriesNotFound` (FRED has never heard of the
    id) stays an exception rather than becoming an empty vintage -- a typo must be loud, not a permanent
    quiet gap -- while a `VintageNotPublished` is an empty vintage and is treated as a gap below.
    """
    asked = sorted(set(days))
    kwargs: dict[str, Any] = {"cache_dir": cache_dir, "today": today, "deadline": deadline}
    components = {name: fetch(name, asked, **kwargs) for name in FRED_COMPONENTS}
    closes = fetch(SPX_SERIES, [d + SETTLEMENT_LAG for d in asked], **kwargs)
    return MeterVintages(components, closes)


def _ready(day: date, vintages: MeterVintages) -> tuple[list[Component], list[str]]:
    """(the components the meter got, the inputs it did not).

    A component is missing either because the series has no vintage for that day or because that vintage
    could not be scored (too few observations, or no spread to score against). Both are gaps: neither is
    a number, so neither may be replaced with one.
    """
    ready: list[Component] = []
    missing: list[str] = []
    for name, (_weight, _sign, window, _required) in FRED_COMPONENTS.items():
        series = vintages.components.get(name, {}).get(day)
        part = component(name, series, day, window) if series else None
        if part is None:
            missing.append(name)
        else:
            ready.append(part)
    return ready, missing


def _closable(day: date, vintages: MeterVintages) -> tuple[float, int] | None:
    """(climatology, outcome) from the settlement vintage, or None if that vintage cannot grade the day."""
    closes = vintages.closes.get(day + SETTLEMENT_LAG)
    if not closes:
        return None
    outcome, climatology = up_outcome(closes, day), climatology_up(closes, day)
    return None if outcome is None or climatology is None else (climatology, outcome)


def meter_on(day: date, vintages: MeterVintages) -> tuple[float, float, int] | None:
    """(P(up), climatology, outcome) for one forecast day, or None if any input has no vintage.

    None is the honest answer for a gap and the only answer this returns for one: no default, no
    carry-forward of the previous day's reading, and above all no value borrowed from another vintage.
    """
    closable = _closable(day, vintages)
    if closable is None:
        return None
    graded = meter(_ready(day, vintages)[0])
    return None if graded is None else (graded[1], *closable)


def day_gaps(day: date, vintages: MeterVintages) -> list[str]:
    """Which inputs this day's forecast could not be built from. Non-empty for every dropped day."""
    parts, missing = _ready(day, vintages)
    names = missing if _closable(day, vintages) is not None else [SPX_SERIES, *missing]
    # The meter refuses without one fresh FRED component, so a day it refused has to blame an input even
    # when every series was present but unusable -- stale, or flat enough to have no spread to score.
    if meter(parts) is None:
        names = list(dict.fromkeys([*names, *FRED_COMPONENTS]))
    return names


def replay_meter(
    days: Sequence[date],
    vintages: MeterVintages,
    *,
    session: Callable[[date], bool] = is_session,
) -> dict[str, Any]:
    """Walk the meter forward one session at a time, grading each on that session's own vintage.

    The window and the by-year split follow `journal.replay`: `date_from`/`date_to` are the sessions that
    actually produced a row, `gaps` counts the days each input could not carry, and `n == 0` writes
    nothing. Same summary function, so a meter row and a quant row on the page are measured the same way.
    """
    rows: list[tuple[float, float, int]] = []
    by_year: dict[str, list[tuple[float, float, int]]] = defaultdict(list)
    scored: list[date] = []
    gaps: dict[str, int] = defaultdict(int)
    for day in days:
        if not session(day):
            continue
        graded = meter_on(day, vintages)
        if graded is None:
            for name in day_gaps(day, vintages):
                gaps[name] += 1
            continue
        rows.append(graded)
        scored.append(day)
        by_year[str(day.year)].append(graded)
    window = list(days) or [date.min]
    return {"forecaster": FORECASTER, "forecaster_version": VERSION,
            **summary(rows),
            "date_from": (scored[0] if scored else window[0]).isoformat(),
            "date_to": (scored[-1] if scored else window[-1]).isoformat(),
            "by_year": {year: summary(group) for year, group in sorted(by_year.items())},
            "components_dropped": [GONE],
            "gaps": dict(sorted(gaps.items()))}