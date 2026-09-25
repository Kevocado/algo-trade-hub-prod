import inspect

import pytest

from shared.kalshi_fees import net_edge_pct
from tradehub.edges import MIN_TAKER_PRICE, Quote, best_side, evaluate_edge

Q = Quote(yes_bid=0.40, yes_ask=0.44, yes_bid_size=100.0, yes_ask_size=100.0)


def test_best_side_public_signature_has_no_contract_count():
    parameters = inspect.signature(best_side).parameters
    assert list(parameters) == ["our_prob", "yes_price", "no_price", "maker"]
    assert parameters["maker"].kind is inspect.Parameter.KEYWORD_ONLY


def test_best_side_picks_larger_net_edge():
    side, price, edge = best_side(0.70, 0.44, 0.60, maker=False)
    assert (side, price) == ("yes", 0.44)
    assert edge == pytest.approx(net_edge_pct(70.0, 44.0))
    assert best_side(0.20, 0.44, 0.60, maker=False)[0] == "no"


def test_evaluate_edge_prefers_maker_at_bid():
    s = evaluate_edge("T", 0.70, Q, min_edge_pct=5.0)
    assert s.maker is True and s.side == "yes"
    assert s.entry_price == pytest.approx(0.40)
    assert s.net_edge_pct == pytest.approx(net_edge_pct(70.0, 40.0, maker=True))
    assert s.market_prob == pytest.approx(0.42)


def test_evaluate_edge_taker_when_maker_disabled():
    s = evaluate_edge("T", 0.70, Q, min_edge_pct=5.0, prefer_maker=False)
    assert s.maker is False and s.entry_price == pytest.approx(0.44)


def test_evaluate_edge_no_taker_longshot():
    thin = Quote(yes_bid=0.02, yes_ask=0.05, yes_bid_size=1.0, yes_ask_size=1.0)
    assert MIN_TAKER_PRICE == pytest.approx(0.10)
    assert evaluate_edge("T", 0.30, thin, min_edge_pct=1.0, prefer_maker=False) is None
    maker = evaluate_edge("T", 0.30, thin, min_edge_pct=1.0)  # maker bid at 0.02 is allowed
    assert maker is not None and maker.maker is True


def test_evaluate_edge_min_edge_and_missing_quotes():
    assert evaluate_edge("T", 0.43, Q, min_edge_pct=5.0) is None
    assert evaluate_edge("T", 0.90, Quote(None, 0.44, 0.0, 1.0), min_edge_pct=1.0) is None
