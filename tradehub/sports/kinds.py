"""The market kinds this build knows how to calibrate. One list, one place.

It used to be written down twice, and nothing tied the two copies together:

- `hub_calibration.KINDS` -- the kinds the hub publishes settled bands for.
- an inlined `("winner", "spread", "total")` inside `feed.parse_feed` -- the kinds it reads off the
  predictor's payload.

and a third site agreed with both only by review: a settled-ledger reader FILTERS settled rows down
to these kinds, so the two copies were not two views of one list -- the second one was a filter, and
anything it left out left the ledger silently. Add a fourth kind to the feed and every settled row
of that kind disappears with nothing logged, while the feed's own band list for it is read and
judged: the record on one side, the evidence on the other, and no word about the gap.

So the triple lives here and every one of those sites imports it. A new kind is then added once, and
a site that has drifted from this list is a site that stopped importing it -- which the tests in
`tests/test_sports_inversion.py` fail on, both by object identity and by what each module actually
reads and publishes.

**Unrecognised kinds are reported, not dropped.** Both places that can meet a kind this build does
not know -- the payload's calibration keys (`parse_feed`) and a settled ledger's kinds
(`HubLedger.unrecognised_by_engine`, filled in by whichever reader built it) -- count what they cannot
use, because "nothing of that kind settled" and "that kind is one this build cannot read" look
identical from every downstream number and are not the same fact: the first is an absence of evidence,
the second is a gap in the build. Both read as a band with `n: 0`, so the distinction has to be
carried rather than inferred. The live reader, `journal_ledger.journal_settled_ledger`, asks only for
forecaster names it composes itself and so always reports `{}`; the reporting channel is kept because
`_unrecognised_for` publishes whatever it is given.

**All three of those reports reach a human as a `per_sport` key, and none of them is only a log
line.** The feed's rides at `feed_unrecognised_kinds` (`Feed.unrecognised_kinds`), the ledger's at
`unrecognised_kinds` (`HubLedger.unrecognised_by_engine`), and both are carried by
`scan.DIAGNOSTIC_KEYS` into `sports_run_summary`. This sentence used to read "The two report in
different places on purpose, and neither is a log line" -- while describing a `log.warning` as the
feed side's whole report. A docstring that asserts a property its own module does not have is worse
than no docstring, because the file exists to stop a reader trusting a claim the code does not
back. It is now true, and the log lines are kept as the *immediate* half: they fire per fetch and
per read, and the run summary is the half that survives to someone reading a report.

The two sites cannot disagree about which names are unrecognised, and not because they share a
helper -- one of them counts, one of them filters a row at a time -- but because both test
membership in the *same object* above. `KINDS` is a tuple, not a copy of one: the feed's filter and
the ledger's filter are the same membership test against the same value, and a site that stops
importing it is a site the identity test in `tests/test_sports_inversion.py` fails on.

`unrecognised()` is the reporting helper for a caller that has already found names it cannot use and
has to say so, which is the feed: a payload is a set of keys, so the whole answer exists at once. A
ledger's rows arrive one at a time, so that side tallies as it goes and reports the tally in the run
report -- see `scan.HubLedger`.

The feed's answer is a LIST of names and the ledger's is a COUNT per name, and the difference is not
a stylistic one. The payload is a single object read once, so the set of names is fully known
immediately; a ledger is read in pages, so a count can only be finished after the last one, and a
count taken from a read that never completed is a count nobody can trust (which is why a failed
ledger read returns `read_failed=True` rather than a cheerful `{}`). Both shapes are the convention
for "a real measurement of a build gap", and neither is the same as an absent key.
"""

from __future__ import annotations

from typing import Iterable

# The kinds the predictors publish, and therefore the kinds the hub has to be able to answer for.
#
# `parse_feed` reads exactly these off the payload, `settled_buckets` publishes exactly these, and
# `check_candidate` looks the calibration up by the kind it is filtering -- so a kind MISSING from here
# does not narrow the record, it makes every edge of that kind `calibration_insufficient` the day the
# inversion fires.
#
# This was once `("winner",)` on a ruling whose premise was "kind cannot be read off a settled row".
# That premise is false: the hub's scan writes `"kind": kind` into the row's own `raw_payload`, so the
# kind is a fact the hub itself recorded.
#
# **There is a second, unrelated `("winner",)` and it is NOT this one.** `journal_ledger.py`'s
# `HUB_LEDGER_KINDS` narrows what the hub's own settled RECORD holds, for a reason that has nothing to
# do with readability: `one_rung` freezes only the rung priced nearest a coin flip, so settled spread and
# total probabilities cluster near 0.5 and bands cut from them cannot describe the 0.9-priced rungs they
# would be applied to. The kinds above are still fully supported; the ledger is deliberately behind.
# Read `journal_ledger.py` before touching `HUB_LEDGER_KINDS`, and measure before widening it.
KINDS: tuple[str, ...] = ("winner", "spread", "total")


def unrecognised(names: Iterable[str]) -> list[str]:
    """The names that are not kinds this build knows, sorted and de-duplicated.

    For a caller that has found names it cannot use and has to decide whether to say so. The result
    is sorted so a message built from it is stable across runs, and de-duplicated so a payload that
    repeats a key cannot inflate a count.
    """
    return sorted({name for name in names if name not in KINDS})
