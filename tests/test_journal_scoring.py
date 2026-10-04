from datetime import UTC, datetime

import pytest

from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.scoring import MIN_BUCKET_TARGETS, murphy, reliability, score, settled_pairs


def _row(target, prob, market=None, rebuilt=False, quote=None):
    row = {"target": target, "probability": prob, "market_prob": market, "rebuilt": rebuilt}
    if quote is not None:
        row["payload"] = {"yes_bid": quote[0], "yes_ask": quote[1]}
    return row


def test_contract_rejects_naive_times_and_bad_values():
    with pytest.raises(ValueError, match="timezone-aware"):
        CalendarEntry("t", "fam", "daily", datetime(2026, 10, 1, 8))  # noqa: DTZ001
    with pytest.raises(ValueError, match="cadence"):
        CalendarEntry("t", "fam", "hourly", datetime(2026, 10, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="probability"):
        Forecast("f", "v1", "t", 1.2)
    with pytest.raises(ValueError, match="outcome"):
        Settlement("t", 2, "src")


def test_source_hash_is_stable_and_input_sensitive():
    a = Forecast("f", "v1", "t", 0.6, payload={"x": 1, "y": 2})
    b = Forecast("f", "v1", "t", 0.6, payload={"y": 2, "x": 1})
    c = Forecast("f", "v1", "t", 0.6, payload={"x": 1, "y": 3})
    assert a.source_hash == b.source_hash != c.source_hash


def test_rebuilt_and_unsettled_rows_are_never_counted():
    rows = [_row("a", 0.9), _row("b", 0.9, rebuilt=True), _row("c", 0.9)]
    pairs = settled_pairs(rows, {"a": 1, "b": 1})
    assert [p["target"] for p in pairs] == ["a"]
    card = score(rows, {"a": 1, "b": 1}, {}, "daily")
    assert card["n_targets"] == 2 and card["n_settled"] == 1


def test_bss_uses_market_where_it_exists_else_climatology():
    rows = [_row("m", 0.8, market=0.6), _row("c", 0.7)]
    cal = {"c": {"climatology_prob": 0.5}}
    card = score(rows, {"m": 1, "c": 1}, cal, "daily")
    ours = ((0.8 - 1) ** 2 + (0.7 - 1) ** 2) / 2
    base = ((0.6 - 1) ** 2 + (0.5 - 1) ** 2) / 2
    assert card["bss"] == pytest.approx(1 - ours / base, abs=1e-6)
    assert card["baseline"] == "market"


def test_a_target_with_no_baseline_is_scored_but_excluded_from_bss():
    card = score([_row("x", 0.9)], {"x": 1}, {}, "daily")
    assert card["brier"] == pytest.approx(0.01)
    assert card["bss"] is None and card["baseline"] == "none"
    assert "no baseline" in " ".join(card["gate_reasons"])


def test_gate_counts_monthly_at_50_and_daily_at_200():
    rows = [_row(f"t{i}", 0.9, market=0.6) for i in range(60)]
    settle = {f"t{i}": 1 for i in range(60)}
    monthly = score(rows, settle, {}, "monthly")
    daily = score(rows, settle, {}, "daily")
    assert not any("settled targets" in r for r in monthly["gate_reasons"])
    assert any("need 200" in r for r in daily["gate_reasons"])


def test_promotion_needs_positive_skill_and_calibrated_buckets():
    good = [_row(f"g{i}", 0.95, market=0.6, quote=(0.58, 0.62)) for i in range(MIN_BUCKET_TARGETS * 3)]
    card = score(good, {r["target"]: 1 for r in good}, {}, "monthly")
    assert card["calibration_ready"] and card["bss"] > 0
    assert card["gate_status"] == "PROMOTED", card["gate_reasons"]
    worse = [_row(f"w{i}", 0.6, market=0.95) for i in range(60)]
    card = score(worse, {r["target"]: 1 for r in worse}, {}, "monthly")
    assert card["gate_status"] == "SHADOW" and any("not positive" in r for r in card["gate_reasons"])


def test_reliability_is_confidence_space_and_murphy_adds_up():
    pairs = [{"probability": 0.3, "outcome": 0}, {"probability": 0.7, "outcome": 1},
             {"probability": 0.7, "outcome": 0}, {"probability": 0.2, "outcome": 0}]
    buckets = {b["bucket"]: b for b in reliability(pairs)}
    assert buckets["70-80"]["n"] == 3  # 0.3 and both 0.7s
    m = murphy(pairs)
    brier = sum((p["probability"] - p["outcome"]) ** 2 for p in pairs) / len(pairs)
    # Binned Murphy is exact when every bin holds a single forecast value, as here.
    assert m["reliability"] - m["resolution"] + m["uncertainty"] == pytest.approx(brier, abs=1e-6)


def test_a_market_forecaster_with_no_frozen_quotes_cannot_promote():
    rows = [_row(f"g{i}", 0.95, market=0.6) for i in range(MIN_BUCKET_TARGETS * 3)]
    card = score(rows, {r["target"]: 1 for r in rows}, {}, "monthly")
    assert card["bss"] > 0 and card["gate_status"] == "SHADOW"
    assert any("no frozen quotes" in r for r in card["gate_reasons"])
    assert card["costs"]["n_quoted"] == 0


def test_skill_that_fees_and_spread_eat_does_not_promote():
    # Forecast 0.75 against a 0.60 mid, with a wide 50/70 book. At a 70% hit rate the Brier skill vs
    # the market is positive (it beats 0.60 whenever the hit rate is above 0.675), but buying at the
    # 70c ask plus a 2c fee needs a 72% hit rate to break even: the edge exists only before costs.
    rows = [_row(f"t{i}", 0.75, market=0.60, quote=(0.50, 0.70)) for i in range(60)]
    settle = {r["target"]: int(i < 42) for i, r in enumerate(rows)}
    card = score(rows, settle, {}, "monthly")
    assert card["bss"] > 0 and card["costs"]["n_traded"] == 60
    assert card["costs"]["net_pnl_cents"] == pytest.approx(42 * (30 - 2) + 18 * (-70 - 2))  # -100
    assert card["gate_status"] == "SHADOW" and any("after fees and spread" in r for r in card["gate_reasons"])


def test_climatology_baselines_carry_no_cost_block():
    rows = [_row(f"c{i}", 0.9) for i in range(5)]
    card = score(rows, {r["target"]: 1 for r in rows}, {r["target"]: {"climatology_prob": 0.5} for r in rows}, "daily")
    assert card["baseline"] == "climatology" and card["costs"] == {}


def test_the_headline_freeze_count_is_gated_on_calibration_too_not_just_the_settled_one():
    """Specs audit, against the v2 journal spec.

    Spec §10 display gate: "any forecaster appears from its first frozen row; headline stats aggregate
    ONLY post-calibration forecasters." `headline()` gated `settled_calibrated` but not the frozen
    count, so a forecaster with 5 locked-in forecasts and zero settled evidence still contributed 5
    to a headline stat. Both numbers now come from the same `calibrated` slice, so they cannot drift.
    """
    from tradehub.journal.scoring import headline

    ready = {"forecaster": "a", "calibration_ready": True, "n_settled": 30, "n_targets": 40,
             "gate_status": "SHADOW"}
    provisional = {"forecaster": "b", "calibration_ready": False, "n_settled": 0, "n_targets": 5,
                   "gate_status": "SHADOW"}

    h = headline([ready, provisional])
    assert h["frozen_calibrated"] == 40, (
        "an uncalibrated forecaster's frozen targets reached a headline stat")
    assert h["settled_calibrated"] == 30
    # The card still APPEARS in the list -- only the aggregate is gated.
    assert h["forecasters"] == 2


def test_market_skill_pools_market_linked_cards_by_their_own_matched_counts():
    """Spec §1/§10/§11 all promise a "Brier skill vs market" headline. §10: it "aggregates
    market-linked targets only".

    Pooling is weighted by each card's own `n_baseline`, because a card with 200 matched targets and a
    card with 3 do not carry equal evidence. Weighting by card COUNT instead -- the obvious mistake --
    gives a very different answer, so the fixture's two cards have deliberately unequal weights. Both
    cards are fully matched here (`n_settled == n_baseline`), so this test pins the WEIGHTS and nothing
    else; the all-targets-vs-matched mismatch is pinned separately, below.
    """
    from tradehub.journal.scoring import market_skill

    big = {"forecaster": "sports_nfl", "calibration_ready": True, "n_settled": 300, "n_baseline": 300,
           "brier": 0.10, "brier_on_baseline": 0.10, "brier_baseline": 0.20,
           "baseline": "market", "gate_status": "SHADOW"}
    small = {"forecaster": "cpi_nowcast", "calibration_ready": True, "n_settled": 100, "n_baseline": 100,
             "brier": 0.30, "brier_on_baseline": 0.30, "brier_baseline": 0.20,
             "baseline": "market", "gate_status": "SHADOW"}

    out = market_skill([big, small])
    assert out is not None
    assert out["n"] == 400
    # count-weighting would give (0.10 + 0.30)/2 = 0.20; count-weighting is wrong and must not pass.
    assert out["brier"] == pytest.approx(0.15, abs=1e-9)
    assert out["brier_baseline"] == pytest.approx(0.20, abs=1e-9)
    assert out["bss"] == pytest.approx(0.25, abs=1e-9)


def test_market_skill_ignores_non_market_cards_and_non_evidence_cards():
    """Climatology-graded forecasters have no market to be better than, and a cautious copy shares its
    model's target set -- both would corrupt the pool. Spec §10: "market-linked targets only"."""
    from tradehub.journal.scoring import market_skill

    real = {"forecaster": "sports_nfl", "calibration_ready": True, "n_settled": 300, "n_baseline": 300,
            "brier": 0.10, "brier_on_baseline": 0.10, "brier_baseline": 0.20,
            "baseline": "market", "gate_status": "SHADOW"}
    climatology = {"forecaster": "housing_direction", "calibration_ready": True, "n_settled": 900,
                   "n_baseline": 900, "brier": 0.40, "brier_on_baseline": 0.40, "brier_baseline": 0.40,
                   "baseline": "climatology", "gate_status": "SHADOW"}
    cautious = {"forecaster": "sports_nfl_cautious", "calibration_ready": True, "n_settled": 300,
                "n_baseline": 300, "brier": 0.05, "brier_on_baseline": 0.05, "brier_baseline": 0.20,
                "baseline": "market", "gate_status": "SHADOW"}
    uncalibrated = {"forecaster": "sports_cfb", "calibration_ready": False, "n_settled": 800,
                    "n_baseline": 800, "brier": 0.01, "brier_on_baseline": 0.01, "brier_baseline": 0.20,
                    "baseline": "market", "gate_status": "SHADOW"}

    out = market_skill([real, climatology, cautious, uncalibrated])
    assert out is not None and out["n"] == 300, out
    assert out["brier"] == pytest.approx(0.10, abs=1e-9)
    assert out["bss"] == pytest.approx(0.50, abs=1e-9)


def test_market_skill_is_absent_rather_than_zero_when_nothing_is_market_linked():
    """A hero that reads 0.00 when there is no market-linked evidence is a fabricated number --
    the exact failure mode this repo keeps fixing. It must be absent, and the UI must say so."""
    from tradehub.journal.scoring import market_skill

    assert market_skill([]) is None
    assert market_skill([{"forecaster": "housing_direction", "calibration_ready": True, "n_settled": 10,
                          "n_baseline": 10, "brier": 0.3, "brier_on_baseline": 0.3, "brier_baseline": 0.3,
                          "baseline": "climatology", "gate_status": "SHADOW"}]) is None
    # A card with no measured Brier yet cannot contribute a probability to the pool.
    assert market_skill([{"forecaster": "sports_nfl", "calibration_ready": True, "n_settled": 5,
                          "n_baseline": 5, "brier": None, "brier_on_baseline": None,
                          "brier_baseline": None, "baseline": "market",
                          "gate_status": "SHADOW"}]) is None


# ── the paired Brier (migration 20260428000020) ──────────────────────────────
#
# `brier` is a mean over EVERY settled target; `brier_baseline` is a mean over only the targets that
# HAVE a baseline. `score()` computes `bss` from a third denominator again -- the model's own Brier on
# exactly the baseline-matched targets -- and threw it away. So the hero pooled an all-targets numerator
# against a matched-subset denominator, over all-targets weights: three denominators, one sign. The card
# has to carry the matched-subset pair and its count, or the pool is guessing.


def _sign_flip_rows():
    """A real forecaster whose two Briers point in OPPOSITE directions.

    100 market-linked targets it calls well (0.1 against a 0.2 market, all resolving NO: ours 0.01,
    market 0.04) and 300 targets with no market at all, on which it is badly wrong (0.9, all resolving
    NO: 0.81). So on the pairs the market is actually graded on, this model has real skill; across every
    settled target it looks worse than the market it beat on 100 of them.
    """
    rows = [_row(f"m{i}", 0.10, market=0.20) for i in range(100)]
    rows += [_row(f"x{i}", 0.90) for i in range(300)]
    return rows


def test_a_scorecard_keeps_the_brier_and_the_count_its_bss_was_actually_computed_from():
    """`bss` is `1 - ours_b / brier_base`, where `ours_b` is the model's Brier over the matched targets
    ONLY. The card stored `brier` (every settled target) and `brier_baseline` (matched only) and not the
    other half of the fraction, so nothing downstream could reconstruct what it had been graded against.

    The fixture is built so the two sides DIFFER: one settled target has a market, one has no baseline at
    all, so an all-targets mean and a matched mean cannot coincide by luck.
    """
    card = score([_row("m", 0.80, market=0.90), _row("x", 0.30)],
                 {"m": 1, "x": 0}, {}, "daily")

    assert card["n_settled"] == 2 and card["n_baseline"] == 1, card
    assert card["brier_on_baseline"] == pytest.approx(0.04, abs=1e-6), card      # (0.8 - 1)**2
    assert card["brier_baseline"] == pytest.approx(0.01, abs=1e-6), card        # (0.9 - 1)**2
    assert card["brier"] == pytest.approx(0.065, abs=1e-6), card                 # (0.04 + 0.09) / 2
    assert card["brier"] != pytest.approx(card["brier_on_baseline"], abs=1e-6), (
        "the fixture is vacuous: both means are equal, so it cannot tell the two fields apart")
    # The stored pair reproduces the BSS that was already stored, over the same n.
    assert card["bss"] == pytest.approx(1 - card["brier_on_baseline"] / card["brier_baseline"], abs=1e-6)
    assert card["brier"] != pytest.approx(card["brier_baseline"]), (
        "the all-targets mean and the baseline mean must not be the same column")


def test_market_skill_sign_flips_onto_the_baseline_matched_targets():
    """THE bug: pool the right pair and the hero reads POSITIVE skill; pool the wrong pair and the same
    card reads NEGATIVE. The sign is the whole claim, so it is what this asserts.

    Fixture (`_sign_flip_rows`): n_settled 400, of which n_baseline 100.
      matched subset : ours 0.01 vs market 0.04  ->  bss = 1 - 0.01/0.04 = +0.75
      every target   : ours 0.61 vs market 0.04  ->  bss = 1 - 0.61/0.04 = -14.25
    Pooling `brier` against `brier_baseline` therefore publishes the OPPOSITE sign for a forecaster
    that beat the market on every target the market is graded on.
    """
    from tradehub.journal.scoring import market_skill

    card = score(_sign_flip_rows(), {r["target"]: 0 for r in _sign_flip_rows()}, {}, "daily")
    assert card["calibration_ready"] and card["baseline"] == "market", card
    assert card["n_settled"] == 400 and card["n_baseline"] == 100, card
    assert card["bss"] > 0, card                       # the card's own BSS is positive

    out = market_skill([card])
    assert out is not None
    assert out["bss"] > 0, (
        f"pooling {out['brier']} against {out['brier_baseline']} flipped a positive-skill card negative")
    assert out["bss"] == pytest.approx(card["bss"], abs=1e-6), out
    assert out["brier"] == pytest.approx(card["brier_on_baseline"], abs=1e-6), out
    assert out["brier_baseline"] == pytest.approx(card["brier_baseline"], abs=1e-6), out
    # The headline's sample size is the pooled set, not the cards' wider one.
    assert out["n"] == 100, out


def test_market_skill_weights_by_the_matched_count_never_the_settled_one():
    """Two eligible cards whose `n_settled` and `n_baseline` orderings are REVERSED, so the weights are
    not interchangeable and the three possible pools disagree on the SIGN.

      A: n_settled 900 / n_baseline  50, paired ours 0.10
      B: n_settled  60 / n_baseline 100, paired ours 0.30
      market 0.20 on both.

    by n_baseline (right) : (50*0.10 + 100*0.30)/150 = 0.2333 -> bss -0.1667  (negative)
    by n_settled          : (900*0.10 + 60*0.30)/960 = 0.1125 -> bss +0.4375  (positive)
    by card count         : (0.10 + 0.30)/2 = 0.20        -> bss  0.0      (a fabricated zero)
    """
    from tradehub.journal.scoring import market_skill

    a = {"forecaster": "sports_nfl", "calibration_ready": True, "n_settled": 900, "n_baseline": 50,
         "brier": 0.99, "brier_on_baseline": 0.10, "brier_baseline": 0.20,
         "baseline": "market", "gate_status": "SHADOW"}
    b = {"forecaster": "cpi_nowcast", "calibration_ready": True, "n_settled": 60, "n_baseline": 100,
         "brier": 0.01, "brier_on_baseline": 0.30, "brier_baseline": 0.20,
         "baseline": "market", "gate_status": "SHADOW"}

    out = market_skill([a, b])
    assert out is not None
    assert out["n"] == 150, out
    assert out["brier"] == pytest.approx(35 / 150, abs=1e-9), out
    assert out["brier_baseline"] == pytest.approx(0.20, abs=1e-9), out
    assert out["bss"] == pytest.approx(1 - (35 / 150) / 0.20, abs=1e-9), out
    assert out["bss"] < 0, "weighting by n_settled would have published this as positive skill"


def test_market_skill_ignores_a_card_scored_before_the_paired_columns_existed():
    """Rows written before migration 20260428000020 carry NULL in `brier_on_baseline` and `n_baseline`.
    They are NOT backfilled, and NULL is not zero: a card we never paired cannot contribute a half to
    the pool, so the hero drops to absent rather than inventing one.
    """
    from tradehub.journal.scoring import market_skill

    legacy = {"forecaster": "sports_nfl", "calibration_ready": True, "n_settled": 400, "n_baseline": None,
              "brier": 0.61, "brier_on_baseline": None, "brier_baseline": 0.04,
              "baseline": "market", "gate_status": "SHADOW"}
    assert market_skill([legacy]) is None, (
        "a NULL paired Brier was read as 0.0 and published a fabricated 1.00 skill")

    paired = {"forecaster": "cpi_nowcast", "calibration_ready": True, "n_settled": 60, "n_baseline": 100,
              "brier": 0.11, "brier_on_baseline": 0.10, "brier_baseline": 0.20,
              "baseline": "market", "gate_status": "SHADOW"}
    out = market_skill([legacy, paired])
    assert out is not None and out["n"] == 100 and out["brier"] == pytest.approx(0.10, abs=1e-9), out

    # A count without the score it counts is not a contribution either, and must not reach the division
    # as a float -- that is a TypeError, i.e. the whole headline 500s rather than degrading.
    orphan = {"forecaster": "gas_leak", "calibration_ready": True, "n_settled": 400, "n_baseline": 100,
              "brier": 0.61, "brier_on_baseline": None, "brier_baseline": 0.04,
              "baseline": "market", "gate_status": "SHADOW"}
    out = market_skill([orphan, paired])
    assert out is not None and out["n"] == 100 and out["brier"] == pytest.approx(0.10, abs=1e-9), out

    # ...and the mirror: a score with no count is not a weight. `int(None)` here is a TypeError, and a
    # TypeError in the hero takes the whole page down instead of showing an em dash.
    weightless = {"forecaster": "sports_cfb", "calibration_ready": True, "n_settled": 400,
                  "n_baseline": None, "brier": 0.61, "brier_on_baseline": 0.01, "brier_baseline": 0.04,
                  "baseline": "market", "gate_status": "SHADOW"}
    out = market_skill([weightless, paired])
    assert out is not None and out["n"] == 100 and out["brier"] == pytest.approx(0.10, abs=1e-9), out
