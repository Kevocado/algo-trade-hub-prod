"""Market-anchored caution (plan 15): a model's probability pulled most of the way back to the Kalshi price.

Today's models are overconfident against the market: where they disagree with the price, the price has
been right more often. A forecast that starts from the market and moves only a fixed fraction toward the
model can lose to the market by at most that fraction of the disagreement, and it still wins whenever the
model really knows something. It cannot create skill. It tells us whether any exists, and it stops the
overconfidence from costing 4x the market's error.

The weight is set here, once, before any result is looked at, and never tuned on journal results.

A cautious row is a PURE FUNCTION of the pure model's FROZEN row: it reads that row out of the store and
applies `m + w * (p - m)` to those numbers. It does not re-run the model. That is what makes the copy
auditable -- `raw_probability` is exactly the probability the model's own row froze, so anyone can
recompute the cautious row from two stored numbers -- and it is what stops the copy from being evidence
about a different instant than the model it is grading. The runner runs the model before the wrapper
(registry order), so the row exists; when it does not, the cautious target is a gap, retried next run,
never a guess. A missing market price is a gap for the same reason.

The inner's payload is carried over unchanged, which matters: `costs.frozen_quote` reads the frozen
`yes_bid`/`yes_ask` from it, and a cautious copy whose payload lost them scored `n_quoted == 0`, which
`scoring.py` turns into the permanent gate reason "no frozen quotes recorded, so edge cannot be netted of
fees and spread". Every cautious forecaster has `baseline == "market"`, so that would have closed the cost
gate on all ten of them for a reason that was pure collateral damage.

`store` is a CALLABLE returning the journal client, not the client itself: the registry is imported by
tests and by tooling that hold no credentials, and building a client there would raise on import.

There is no settlement of its own: it settles on whatever the wrapped forecaster settles on.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from tradehub.journal.contract import CalendarEntry, Forecast, Forecaster, Settlement
from tradehub.journal.store import fetch_forecasts

SHRINK_WEIGHT = 0.25
SUFFIX = "_cautious"

# Exactly one weight, by ruling (2026-10-02). It is not a tunable: the weight is part of the version
# string, and `round(weight * 100)` put any two weights within 0.005 of each other on the SAME key --
# and with UNIQUE (forecaster, forecaster_version, target) that meant the second wrapper's freezes were
# refused while both models' rows blended into one scorecard. Adding a weight here is a deliberate act
# that starts a new scorecard, not a value someone passes at a call site.
ALLOWED_WEIGHTS = (SHRINK_WEIGHT,)


class MarketShrunk:
    def __init__(self, inner: Forecaster, store: Callable[[], Any], weight: float = SHRINK_WEIGHT):
        if weight not in ALLOWED_WEIGHTS:
            raise ValueError(f"weight must be one of {ALLOWED_WEIGHTS}, not {weight!r}: the weight names a "
                             "scorecard, so it cannot be chosen freely")
        if not callable(store):
            raise TypeError(f"store must be a callable returning the journal client, got {type(store).__name__}: "
                            "passing a client here would build one at import time, where there are no credentials")
        self.inner, self._store_factory, self.weight = inner, store, weight
        self.name = f"{inner.name}{SUFFIX}"
        # From `self.weight`, not from the allowlist's first entry: a version naming a weight other than
        # the one applied is the F3 collision all over again, wearing a different number.
        self.version = f"{inner.version}+w{round(self.weight * 100)}"
        self.cadence = inner.cadence
        self._rows: dict[str, dict] | None = None
        self._read_at: datetime | None = None

    def bind_store(self, supa) -> None:
        """Adopt the client the run was actually given.

        The constructor takes a FACTORY because the registry is imported with no credentials, so a
        client cannot be built there. But a factory wired to the singleton is the wrong client for any
        run that was handed a different one: the pure row would freeze into `supa` while the cautious row
        read production, and the two would score different stores under one name. The runner calls this
        before driving us, so the cautious row is a function of the same store the pure row came from.
        """
        self._store_factory = lambda: supa
        # Drop the cache: it belongs to the client we were just swapped off. Keyed on the hour only,
        # so without this a second run in the same hour against a different store would read the FIRST
        # store's frozen rows and freeze a cautious row from another database's history.
        self._rows = None
        self._read_at = None

    @property
    def store(self):
        return self._store_factory

    def targets(self, now: datetime) -> list[CalendarEntry]:
        return [e for e in self.inner.targets(now) if e.market_linked]

    def _frozen_row(self, target: str, now: datetime) -> dict | None:
        """The inner's frozen row for one target, or None while there is none.

        Read once per hour and cached, because a row whose `market_prob` is NULL is a permanent gap
        until its cutoff and an uncached read meant a full paginated history read PER TARGET, every
        hourly run, forever (24 SELECTs for a 20-target sports run).

        A MISS re-reads. The cache cannot be trusted to stay authoritative within the hour: the model
        is driven immediately before this wrapper in the same run, and on a retry the row it freezes
        this hour is the very row we came for. So the cache is an optimisation for the common case
        where the row is already there, and never the reason a gap is reported as a gap.
        """
        hour = now.replace(minute=0, second=0, microsecond=0)
        if self._rows is None or self._read_at != hour:
            self._read_at = hour
            self._rows = {r["target"]: r for r in fetch_forecasts(self.store(), self.inner.name, self.inner.version)}
        if target not in self._rows:
            self._rows = {r["target"]: r for r in fetch_forecasts(self.store(), self.inner.name, self.inner.version)}
        return self._rows.get(target)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        row = self._frozen_row(entry.target, now)
        if row is None:
            return None   # the model has not frozen yet: a gap, retried next run, never a guess
        market_prob = row.get("market_prob")
        if market_prob is None:
            return None   # nothing to shrink toward: a gap, same rule
        raw_probability = float(row["probability"])
        probability = float(market_prob) + self.weight * (raw_probability - float(market_prob))
        return Forecast(self.name, self.version, entry.target, probability, market_prob=float(market_prob),
                        payload={**(row.get("payload") or {}),
                                 "raw_probability": raw_probability, "weight": self.weight})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return self.inner.settle(target, now)