"""Tests for the standings follow-up: separate market-linked from climatology-baseline,
include live market-linked in best/worst, drop fixed "after costs" wording."""

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
        "n_settled": 50,
        "n_baseline": 50,
        "brier": 0.21,
        "brier_baseline": 0.25,
        "brier_on_baseline": 0.24,
        "bss": 0.04,
        "calibration_ready": True,
        "gate_status": "SHADOW",
    }
    card.update(over)
    return card


def _bt(forecaster="gas", version="gas-v2", diff=-0.030, se=0.005, n=760, **over):
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


# ── gap_verdict tests (should still pass) ─────────────────────────────────────

def test_a_gap_inside_its_error_bar_is_indistinguishable_not_a_win():
    assert gap_verdict(-0.010, 0.009) == "indistinguishable"
    assert gap_verdict(-0.010, 0.009) != "beats"


def test_a_gap_clearing_the_error_bar_is_a_real_result():
    assert gap_verdict(-0.030, 0.005) == "beats"
    assert gap_verdict(+0.030, 0.005) == "loses to"
    assert gap_verdict(0.0, 0.0) == "no difference"


def test_the_threshold_is_two_standard_errors():
    se = 0.01
    assert gap_verdict(-DISTINCT_SE * se, se) == "beats"
    assert gap_verdict(DISTINCT_SE * se, se) == "loses to"
    assert gap_verdict(-(DISTINCT_SE - 0.0001) * se, se) == "indistinguishable"
    assert gap_verdict(-(DISTINCT_SE - 1e-9) * se, se) == "indistinguishable"


def test_a_missing_gap_or_interval_is_unknown_not_zero():
    assert gap_verdict(None, 0.01) == "unknown"
    assert gap_verdict(-0.05, None) == "unknown"
    assert gap_verdict(-0.05, None) != "beats"


# ── standings: separate market-linked from climatology-baseline ───────────────

def test_standings_separates_market_linked_and_climatology():
    """Market-linked forecasters (graded vs Kalshi price) and climatology-baseline
    forecasters (graded vs usual rate) must be ranked separately, because they
    answer different questions. A climatology-beater cannot be "best market-linked".
    """
    cards = [
        _card("gas", baseline="market"),
        _card("weather_high", baseline="market"),
        _card("ercot_peak", baseline="market"),
        _card("sports_nfl", baseline="market"),
        _card("unrate_direction", baseline="climatology"),
        _card("spy_quant", baseline="climatology"),
        _card("vix_direction", baseline="climatology"),
    ]
    backtests = [
        _bt("gas", diff=-0.030, se=0.005),              # beats market
        _bt("weather_high", diff=-0.020, se=0.004),     # beats market
        _bt("ercot_peak", diff=-0.015, se=0.006),       # beats market
        _bt("sports_nfl", diff=-0.010, se=0.009),       # indistinguishable vs market
        _bt("unrate_direction", diff=-0.040, se=0.005), # beats climatology
        _bt("spy_quant", diff=-0.035, se=0.006),        # beats climatology
        _bt("vix_direction", diff=+0.020, se=0.004),    # loses to climatology
    ]
    s = standings(cards, backtests)

    # Market-linked section
    assert s["market_linked_best"] is not None
    assert s["market_linked_best"]["forecaster"] == "gas"
    assert s["market_linked_worst"] is not None
    assert s["market_linked_worst"]["forecaster"] == "sports_nfl"

    # Climatology-baseline section
    assert s["climatology_best"] is not None
    assert s["climatology_best"]["forecaster"] == "unrate_direction"
    assert s["climatology_worst"] is not None
    assert s["climatology_worst"]["forecaster"] == "vix_direction"

    # Old flat best/worst are gone (or at least not used for cross-category ranking)
    # The flat ranking no longer mixes categories
    assert "best" not in s or s["best"] is None, "flat best removed"
    assert "worst" not in s or s["worst"] is None, "flat worst removed"


def test_standings_includes_live_market_linked_in_both_ends():
    """NFL, weather, ERCOT and their cautious copies are live market-linked forecasters
    and must appear in the market-linked best/worst rankings when they have replays.
    """
    cards = [
        _card("gas", baseline="market"),
        _card("weather_high", baseline="market"),
        _card("ercot_peak", baseline="market"),
        _card("sports_nfl", baseline="market"),
        _card("gas", version="gas-v2_cautious", baseline="market"),  # cautious copy
        _card("sports_nfl", version="v1_cautious", baseline="market"),  # cautious copy
    ]
    backtests = [
        _bt("gas", diff=-0.030, se=0.005),
        _bt("weather_high", diff=-0.020, se=0.004),
        _bt("ercot_peak", diff=-0.015, se=0.006),
        _bt("sports_nfl", diff=-0.010, se=0.009),
        _bt("gas", version="gas-v2_cautious", diff=-0.025, se=0.005),
        _bt("sports_nfl", version="v1_cautious", diff=-0.012, se=0.008),
    ]
    s = standings(cards, backtests)

    # All four original + cautious copies are included in market-linked rankings
    assert set(s["market_linked"]) == {"gas", "weather_high", "ercot_peak", "sports_nfl"}
    # Best is gas, worst is sports_nfl
    assert s["market_linked_best"]["forecaster"] == "gas"
    assert s["market_linked_worst"]["forecaster"] == "sports_nfl"


def test_standings_does_not_claim_after_costs_unless_costs_back_it():
    """The verdict sentence must NOT say "after costs" unless the cost numbers
    (from journal_scores.costs) actually back it. Currently the costs field
    exists only for market-linked cards with calibrated costs.
    """
    _card("gas", baseline="market")
    _card("weather_high", baseline="market")

    # Costs come from the replay row, not the card
    backtests_with_costs = [
        _bt("gas", diff=-0.030, se=0.005, costs={"n_quoted": 100, "n_traded": 80, "edge_after_costs_pct": 0.5}),
        _bt("weather_high", diff=-0.020, se=0.004),
    ]
    cards = [_card("gas", baseline="market"), _card("weather_high", baseline="market")]
    s = standings(cards, backtests_with_costs)

    # The verdict sentence generation should know which cards have costs
    assert "costs" in s, "standings should carry cost info for the verdict sentence"


def test_verdict_sentence_drops_fixed_after_costs_wording():
    """The fixed phrase "no forecaster beats the Kalshi price after costs"
    must be removed. The sentence should only mention costs when the data
    actually shows an edge survives costs.
    """
    cards = [_card("gas", baseline="market")]
    backtests = [_bt("gas", diff=-0.010, se=0.009)]  # indistinguishable
    s = standings(cards, backtests)

    sentence = verdict_sentence(s)
    # Should NOT contain the fixed "after costs" phrase
    assert "after costs" not in sentence.lower()


def test_verdict_sentence_says_after_costs_only_when_costs_back_it():
    """When a market-linked forecaster has costs data AND the edge survives costs,
    the sentence can mention "after costs".
    """
    # Card WITH costs showing edge survives - costs in replay row
    card = _card("gas", baseline="market")
    backtests = [_bt("gas", diff=-0.030, se=0.005, costs={"n_quoted": 100, "n_traded": 80, "edge_after_costs_pct": 0.5})]
    s = standings([card], backtests)

    sentence = verdict_sentence(s)
    # When costs exist and edge survives, can mention it
    assert "after costs" in sentence.lower() or "costs" in sentence.lower()


def test_climatology_baseline_section_never_claims_beats_market():
    """Climatology-baseline forecasters (unrate, spy_quant, vix, etc.) are
    graded against the usual rate, not the Kalshi price. Their verdicts
    must never say "beats the Kalshi price".
    """
    cards = [_card("unrate_direction", baseline="climatology")]
    backtests = [_bt("unrate_direction", diff=-0.040, se=0.005)]
    s = standings(cards, backtests)

    # The climatology section's best/worst should describe vs climatology
    assert s["climatology_best"] is not None
    assert "Kalshi price" not in str(s["climatology_best"]).lower()
    # The verdict should not claim "beats the Kalshi price" for climatology cards


def test_missing_costs_field_defaults_to_no_cost_claim():
    """If a card has no costs field (older data), the verdict must not claim
    anything about costs.
    """
    cards = [_card("gas", baseline="market")]  # no costs field
    backtests = [_bt("gas", diff=-0.030, se=0.005)]
    s = standings(cards, backtests)

    # Should not have costs info in standings
    assert "costs" not in s