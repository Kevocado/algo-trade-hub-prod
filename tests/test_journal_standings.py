"""Tests for the front page's "what we found": best/worst forecaster, each with its own interval.

Pure, so every rule is testable without a database. The rules that matter here are honesty rules,
because this is the first thing a reader lands on:

  * A gap inside its own error bar is NOT a result. `|brier_diff| < 2 * brier_diff_se` is reported as
    indistinguishable, never as "beats" or "loses to".
  * No interval is ever put on `bss`. It is a ratio of two means; the migration that added the error
    bar says so explicitly and this module does not go around it.
  * A missing figure is None, never 0.0. A card written before migration 017 carries no error bar, and
    "we did not measure an interval" is not "we measured zero".
  * The verdict sentence is assembled from the numbers. No branch of it is a fixed conclusion.
"""

from __future__ import annotations

from tradehub.journal.standings import (
    DISTINCT_SE,
    gap_verdict,
    standings,
    verdict_sentence,
)


def _card(forecaster="gas", version="gas-v2", baseline="market", **over):
    card = {
        "forecaster": forecaster,
        "forecaster_version": version,
        "cadence": "daily",
        "baseline": baseline,
        "n_targets": 100,
        "n_settled": 90,
        "n_baseline": 80,
        "brier": 0.21,
        "brier_baseline": 0.25,
        "brier_on_baseline": 0.24,
        "bss": 0.04,
        "calibration_ready": True,
        "gate_status": "SHADOW",
    }
    card.update(over)
    return card


def _bt(forecaster="gas", version="gas-v2", diff=-0.010, se=0.009, n=760, **over):
    row = {
        "forecaster": forecaster,
        "forecaster_version": version,
        "n": n,
        "brier": 0.21,
        "brier_baseline": 0.22,
        "brier_diff": diff,
        "brier_diff_se": se,
        "bss": 0.045,
        "date_from": "2026-06-01",
        "date_to": "2026-09-20",
    }
    row.update(over)
    return row


# ── gap_verdict: the one rule the whole page rests on ─────────────────────────


def test_a_gap_inside_its_error_bar_is_indistinguishable_not_a_win():
    # The audit that motivated migration 017: the best daily model was 1.1 SE from zero.
    assert gap_verdict(-0.010, 0.009) == "indistinguishable"
    assert gap_verdict(-0.010, 0.009) != "beats"


def test_a_gap_clearing_the_error_bar_is_a_real_result():
    assert gap_verdict(-0.030, 0.005) == "beats"       # negative gap = lower squared error = better
    assert gap_verdict(+0.030, 0.005) == "loses to"
    assert gap_verdict(0.0, 0.0) == "no difference"     # zero gap with zero spread: equal by definition


def test_the_threshold_is_two_standard_errors():
    se = 0.01  # the threshold is DISTINCT_SE * se, so the boundary sits at -0.02
    # "Clears two standard errors" includes exactly two: at the threshold the gap IS a result.
    assert gap_verdict(-DISTINCT_SE * se, se) == "beats"
    assert gap_verdict(DISTINCT_SE * se, se) == "loses to"
    # A hair inside it is not, and the boundary is on the strict side of the comparison.
    assert gap_verdict(-(DISTINCT_SE - 0.0001) * se, se) == "indistinguishable"
    assert gap_verdict(-(DISTINCT_SE - 1e-9) * se, se) == "indistinguishable"


def test_a_missing_gap_or_interval_is_unknown_not_zero():
    assert gap_verdict(None, 0.01) == "unknown"
    assert gap_verdict(-0.05, None) == "unknown"
    # The killer: without this, a missing error bar compares as a zero-width bar and every gap "beats".
    assert gap_verdict(-0.05, None) != "beats"


# ── standings: market-linked and climatology leaderboards ─────────────────────


def test_standings_ranks_market_linked_by_gap_and_reports_both_ends():
    rows = standings(
        [_card("gas"), _card("weather_high")],
        [_bt("gas", diff=-0.030, se=0.005), _bt("weather_high", diff=+0.020, se=0.004)],
    )
    assert rows["market_linked_best"]["forecaster"] == "gas"
    assert rows["market_linked_best"]["gap"] == -0.030
    assert rows["market_linked_best"]["se"] == 0.005
    assert rows["market_linked_best"]["verdict"] == "beats"
    assert rows["market_linked_worst"]["forecaster"] == "weather_high"
    assert rows["market_linked_worst"]["verdict"] == "loses to"
    assert rows["market_linked_worst"]["n"] == 760


def test_standings_reports_a_market_forecaster_with_no_error_bar_as_unknown():
    rows = standings([_card("gas")], [_bt("gas", diff=-0.030, se=None)])
    assert rows["market_linked_best"]["se"] is None
    assert rows["market_linked_best"]["verdict"] == "unknown"
    # And it is still the best on the number we do have, rather than being dropped from the page.
    assert rows["market_linked_best"]["forecaster"] == "gas"


def test_standings_with_nothing_measured_returns_none_not_a_zero():
    rows = standings([], [])
    assert rows["market_linked_best"] is None
    assert rows["market_linked_worst"] is None
    assert rows["n_settled"] == 0
    assert rows["n_replayed"] == 0


def test_a_market_forecaster_without_a_replay_row_is_not_ranked():
    # One model has no replay. It must not appear as a gap of 0.0 and win the "best" slot.
    rows = standings([_card("gas"), _card("weather_high")], [_bt("gas", diff=-0.030, se=0.005)])
    assert rows["market_linked_best"]["forecaster"] == "gas"
    assert rows["market_linked_worst"] is None  # only one has a replay


def test_standings_counts_settled_targets_from_the_cards_not_the_replays():
    rows = standings([_card("gas", n_settled=90), _card("weather_high", n_settled=40)], [])
    assert rows["n_settled"] == 130


def test_only_market_linked_baselines_can_support_a_beating_the_market_claim():
    rows = standings(
        [_card("gas", baseline="market"), _card("climatology_model", baseline="climatology")],
        [_bt("gas", diff=-0.030, se=0.005), _bt("climatology_model", diff=-0.030, se=0.005)],
    )
    # Both are listed (they were measured), but only the market-linked one is pooled as a market claim.
    assert rows["market_linked"] == ["gas"]
    assert rows["market_linked_best"]["baseline"] == "market"
    # Climatology model is in the climatology section, not market-linked
    assert rows["climatology_best"]["forecaster"] == "climatology_model"


def test_climatology_section_ranks_separately_and_reports_vs_climatology():
    rows = standings(
        [_card("unrate_direction", baseline="climatology"), _card("quits_direction", baseline="climatology")],
        [_bt("unrate_direction", diff=-0.040, se=0.005), _bt("quits_direction", diff=+0.020, se=0.004)],
    )
    assert rows["climatology_best"]["forecaster"] == "unrate_direction"
    assert rows["climatology_best"]["verdict"] == "beats"
    assert rows["climatology_worst"]["forecaster"] == "quits_direction"
    assert rows["climatology_worst"]["verdict"] == "loses to"
    # Market-linked section is empty
    assert rows["market_linked_best"] is None


# ── the verdict sentence: assembled from the numbers, never typed ──────────────


def test_no_evidence_yields_a_sentence_that_says_so():
    s = verdict_sentence(standings([], []))
    assert "no" in s.lower()
    assert "settled" in s.lower()
    assert "0" not in s  # a bare 0 would read as a measurement


def test_an_indistinguishable_result_says_so_rather_than_claiming_a_win():
    rows = standings([_card("gas")], [_bt("gas", diff=-0.010, se=0.009)])
    s = verdict_sentence(rows)
    assert "noise" in s.lower() or "indistinguishable" in s.lower()
    # Should not claim "beats the Kalshi price" (the market claim)
    assert "beats the kalshi price" not in s.lower()


def test_a_real_result_names_the_number_and_the_interval_it_was_measured_on():
    rows = standings([_card("gas", n_settled=1982)], [_bt("gas", diff=-0.030, se=0.005)])
    s = verdict_sentence(rows)
    assert "1982" in s
    assert "0.005" in s  # the interval travels with the number
    assert "beat" in s.lower()


def test_the_sentence_never_claims_an_edge_it_did_not_measure():
    # A replay with no error bar: we know the sign, not whether it is real.
    rows = standings([_card("gas")], [_bt("gas", diff=-0.030, se=None)])
    s = verdict_sentence(rows)
    assert "beat" not in s.lower()
    assert "interval" in s.lower() or "noise" in s.lower()


def test_the_sentence_is_short_enough_to_be_a_lede():
    for cards, bts in (
        ([_card("gas")], [_bt("gas", diff=-0.030, se=0.005)]),
        ([_card("gas")], [_bt("gas", diff=-0.010, se=0.009)]),
        ([_card("gas")], [_bt("gas", diff=-0.030, se=None)]),
        ([], []),
    ):
        assert len(verdict_sentence(standings(cards, bts)).split()) <= 45


def test_verdict_sentence_mentions_after_costs_only_when_costs_back_it():
    """When a market-linked forecaster has costs data AND the edge survives costs,
    the sentence mentions "after costs". Without costs data, it must not claim it.
    """
    # With costs backing the edge
    rows = standings(
        [_card("gas")],
        [_bt("gas", diff=-0.030, se=0.005, costs={"n_quoted": 100, "n_traded": 80, "edge_after_costs_pct": 0.5})],
    )
    s = verdict_sentence(rows)
    assert "after costs" in s.lower()

    # Without costs - should NOT say "after costs"
    rows = standings([_card("gas")], [_bt("gas", diff=-0.030, se=0.005)])
    s = verdict_sentence(rows)
    assert "after costs" not in s.lower()


def test_climatology_result_says_vs_climatology_not_market():
    rows = standings([_card("unrate_direction", baseline="climatology")], [_bt("unrate_direction", diff=-0.040, se=0.005)])
    s = verdict_sentence(rows)
    assert "climatology" in s.lower()
    assert "Kalshi price" not in s.lower()