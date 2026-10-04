"""Naive baselines (v2 spec §8, §10): previous-session persistence and climatology, as forecasters.

Spec §8: "No new modelling: naive baselines (previous-day persistence + climatology) publish first so
the journal has honest company for any later model -- and baselines implement the full §3 contract
including freeze tests, no unscored decoration." §10: non-market targets score BSS against climatology,
"with persistence shown beside it".

So these are forecasters, not decoration: each registers the SAME calendar row as the model it prices,
freezes inside the same window, settles on the family's own outcome, and is scored by the same
`scoring.score`. `KalshiImplied` is the existing precedent for a pseudo-forecaster beside a model, and
the two rules below are what keep these from being mistaken for one.

**They are never promoted** (`scoring._baseline`). `KalshiImplied` needs no such rule: its BSS against the
market it froze is 0 by construction. Neither baseline has that property. Persistence freezes 0.0 or
1.0, which `bucketize` puts in a single bucket, so 200 settled daily targets make it
`calibration_ready`, and on a trending series it can hold genuinely positive BSS against climatology.
Climatology is subtler and just as real: `store.freeze` rounds the probability to 5dp while the calendar
stores `climatology_prob` unrounded, so "the same number" is off by dust and BSS lands a hair above
zero. Either way, one year of hourly runs would have posted PROMOTED on a coin flip, and `headline`
counts PROMOTED cards.

**They are not evidence** (`scoring._independent`), for the same reason `_cautious` copies are not: they
freeze the model's exact target set, so summing both counts every event twice. Unlike `kalshi_implied_*`
this is UNCONDITIONAL -- there is no "only when the model is present" branch. That branch is right for a
market, because the Kalshi price is genuine information about the future and a market with no model is
the only evidence there is. Persistence and climatology are the null hypothesis: with no model on a
family, counting their rows would put a base rate into the hero number. They still appear in the list
(`forecasters`, `calibrated`), exactly as `_cautious` copies do.

**Nothing is fabricated.** A family with no previous session, or without enough history for a base rate,
returns None and the runner records a gap. Neither baseline interpolates across a hole in its series.

`BASELINE_PREFIX` is the single source of truth for "this is a baseline"; `scoring` imports it rather
than retyping the literal, for the reason `shrunk.SUFFIX` is imported.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Protocol

from tradehub.journal.calendars import is_target_day
from tradehub.journal.contract import CalendarEntry, Forecast, Forecaster, Settlement
from tradehub.journal.daily import daily_target, next_target_day, previous_session, settle_daily, target_day
from tradehub.journal.forecasters.housing import (
    FAMILY as HOUSING_FAMILY,
    FREEZE_WINDOW,
    SETTLEMENT_SOURCE,
    HousingForecaster,
    add_months,
    release_cutoff,
    target_for,
    target_month,
)
from tradehub.journal.nyse import is_session
from tradehub.journal.spx import CLIMATOLOGY_SESSIONS, climatology_up, freeze_at, settle_spx
from tradehub.models.monthly_direction import climatology

BASELINE_PREFIX = "baseline_"
PERSISTENCE = "persistence"
CLIMATOLOGY = "climatology"
KINDS = (PERSISTENCE, CLIMATOLOGY)


class Closes(Protocol):
    """A `DailyCloses` or an `SpxCloses`: anything that hands back the closes known before `now`."""

    def get(self, now: datetime) -> Mapping[date, float]: ...


Settle = Callable[[str, datetime], Settlement | None]


def baseline_name(kind: str, family: str) -> str:
    return f"{BASELINE_PREFIX}{kind}_{family}"


def is_baseline(name: str) -> bool:
    return str(name).startswith(BASELINE_PREFIX)


def persistence_up(closes: Mapping[date, float], day: date,
                   is_session: Callable[[date], bool]) -> tuple[float, date] | None:
    """(P(up on `day`), the date it was read from), or None when there is nothing to repeat.

    The target session is `day`, so the pair read is the two sessions before it, and "up" repeats the
    previous session's direction. None -- never a guess -- unless BOTH of those sessions has a close.

    The test is identity against the calendar (`newest close == the previous session`), not a staleness
    bound, and it needs no second rule: a series whose newest close is older than the previous session
    IS a series whose previous session has not printed, so the same check catches a stale feed, a hole
    and a holiday run in one comparison. Walking the calendar rather than counting days back is what
    makes it work on a Monday, where the previous session is three calendar days earlier.
    """
    previous = previous_session(day, is_session)
    earlier = previous_session(previous, is_session)
    if previous not in closes or earlier not in closes:
        return None
    return (1.0 if closes[previous] > closes[earlier] else 0.0), previous


def _source_of(closes: object) -> dict[str, str]:
    """The settlement source, when the closes carry one. Named so the row says what it read."""
    source = getattr(closes, "source", None)
    return {"source": source.source} if source is not None else {}


class DirectionBaseline:
    """Persistence or climatology for one daily-direction family: spx, vix, gold, eurusd.

    `closes` is the SAME object the family's model reads (`SpxCloses` or `DailyCloses`). That is the
    whole point of passing it in rather than fetching: the calendar's `climatology_prob` and the number
    this card freezes must be the same number, or the climatology baseline grades itself against a
    slightly different base rate. `settle` is the family's own settlement, so there is no second
    definition of "up" anywhere in this module.
    """

    cadence = "daily"
    version = "v1"

    def __init__(self, closes: Closes, family: str, kind: str, *, is_session: Callable[[date], bool],
                 settle: Settle):
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
        self._closes, self._family, self.kind = closes, family, kind
        self._is_session, self._settle = is_session, settle
        self.name = baseline_name(kind, family)

    def targets(self, now: datetime) -> list[CalendarEntry]:
        day = next_target_day(now, self._is_session)
        if day is None:
            return []
        return [CalendarEntry(daily_target(self._family, day), self._family, self.cadence, freeze_at(day),
                              climatology_prob=climatology_up(self._closes.get(now), day))]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        day = target_day(entry.target)
        closes = self._closes.get(now)
        source = _source_of(self._closes)
        if self.kind == CLIMATOLOGY:
            found = climatology_up(closes, day)
            if found is None:
                return None   # under 253 sessions of history: a gap, never a made-up base rate
            return Forecast(self.name, self.version, entry.target, found,
                            payload={"kind": CLIMATOLOGY, "window_sessions": CLIMATOLOGY_SESSIONS, **source})
        found = persistence_up(closes, day, self._is_session)
        if found is None:
            return None       # the previous session has not printed: a gap, retried next run
        probability, previous = found
        return Forecast(self.name, self.version, entry.target, probability,
                        payload={"kind": PERSISTENCE, "previous_session": previous.isoformat(), **source})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return self._settle(target, now)


class MonthlyBaseline:
    """The same two baselines for the monthly direction target (spec §8 wave 3, housing).

    Reads the housing model's OWN level series through `history()`, which the model has already fetched
    for this run: one HTTP call, and a climatology number identical to the calendar's. Note that
    `targets()` derives the month from the data (`HousingForecaster` does the same), so a hole in the
    series moves the TARGET rather than silently grading a stale month -- and `forecast()` still refuses
    any month whose previous month is missing.

    ORDERING PRECONDITION (CodeRabbit, on #108): this shares the model's cached `_levels` for one run,
    which is the point -- one HTTP call instead of two. The consequence is that the baseline sees
    whatever the model last fetched. `HousingForecaster.targets()` clears that cache
    ("refetched once per run"), so the supported order is: let the model's `targets()` run FIRST, then
    run the baselines against it. A caller that runs `MonthlyBaseline` before the model's `targets()` in
    the same pass, or never runs the model in a later pass, will read the PREVIOUS pass's levels -- a
    stale target month and a stale climatology, both wrong and neither loud.

    The staleness warning applies ONLY to an instance whose cache still holds levels from an EARLIER
    pass, because `targets()` has not yet run in the current one. Precisely:

      * an instance that has never fetched (`_levels is None`) -- `history()` fetches fresh levels, so
        nothing stale is inherited and the baseline is correct whatever the order. It merely costs an
        extra fetch, because the model's own `targets()` then clears and refetches;
      * an instance already used in THIS pass -- the levels are current, so they are correct, though
        the baseline reading them before `targets()` runs means the model refetches afterwards.

    Staleness needs the third case: a REUSED instance from a previous pass, where `targets()` has not
    run since. `registry.py` never reuses one across passes, so the shipped path cannot hit it. `registry.py` builds the baselines from the same instance the runner walks,
    so the shipped path satisfies this; the constraint is recorded here because the class is public.
    """

    cadence = "monthly"
    version = "v1"

    def __init__(self, housing: HousingForecaster, kind: str):
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
        self._housing, self.kind = housing, kind
        self.name = baseline_name(kind, HOUSING_FAMILY)

    def targets(self, now: datetime) -> list[CalendarEntry]:
        levels = self._housing.history()
        month = add_months(max(levels), 1)   # the first month not yet published
        cutoff = release_cutoff(month)
        if not now < cutoff <= now + FREEZE_WINDOW:
            return []
        return [CalendarEntry(target_for(month), HOUSING_FAMILY, self.cadence, cutoff,
                              climatology_prob=climatology(levels, month))]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        month = target_month(entry.target)
        levels = self._housing.history()
        if month in levels:
            return None   # already published: never forecast a known value
        if self.kind == CLIMATOLOGY:
            found = climatology(levels, month)
            if found is None:
                return None   # under 60 month-over-month changes: a gap, not a made-up base rate
            return Forecast(self.name, self.version, entry.target, found,
                            payload={"kind": CLIMATOLOGY, "source": SETTLEMENT_SOURCE})
        newest = max(levels)
        if add_months(newest, 1) != month or add_months(newest, -1) not in levels:
            return None   # the previous month is not the newest published: a gap, never a guess
        up = levels[newest] > levels[add_months(newest, -1)]
        return Forecast(self.name, self.version, entry.target, 1.0 if up else 0.0,
                        payload={"kind": PERSISTENCE, "previous_month": newest.strftime("%Y-%m"),
                                 "source": SETTLEMENT_SOURCE})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return self._housing.settle(target, now)


def build_baselines(spx_closes: Closes, wave2: Mapping[str, Closes],
                    housing: HousingForecaster) -> list[Forecaster]:
    """Both baselines for every non-market direction family, beside the model whose targets they price.

    Each family keeps its own session calendar (spec §8: EUR/USD settles on ECB reference days, the rest
    on NYSE sessions) and its own settlement, so a baseline row settles on exactly what its model's row
    settles on.
    """
    out: list[Forecaster] = []
    for family, closes in [("spx", spx_closes), *wave2.items()]:
        settle = settle_spx if family == "spx" else (lambda t, n, c=closes: settle_daily(t, n, c))
        out += [DirectionBaseline(closes, family, kind,
                                  is_session=is_target_day if family == "eurusd" else is_session,
                                  settle=settle)
                for kind in KINDS]
    return out + [MonthlyBaseline(housing, kind) for kind in KINDS]