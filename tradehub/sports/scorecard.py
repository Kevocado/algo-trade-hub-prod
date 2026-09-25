"""Keep-or-drop test for the LLM reviewer (spec §3.2): do approved picks beat rejected ones?"""

from __future__ import annotations

from typing import Any

from shared.kalshi_fees import kalshi_fee_cents

MIN_SETTLED = 100


def _summary(picks: list[tuple[float, int, float]]) -> dict[str, Any]:
    if not picks:
        return {"n": 0, "brier": None, "pnl_per_contract": None}
    return {
        "n": len(picks),
        "brier": sum(b for b, _, _ in picks) / len(picks),
        "pnl_per_contract": sum(p for _, _, p in picks) / len(picks),
    }


def reviewer_scorecard(reviews: list[dict[str, Any]], results: dict[str, str]) -> dict[str, Any]:
    """`reviews`: ok rows from sports_reviews; `results`: market_ticker -> 'yes'/'no' for settled markets.
    P&L is per contract at the reviewed entry price, as a taker (conservative fee)."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for r in sorted(reviews, key=lambda r: r["created_at"]):
        if r.get("status") == "ok":
            latest[(r["market_ticker"], r["side"])] = r
    approved: list[tuple[float, int, float]] = []
    rejected: list[tuple[float, int, float]] = []
    for (ticker, side), r in latest.items():
        result = results.get(ticker)
        if result not in ("yes", "no"):
            continue
        y = 1 if result == "yes" else 0
        price = float(r["entry_price"])
        won = (side == "yes") == (y == 1)
        pnl = (1.0 - price if won else -price) - kalshi_fee_cents(price * 100.0) / 100.0
        pick = ((float(r["our_prob"]) - y) ** 2, y, pnl)
        (approved if r["explainable"] and not r["red_flags"] else rejected).append(pick)
    a, rj = _summary(approved), _summary(rejected)
    n = a["n"] + rj["n"]
    if n < MIN_SETTLED or not a["n"] or not rj["n"]:
        verdict = "insufficient"
    elif a["brier"] < rj["brier"] or a["pnl_per_contract"] > rj["pnl_per_contract"]:
        verdict = "keep"
    else:
        verdict = "drop"
    return {"n_settled": n, "min_settled": MIN_SETTLED, "approved": a, "rejected": rj, "verdict": verdict}
