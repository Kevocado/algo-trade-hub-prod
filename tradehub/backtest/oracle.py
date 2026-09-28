"""The oracle bound: the best Brier any pure recalibration of a model could reach.

Section 5a of the hub-redesign spec asks the question this module answers: an engine
loses to the market, so is the loss *confidence* (a fixable calibration problem) or
*resolution* (a discrimination problem nobody can recalibrate away)? Replacing each
prediction with the observed hit rate of its own calibration bucket removes calibration
error entirely and leaves only resolution. Whatever Brier that scores is the floor for
any bucket-conditional recalibration -- and if it is still worse than the market, no
recalibration, bin-width change or confidence tweak can rescue the engine.

This is the weather precedent: perfectly calibrating weather scored 0.12294 against the
market's 0.09713, buying 0.0013 of a 0.0271 gap, so the residual was discrimination.

Two variants, and the difference between them is the whole point of the module:

`oracle_full_sample`
    The literal "perfectly calibrated version of the same model": the bucket rate is
    estimated from *every* row in the sample, including the row being scored. That is
    the best in-sample Brier a bucket map can produce, so it is a genuine upper bound on
    achievable Brier -- but the rate it substitutes already knows the answer it is scored
    against, so it flatters a bad model and is NOT evidence about a deployable
    recalibration. Reported for comparability with the weather number.

`oracle_pit`
    The point-in-time variant: a row's bucket rate comes only from rows decided
    *strictly before* it. This is what a recalibrator actually ships, and using the
    full-sample rate here would be lookahead -- the single easiest way to make a badly
    calibrated model look calibrated. Rates are shrunk toward the bucket's own mean
    prediction (`shrink` pseudo-observations) because an unshrunk point-in-time rate on a
    thin bucket is 0.0 or 1.0, which is a worse forecast than the model it replaced and
    would make the bound an artifact of sample size rather than a measurement of
    resolution. A bucket with no strictly-earlier observation returns the model's own
    probability, so the first rows of a bucket can never be scored against themselves.

Side preservation: buckets are side-mirrored at 0.5, exactly as
`track_record.compute_calibration` buckets them, so a bucket's observed rate is a rate for
*the side the model favoured*. A model probability of 0.15 (favouring NO) therefore gets
`1 - rate` substituted, not `rate`; substituting the rate directly would flip the sign of
the forecast and score a model that ranks perfectly as though it were random.

Ladder caution: a month of KXPAYROLLS is ~8 strikes on one number, so those rows share an
outcome driver and the effective sample is closer to the month count than the row count.
`oracle_bound` reports `n_months` for that reason; treat a row-count significance claim
with suspicion.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from tradehub.settlement import brier_score
from tradehub.track_record import BUCKETS, bucketize

DEFAULT_SHRINK = 5.0


def confidence_of(prob: float) -> float:
    """The side-mirrored confidence, in [0.5, 1.0] -- the quantity buckets are cut on."""
    return min(max(max(prob, 1.0 - prob), 0.5), 1.0)


def favoured_yes(prob: float) -> bool:
    return prob >= 0.5


def _hit(prob: float, result: str) -> float:
    """1.0 when the side the model favoured is the side that won."""
    return 1.0 if (result == "yes") == favoured_yes(prob) else 0.0


def _outcome(result: str) -> int:
    if result not in ("yes", "no"):
        raise ValueError(f"result must be yes/no, got {result!r}")
    return 1 if result == "yes" else 0


def _unmirror(rate: float, prob: float) -> float:
    """Put a favoured-side hit rate back onto the scale of `prob` (which may favour NO)."""
    return rate if favoured_yes(prob) else 1.0 - rate


def _mean_brier(probs: Sequence[float], results: Sequence[str],
                weights: Sequence[float] | None = None) -> float | None:
    if not probs:
        return None
    if weights is None:
        return sum(brier_score(p, _outcome(r)) for p, r in zip(probs, results)) / len(probs)
    total = sum(weights)
    if not total:
        return None
    return sum(w * brier_score(p, _outcome(r)) for p, r, w in zip(probs, results, weights)) / total


def _weights(rows: Sequence[Mapping[str, Any]]) -> list[float]:
    """Row weights, honouring a `weight` key so a ledger can be contract-weighted.

    The ledger's hourly scan predicts the same market many times, so an unweighted mean
    would let one contract count ~24 times -- the same reason
    `track_record._contract_weights` exists for the gate.
    """
    return [float(r.get("weight", 1.0)) for r in rows]


def _order_key(row: Mapping[str, Any]) -> tuple[str, str]:
    decided = row.get("decided_at")
    if isinstance(decided, datetime):
        stamp = decided.astimezone().isoformat()
    else:
        stamp = str(decided)
    return (stamp, str(row.get("market_ticker") or ""))


def _bucket_table(probs: Sequence[float], results: Sequence[str],
                  mids: Sequence[float | None] | None = None) -> list[dict[str, Any]]:
    """Per-bucket n, mean predicted confidence, observed favoured-side hit rate.

    Rows are bucketed on `probs`. When `mids` is given, the market's mean confidence and
    observed hit rate are reported *within the same buckets* -- that is a conditional
    comparison ("in the rows the model was unsure about, the market said 0.70 and won 54%"),
    which is not the market's own calibration curve. For that, call this again with the
    market's own probabilities as `probs`; `oracle_bound` reports it as `market_buckets`.
    """
    buckets: dict[str, list[int]] = defaultdict(list)
    for index, prob in enumerate(probs):
        buckets[bucketize(confidence_of(prob))].append(index)
    out: list[dict[str, Any]] = []
    for bucket in BUCKETS:
        members = buckets.get(bucket)
        if not members:
            continue
        n = len(members)
        row: dict[str, Any] = {
            "bucket": bucket,
            "n_rows": n,
            "predicted": round(sum(confidence_of(probs[i]) for i in members) / n, 4),
            "observed": round(sum(_hit(probs[i], results[i]) for i in members) / n, 4),
        }
        if mids is not None and all(mids[i] is not None for i in members):
            market_probs = [float(mids[i]) for i in members]  # type: ignore[arg-type]
            row["market_predicted"] = round(
                sum(confidence_of(m) for m in market_probs) / n, 4)
            row["market_observed"] = round(
                sum(_hit(m, results[i]) for m, i in zip(market_probs, members)) / n, 4)
        out.append(row)
    return out


def oracle_brier(rows: Sequence[Mapping[str, Any]], *, variant: str = "pit",
                 shrink: float = DEFAULT_SHRINK) -> dict[str, Any]:
    """Score `rows` after replacing every probability with its bucket's observed rate.

    `rows` are `tradehub.backtest.metrics.prediction_row` dicts plus a `decided_at` key
    (datetime or ISO string) so point-in-time ordering is possible. Point-in-time ordering
    is by `decided_at`; the `full` variant is order-free.

    Returns {"brier", "n_rows", "n_scored", "n_unpopulated"} -- `n_unpopulated` counts
    rows left at their raw probability because no observation existed to calibrate them
    from, which is the honest cost of refusing to look ahead.
    """
    if variant not in ("pit", "full"):
        raise ValueError(f"variant must be 'pit' or 'full', got {variant!r}")
    ordered = sorted(rows, key=_order_key)
    probs = [float(r["our_prob"]) for r in ordered]
    results = [str(r["result"]) for r in ordered]
    weights = _weights(ordered)

    if variant == "full":
        hit_sum: dict[str, float] = defaultdict(float)
        weight_sum: dict[str, float] = defaultdict(float)
        for prob, result, weight in zip(probs, results, weights):
            bucket = bucketize(confidence_of(prob))
            hit_sum[bucket] += weight * _hit(prob, result)
            weight_sum[bucket] += weight
        rates = {b: hit_sum[b] / weight_sum[b] for b in weight_sum if weight_sum[b]}
        scored: list[float] = []
        scored_weights: list[float] = []
        unpopulated = 0
        for prob, weight in zip(probs, weights):
            bucket = bucketize(confidence_of(prob))
            if bucket not in rates:
                unpopulated += 1
                scored.append(prob)  # nothing to substitute: leave the model alone
            else:
                scored.append(_unmirror(rates[bucket], prob))
            scored_weights.append(weight)
        return {"brier": _mean_brier(scored, results, scored_weights), "n_rows": len(ordered),
                "n_scored": len(scored), "n_unpopulated": unpopulated}

    scored, no_prior = pit_probabilities(rows, shrink=shrink)
    return {"brier": _mean_brier(scored, [str(r["result"]) for r in ordered], _weights(ordered)),
            "n_rows": len(ordered), "n_scored": len(scored), "n_unpopulated": no_prior}


def pit_probabilities(rows: Sequence[Mapping[str, Any]], *, shrink: float = DEFAULT_SHRINK
                      ) -> tuple[list[float], int]:
    """The point-in-time calibrated probability for every row, in `decided_at` order.

    Row *i* is calibrated from rows decided strictly before it, and from nothing else. The
    returned count is how many rows had no strictly-earlier observation in their own bucket
    and were therefore left at the model's probability -- with `shrink` pseudo-observations
    toward the bucket's running mean confidence, an empty bucket returns that prior, which
    for the first row in a bucket is the model's own confidence, so the substitution is the
    identity rather than a guess.

    Exposed separately from `oracle_brier` because the causality property is the whole
    honesty claim of this module, and it has to be testable against the real function rather
    than against a copy of it.
    """
    ordered = sorted(rows, key=_order_key)
    seen: dict[str, dict[str, float]] = {b: {"hit": 0.0, "n": 0.0, "conf": 0.0} for b in BUCKETS}
    scored: list[float] = []
    no_prior = 0
    for row in ordered:
        prob = float(row["our_prob"])
        weight = float(row.get("weight", 1.0))
        conf = confidence_of(prob)
        state = seen[bucketize(conf)]
        if state["n"] == 0:
            rate = conf  # no strictly-earlier row: the shrunk formula returns the model itself
            no_prior += 1
        else:
            prior = state["conf"] / state["n"]
            rate = (state["hit"] + shrink * prior) / (state["n"] + shrink)
        scored.append(_unmirror(rate, prob))
        # Only now does this row's own outcome enter the running state.
        state["hit"] += weight * _hit(prob, str(row["result"]))
        state["n"] += weight
        state["conf"] += weight * conf
    return scored, no_prior


def clustered_gap(rows: Sequence[Mapping[str, Any]], *, group_key: str = "month",
                  draws: int = 4000, seed: int = 20260928) -> dict[str, Any]:
    """Bootstrap the paired (ours - market) Brier gap, resampling whole groups.

    A month of KXPAYROLLS is ~8 strikes on one payroll print, so those rows share an outcome
    driver and the effective sample is the number of months, not the number of rows.
    Resampling rows independently would shrink the interval by roughly sqrt(rows per group)
    and turn a 41-event comparison into a 370-event one that looks decisive when it is not.
    So the resampling unit is the group, and the reported interval is the honest one.

    Returns the point gap, a percentile interval, the two-sided bootstrap p-value for
    "the gap is zero or negative" (i.e. for us being no worse than the market), and how many
    groups the interval rests on.
    """
    import random

    pairs: list[tuple[Any, float]] = []
    for row in rows:
        mid = row.get("market_prob")
        if mid is None:
            continue  # unpaired rows cannot enter a paired test
        prob = float(row["our_prob"])
        outcome = _outcome(str(row["result"]))
        pairs.append((row.get(group_key), brier_score(prob, outcome) - brier_score(float(mid), outcome)))
    if not pairs:
        return {"gap": None, "n_groups": 0, "n_pairs": 0}
    groups: dict[Any, list[float]] = defaultdict(list)
    for key, diff in pairs:
        groups[key].append(diff)
    keys = sorted(groups, key=lambda k: str(k))
    point = sum(diff for _, diff in pairs) / len(pairs)
    rng = random.Random(seed)
    n = len(keys)
    samples = []
    for _ in range(draws):
        total = 0.0
        count = 0
        for _ in range(n):
            group = groups[keys[rng.randrange(n)]]
            total += sum(group)
            count += len(group)
        samples.append(total / count)
    samples.sort()
    low = samples[int(0.025 * draws)]
    high = samples[min(draws - 1, int(0.975 * draws))]
    at_least_zero = sum(1 for s in samples if s >= 0.0)
    return {
        "gap": round(point, 5),
        "ci95": [round(low, 5), round(high, 5)],
        "p_not_worse_than_market": round(2.0 * min(at_least_zero, draws - at_least_zero) / draws, 4),
        "n_groups": n,
        "n_pairs": len(pairs),
        "group_key": group_key,
    }


def _verdict(oracle: float | None, market: float | None) -> str | None:
    if oracle is None or market is None:
        return None
    return "calibration_can_close_the_gap" if oracle < market else "discrimination_not_calibration"


def oracle_bound(rows: Sequence[Mapping[str, Any]], *, shrink: float = DEFAULT_SHRINK,
                 market_brier: float | None = None) -> dict[str, Any]:
    """The full decomposition: raw, oracle (both variants), market, and the verdict.

    `market_brier` is the reference the caller wants to beat (e.g. the market's published
    Brier for the series). It is reported next to the market Brier measured on *these*
    rows, so a caller comparing against a number from a different window or a different
    quote timestamp sees the difference instead of missing it.

    `verdict` answers only the question it is asked: whether a perfectly calibrated version
    of this model could reach the market. It is a statement about a CEILING, not about
    significance -- whether the observed gap is even distinguishable from zero at this
    sample size is `clustered_gap`, and the two must be read together. An engine can fail
    the bound decisively and still be too close to call on 41 months.
    """
    probs = [float(r["our_prob"]) for r in rows]
    results = [str(r["result"]) for r in rows]
    mids: list[float | None] = [r.get("market_prob") for r in rows]
    weights = _weights(rows)
    ours = _mean_brier(probs, results, weights)
    paired = [(float(m), r, w) for m, r, w in zip(mids, results, weights) if m is not None]
    market = (_mean_brier([m for m, _, _ in paired], [r for _, r, _ in paired], [w for _, _, w in paired])
              if len(paired) == len(rows) else None)
    pit = oracle_brier(rows, variant="pit", shrink=shrink)
    full = oracle_brier(rows, variant="full")
    out: dict[str, Any] = {
        "n_rows": len(rows),
        "n_contracts": len({r.get("market_ticker") for r in rows if r.get("market_ticker")}),
        "n_months": len({str(r.get("month")) for r in rows if r.get("month")}),
        "brier_ours": round(ours, 5) if ours is not None else None,
        "brier_oracle_pit": round(pit["brier"], 5) if pit["brier"] is not None else None,
        "brier_oracle_full_sample": round(full["brier"], 5) if full["brier"] is not None else None,
        "brier_market": round(market, 5) if market is not None else None,
        "pit_n_scored": pit["n_scored"],
        "pit_n_no_prior": pit["n_unpopulated"],
        "shrink": shrink,
        "buckets": _bucket_table(probs, results, mids),
    }
    if market is not None:
        # The market's own calibration curve, bucketed on the market's own confidence, so
        # "who is the miscalibrated one" is answerable from two comparable tables.
        out["market_buckets"] = _bucket_table([float(m) for m in mids], results)
    else:
        out["market_buckets"] = []
    # Two verdicts, because they answer different questions and on a thin sample they can
    # disagree. `verdict_full_sample` is the CEILING: with the calibration map known exactly,
    # can recalibration reach the market at all? `verdict_pit` is the DEPLOYABLE one: with the
    # map estimated only from the past, does recalibration actually beat the market? A
    # pessimistic PIT rate on a small sample is a statement about estimation noise, not about
    # the ceiling, so the ceiling is the one that refutes the calibration hypothesis.
    out["verdict_full_sample"] = _verdict(full["brier"], market)
    out["verdict_pit"] = _verdict(pit["brier"], market)
    if ours is not None and market and full["brier"] is not None:
        gap = ours - market
        out["gap_ours"] = round(gap, 5)
        out["gap_closed_by_perfect_calibration"] = (
            round((gap - (full["brier"] - market)) / gap, 4) if gap > 0 else None)
    out["clustered_gap_ours_vs_market"] = clustered_gap(rows)
    if market_brier:
        out["market_brier_reference"] = market_brier
        if out["brier_ours"] is not None:
            out["ratio_ours_vs_reference"] = round(out["brier_ours"] / market_brier, 4)
        if out["brier_oracle_pit"] is not None:
            out["ratio_oracle_pit_vs_reference"] = round(out["brier_oracle_pit"] / market_brier, 4)
        if out["brier_oracle_full_sample"] is not None:
            out["ratio_oracle_full_vs_reference"] = round(out["brier_oracle_full_sample"] / market_brier, 4)
    return out


def bound_from_rows(rows: Iterable[Mapping[str, Any]], **kwargs: Any) -> dict[str, Any]:
    """`oracle_bound` for a caller that already holds an iterable."""
    return oracle_bound(list(rows), **kwargs)


__all__ = [
    "DEFAULT_SHRINK",
    "bound_from_rows",
    "clustered_gap",
    "confidence_of",
    "oracle_bound",
    "oracle_brier",
    "pit_probabilities",
]
