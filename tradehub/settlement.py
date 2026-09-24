"""Settle `predictions` rows against Kalshi public market results.

Pure math here; Supabase/Kalshi I/O is injected or isolated in thin
wrappers so the settlement rules are unit-testable. Predictions settle
against the Kalshi market result (spec section 4.5) — never against the
portfolio settlement history, which covers only owned positions.
"""

from __future__ import annotations

from typing import Any

PREDICTIONS_TABLE = "predictions"
TRACK_RECORD_TABLE = "track_record"

OPEN = "OPEN"
SETTLED = "SETTLED"
CANCELED = "CANCELED"


def compute_realized_pnl(qty: int, buy_price: float, settle_price: float, fees_cents: int = 0) -> float:
    """Realized dollar P&L for one settled position: (settle - buy) * qty minus fees."""
    return (settle_price - buy_price) * qty - fees_cents / 100.0


def brier_score(prob: float, outcome: int) -> float:
    """Brier score for a binary prediction: (prob - outcome) ** 2."""
    return (prob - outcome) ** 2


def parse_market_result(market: Any) -> tuple[str, int | None]:
    """Map a Kalshi `GET /markets/{ticker}` payload to (disposition, outcome).

    Disposition is OPEN, SETTLED, or CANCELED; outcome is 1/0/None.
    Anything malformed or ambiguous returns ("OPEN", None) — never settle
    on what we cannot parse. A finalized market whose result key is missing
    is malformed (stays OPEN, retried next pass); a finalized market with a
    present-but-non-binary result (null, "", "canceled", ...) was voided and
    is CANCELED — we never fabricate a yes/no.
    """
    try:
        inner = market["market"]
        status = inner["status"]
        result = inner.get("result")
    except (TypeError, KeyError, AttributeError):
        return (OPEN, None)
    if status == "finalized":
        if result == "yes":
            return (SETTLED, 1)
        if result == "no":
            return (SETTLED, 0)
        if "result" in inner:
            return (CANCELED, None)
        return (OPEN, None)
    return (OPEN, None)


def is_market_canceled(market: Any) -> bool:
    """True iff the market was finalized without a yes/no result."""
    return parse_market_result(market)[0] == CANCELED


def settle_prediction_row(row: dict[str, Any], market: Any) -> dict[str, Any] | None:
    """Build the `predictions` update payload for one row against a fetched market.

    Returns None when the market is still open (caller skips the row).
    A canceled market yields a CANCELED payload with no fabricated result.
    """
    disposition, outcome = parse_market_result(market)
    if disposition == OPEN:
        return None
    if disposition == CANCELED:
        return {"id": row["id"], "status": CANCELED}
    outcome_str = "yes" if outcome == 1 else "no"
    update: dict[str, Any] = {
        "id": row["id"],
        "status": SETTLED,
        "result": outcome_str,
        "brier": round(brier_score(float(row["our_prob"]), outcome), 5),
        "raw_payload": market,
    }
    market_prob = row.get("market_prob")
    update["market_brier"] = (
        round(brier_score(float(market_prob), outcome), 5) if market_prob is not None else None
    )
    return update
