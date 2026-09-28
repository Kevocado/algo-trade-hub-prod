"""The oracle bound's contracts.

The point-in-time causality test is the one that matters: if the bound can see an outcome
that had not happened when the prediction was made, it will report a badly calibrated
model as calibrated, and the whole labor question gets answered backwards.
"""

from datetime import UTC, datetime, timedelta

from tradehub.backtest.metrics import prediction_row
from tradehub.backtest.oracle import (
    clustered_gap,
    confidence_of,
    oracle_bound,
    oracle_brier,
    pit_probabilities,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _row(prob, result, index, ticker=None, mid=None, weight=None, month=None):
    row = prediction_row(prob, mid, result, market_ticker=ticker or f"T{index}")
    row["decided_at"] = T0 + timedelta(days=index)
    row["month"] = month if month is not None else f"2026-{1 + index // 28:02d}"
    if weight is not None:
        row["weight"] = weight
    return row


# ── the calibration-identity properties ───────────────────────────────────────

def test_confidence_is_side_mirrored():
    assert confidence_of(0.85) == 0.85
    assert confidence_of(0.15) == 0.85
    assert confidence_of(0.5) == 0.5


def test_a_calibrated_model_keeps_its_own_brier_under_the_full_sample_oracle():
    """If each bucket's realized hit rate already equals its predicted rate, substitution is a no-op."""
    rows = [_row(0.8, "yes" if i < 8 else "no", i) for i in range(10)]
    bound = oracle_bound(rows)
    assert abs(bound["brier_ours"] - bound["brier_oracle_full_sample"]) < 1e-12


def test_the_full_sample_oracle_is_never_worse_than_the_raw_model():
    """Substituting a bucket's own mean outcome is the in-sample minimiser, so it cannot lose."""
    import random

    rng = random.Random(7)
    rows = [_row(round(rng.uniform(0.5, 0.99), 2), "yes" if rng.random() < 0.7 else "no", i)
            for i in range(400)]
    bound = oracle_bound(rows)
    assert bound["brier_oracle_full_sample"] <= bound["brier_ours"] + 1e-12


def test_a_low_probability_row_is_not_flipped_onto_the_wrong_side():
    """A 0.15 forecast favours NO. The bucket's observed rate is a NO-rate, so the
    substitution must be 1 - rate. Substituting the rate directly would score a model that
    ranks perfectly as though it were random."""
    rows = [_row(0.15, "no", i) for i in range(10)]
    bound = oracle_bound(rows)
    assert bound["brier_oracle_full_sample"] < bound["brier_ours"]


# ── the point-in-time guarantee ───────────────────────────────────────────────

def test_pit_substitution_cannot_see_a_later_outcome():
    """Flip every outcome from index 50 on; the substituted probabilities of rows 0..49
    must not move by a single float. This is the no-lookahead claim, tested against the
    real function rather than a copy of it."""
    import random

    rng = random.Random(11)
    base = [_row(round(rng.uniform(0.5, 0.99), 2), "yes" if rng.random() < 0.6 else "no", i)
            for i in range(120)]

    flipped = []
    for row in base:
        copy = dict(row)
        if copy["decided_at"] >= T0 + timedelta(days=50):
            copy["result"] = "no" if copy["result"] == "yes" else "yes"
        flipped.append(copy)

    before, _ = pit_probabilities(base)
    after, _ = pit_probabilities(flipped)
    for i in range(50):
        assert abs(before[i] - after[i]) < 1e-12, f"row {i} moved when only later outcomes changed"


def test_pit_uses_the_row_before_it_not_itself():
    """A single mispredicted row must not be calibrated by its own outcome."""
    row = _row(0.8, "no", 0)
    assert pit_probabilities([row])[0] == [0.8]


def test_pit_first_row_of_each_bucket_scores_as_the_model():
    rows = [_row(0.8, "yes", 0), _row(0.82, "no", 1)]
    scored, no_prior = pit_probabilities(rows)
    assert no_prior == 1
    assert abs(scored[0] - 0.8) < 1e-12


def test_pit_reports_how_many_rows_it_could_not_calibrate():
    # 50-60 bucket needs confidence in [0.5, 0.6); the first row of each has no prior.
    rows = [_row(0.55, "yes", 0), _row(0.9, "yes", 1), _row(0.91, "no", 2)]
    bound = oracle_bound(rows)
    assert bound["pit_n_no_prior"] == 2


def test_shrinkage_pulls_a_thin_bucket_back_toward_the_model():
    """One prior observation must not be allowed to swing a forecast from 0.8 to 0.0."""
    rows = [_row(0.8, "yes", 0)] + [_row(0.8, "no", i) for i in range(1, 4)]
    shrunk, _ = pit_probabilities(rows, shrink=5.0)
    assert 0.6 < shrunk[-1] < 0.8, f"thin-bucket rate {shrunk[-1]} is not shrunk toward the prior"
    unshrunk, _ = pit_probabilities(rows, shrink=0.0)
    assert unshrunk[-1] == 1 / 3  # the raw thin-bucket rate, which is why it needs shrinking


# ── weighting, counts, verdict ────────────────────────────────────────────────

def test_contract_weights_change_the_mean():
    rows = [_row(0.9, "yes", 0, weight=9.0), _row(0.1, "yes", 1, weight=1.0)]
    unweighted = oracle_bound([{k: v for k, v in r.items() if k != "weight"} for r in rows])
    weighted = oracle_bound(rows)
    assert weighted["brier_ours"] < unweighted["brier_ours"]  # the winning row counts 9x


def test_counts_report_contracts_and_months_separately_from_rows():
    rows = [_row(0.8, "yes", i, ticker="A" if i < 3 else "B") for i in range(5)]
    bound = oracle_bound(rows)
    assert bound["n_rows"] == 5
    assert bound["n_contracts"] == 2
    assert bound["n_months"] == 1  # 5 consecutive days, one reference month


def test_a_ladder_month_is_reported_as_one_month_not_eight_contracts():
    """Eight strikes on one payroll print: the row count overstates the independent sample."""
    rows = [_row(0.8, "yes", i, ticker=f"26SEP-T{i}") for i in range(8)]
    bound = oracle_bound(rows)
    assert (bound["n_rows"], bound["n_contracts"], bound["n_months"]) == (8, 8, 1)


def test_verdict_is_discrimination_when_the_oracle_cannot_reach_the_market():
    """A flat model against a market that discriminates.

    Every prediction is 0.8, so the model has no resolution at all: its bucket rate is the
    base rate and the best it can do is predict that. The market resolves each month. No
    recalibration of a flat model can invent the signal the market already has.
    """
    rows = [_row(0.8, "yes" if i % 4 else "no", i, mid=0.9 if i % 4 else 0.1,
                 month=f"m{i // 4:02d}") for i in range(40)]
    bound = oracle_bound(rows)
    assert bound["verdict_full_sample"] == "discrimination_not_calibration"
    assert bound["brier_market"] == 0.01  # the market is right every time
    assert bound["brier_oracle_full_sample"] == 0.1875  # the model can only reach the base rate


def test_verdict_is_calibration_when_a_well_pushed_recalibration_reaches_the_market():
    """A model that says 0.9 and is right 50% of the time, against a market at 0.55. A
    perfect map lands on 0.5, which beats 0.55, so the failure really is confidence."""
    rows = [_row(0.9, "yes" if i % 2 else "no", i, mid=0.55, month=f"m{i // 2:02d}")
            for i in range(20)]
    bound = oracle_bound(rows, shrink=0.0)
    assert bound["verdict_full_sample"] == "calibration_can_close_the_gap"
    assert bound["brier_oracle_full_sample"] < bound["brier_market"] < bound["brier_ours"]


def test_market_brier_reference_is_reported_next_to_the_measured_one():
    rows = [_row(0.8, "yes", i, mid=0.7) for i in range(10)]
    bound = oracle_bound(rows, market_brier=0.1659)
    assert bound["market_brier_reference"] == 0.1659
    assert bound["brier_market"] == 0.09
    assert bound["ratio_oracle_pit_vs_reference"] == round(bound["brier_oracle_pit"] / 0.1659, 4)


def test_bucket_table_reports_the_market_alongside_the_model():
    rows = [_row(0.8, "yes", i, mid=0.7) for i in range(10)]
    table = oracle_bound(rows)["buckets"]
    assert table[0]["bucket"] == "80-90"
    assert table[0]["predicted"] == 0.8
    assert table[0]["observed"] == 1.0
    assert table[0]["market_predicted"] == 0.7
    assert table[0]["market_observed"] == 1.0


def test_a_bucket_with_no_rows_is_omitted_rather_than_reported_as_zero():
    rows = [_row(0.8, "yes", i) for i in range(4)]
    assert [b["bucket"] for b in oracle_bound(rows)["buckets"]] == ["80-90"]


def test_the_market_gets_its_own_calibration_curve_bucketed_on_its_own_confidence():
    """The in-bucket market columns are conditional on the model's confidence, so a claim
    about who is miscalibrated needs a second table bucketed on the market itself."""
    rows = ([_row(0.8, "yes", i, mid=0.95) for i in range(5)]
            + [_row(0.8, "no", 5 + i, mid=0.55) for i in range(5)])
    bound = oracle_bound(rows)
    # everything sits in the model's 80-90 bucket...
    assert [b["bucket"] for b in bound["buckets"]] == ["80-90"]
    # ...but the market splits across two of its own, at very different accuracy
    market = {b["bucket"]: b for b in bound["market_buckets"]}
    assert set(market) == {"50-60", "90-100"}
    assert market["90-100"]["observed"] == 1.0
    assert market["50-60"]["observed"] == 0.0


def test_empty_rows_do_not_divide_by_zero():
    assert oracle_brier([], variant="pit")["brier"] is None
    assert oracle_brier([], variant="full")["brier"] is None


def test_unknown_variant_is_rejected():
    import pytest

    with pytest.raises(ValueError, match="variant"):
        oracle_brier([_row(0.8, "yes", 0)], variant="half")


# ── the two verdicts, and how much of the gap calibration actually buys ────────

def _ladder_rows(n_months, per_month=8, our=0.8, mid=0.7, hit=0.5, market_by_outcome=None):
    """A synthetic ladder: `per_month` strikes per month, all sharing one outcome driver.

    One outcome per month, which is the real structure of a payroll ladder -- eight strikes
    on one print, not eight independent events. `market_by_outcome` gives a market that
    resolves the individual month ({True: mid_if_won, False: mid_if_lost}); without it the
    market is flat and carries no per-event information, only the base rate.
    """
    rows = []
    for m in range(n_months):
        won = m < round(n_months * hit)
        month = f"m{m:03d}"
        quote = market_by_outcome[won] if market_by_outcome else mid
        for k in range(per_month):
            rows.append(_row(our, "yes" if won else "no", m * per_month + k,
                             ticker=f"M{m}-T{k}", mid=quote, month=month))
    return rows


def test_a_flat_model_against_a_resolving_market_fails_the_bound():
    """The decisive shape: a good base rate, no per-event signal, and a market that resolves
    each month. Perfect calibration can only move the model to the base rate, which is worse
    than what the market achieves, so no recalibration can close the gap."""
    rows = _ladder_rows(40, our=0.8, hit=0.8, market_by_outcome={True: 0.95, False: 0.40})
    bound = oracle_bound(rows)
    # base rate 0.8: model 0.8*0.04 + 0.2*0.64 = 0.16, and no better than that
    assert bound["brier_oracle_full_sample"] == 0.16
    # market 0.8*0.05^2 + 0.2*0.40^2 = 0.034, because it resolves each month
    assert bound["brier_market"] == 0.034
    assert bound["verdict_full_sample"] == "discrimination_not_calibration"
    assert bound["verdict_pit"] == "discrimination_not_calibration"


def test_a_miscalibrated_model_can_still_pass_the_bound():
    """Both the model and the market are overconfident about a 70% base rate. The model
    alone is not behind the market, and recalibrating it lands on the truth -- so the
    failure here really is confidence, and the bound says so."""
    rows = _ladder_rows(40, our=0.9, mid=0.9, hit=0.7)
    bound = oracle_bound(rows)
    assert bound["brier_ours"] == bound["brier_market"]  # identically overconfident
    assert bound["verdict_full_sample"] == "calibration_can_close_the_gap"
    assert bound["brier_oracle_full_sample"] == 0.21
    assert bound["brier_market"] == 0.25
    # the share exceeds 1.0: a perfect map lands past the market. Reporting that beats clipping.
    assert bound["gap_closed_by_perfect_calibration"] is None  # raw gap is 0, so no share exists


def test_perfect_calibration_closes_the_gap_it_is_the_cause_of():
    """Over-confident model, market at the true rate: the ceiling reaches the market."""
    rows = _ladder_rows(40, our=0.9, mid=0.7, hit=0.7)
    bound = oracle_bound(rows)
    assert bound["brier_ours"] > bound["brier_market"]
    assert bound["brier_oracle_full_sample"] == bound["brier_market"]
    assert bound["verdict_full_sample"] == "discrimination_not_calibration"  # ties, does not beat


def test_clustered_gap_resamples_whole_ladder_months():
    """The interval must rest on the month count, not the row count."""
    rows = _ladder_rows(41, per_month=8, our=0.8, mid=0.7, hit=0.5)
    gap = clustered_gap(rows)
    assert gap["n_groups"] == 41
    assert gap["n_pairs"] == 328
    assert gap["group_key"] == "month"
    # 20 of 41 months hit: ours 0.8*0.04 + 0.5122*0.64 = 0.3473, market 0.7*0.09 + 0.5122*0.49 = 0.2949
    assert gap["gap"] == 0.05244


def test_clustered_interval_is_wider_than_a_row_level_bootstrap():
    """Rows inside a ladder month repeat one outcome, so a row-level resample treats 328
    rows as 328 events and reports an interval about sqrt(8) too narrow. The clustered one
    is the honest width, and it is the one a verdict should rest on."""
    import random

    rows = _ladder_rows(41, per_month=8, our=0.8, mid=0.7, hit=0.5)
    diffs = []
    for row in rows:
        ours = (0.8 - (1 if row["result"] == "yes" else 0)) ** 2
        theirs = (0.7 - (1 if row["result"] == "yes" else 0)) ** 2
        diffs.append(ours - theirs)
    rng = random.Random(3)
    row_level = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(2000))
    row_width = row_level[1900] - row_level[99]
    gap = clustered_gap(rows)
    clustered_width = gap["ci95"][1] - gap["ci95"][0]
    assert clustered_width > row_width * 2, (clustered_width, row_width)


def test_clustered_gap_ignores_rows_with_no_market_quote():
    rows = _ladder_rows(10) + [_row(0.8, "yes", 999, ticker="NOQUOTE", month="mZZZ")]
    assert clustered_gap(rows)["n_pairs"] == 80


def test_clustered_gap_on_an_empty_or_unpaired_sample_is_none_not_an_error():
    assert clustered_gap([])["gap"] is None
    assert clustered_gap([_row(0.8, "yes", 0)])["gap"] is None
