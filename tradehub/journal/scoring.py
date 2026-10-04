"""Scoring (v2 spec §3 step 3, §10): pure functions from frozen rows + settlements to a scorecard.

Idempotent by construction: the same rows give the same scorecard, so the score job can recompute
everything every run. Rebuilt rows are displayed elsewhere but never reach these functions' counts.
"""

from __future__ import annotations

from typing import Any

from tradehub.journal.costs import cost_summary
from tradehub.journal.forecasters.baselines import BASELINE_PREFIX
from tradehub.journal.forecasters.shrunk import SUFFIX as SHRINK_SUFFIX
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
          calendar: dict[str, dict[str, Any]], cadence: str, forecaster: str = "") -> dict[str, Any]:
    """The scorecard for one (forecaster, version).

    `brier` covers every settled target; `bss` compares the forecaster with its baseline on exactly
    the targets that have a baseline (same contracts on both sides), and `baseline` says which
    baseline dominates so the tile can label it.

    `forecaster` is the name, not a guess: `runner` is the only caller that knows it, and the gate
    below has to be able to tell a naive baseline (spec §8) from a model without reading its rows.
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
    # A naive baseline is the reference line, not a model, and can never be promoted. `KalshiImplied`
    # does not need this rule (its BSS against the market it froze is 0 by construction) and neither
    # does a real model (a positive BSS is the point). Persistence freezes 0.0/1.0 into a single
    # calibration bucket, so 200 settled targets make it calibrated and it can hold positive skill
    # against climatology; climatology scores a hair above zero because `freeze` rounds to 5dp while
    # the calendar does not. Without this line both would post PROMOTED within a year of hourly runs.
    if _baseline(forecaster):
        reasons.append("a naive baseline is the reference line, not a model, so it is never promoted")
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
        # The other half of the fraction `bss` was computed from, and its denominator. `brier` covers
        # every settled target and `brier_baseline` only the baseline-matched ones, so pairing THOSE two
        # is pairing an all-targets mean with a matched mean -- three denominators and a sign that can
        # be wrong. `brier_on_baseline`/`n_baseline` are the matched pair `brier_baseline` belongs to.
        "brier_on_baseline": round(ours_b, 6) if ours_b is not None else None,
        "n_baseline": len(ours_on_base),
        "bss": round(bss, 6) if bss is not None else None,
        "reliability": buckets,
        "murphy": murphy(pairs) or {},
        "costs": costs,
        "calibration_ready": calibration_ready,
        "gate_status": "PROMOTED" if not reasons else "SHADOW",
        "gate_reasons": reasons,
    }


def _cautious(name: str) -> bool:
    """The market-anchored copy of a model (plan 15). `shrunk.SUFFIX` is the source of truth and is
    imported, not retyped: four copies of this literal once existed, and renaming the constant while
    the three consumers kept the old string would silently return the double count below."""
    return str(name).endswith(SHRINK_SUFFIX)


def _baseline(name: str) -> bool:
    """A naive baseline (spec §8: persistence, climatology). `baselines.BASELINE_PREFIX` is the source
    of truth and is imported, not retyped, for the reason `_cautious` gives -- and here the two
    consumers disagree if either one is stale, because one gates PROMOTED and the other gates the
    headline's evidence count."""
    return str(name).startswith(BASELINE_PREFIX)


def _independent(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The cards whose settled rows are evidence in their own right.

    Three kinds of card are not, because they are scored on somebody else's exact target set, or are not
    evidence about the future at all:

      * a `_cautious` copy, which is `m + w*(p - m)` of its model's frozen row;
      * a `kalshi_implied_*` baseline, which `KalshiImplied` freezes on its model's tickers. NOT yet
        excluded: the pair is not derivable from names (`kalshi_implied_cpi` strips to `cpi`, while the
        model is `cpi_nowcast`), and guessing would silently drop real evidence;
      * a `baseline_*` naive baseline (spec §8), excluded UNCONDITIONALLY. Its target set is the
        model's by construction, and unlike a market it is not evidence about the future: with no
        model on the family, persistence and climatology are the only rows there would be, and summing
        them would put the base rate into the hero number.

    Summing any of them alongside the card they mirror counts every event twice -- 200 settled forecasts
    reported as 400, the same double counting a spread ladder caused before plan 12.

    Every one of these is still a forecaster: `forecasters`, `calibrated` and `promoted` count them all
    (and `promoted` cannot reach a baseline, because `score` refuses to promote one).
    """
    return [c for c in cards if not _cautious(c.get("forecaster", ""))
            and not _baseline(c.get("forecaster", ""))]


def market_skill(cards: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The pooled "Brier skill vs market" the hero leads with, or None when there is none to give.

    Spec §1, §10 and §11 all promise this number and it did not exist. §10: it "aggregates
    market-linked targets only", so cards graded against climatology are out -- they have no market to
    be better than. Cards that are not their own evidence are out for the reason `_independent`
    explains: a cautious copy is scored on its model's exact target set, so pooling both would count
    every event twice. Uncalibrated cards are out for the same reason the rest of the headline is.

    Pooling is weighted by each card's `n_baseline` -- the count of the targets its `brier_baseline`
    actually averaged -- because a card carrying 300 matched targets and a card carrying 3 do not carry
    equal evidence. It is NOT `n_settled`, and the numerator is NOT `brier`: those two cover every
    settled target, while the baseline covers only the targets that have one, so pairing them grades the
    model on contracts the market was never asked about. That mismatch did not merely blur the number,
    it inverted the sign: a card with 100 market-linked targets it beats the market on and 300 targets
    with no market at all pools as deeply NEGATIVE skill while its own `bss` is +0.75. So the numerator
    is `brier_on_baseline`, the denominator is `brier_baseline`, both are means over the same
    `n_baseline` targets, and the returned `n` is that pooled matched count -- the sample the reported
    skill was measured on, not the wider one.

    This is an aggregate of each card's stored Brier scores, not a re-scoring of the pooled sample:
    `bss = 1 - brier/brier_baseline` over averaged scores is not identical to the BSS of the
    concatenated pairs. It is the same aggregation the hero's other numbers use, and -- now that both
    sides of the ratio come from one card's matched subset -- it agrees with that card's own `bss`, which
    is the strongest consistency claim available without re-deriving it here. A card carrying NULL in
    `brier_on_baseline` (written before migration 20260428000020) is skipped rather than read as 0.0, and
    `None` rather than `0.0` is returned when nothing is left to pool -- a hero reading 0.00 for "we have
    not measured this" is a fabricated number, which is the failure this repo keeps fixing.
    """
    eligible = [
        c for c in _independent([c for c in cards
                                 if c.get("calibration_ready") and c.get("baseline") == "market"])
        if c.get("brier_on_baseline") is not None and c.get("brier_baseline") is not None
        and int(c.get("n_baseline") or 0) > 0
    ]
    total = sum(int(c["n_baseline"]) for c in eligible)
    if not total:
        return None
    brier = sum(int(c["n_baseline"]) * float(c["brier_on_baseline"]) for c in eligible) / total
    baseline = sum(int(c["n_baseline"]) * float(c["brier_baseline"]) for c in eligible) / total
    return {"n": total, "brier": brier, "brier_baseline": baseline,
            "bss": (1 - brier / baseline) if baseline > 0 else None}


def headline(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """The journal's hero numbers (spec §10 display gate): headline counts cover calibrated forecasters only.

    `settled_calibrated` counts settled TARGETS, not settled cards -- see `_independent` for the two
    card shapes that share a target set with another card and must not be added on top of it.
    """
    calibrated = [c for c in cards if c.get("calibration_ready")]
    evidence = {id(c) for c in _independent(calibrated)}
    return {
        "forecasters": len(cards),
        "calibrated": len(calibrated),
        "frozen_calibrated": sum(int(c.get("n_targets") or 0) for c in calibrated if id(c) in evidence),
        "settled_calibrated": sum(int(c.get("n_settled") or 0) for c in calibrated if id(c) in evidence),
        "promoted": sum(1 for c in cards if c.get("gate_status") == "PROMOTED"),
        "market_skill": market_skill(cards),
    }
