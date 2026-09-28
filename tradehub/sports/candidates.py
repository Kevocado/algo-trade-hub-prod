"""Deterministic candidate filter (spec §3.2 stage 1): edge after fees is decided by
tradehub.edges; this adds liquidity, time-to-start and predictor calibration in the bucket."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from tradehub.edges import EdgeSuggestion
from tradehub.sports.kinds import KINDS
from tradehub.sports.kalshi import SportsMarket
from tradehub.sports.mapping import MatchedGame
from tradehub.sports.pricing import home_oriented


@dataclass(frozen=True)
class CandidateCheck:
    ok: bool
    reasons: tuple[str, ...]
    bucket: dict[str, Any] | None
    # Which calibration the decision was made against, so a row can record which gate passed rather
    # than leaving the page to guess. Defaults to the predictor, which is what every caller that has
    # no hub ledger to offer is using.
    calibration_source: str = "predictor"


def bucket_for(buckets: list[dict[str, Any]], prob: float) -> dict[str, Any] | None:
    for b in buckets:
        if b["lo"] <= prob < b["hi"] or (prob == 1.0 and b["hi"] == 1.0):
            return b
    return None


# Enough settled results for the hub's own ledger to become the authority instead of the predictor's
# published one. 100 is the reviewer's MIN_SETTLED (sports/scorecard.py) for the same reason: it is
# what this product means by "enough settled", and two thresholds for one concept is how they drift.
# Named rather than inlined so a later ruling changes one place; tests/test_sports_inversion.py ties
# the two together so a change to one without the other fails.
HUB_LEDGER_MIN_SETTLED = 100


def _publishes_bands(calibration: Mapping[str, list[dict[str, Any]]] | None) -> bool:
    """Whether this is a record, or an empty shell shaped like one.

    `parse_feed` returns `{k: calibration.get(k) or [] for k in KINDS}` -- three keys, always -- so a
    truthiness test on the mapping is true for a predictor that published no calibration at all.
    Read directly:

        parse_feed({"calibration": {}}).calibration  ->  {'winner': [], 'spread': [], 'total': []}
        bool(that)                                    ->  True

    and `choose_calibration` labelled that `predictor`, which downstream reads as *the predictor's
    record rejected this* when the predictor published nothing at all. The same attribution defect
    this module already fixed once, in the reviewer's fact pack. So the test is per bucket, where
    "did the predictor send any bands" is the question that was actually being asked.

    `bool(calibration)` first, so a `None` -- the shape `check_candidate`'s default and
    `choose_calibration`'s own callers pass for "no record" -- is not a mapping to ask about.
    """
    return bool(calibration) and any(calibration.get(kind) for kind in KINDS)


def choose_calibration(
    predictor_calibration: Mapping[str, list[dict[str, Any]]] | None,
    hub_calibration: Mapping[str, list[dict[str, Any]]] | None,
    params: Mapping[str, float],
    kind: str,
) -> tuple[Mapping[str, list[dict[str, Any]]], str]:
    """Which calibration the candidate filter should judge against, and which one it used.

    Approved 2026-09-27: "the publishing predictor's own published calibration first, then the hub's
    settled ledger once it has enough". The predictor publishes its own reliability record, so it is
    available immediately and it is the model's own view of itself. The hub's ledger reflects what
    the hub actually graded and priced against, so once it has enough settled results it is the
    better record. Below the threshold the hub has no record worth deferring to, and deferring to it
    would be deferring to nothing -- which reads downstream as `calibration_insufficient`, i.e. as bad
    luck rather than as an absent measurement.

    `kind` is REQUIRED, and it counts only that kind's buckets. The threshold is about settled
    evidence for the thing being judged, and the thing being judged is a band of ONE kind. Summing
    `n` across every kind is safe only while the hub published one kind, which was true under the
    superseded winner-only ruling and is false now that all three are published: CFB's live ledger is
    42 winner / 33 spread / 32 total, an aggregate of 107 that would hand the hub authority on a
    WINNER bucket holding 42 settled rows -- 42% of the 100 this threshold is asking for. A kind
    borrows no other kind's evidence, so the count has to be per kind. Made required rather than
    defaulted for the same reason: a default would be a silent wrong answer at a call site that
    forgot, and the two sources of "enough settled" are exactly the thing that must not be guessed.

    `params` is accepted and deliberately unread today. The threshold is the named constant above; a
    config key nobody has ruled on is not a reason to read one.

    "Did the predictor publish a record" is asked per BUCKET (`_publishes_bands`), not of the
    mapping. `parse_feed` hands back three keys whatever the payload held, so a truthiness test on
    the mapping labelled a predictor that published nothing as the record that rejected the edge --
    see that helper. The hub's side below is deliberately not asked the same way, and the asymmetry
    is the attribution rather than an oversight: that branch is only reached once the hub ledger read
    COMPLETED, so a band set of `n: 0` really is the hub's own record saying it has settled nothing
    of that kind. "The hub read and holds nothing" and "the hub never read" are different facts and
    the flag on the ledger already tells them apart.

    Returns the mapping and its source, so the row can record which gate passed.
    """
    hub_total = 0
    for bucket in (hub_calibration or {}).get(kind) or []:
        n = bucket.get("n")
        if isinstance(n, (int, float)):
            hub_total += int(n)

    if hub_total >= HUB_LEDGER_MIN_SETTLED and hub_calibration:
        return hub_calibration, "hub_ledger"
    if _publishes_bands(predictor_calibration):
        return predictor_calibration, "predictor"
    if hub_calibration:
        # No predictor payload at all must not leave the filter with nothing to judge against. Note
        # this is reachable with a hub ledger BELOW the threshold, and with a hub ledger that has no
        # bands for `kind` at all -- both read downstream as "no bucket", i.e. `calibration_insufficient`,
        # which is the honest answer for an absent measurement. What this branch must never do is
        # invent a band: it hands over exactly the mapping it was given.
        #
        # Mapping truthiness, NOT `_publishes_bands`, and the docstring says why: reaching here means
        # the hub's read completed, so empty bands are a measurement rather than an absence. Do not
        # "tidy" the two branches into one predicate.
        return hub_calibration, "hub_ledger"
    return {}, "none"


def check_candidate(
    kind: str, sm: SportsMarket, mg: MatchedGame, edge: EdgeSuggestion,
    calibration: Mapping[str, list[dict[str, Any]]], params: Mapping[str, float], now: datetime,
    *, hub_calibration: Mapping[str, list[dict[str, Any]]] | None = None,
) -> CandidateCheck:
    # The inversion. `calibration` stays the predictor's published record and `hub_calibration` is
    # keyword-only and defaulted, so every existing caller and test behaves exactly as it did before
    # this parameter existed -- which is the point of the gate failing toward the published record.
    # `kind` is already this function's first positional argument, so the per-kind count needs no
    # new parameter here and this signature is unchanged from the pre-inversion one plus that keyword.
    calibration, calibration_source = choose_calibration(calibration, hub_calibration, params, kind)
    reasons: list[str] = []
    q = sm.quote
    if q.yes_bid is None or q.yes_ask is None or q.yes_ask - q.yes_bid > params["max_quote_spread"] + 1e-9:
        reasons.append("wide_quote")
    if min(q.yes_bid_size, q.yes_ask_size) < params["min_resting_size"]:
        reasons.append("thin_book")
    if sm.volume < params["min_volume"]:
        reasons.append("low_volume")
    hours = (mg.game.start_utc - now).total_seconds() / 3600.0
    if hours < params["min_hours_to_start"]:
        reasons.append("starts_too_soon")
    elif hours > params["max_hours_to_start"]:
        reasons.append("starts_too_late")
    bucket = bucket_for(calibration.get(kind) or [], home_oriented(kind, sm, mg, edge.our_prob))
    if bucket is None or bucket["n"] < params["calibration_min_n"] or bucket["mean_prob"] is None:
        reasons.append("calibration_insufficient")
    # No per-bucket calibration test here, and that is deliberate (ruled 2026-09-27).
    #
    # This used to be: `elif abs(mean_prob - hit_rate) > calibration_max_dev` -> `calibration_off`.
    # At calibration_min_n 20 and a 10pp threshold, a *correctly calibrated* bucket trips that about
    # 37% of the time -- n=20 gives an 11.2pp standard error, so 10pp is 0.89 SD. It rejected weather
    # on a bucket with n=23 and z=1.42, which is a coin flip wearing a threshold.
    #
    # It could not be tuned into shape either, because the two demands are mutually exclusive:
    # admission wants a small min_n (the aggregate n_buckets x min_n must stay under the reviewer's
    # 100) while a 10pp comparison needs n >= 97. At 10 buckets that asks for min_n <= 10 and
    # min_n >= 97 at once.
    #
    # So the quality call belongs to the reviewer, which is built for it and already requires
    # n_settled >= 100 (MIN_SETTLED in sports/scorecard.py). What is left here is what can honestly
    # be tested at small n: is it tradeable, is the window open, and is there any settled history in
    # this bucket at all. `calibration_insufficient` stays for exactly that reason -- n < min_n is an
    # absence, not a noisy comparison.
    return CandidateCheck(ok=not reasons, reasons=tuple(reasons), bucket=bucket,
                          calibration_source=calibration_source)
