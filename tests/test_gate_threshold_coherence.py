"""The candidate gate and the reviewer must not disagree about how much evidence is enough.

Found by reading the live feeds on 2026-09-27, not by reading this code. `/api/kalshi-feed` on both
predictors reports `calibration.n_buckets = 10`, and `engines.yaml` sets `calibration_min_n: 20` for
both sports. `check_candidate` requires `bucket["n"] >= calibration_min_n` in the bucket the edge
falls in, so an edge is only ever admitted once *every* bucket can clear the bar -- which takes

    10 buckets x 20 = 200 settled contracts.

The reviewer's own threshold is `MIN_SETTLED = 100` (`sports/scorecard.py`). At 100 settled it renders
a verdict on the engine. So the product is required to be **twice as strict about admitting an edge as
its own reviewer is about judging one**, and it cannot surface a candidate until roughly twice as long
after launch as the point at which the reviewer could already have declared an engine good or bad.

Nothing fails when this is wrong. The gate just stays shut, and every row carries
`calibration_insufficient`, which reads like a data problem rather than a threshold contradiction.

What is settled so far, for scale: NFL has **0** settled contracts in every bucket; CFB has 42
(winner) / 33 (spread) / 32 (total) with a largest single bucket of 11. So zero buckets reach 20 today.
That number is here to keep the fix honest -- aligning the thresholds does NOT open the gate, because
42 < 100 either way. It makes the target coherent and reachable rather than unreachable.

Ruled 2026-09-27: `n_buckets` becomes 4 and the per-bucket `calibration_off` test is dropped in
favour of the reviewer. Those two halves have to arrive together — see the module note in
`PREDICTOR_N_BUCKETS` and the rationale in `candidates.py`. The test is no longer an xfail: it was
`xfail(strict=True)` against the old `10 x 20 = 200`, and the ruling makes it pass for real.

The coherence test is `xfail(strict=True)`: it fails today by design, and when someone fixes the
thresholds it will XPASS, which under `strict` is itself a failure telling them to delete this marker.
Without `strict` the fix would silently leave a stale xfail behind and the defect would be forgotten
again.

**TWO consumers now, and the whole point of this file is the relation between them.** When this was
written, `MIN_SETTLED` was the only number in the product that meant "enough settled". The inversion
added a second one — `HUB_LEDGER_MIN_SETTLED` in `sports/candidates.py`, chosen as 100 *precisely
because* it equals `MIN_SETTLED` — so a test in `test_sports_inversion.py` ties the two constants
together and calls the tie done. What the tie does not cover is the arithmetic on the other side of
the constant: `choose_calibration` counts settled rows of ONE kind, so a kind goes live at
`HUB_LEDGER_MIN_SETTLED` of its own rows, and the same `n_buckets x calibration_min_n` that has to
fit under the reviewer's bar has to fit under this one too. Two thresholds for one concept with the
equation between them unpinned is the same defect this file exists to prevent, one increment later —
and the increment is silent, because raising `HUB_LEDGER_MIN_SETTLED` to 200 would fail the equality
test and pass this one, or the reverse, and nobody would be watching the relation.

That is why the second test below exists. It is worth being precise about what it is: **a missing
invariant, not a missing mutation.** `HUB_LEDGER_MIN_SETTLED`'s value is already pinned twice (its
equality with `MIN_SETTLED`, and its use as a threshold in the per-kind tests), so a mutation to 300
fails today. What nothing watched was the relation — the one fact that is not a value.
"""
import pytest
import yaml

from tradehub.sports.candidates import HUB_LEDGER_MIN_SETTLED
from tradehub.sports.scorecard import MIN_SETTLED

ENGINES_YAML = "tradehub/config/engines.yaml"

# RULED 2026-09-27: 4 buckets x min_n 20 = 80, under the reviewer's 100.
#
# The live feeds reported 10 as of 2026-09-27, which is what made the gate incoherent: 10 x 20 = 200
# against a reviewer bar of 100, so admitting an edge needed twice the evidence of judging one.
# `n_buckets` is the PREDICTOR's setting, so the change to 4 lands in NFL_Predictor and CFB_Predictor
# -- two other repos, and it is OUTSTANDING as of this commit. This constant is the ruled value, not a
# live reading, so the test states the invariant the ruling intends; the deployed feeds still emit 10
# until those PRs merge, which is why the docstring says so rather than leaving it implied.
PREDICTOR_N_BUCKETS = 4


def _sport_params(sport: str) -> dict:
    with open(ENGINES_YAML) as handle:
        config = yaml.safe_load(handle)
    return config[sport]


@pytest.mark.parametrize("sport", ["sports_nfl", "sports_cfb"])
def test_every_sport_reports_the_calibration_min_n_it_gates_on(sport):
    """A sport missing the key would fall back to a default somewhere and quietly gate differently.
    `sports_cfb` once looked empty in a `grep -A 2` and was believed to be; it is not."""
    params = _sport_params(sport)

    assert "calibration_min_n" in params, f"{sport} has no calibration_min_n in {ENGINES_YAML}"


@pytest.mark.parametrize("sport", ["sports_nfl", "sports_cfb"])
def test_the_gate_needs_no_more_evidence_than_the_reviewer_does(sport):
    """The invariant: admitting an edge must not require more settled contracts than judging one.

    Ruled 2026-09-27: 4 buckets x min_n 20 = 80, which is under the reviewer's 100. This test was
    `xfail(strict=True)` against the old 10 x 20 = 200 and is now a real assertion.
    """
    params = _sport_params(sport)
    implied_required = PREDICTOR_N_BUCKETS * params["calibration_min_n"]

    assert implied_required <= MIN_SETTLED, (
        f"{sport} needs {implied_required} settled contracts for every calibration bucket to clear "
        f"({PREDICTOR_N_BUCKETS} buckets x min_n {params['calibration_min_n']}), but the reviewer "
        f"renders a verdict at {MIN_SETTLED}. The product cannot surface a candidate until twice as "
        f"long after launch as the point where the reviewer could already have ruled."
    )


@pytest.mark.parametrize("sport", ["sports_nfl", "sports_cfb"])
def test_the_gate_needs_no_more_evidence_than_the_hub_ledger_demands(sport):
    """The same invariant, for the second consumer of it, which is the one the gate itself reads.

    `n_buckets x calibration_min_n` is what every calibration bucket needs before a single edge can
    be admitted, and it is what `HUB_LEDGER_MIN_SETTLED` demands before the hub's own settled record
    takes over from the published one. They are the SAME concept with TWO consumers — "enough
    settled" in this product — so a change to either has to confront the other, and this is the file
    that says so. Today it holds at 4 x 20 = 80 under both 100s.

    It is worth saying out loud what this file did NOT have, because the difference is the finding:
    the constant's VALUE was already pinned (`test_the_threshold_is_the_reviewers_own_number` ties
    `HUB_LEDGER_MIN_SETTLED` to `MIN_SETTLED`, and the per-kind tests use it as a threshold), so
    mutating the constant to 300 fails today. What nothing watched was the RELATION — which is not a
    value, and is the only thing here that can be wrong while every number is individually correct.

    The sting, and why the relation is worth this assertion: the 4-bucket ruling is OUTSTANDING in
    NFL_Predictor and CFB_Predictor and the live feeds still emit `n_buckets = 10`. So on the day
    the flip lands, admitting an edge through the hub needs `10 x 20 = 200` settled OF THAT KIND,
    while the reviewer renders its verdict at 100 ACROSS THE ENGINE. That is this file's original
    defect, reintroduced one threshold over, and it would have been invisible: a wider band is a
    thinner band, so every edge would read `calibration_insufficient` and a hub that had 200 settled
    rows would still be described as short of evidence.
    """
    params = _sport_params(sport)
    implied_required = PREDICTOR_N_BUCKETS * params["calibration_min_n"]

    assert implied_required <= HUB_LEDGER_MIN_SETTLED, (
        f"{sport} needs {implied_required} settled contracts of ONE kind for every calibration bucket "
        f"to clear ({PREDICTOR_N_BUCKETS} buckets x min_n {params['calibration_min_n']}), but the "
        f"hub's ledger only takes over at {HUB_LEDGER_MIN_SETTLED} of that kind. Until it does, every "
        f"edge of that kind is judged on the published record -- which is the safe direction, and "
        f"which also means the hub is off while a reader of the run summary is told nothing about "
        f"why. Raise the bucket count or the per-bucket minimum together, or move "
        f"HUB_LEDGER_MIN_SETTLED."
    )


@pytest.mark.parametrize("sport", ["sports_nfl", "sports_cfb"])
def test_the_current_gate_arithmetic_is_what_this_file_claims(sport):
    """Pins the two numbers the docstring quotes, so a config change cannot quietly invalidate the
    reasoning above without this failing and forcing the comment to be rewritten."""
    params = _sport_params(sport)

    assert params["calibration_min_n"] == 20
    assert PREDICTOR_N_BUCKETS * params["calibration_min_n"] == 80, (
        "4 buckets x 20 is the ruled setting; 200 was the old 10 x 20 that put admission above the "
        "reviewer's bar"
    )
    assert MIN_SETTLED == 100
    # And the second consumer is the same number today, which is what lets the test above be a
    # relation rather than two independent accidents. `test_sports_inversion.py` pins the equality
    # itself; this is here so that moving one of them fails in the file that owns the arithmetic.
    assert HUB_LEDGER_MIN_SETTLED == 100
