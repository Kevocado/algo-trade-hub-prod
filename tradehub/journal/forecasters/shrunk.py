"""Market-anchored caution (plan 15): a model's probability pulled most of the way back to the Kalshi price.

Today's models are overconfident against the market: where they disagree with the price, the price has
been right more often. A forecast that starts from the market and moves only a fixed fraction toward the
model can lose to the market by at most that fraction of the disagreement, and it still wins whenever the
model really knows something. It cannot create skill. It tells us whether any exists, and it stops the
overconfidence from costing 4x the market's error.

The weight is set here, once, before any result is looked at, and never tuned on journal results. A
different weight is a different forecaster: it is part of the version string (`v1+w25`), so a change
starts a new scorecard instead of rewriting history.

The wrapper is its own forecaster beside the pure model, which keeps scoring exactly as it was. It adds no
settlement of its own: it settles on whatever the wrapped forecaster settles on. With no market price there
is nothing to shrink toward, so that is a gap, never a guess.
"""

from __future__ import annotations

from datetime import datetime

from tradehub.journal.contract import CalendarEntry, Forecast, Forecaster, Settlement

SHRINK_WEIGHT = 0.25
SUFFIX = "_cautious"


class MarketShrunk:
    def __init__(self, inner: Forecaster, weight: float = SHRINK_WEIGHT):
        if not 0.0 < weight < 1.0:
            raise ValueError("weight must be strictly between 0 and 1")
        self.inner, self.weight = inner, weight
        self.name = f"{inner.name}{SUFFIX}"
        self.version = f"{inner.version}+w{round(weight * 100)}"
        self.cadence = inner.cadence

    def targets(self, now: datetime) -> list[CalendarEntry]:
        return [e for e in self.inner.targets(now) if e.market_linked]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        raw = self.inner.forecast(entry, now)
        if raw is None or raw.market_prob is None:
            return None
        probability = raw.market_prob + self.weight * (raw.probability - raw.market_prob)
        return Forecast(self.name, self.version, entry.target, probability, market_prob=raw.market_prob,
                        payload={**raw.payload, "raw_probability": raw.probability, "weight": self.weight})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return self.inner.settle(target, now)