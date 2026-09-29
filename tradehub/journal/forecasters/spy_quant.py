"""Walk-forward quant (v2 spec §7): P(S&P 500 up on session t) from a monthly-refit logistic model.

The model used for any session in month M is trained only on sessions before the 1st of M, on an
expanding window, and is written once as a hashed artifact; later sessions in M load that same
artifact. Nothing is ever trained on a session it is then scored on.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.spx import SpxCloses, settle_spx, spx_entry, target_day
from tradehub.models.spy_direction.features import features_for, training_set
from tradehub.models.spy_direction.model import Artifact, ArtifactStore, fit

STALE_DAYS = 5  # newest close older than this before the session -> gap, not a guess


def artifact_name(day: date) -> str:
    return f"spy-dir-{day:%Y-%m}"


class SpyQuant:
    name = "spy_quant"
    version = "spy-wf-v1"
    cadence = "daily"

    def __init__(self, closes: SpxCloses, store: ArtifactStore | None = None):
        self._closes = closes
        self._store = store or ArtifactStore()

    def targets(self, now: datetime) -> list[CalendarEntry]:
        return spx_entry(now, self._closes, "spx")

    def model_for(self, day: date, now: datetime) -> tuple[Artifact, str]:
        name = artifact_name(day)
        found = self._store.load(name)
        if found is not None:
            return found
        month_start = day.replace(day=1)
        artifact = fit(*training_set(self._closes.get(now), before=month_start))
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
                                 "train_start": artifact.train_start, "train_end": artifact.train_end,
                                 "n_train": artifact.n_train})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_spx(target, now, self._closes)
