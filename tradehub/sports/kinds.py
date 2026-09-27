"""The market kinds this build knows how to calibrate. One list, one place.

It used to be written down twice, and nothing tied the two copies together:

- `hub_calibration.KINDS` -- the kinds the hub publishes settled bands for.
- an inlined `("winner", "spread", "total")` inside `feed.parse_feed` -- the kinds it reads off the
  predictor's payload.

and a third site agreed with both only by review: `sports/scan.py` FILTERS settled rows down to
these kinds, so the two copies were not two views of one list -- the second one was a filter, and
anything it left out left the ledger silently. Add a fourth kind to the feed and every settled row
of that kind disappears with nothing logged, while the feed's own band list for it is read and
judged: the record on one side, the evidence on the other, and no word about the gap.

So the triple lives here and every one of those sites imports it. A new kind is then added once, and
a site that has drifted from this list is a site that stopped importing it -- which the tests in
`tests/test_sports_inversion.py` fail on, both by object identity and by what each module actually
reads and publishes.

**Unrecognised kinds are reported, not dropped.** Both places that can meet a kind this build does
not know -- the payload's calibration keys (`parse_feed`) and a settled row's `raw_payload.kind`
(`_hub_settled_ledger`) -- count what they cannot use and say so, because "nothing of that kind
settled" and "that kind is one this build cannot read" look identical from every downstream number
and are not the same fact: the first is an absence of evidence, the second is a gap in the build.
`unrecognised()` is the one definition of that test, so both sites cannot disagree about it either.
"""

from __future__ import annotations

from typing import Iterable

# The kinds the predictors publish, and therefore the kinds the hub has to be able to answer for.
#
# `parse_feed` reads exactly these off the payload, `_hub_settled_ledger` keeps exactly these out of
# the settled rows, `settled_buckets` publishes exactly these, and `check_candidate` looks the
# calibration up by the kind it is filtering -- so publishing fewer than all of them does not narrow
# the record, it makes every spread and total edge `calibration_insufficient` the day the inversion
# fires, and dropping a settled row of a kind that is NOT here does not narrow it either, it deletes
# evidence (see the module docstring).
#
# This was `("winner",)` on a superseded ruling whose premise was "kind cannot be read off a settled
# row". The premise is false: `sports/scan.py` writes `"kind": kind` into the sports `predictions`
# row's own `raw_payload`, so the kind is a fact the hub itself recorded, and the hub's scan is the
# only thing that can have written it. A kind the hub cannot read is a kind the hub never wrote.
KINDS: tuple[str, ...] = ("winner", "spread", "total")


def unrecognised(names: Iterable[str]) -> list[str]:
    """The names that are not kinds this build knows, sorted and de-duplicated.

    For a caller that has found names it cannot use and has to decide whether to say so. The result
    is sorted so a message built from it is stable across runs, and de-duplicated so a payload that
    repeats a key cannot inflate a count.
    """
    return sorted({name for name in names if name not in KINDS})
