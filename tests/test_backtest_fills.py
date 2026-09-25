from datetime import datetime, timedelta, timezone

import pytest

from shared.kalshi_fees import kalshi_fee_cents, net_edge_pct
from tradehub.backtest.fills import MIN_TAKER_PRICE, maker_fill, quote_at, taker_fill
from tradehub.backtest.kalshi_history import Candle, Trade
from tradehub.backtest.pit import Decision

T0 = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
CLOSE = datetime(2026, 7, 25, 4, 59, tzinfo=timezone.utc)


def candle(hours_before, bid, ask):
    return Candle(end_ts=T0 - timedelta(hours=hours_before), yes_bid=bid, yes_ask=ask, volume=1.0)


def test_quote_at_uses_last_candle_at_or_before_decision_not_future():
    candles = [candle(2, 0.30, 0.34), candle(1, 0.40, 0.44), candle(-1, 0.90, 0.95)]
    assert quote_at(candles, T0).yes_ask == pytest.approx(0.44)


def test_quote_at_skips_candles_without_both_quotes():
    candles = [candle(2, 0.30, 0.34), Candle(T0 - timedelta(hours=1), None, 0.5, 0.0)]
    assert quote_at(candles, T0).yes_ask == pytest.approx(0.34)


def test_quote_at_none_when_no_prior_candle():
    assert quote_at([candle(-1, 0.4, 0.44)], T0) is None


def test_taker_buys_yes_at_ask_with_taker_fee():
    fill = taker_fill(Decision("T", T0, 0.70), [candle(1, 0.40, 0.44)], contracts=10)
    assert fill.side == "yes" and fill.maker is False
    assert fill.price == pytest.approx(0.44)
    assert fill.fee == pytest.approx(kalshi_fee_cents(44.0, contracts=10) / 100)
    assert fill.filled_at == T0


def test_taker_buys_no_at_one_minus_bid():
    fill = taker_fill(Decision("T", T0, 0.20), [candle(1, 0.40, 0.44)])
    assert fill.side == "no"
    assert fill.price == pytest.approx(0.60)


def test_taker_never_buys_below_10_cents():
    # our_prob 0.30 vs ask 0.05 is a big YES edge, but 5c < 10c -> no taker fill.
    assert MIN_TAKER_PRICE == pytest.approx(0.10)
    assert taker_fill(Decision("T", T0, 0.30), [candle(1, 0.03, 0.05)]) is None


def test_taker_respects_min_edge_after_fees():
    # 0.47 vs ask 0.44: gross 3pp, whole-cent fee 2pp -> net 1pp.
    d = Decision("T", T0, 0.47)
    assert taker_fill(d, [candle(1, 0.40, 0.44)], min_edge_pct=1.0) is not None
    assert taker_fill(d, [candle(1, 0.40, 0.44)], min_edge_pct=2.0) is None


def test_taker_no_fill_without_edge():
    assert taker_fill(Decision("T", T0, 0.42), [candle(1, 0.40, 0.44)]) is None


def test_maker_yes_bid_fills_on_later_no_taker_trade_at_or_through_limit():
    trades = [
        Trade(T0 - timedelta(minutes=5), 0.39, 0.61, 3.0, "no"),   # before decision: ignored
        Trade(T0 + timedelta(minutes=10), 0.41, 0.59, 2.0, "no"),  # above limit 0.40: no fill
        Trade(T0 + timedelta(minutes=20), 0.40, 0.60, 5.0, "no"),  # at limit: fill
    ]
    fill = maker_fill(Decision("T", T0, 0.60), [candle(1, 0.40, 0.44)], trades, CLOSE, contracts=2)
    assert fill.side == "yes" and fill.maker is True
    assert fill.price == pytest.approx(0.40)
    assert fill.filled_at == T0 + timedelta(minutes=20)
    assert fill.fee == pytest.approx(kalshi_fee_cents(40.0, contracts=2, maker=True) / 100)


def test_maker_ignores_same_side_takers_and_trades_after_close():
    trades = [
        Trade(T0 + timedelta(minutes=5), 0.30, 0.70, 1.0, "yes"),  # taker bought YES: doesn't hit our bid
        Trade(CLOSE + timedelta(minutes=1), 0.30, 0.70, 1.0, "no"),  # after close
    ]
    assert maker_fill(Decision("T", T0, 0.60), [candle(1, 0.40, 0.44)], trades, CLOSE) is None


def test_maker_no_side_fills_on_yes_taker_at_or_through_no_limit():
    # our_prob 0.20 -> buy NO; limit = 1 - ask = 0.56; a YES taker printing no_price <= 0.56 fills it.
    trades = [Trade(T0 + timedelta(minutes=3), 0.45, 0.55, 1.0, "yes")]
    fill = maker_fill(Decision("T", T0, 0.20), [candle(1, 0.40, 0.44)], trades, CLOSE)
    assert fill.side == "no"
    assert fill.price == pytest.approx(0.56)


def test_maker_needs_positive_limit():
    assert maker_fill(Decision("T", T0, 0.90), [candle(1, 0.0, 0.02)], [], CLOSE) is None


def test_net_edge_pct_subtracts_fees_from_negative_gross_edges():
    expected = -5.0 - kalshi_fee_cents(44.0, contracts=1)
    assert net_edge_pct(39.0, 44.0, contracts=1) == pytest.approx(expected)


def test_negative_gross_edge_never_fills_even_when_fee_would_flip_the_sign():
    assert taker_fill(Decision("T", T0, 0.435), [candle(1, 0.40, 0.44)]) is None


def test_taker_edge_threshold_uses_requested_contract_count():
    decision = Decision("T", T0, 0.1072)
    quotes = [candle(1, 0.08, 0.10)]
    assert taker_fill(decision, quotes, contracts=1, min_edge_pct=0.015) is None
    assert taker_fill(decision, quotes, contracts=10, min_edge_pct=0.015) is not None


def test_maker_edge_threshold_uses_requested_contract_count():
    decision = Decision("T", T0, 0.1022)
    quotes = [candle(1, 0.10, 0.101)]
    trades = [Trade(T0 + timedelta(minutes=5), 0.10, 0.90, 10.0, "no")]
    assert maker_fill(decision, quotes, trades, CLOSE, contracts=1, min_edge_pct=0.011) is None
    assert maker_fill(decision, quotes, trades, CLOSE, contracts=10, min_edge_pct=0.011) is not None


def test_maker_ignores_block_trades():
    trades = [Trade(T0 + timedelta(minutes=5), 0.40, 0.60, 10.0, "no", True)]
    assert maker_fill(Decision("T", T0, 0.60), [candle(1, 0.40, 0.44)], trades, CLOSE) is None


def test_maker_requires_enough_qualifying_post_decision_volume():
    trades = [Trade(T0 + timedelta(minutes=10), 0.40, 0.60, 0.75, "no")]
    assert maker_fill(Decision("T", T0, 0.60), [candle(1, 0.40, 0.44)], trades, CLOSE) is None


def test_maker_fills_when_accumulated_qualifying_volume_reaches_contracts():
    trades = [
        Trade(T0 + timedelta(minutes=10), 0.40, 0.60, 0.75, "no"),
        Trade(T0 + timedelta(minutes=20), 0.40, 0.60, 0.25, "no"),
    ]
    fill = maker_fill(Decision("T", T0, 0.60), [candle(1, 0.40, 0.44)], trades, CLOSE)
    assert fill is not None
    assert fill.filled_at == T0 + timedelta(minutes=20)
