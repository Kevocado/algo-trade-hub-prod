"""The hub's own settled record, in the shape the predictor's feed publishes.

The inversion (approved 2026-09-27) prefers the predictor's published calibration and defers to this
once it has enough settled results. "Deferring to this" only means something if this is shaped like
what it replaces, so this module produces the same bucket keys `candidates.bucket_for` reads --
`lo`, `hi`, `n`, `mean_prob`, `hit_rate` -- cut on the same edges the feed published, and with the
last bucket closed at 1.0 so a probability of exactly 1.0 is not lost.

Pure: the caller reads the rows, this turns them into buckets. That keeps it testable without a
database and keeps the SQL in one place.

The bucket COUNT is not decided here. `n_buckets` belongs to whoever published the calibration this
replaces, so the caller passes it (`Feed.n_buckets`) rather than this module assuming a number that
is being changed from 10 to 4 in the predictors.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

# Winner rows only, which is a fact about what the hub has read, not a preference.
#
# The flat version of this helper bucketed every kind's rows into one bucket set and published it
# under winner, spread AND total. That is a kind attribution with no evidence behind it, and a wrong
# attribution is worse than an absent one: an absent kind produces `calibration_insufficient`, a
# reason the codebase already knows how to read, while a wrong one quietly judges a spread edge
# against the winner model's record. A caller that has genuinely read spread rows passes the kind it
# read; nothing else is inferred.
DEFAULT_KINDS: tuple[str, ...] = ("winner",)


def settled_buckets(
    pairs: Iterable[tuple[float, bool]],
    n_buckets: int = 10,
    *,
    kinds: Sequence[str] = DEFAULT_KINDS,
) -> dict[str, list[dict[str, Any]]]:
    """Bucket `(our_prob, hit)` pairs into the feed's calibration shape.

    `pairs` is the ledger's own view of itself: the probability the hub recorded and whether the
    market resolved that way. An empty input gives buckets with `n: 0` and `None` statistics rather
    than no buckets at all, so "no settled results in this band" is distinguishable from "no data",
    and a bucket the caller has not earned is visibly unearned.

    Known limitation, stated rather than hidden: `our_prob` on a settled row is the probability for
    that market's SIDE, while `check_candidate` looks up a home-oriented probability. A sport that
    lists a winner market for both teams therefore contributes both orientations to the same band.
    Fixing it needs the home/away orientation on the settled row, which the ledger does not carry
    today; stating it beats guessing a side and being wrong half the time.
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
            })
        out[kind] = buckets
    return out
