import pytest

from shared.kalshi_fees import kalshi_fee_cents
from tradehub.journal.costs import cost_summary, frozen_quote, simulated_trade


def test_a_quote_needs_both_sides_and_a_sane_book():
    assert frozen_quote({"yes_bid": 0.4, "yes_ask": 0.44}) == (0.4, 0.44)
    assert frozen_quote({"yes_bid": None, "yes_ask": 0.44}) is None
    assert frozen_quote({"yes_bid": 0.5, "yes_ask": 0.4}) is None  # crossed
    assert frozen_quote({}) is None and frozen_quote(None) is None


def test_a_yes_trade_pays_the_ask_and_the_fee_and_settles_at_par():
    won = simulated_trade(0.80, 0.58, 0.62, outcome=1)
    assert won["gross_cents"] == pytest.approx(38.0)  # 100 - 62
    assert won["fee_cents"] == kalshi_fee_cents(62.0)
    assert won["net_cents"] == pytest.approx(38.0 - won["fee_cents"])
    lost = simulated_trade(0.80, 0.58, 0.62, outcome=0)
    assert lost["gross_cents"] == pytest.approx(-62.0) and lost["net_cents"] < -62.0


def test_a_no_trade_pays_the_no_ask_which_is_one_minus_the_yes_bid():
    trade = simulated_trade(0.10, 0.58, 0.62, outcome=0)  # we think NO; buy NO at 1 - 0.58 = 42c
    assert trade["gross_cents"] == pytest.approx(100.0 - 42.0)


def test_no_edge_after_fees_means_no_trade_and_longshots_are_not_taken():
    assert simulated_trade(0.61, 0.58, 0.62, outcome=1) is None  # below the ask: nothing to buy
    assert simulated_trade(0.99, 0.02, 0.06, outcome=1) is None  # a 6c ask is under the 10c taker floor


def test_the_summary_counts_quoted_and_traded_separately():
    pairs = [
        {"probability": 0.8, "outcome": 1, "payload": {"yes_bid": 0.58, "yes_ask": 0.62}},   # trades, wins
        {"probability": 0.61, "outcome": 1, "payload": {"yes_bid": 0.58, "yes_ask": 0.62}},  # quoted, no trade
        {"probability": 0.9, "outcome": 1, "payload": {}},                                     # no quote at all
    ]
    summary = cost_summary(pairs)
    assert (summary["n_quoted"], summary["n_traded"]) == (2, 1)
    assert summary["net_pnl_cents"] == pytest.approx(summary["gross_pnl_cents"] - summary["fees_cents"])
