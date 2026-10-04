"""The forecaster contract (v2 spec §3): what every forecaster implements and what the pipeline stores.

A forecaster names its upcoming targets (with their freeze cutoffs), gives one probability per target
before the cutoff, and settles targets once their outcome is public. Everything else -- storage,
the freeze guarantees, scoring, gates -- is the pipeline's job and is identical for every forecaster.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

CADENCES = ("daily", "monthly", "meeting")


def require_aware(value: datetime, name: str) -> datetime:
    """Every journal timestamp is timezone-aware: naive local time rotted fixtures in #46."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware, got naive {value!r}")
    return value


@dataclass(frozen=True)
class CalendarEntry:
    """One target and the moment after which nobody may forecast it."""

    target: str
    family: str
    cadence: str
    cutoff_at: datetime
    market_linked: bool = False
    climatology_prob: float | None = None

    def __post_init__(self) -> None:
        if not self.target or not self.family:
            raise ValueError("target and family are required")
        if self.cadence not in CADENCES:
            raise ValueError(f"cadence must be one of {CADENCES}, got {self.cadence!r}")
        require_aware(self.cutoff_at, "cutoff_at")
        if self.climatology_prob is not None and not 0.0 < self.climatology_prob < 1.0:
            raise ValueError("climatology_prob must be in (0, 1)")


@dataclass(frozen=True)
class Forecast:
    """One frozen probability that `target` resolves to 1."""

    forecaster: str
    forecaster_version: str
    target: str
    probability: float
    market_prob: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    """
    Seconds from this freeze to the target's cutoff. Spec §3 step 1 lists `horizon` in the frozen
    row's shape; it was never written, so a 5-minute-ahead CPI call and a month-ahead housing call
    were indistinguishable in the ledger. The RUNNER sets it from the calendar entry it already
    holds, so no forecaster has to know about it. `None` means "not measured" and is stored as NULL
    rather than guessed -- an invented horizon is worse than an absent one.
    """
    horizon_seconds: int | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(f"probability must be in [0, 1], got {self.probability}")
        if self.market_prob is not None and not 0.0 <= self.market_prob <= 1.0:
            raise ValueError(f"market_prob must be in [0, 1], got {self.market_prob}")

    @property
    def source_hash(self) -> str:
        """Hash of the inputs the forecaster recorded, so the row is auditable against its payload."""
        blob = json.dumps(self.payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class Settlement:
    """The realised outcome of one target (1 = the event happened)."""

    target: str
    outcome: int
    source: str
    realized_value: float | None = None

    def __post_init__(self) -> None:
        if self.outcome not in (0, 1):
            raise ValueError(f"outcome must be 0 or 1, got {self.outcome}")
        if not self.source:
            raise ValueError("a settlement must name its source")


class Forecaster(Protocol):
    """What plans (b)-(f) implement. The runner calls these in order: targets, forecast, settle."""

    name: str
    version: str
    cadence: str  # one of CADENCES; sets the gate's settled-target minimum

    def targets(self, now: datetime) -> list[CalendarEntry]:
        """Upcoming targets (cutoff in the future) this forecaster will forecast."""

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        """The forecast for `entry`, or None when the inputs are not available (a gap, never a guess)."""

    def settle(self, target: str, now: datetime) -> Settlement | None:
        """The outcome of `target` if it is public by `now`, else None (retried next run)."""
