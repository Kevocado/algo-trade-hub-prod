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

`n_buckets` is chosen by the predictor, not the hub, so the coupling is real and worth pinning: if a
predictor changes its bucket count, this test's arithmetic changes with it, which is the point. The
value below was read from both live feeds on 2026-09-27 and is the one thing here that is not derived
from this repository.

The coherence test is `xfail(strict=True)`: it fails today by design, and when someone fixes the
thresholds it will XPASS, which under `strict` is itself a failure telling them to delete this marker.
Without `strict` the fix would silently leave a stale xfail behind and the defect would be forgotten
again.
"""
import pytest
import yaml

from tradehub.sports.scorecard import MIN_SETTLED

ENGINES_YAML = "tradehub/config/engines.yaml"

# Read from `/api/kalshi-feed` on both predictors, 2026-09-27. The hub does not choose this.
PREDICTOR_N_BUCKETS = 10


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
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known contradiction, found 2026-09-27: 10 predictor buckets x calibration_min_n 20 = 200 "
        "settled required, against the reviewer's MIN_SETTLED of 100. Fixing the thresholds makes this "
        "XPASS, which under strict=True is a failure telling the fixer to delete this marker."
    ),
)
def test_the_gate_needs_no_more_evidence_than_the_reviewer_does(sport):
    """The invariant: admitting an edge must not require more settled contracts than judging one.

    xfail(strict=True) -- see the module docstring. Delete this marker when it passes.
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
def test_the_current_gate_arithmetic_is_what_this_file_claims(sport):
    """Pins the two numbers the docstring quotes, so a config change cannot quietly invalidate the
    reasoning above without this failing and forcing the comment to be rewritten."""
    params = _sport_params(sport)

    assert params["calibration_min_n"] == 20
    assert PREDICTOR_N_BUCKETS * params["calibration_min_n"] == 200
    assert MIN_SETTLED == 100
