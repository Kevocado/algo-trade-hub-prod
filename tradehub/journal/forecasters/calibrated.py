"""Sports calibration layer: a journal forecaster that wraps a sports forecaster and applies
post-hoc calibration fitted walk-forward on settled journal results.

Protocol (docs/superpowers/plans/2026-10-18-improve-the-models.md):
1. Frozen before looking: metric = Brier gap vs Kalshi price with SE, stated before running.
2. Time split: develop on earlier 70% of settled history (by cutoff time), judge once on later 30%.
3. Count variants tried (4: identity, Platt, isotonic, shrinkage) and report next to result.
4. New version beside the old: ships as `<name>_cal` in the journal, runs live next to original.
5. Stop rule: if out-of-sample gap does not clear 2 SE better than identity, stop (ship identity).
6. Free data only: fitted from settled journal rows, no external data.

This forecaster wraps an inner sports forecaster (e.g. `sports_nfl`), reads that forecaster's
frozen row from the journal store, applies the fitted calibration, and publishes a `<name>_cal`
row beside the original. No change to `tradehub.sports.scan`: the calibrated forecaster is purely
a journal-side wrapper.

Calibration parameters are fitted once per hourly run from all settled journal rows for the inner
forecaster, using only rows whose cutoff is earlier than the current forecast's cutoff (walk-forward).
The best variant is chosen on a validation slice of the training data; the chosen variant is judged
once on a time-split test slice. Minimum 100 settled results per engine and kind.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from tradehub.journal.contract import CalendarEntry, Forecast, Forecaster, Settlement
from tradehub.journal.store import fetch_forecasts, fetch_settlements
from tradehub.sports.calibration import calibrate_engine

SHRINK_SUFFIX = "_cal"


class CalibratedForecaster:
    """Wrap an inner sports forecaster and apply post-hoc calibration fitted on settled journal rows.

    The inner forecaster's frozen row is read from the store; calibration parameters (fitted
    walk-forward on earlier settled rows) are applied to its probability. The calibrated row is
    published under `inner.name + "_cal"` with version `inner.version + "+cal"`, beside the
    original in the journal. Both are scored independently by `scoring.py`.

    No change to `tradehub.sports.scan`: this is purely a journal-side wrapper, like
    `forecasters/shrunk.MarketShrunk`.
    """

    def __init__(self, inner: Forecaster, store: Callable[[], Any]):
        if not callable(store):
            raise TypeError(f"store must be a callable returning the journal client, got {type(store).__name__}")
        self.inner = inner
        self._store_factory = store
        self.name = f"{inner.name}{SHRINK_SUFFIX}"
        self.version = f"{inner.version}+cal"
        self.cadence = inner.cadence
        # kind comes from the inner forecaster (sports forecasters have .kind)
        self.kind = getattr(inner, "kind", "winner")
        self._calibration: tuple[str, tuple[float, ...]] | None = None
        self._rows: dict[str, dict] | None = None
        self._read_at: datetime | None = None

    def bind_store(self, supa) -> None:
        """Adopt the client the run was actually given (see forecasters/shrunk.MarketShrunk)."""
        self._store_factory = lambda: supa
        self._rows = None
        self._calibration = None
        self._read_at = None

    @property
    def store(self) -> Callable[[], Any]:
        return self._store_factory

    def targets(self, now: datetime) -> list[CalendarEntry]:
        return [e for e in self.inner.targets(now) if e.market_linked]

    def _load_settled_pairs(self, supa) -> list[tuple[datetime, float, bool]]:
        """Load settled (cutoff_time, probability, hit) pairs for the inner forecaster.

        Only non-rebuilt frozen rows with a settlement are used. `frozen_at` is the cutoff-time
        proxy for the time split; falls back to the row id if the column is absent.
        """
        forecasts = fetch_forecasts(supa, self.inner.name, self.inner.version)
        if not forecasts:
            return []
        targets = [f["target"] for f in forecasts]
        outcomes = fetch_settlements(supa, targets)
        pairs: list[tuple[datetime, float, bool]] = []
        for f in forecasts:
            target = f["target"]
            if target not in outcomes:
                continue
            prob = f.get("probability")
            if prob is None:
                continue
            cutoff = f.get("frozen_at")
            if cutoff is None:
                cutoff = f.get("id", 0)
            if isinstance(cutoff, str):
                cutoff = datetime.fromisoformat(cutoff)
            pairs.append((cutoff, float(prob), bool(outcomes[target])))
        return pairs

    def _fit_calibration(self, supa) -> None:
        """Fit calibration from settled journal rows with earlier cutoffs.

        Result is cached in `self._calibration` as `(variant_name, params)` or `None`
        (identity: pass the raw probability through unchanged). Fits only if there are at
        least MIN_SETTLED settled results.
        """
        from tradehub.sports.calibration import MIN_SETTLED

        pairs = self._load_settled_pairs(supa)
        if len(pairs) < MIN_SETTLED:
            self._calibration = None
            return

        result = calibrate_engine(self.inner.name, self.kind, pairs)
        if result is not None and result.get("ship"):
            self._calibration = (result["best_variant"], result["params"])
            log.info(
                "sports calibration %s/%s: %s (gap %s, SE %s, ship=%s)",
                self.inner.name, self.kind, result["best_variant"],
                result["gap"], result["gap_se"], result["ship"],
            )
        else:
            self._calibration = None  # identity: pass raw probability through
            log.info(
                "sports calibration %s/%s: %s (not shipped)",
                self.inner.name, self.kind, result["stop_reason"] if result else "insufficient data",
            )

    def _frozen_row(self, target: str, now: datetime) -> dict | None:
        """Read the inner's frozen row for one target, cached per hour."""
        hour = now.replace(minute=0, second=0, microsecond=0)
        if self._rows is None or self._read_at != hour:
            self._read_at = hour
            self._rows = {r["target"]: r for r in fetch_forecasts(self.store(), self.inner.name, self.inner.version)}
        if target not in self._rows:
            self._rows = {r["target"]: r for r in fetch_forecasts(self.store(), self.inner.name, self.inner.version)}
        return self._rows.get(target)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        supa = self.store()

        # Load/refit calibration once per hour
        hour = now.replace(minute=0, second=0, microsecond=0)
        if self._calibration is None or self._read_at != hour:
            self._read_at = hour
            self._fit_calibration(supa)

        # Read the inner's frozen row
        row = self._frozen_row(entry.target, now)
        if row is None:
            return None
        market_prob = row.get("market_prob")
        if market_prob is None:
            return None

        raw_probability = float(row["probability"])

        # Apply calibration (or identity if none fitted / stop rule triggered)
        variant_name = "identity"
        probability = raw_probability
        if self._calibration is not None:
            variant_name, params = self._calibration
            from tradehub.sports.calibration import (
                _apply_isotonic, _apply_linear_shrinkage, _apply_platt,
            )
            if variant_name == "platt":
                probability = _apply_platt(raw_probability, params)
            elif variant_name == "isotonic":
                probability = _apply_isotonic(raw_probability, params)
            elif variant_name == "shrinkage":
                probability = _apply_linear_shrinkage(raw_probability, params)

        return Forecast(
            self.name, self.version, entry.target, probability,
            market_prob=float(market_prob),
            payload={**(row.get("payload") or {}),
                     "raw_probability": raw_probability,
                     "calibration_variant": variant_name},
        )

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return self.inner.settle(target, now)