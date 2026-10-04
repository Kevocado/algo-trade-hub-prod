"""Wave-2 daily-direction forecasters (v2 spec §8): VIX, gold, EUR/USD.

No new modelling pattern: each is the wave-1 walk-forward logistic (`tradehub/models/spy_direction`,
price-only features of its own closes, monthly refit on sessions before the month, hashed artifact)
pointed at a different series, and each is graded against climatology like the S&P.

Sources (all reachability-checked from the VPS on 2026-09-30; Stooq, the spec's source, is behind a
JavaScript proof-of-work wall and is not used):
    vix     FRED VIXCLS              NYSE sessions   settles when FRED posts the close (a day or two late)
    gold    Yahoo chart, GLD ETF     NYSE sessions   the ETF, not COMEX GC=F: a continuous futures
                                                     series jumps at each contract roll, which would
                                                     grade roll artefacts as "direction"
    eurusd  Frankfurter, ECB ref.    TARGET days     one reference rate per business day (~16:00 CET,
                                                     after the 08:00 CT freeze)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from tradehub.data.frankfurter import fetch_eurusd
from tradehub.data.fred_daily import fetch_fred_daily
from tradehub.data.yahoo_chart import fetch_chart
from tradehub.journal.calendars import is_target_day
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.daily import DailyCloses, DailySource, daily_entry, settle_daily, target_day
from tradehub.journal.nyse import is_session
from tradehub.models.spy_direction.features import features_for, training_set
from tradehub.models.spy_direction.model import Artifact, ArtifactStore, fit

STALE_DAYS = 6  # newest close older than this before the session -> a recorded gap, not a guess


def vix_source(fred=fetch_fred_daily) -> DailySource:
    return DailySource("vix", "fred:VIXCLS", lambda start: (fred("VIXCLS", start), "America/New_York"), is_session)


def gold_source(chart=fetch_chart) -> DailySource:
    return DailySource("gold", "yahoo:GLD", lambda start: chart("GLD", start), is_session)


def eurusd_source(rates=fetch_eurusd) -> DailySource:
    return DailySource("eurusd", "ecb:EURUSD", lambda start: (rates(start), "Europe/Berlin"), is_target_day)


class DirectionForecaster:
    cadence = "daily"

    def __init__(self, closes: DailyCloses, name: str, version: str, store: ArtifactStore | None = None):
        self._closes, self.name, self.version = closes, name, version
        self._family = closes.source.family
        self._store = store or ArtifactStore(namespace=f"{self._family}_direction")

    def targets(self, now: datetime) -> list[CalendarEntry]:
        return daily_entry(now, self._closes)

    def _artifact_name(self, day: date) -> str:
        return f"{self._family}-dir-{day:%Y-%m}"

    def model_for(self, day: date, now: datetime) -> tuple[Artifact, str]:
        name = self._artifact_name(day)
        found = self._store.load(name)
        if found is not None:
            return found
        artifact = fit(*training_set(self._closes.get(now), before=day.replace(day=1)))
        return artifact, self._store.save(name, artifact)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        day = target_day(entry.target)
        found = features_for(self._closes.get(now), day)
        if found is None or (day - found[1]) > timedelta(days=STALE_DAYS):
            return None
        row, newest = found
        artifact, digest = self.model_for(day, now)
        return Forecast(self.name, self.version, entry.target, artifact.predict(row),
                        payload={"features": row, "newest_close": newest.isoformat(), "artifact_sha256": digest,
                                 "train_end": artifact.train_end, "n_train": artifact.n_train,
                                 "source": self._closes.source.source})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_daily(target, now, self._closes)


def wave2_closes() -> dict[str, DailyCloses]:
    """One `DailyCloses` per family, shared by the walk-forward model and its naive baselines.

    They must be the SAME object: `baselines.py` freezes the calendar's own `climatology_prob` as its
    forecast, so a second fetch would leave the climatology card grading itself against a slightly
    different base rate.
    """
    return {"vix": DailyCloses(vix_source()), "gold": DailyCloses(gold_source()),
            "eurusd": DailyCloses(eurusd_source())}


def build_wave2(closes: dict[str, DailyCloses] | None = None,
                store_root=None) -> list[DirectionForecaster]:
    def store(family):
        return ArtifactStore(store_root, namespace=f"{family}_direction") if store_root else None

    return [DirectionForecaster(shared, f"{family}_direction", f"{family}-wf-v1", store(family))
            for family, shared in (wave2_closes() if closes is None else closes).items()]
