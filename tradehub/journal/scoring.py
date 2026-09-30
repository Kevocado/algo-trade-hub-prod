"""Scoring (v2 spec §3 step 3, §10): pure functions from frozen rows + settlements to a scorecard.

Idempotent by construction: the same rows give the same scorecard, so the score job can recompute
everything every run. Rebuilt rows are displayed elsewhere but never reach these functions' counts.
"""

from __future__ import annotations

from typing import Any

from tradehub.journal.costs import cost_summary
from tradehub.track_record import BUCKETS, bucketize

MIN_SETTLED = {"daily": 200, "monthly": 50, "meeting": 50}
MIN_BUCKET_TARGETS = 20
MURPHY_BINS = 10


def _brier(prob: float, outcome: int) -> float:
    return (prob - outcome) ** 2


def settled_pairs(forecasts: list[dict[str, Any]], settlements: dict[str, int]) -> list[dict[str, Any]]:
    """Counted, settled forecasts: rebuilt rows excluded, unsettled targets excluded.

    One forecast per (forecaster, version, target) is enforced by the table's UNIQUE constraint, so
    every row here is a distinct target: counts are targets, never rows (spec §10 counting rule).
    """
    out = []
    for row in forecasts:
        if row.get("rebuilt"):
            continue
        outcome = settlements.get(row["target"])
        if outcome is None:
            continue
        out.append({**row, "outcome": int(outcome)})
    return out


def baseline_prob(row: dict[str, Any], calendar: dict[str, dict[str, Any]]) -> tuple[float | None, str]:
    """The no-skill reference for one target: the market where one exists, else climatology."""
    if row.get("market_prob") is not None:
        return float(row["market_prob"]), "market"
    clim = (calendar.get(row["target"]) or {}).get("climatology_prob")
    if clim is not None:
        return float(clim), "climatology"
    return None, "none"


def reliability(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Confidence-space buckets (a 0.30 forecast is 70% confidence in 'no'), as in `bucketize`."""
    groups: dict[str, list[tuple[float, bool]]] = {b: [] for b in BUCKETS}
    for row in pairs:
        prob = float(row["probability"])
        favored_yes = prob >= 0.5
        confidence = prob if favored_yes else 1.0 - prob
        hit = (row["outcome"] == 1) if favored_yes else (row["outcome"] == 0)
        groups[bucketize(prob)].append((confidence, hit))
    out = []
    for bucket in BUCKETS:
        members = groups[bucket]
        if not members:
            continue
        out.append({
            "bucket": bucket,
            "n": len(members),
            "predicted": round(sum(c for c, _ in members) / len(members), 4),
            "observed": round(sum(1 for _, h in members if h) / len(members), 4),
        })
    return out


def murphy(pairs: list[dict[str, Any]]) -> dict[str, float] | None:
    """Binned Murphy decomposition: Brier ~= reliability - resolution + uncertainty."""
    n = len(pairs)
    if n == 0:
        return None
    base = sum(r["outcome"] for r in pairs) / n
    bins: dict[int, list[dict[str, Any]]] = {}
    for row in pairs:
        idx = min(int(float(row["probability"]) * MURPHY_BINS), MURPHY_BINS - 1)
        bins.setdefault(idx, []).append(row)
    rel = res = 0.0
    for members in bins.values():
        k = len(members)
        f = sum(float(r["probability"]) for r in members) / k
        o = sum(r["outcome"] for r in members) / k
        rel += k * (f - o) ** 2
        res += k * (o - base) ** 2
    return {"reliability": round(rel / n, 6), "resolution": round(res / n, 6),
            "uncertainty": round(base * (1 - base), 6)}


def score(forecasts: list[dict[str, Any]], settlements: dict[str, int],
          calendar: dict[str, dict[str, Any]], cadence: str) -> dict[str, Any]:
    """The scorecard for one (forecaster, version).

    `brier` covers every settled target; `bss` compares the forecaster with its baseline on exactly
    the targets that have a baseline (same contracts on both sides), and `baseline` says which
    baseline dominates so the tile can label it.
    """
    if cadence not in MIN_SETTLED:
        raise ValueError(f"unknown cadence {cadence!r}")
    counted = [r for r in forecasts if not r.get("rebuilt")]
    pairs = settled_pairs(forecasts, settlements)
    brier = sum(_brier(float(r["probability"]), r["outcome"]) for r in pairs) / len(pairs) if pairs else None

    ours_on_base, theirs, kinds = [], [], {"market": 0, "climatology": 0}
    for row in pairs:
        prob, kind = baseline_prob(row, calendar)
        if prob is None:
            continue
        kinds[kind] += 1
        ours_on_base.append(_brier(float(row["probability"]), row["outcome"]))
        theirs.append(_brier(prob, row["outcome"]))
    brier_base = sum(theirs) / len(theirs) if theirs else None
    ours_b = sum(ours_on_base) / len(ours_on_base) if ours_on_base else None
    bss = (1.0 - ours_b / brier_base) if (ours_b is not None and brier_base) else None
    baseline = "none" if not theirs else ("market" if kinds["market"] >= kinds["climatology"] else "climatology")

    buckets = reliability(pairs)
    calibration_ready = bool(buckets) and all(b["n"] >= MIN_BUCKET_TARGETS for b in buckets)
    costs = cost_summary(pairs) if baseline == "market" else {}
    reasons = []
    if len(pairs) < MIN_SETTLED[cadence]:
        reasons.append(f"only {len(pairs)} settled targets, need {MIN_SETTLED[cadence]} ({cadence})")
    if bss is None:
        reasons.append("no baseline to compare against")
    elif bss <= 0:
        reasons.append(f"Brier skill {bss:.4f} vs {baseline} is not positive")
    if baseline == "market":  # spec §10: the edge must survive Kalshi's taker fee and the spread
        if not costs["n_quoted"]:
            reasons.append("no frozen quotes recorded, so edge cannot be netted of fees and spread")
        elif costs["net_pnl_cents"] <= 0:
            reasons.append(f"simulated P&L after fees and spread is {costs['net_pnl_cents']:.1f}c over "
                           f"{costs['n_traded']} trades, not positive")
    if not calibration_ready:
        reasons.append(f"a calibration bucket has fewer than {MIN_BUCKET_TARGETS} settled targets")
    return {
        "cadence": cadence,
        "baseline": baseline,
        "n_targets": len(counted),
        "n_settled": len(pairs),
        "brier": round(brier, 6) if brier is not None else None,
        "brier_baseline": round(brier_base, 6) if brier_base is not None else None,
        "bss": round(bss, 6) if bss is not None else None,
        "reliability": buckets,
        "murphy": murphy(pairs) or {},
        "costs": costs,
        "calibration_ready": calibration_ready,
        "gate_status": "PROMOTED" if not reasons else "SHADOW",
        "gate_reasons": reasons,
    }


def headline(cards: list[dict[str, Any]]) -> dict[str, int]:
    """The journal's hero numbers (spec §10 display gate): headline counts cover calibrated forecasters only."""
    calibrated = [c for c in cards if c.get("calibration_ready")]
    return {
        "forecasters": len(cards),
        "calibrated": len(calibrated),
        "settled_calibrated": sum(int(c.get("n_settled") or 0) for c in calibrated),
        "promoted": sum(1 for c in cards if c.get("gate_status") == "PROMOTED"),
    }
