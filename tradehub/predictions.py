"""Predictions ledger writer.

Every engine output becomes a row in the `predictions` Supabase table,
whether or not anyone trades on it (spec section 4.4). The settlement job
(tradehub/settlement.py) later flips rows to SETTLED against the Kalshi
market result.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

PREDICTIONS_TABLE = "predictions"


def build_prediction_row(
    *,
    market_ticker: str,
    our_prob: float,
    market_prob: float | None,
    engine: str,
    as_of: datetime,
    engine_version: str = "v0",
    raw_payload: dict | None = None,
) -> dict[str, Any]:
    """Validate engine output and build the `predictions` insert payload."""
    if not market_ticker or not market_ticker.strip():
        raise ValueError("market_ticker must be a non-empty string")
    if not engine or not engine.strip():
        raise ValueError("engine must be a non-empty string")
    our_prob = float(our_prob)
    if not 0.0 <= our_prob <= 1.0:
        raise ValueError(f"our_prob must be in [0, 1], got {our_prob}")
    if market_prob is not None:
        market_prob = float(market_prob)
        if not 0.0 <= market_prob <= 1.0:
            raise ValueError(f"market_prob must be in [0, 1] or None, got {market_prob}")
    if not isinstance(as_of, datetime):
        raise ValueError("as_of must be a datetime")  # noqa: TRY004 - preserve public contract
    return {
        "market_ticker": market_ticker.strip(),
        "our_prob": round(our_prob, 4),
        "market_prob": round(market_prob, 4) if market_prob is not None else None,
        "engine": engine.strip(),
        "engine_version": engine_version,
        "as_of": as_of.isoformat(),
        "status": "OPEN",
        "raw_payload": raw_payload or {},
    }


def record_prediction(supa, row: dict[str, Any]) -> dict[str, Any]:
    """Insert one prediction row; returns the inserted row."""
    res = supa.table(PREDICTIONS_TABLE).insert(row).execute()
    data = res.data or []
    return data[0] if data else {}


def record_predictions(supa, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Batch-insert prediction rows; an empty list is a no-op."""
    if not rows:
        return []
    res = supa.table(PREDICTIONS_TABLE).insert(rows).execute()
    return res.data or []
