"""The hub's own settled record, in the shape the predictor's feed publishes.

The inversion (approved 2026-09-27) prefers the predictor's published calibration and defers to this
once it has enough settled results. "Deferring to this" only means something if this is shaped like
what it replaces, so this module produces the same bucket keys `candidates.bucket_for` reads --
`lo`, `hi`, `n`, `mean_prob`, `hit_rate` -- cut on the same edges the feed published, and with the
last bucket closed at 1.0 so a probability of exactly 1.0 is not lost.

Pure: the caller reads the rows, this turns them into buckets. That keeps it testable without a
database and keeps the SQL in one place.

The bucket COUNT is not decided here. `n_buckets` belongs to whoever published the calibration this
replaces, so the caller passes it (`Feed.n_buckets`) and it is REQUIRED rather than defaulted: a
default of 10 here would contradict this module's own docstring, and it is the exact number the
predictors are moving away from. A call site that has no count has no cut, which is the honest state.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

# The kinds the predictor's feed publishes, and therefore the kinds the hub has to be able to answer
# for. `parse_feed` reads exactly these three, and `check_candidate` looks the calibration up by the
# kind it is filtering -- so publishing fewer than all three does not narrow the record, it makes
# every spread and total edge `calibration_insufficient` the day the inversion fires.
#
# This was `("winner",)` on a superseded ruling whose premise was "kind cannot be read off a settled
# row". The premise is false: `sports/scan.py` writes `"kind": kind` into the sports `predictions`
# row's own `raw_payload`, so the kind is a fact the hub itself recorded, and the hub's scan is the
# only thing that can have written it. A kind the hub cannot read is a kind the hub never wrote.
KINDS: tuple[str, ...] = ("winner", "spread", "total")

# The source of these probabilities is NOT normalised to the orientation `check_candidate` looks up.
#
# `our_prob` on a settled row is the probability for that market's SIDE, while `bucket_for` is asked
# for a home-oriented probability (`pricing.home_oriented`). NFL and CFB list a winner market for
# BOTH teams of a game, so bucketing the ledger's `our_prob` as-is mixes a home 0.65 and an away 0.65
# into one band. The bias is real and it is parked, not fixed: orientation is recoverable only by
# joining the market-ticker suffix against the feed's game for `raw_payload.game_id`, which is a
# separate piece of work (`home_oriented` at pricing.py:44 is the consumer).
#
# The reason it is a constant on the output rather than a paragraph here: a limitation that lives in
# prose is invisible to whoever reads the data, and this one is the kind that gets silently inherited
# by the next person to trust the number. So every band this module publishes carries
# `{"orientation": "raw"}`, and that travels into the stored edge row and into the reviewer's fact
# pack, which is where a future reader meets it.
HUB_ORIENTATION = "raw"


def settled_buckets(
    pairs: Iterable[tuple[float, bool]],
    n_buckets: int,
    *,
    kinds: Sequence[str] = KINDS,
) -> dict[str, list[dict[str, Any]]]:
    """Bucket `(our_prob, hit)` pairs into the feed's calibration shape, one band set per kind.

    `pairs` is the ledger's own view of itself: the probability the hub recorded and whether the
    market resolved that way. An empty input gives buckets with `n: 0` and `None` statistics rather
    than no buckets at all, so "no settled results in this band" is distinguishable from "no data",
    and a bucket the caller has not earned is visibly unearned.

    `kinds` names which band sets to publish, not which pairs go in them -- the pairs are one kind's
    pairs, and the caller has already bucketed by `raw_payload.kind` before getting here (see KINDS).
    Publishing a kind the caller has no pairs for is deliberate: it yields `n: 0` bands, which read as
    "nothing settled in this band" rather than as "this kind has no record at all".

    Every band also carries `orientation: HUB_ORIENTATION`. See that constant: the bands are cut on
    raw side-oriented probabilities and anything reading them has to know that.
    """
    if n_buckets <= 0:
        raise ValueError(f"n_buckets must be positive, got {n_buckets}")

    collected = [(float(prob), bool(hit)) for prob, hit in pairs]
    out: dict[str, list[dict[str, Any]]] = {}
    for kind in kinds:
        buckets = []
        for index in range(n_buckets):
            lo, hi = index / n_buckets, (index + 1) / n_buckets
            # The last bucket owns 1.0, which `lo <= p < hi` would otherwise drop.
            last = index == n_buckets - 1
            inside = [(p, h) for p, h in collected if (lo <= p < hi) or (last and p == 1.0)]
            n = len(inside)
            buckets.append({
                "lo": lo,
                "hi": hi,
                "n": n,
                "mean_prob": round(sum(p for p, _ in inside) / n, 4) if n else None,
                "hit_rate": round(sum(1 for _, h in inside if h) / n, 4) if n else None,
                "orientation": HUB_ORIENTATION,
            })
        out[kind] = buckets
    return out
