"""Point-in-time primitives: every feature carries the moment it became knowable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class LeakageError(RuntimeError):
    """A decision used information published after the decision time."""


@dataclass(frozen=True)
class Observation:
    name: str
    value: float
    published_at: datetime


@dataclass(frozen=True)
class Decision:
    market_ticker: str
    decided_at: datetime
    our_prob: float
    features: tuple[Observation, ...] = ()


def _require_aware(ts: datetime, what: str) -> None:
    if ts.tzinfo is None:
        raise ValueError(f"{what} must be timezone-aware, got naive {ts!r}")


def check_no_lookahead(decision: Decision) -> None:
    """Raise LeakageError if any feature was published after the decision time."""
    _require_aware(decision.decided_at, "decided_at")
    late = []
    for obs in decision.features:
        _require_aware(obs.published_at, f"published_at of {obs.name}")
        if obs.published_at > decision.decided_at:
            late.append(obs.name)
    if late:
        raise LeakageError(
            f"{decision.market_ticker} at {decision.decided_at.isoformat()}: "
            f"features published after the decision: {late}"
        )
