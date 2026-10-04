"""Housing: S&P Cotality Case-Shiller US National HPI (seasonally adjusted) month-over-month direction.

Spec §8 wave 3: frozen monthly on the release calendar, data lag stated, no nowcasting.

Target, exactly: `housing:<YYYY-MM>:up` is 1 iff the FIRST PRINT of month m's index level exceeds
month m-1's level as printed in that same release. The index is published on the last Tuesday of month
m+2 at 09:00 ET (FRED `CSUSHPISA`; checked against the 30 real vintage dates 2024-03..2026-08, all last
Tuesdays), so the tile reads "two months behind". It is revised afterwards; settlement is the first print
from the ALFRED vintage of release day, never the revised value.

Point-in-time: the forecast uses only months strictly before m. If month m is already present in the
series fetched at freeze time (an early or off-calendar release), no forecast is made: a gap, not a leak.
Training history is the current (revised) vintage; that is a stated approximation, because pre-2012
first prints are not reconstructible from a keyless vintage pull.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tradehub.data.alfred_vintages import Vintage, fetch_vintages
from tradehub.data.fred_daily import fetch_fred_daily
from tradehub.engines.labor import first_prints
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.models.monthly_direction import FEATURES, climatology, features_for, training_set
from tradehub.models.spy_direction.model import Artifact, ArtifactStore, fit

ET = ZoneInfo("America/New_York")
SERIES = "CSUSHPISA"
FAMILY = "housing"
RELEASE_TIME_ET = time(9, 0)
FREEZE_WINDOW = timedelta(days=5)  # register and freeze inside the five days before the release
MIN_TRAIN_MONTHS = 120
HISTORY_START = date(1987, 1, 1)
SETTLEMENT_SOURCE = "fred:CSUSHPISA:first_print"


def add_months(month: date, k: int) -> date:
    index = month.year * 12 + month.month - 1 + k
    return date(index // 12, index % 12 + 1, 1)


def release_day(month: date) -> date:
    """The last Tuesday of month m+2: when month m's index is first published."""
    published = add_months(month, 2)
    last = add_months(published, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - 1) % 7)


def release_cutoff(month: date) -> datetime:
    return datetime.combine(release_day(month), RELEASE_TIME_ET, ET)


def target_for(month: date) -> str:
    return f"{FAMILY}:{month:%Y-%m}:up"


def target_month(target: str) -> date:
    return date.fromisoformat(target.split(":")[1] + "-01")


class HousingForecaster:
    name = "housing_direction"
    version = "housing-wf-v1"
    cadence = "monthly"

    def __init__(self, *, levels_fn: Callable[[date], Mapping[date, float]] = lambda start: fetch_fred_daily(SERIES, start),
                 vintages_fn: Callable[..., dict[date, Vintage]] = fetch_vintages,
                 store: ArtifactStore | None = None):
        self._levels_fn, self._vintages_fn = levels_fn, vintages_fn
        self._store = store or ArtifactStore(namespace="housing_direction")
        self._levels: Mapping[date, float] | None = None

    def _history(self) -> Mapping[date, float]:
        if self._levels is None:
            self._levels = self._levels_fn(HISTORY_START)
        return self._levels

    def history(self) -> Mapping[date, float]:
        """The fetched level series. Public so the naive baselines beside it read the SAME fetch
        (`baselines.py`), which is one HTTP call per run instead of two, and is what makes the
        climatology they freeze identical to the calendar's."""
        return self._history()

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._levels = None  # refetched once per run
        levels = self._history()
        month = add_months(max(levels), 1)  # the first month not yet published
        cutoff = release_cutoff(month)
        if not now < cutoff <= now + FREEZE_WINDOW:
            return []
        return [CalendarEntry(target_for(month), FAMILY, self.cadence, cutoff,
                              climatology_prob=climatology(levels, month))]

    def model_for(self, month: date) -> tuple[Artifact, str]:
        name = f"housing-dir-{month:%Y-%m}"
        found = self._store.load(name)
        if found is not None:
            return found
        x, y, days = training_set(self._history(), before=month)
        artifact = fit(x, y, days, features=FEATURES, min_train=MIN_TRAIN_MONTHS)
        return artifact, self._store.save(name, artifact)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        month = target_month(entry.target)
        levels = self._history()
        if month in levels:  # already published: never forecast a known value
            return None
        found = features_for(levels, month)
        if found is None:
            return None
        row, newest = found
        # The 12-month feature looks back 12 months: a hole anywhere in them is a gap, not a guess.
        if add_months(newest, 1) != month or any(add_months(newest, -k) not in levels for k in range(13)):
            return None
        artifact, digest = self.model_for(month)
        return Forecast(self.name, self.version, entry.target, artifact.predict(row),
                        payload={"features": row, "newest_level": newest.isoformat(), "artifact_sha256": digest,
                                 "train_end": artifact.train_end, "n_train": artifact.n_train,
                                 "release_day": release_day(month).isoformat(), "provisional": True,
                                 "source": SETTLEMENT_SOURCE})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        month = target_month(target)
        released = release_day(month)
        today = now.astimezone(ET).date()
        if today <= released:
            return None
        vintages = self._vintages_fn(SERIES, [released - timedelta(days=1), released], today=today)
        change = first_prints(vintages, change=True).get(month)
        if change is None:
            return None
        return Settlement(target, int(change > 0), SETTLEMENT_SOURCE, realized_value=change)
