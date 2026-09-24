import pytest

from tradehub import settlement


def test_compute_realized_pnl_long_winner():
    # 10 contracts bought at 55c, settled at $1.00, 10c total fees.
    assert settlement.compute_realized_pnl(10, 0.55, 1.0, fees_cents=10) == pytest.approx(4.40)


def test_compute_realized_pnl_short_loser():
    # Short 5 contracts at 40c, settles YES at $1.00: loss.
    assert settlement.compute_realized_pnl(-5, 0.40, 1.0) == pytest.approx(-3.00)


def test_compute_realized_pnl_zero_qty():
    assert settlement.compute_realized_pnl(0, 0.50, 1.0, fees_cents=7) == pytest.approx(-0.07)


def test_brier_score_perfect_and_worst():
    assert settlement.brier_score(1.0, 1) == pytest.approx(0.0)
    assert settlement.brier_score(0.0, 1) == pytest.approx(1.0)
    assert settlement.brier_score(0.7, 1) == pytest.approx(0.09)


def test_parse_market_result_finalized_yes():
    assert settlement.parse_market_result({"market": {"status": "finalized", "result": "yes"}}) == ("SETTLED", 1)


def test_parse_market_result_finalized_no():
    assert settlement.parse_market_result({"market": {"status": "finalized", "result": "no"}}) == ("SETTLED", 0)


def test_parse_market_result_active_and_determined_are_open():
    for status in ("active", "determined", "paused", "unknown"):
        assert settlement.parse_market_result({"market": {"status": status, "result": None}}) == ("OPEN", None)


def test_parse_market_result_canceled_outcomes():
    for result in (None, "", "canceled"):
        payload = {"market": {"status": "finalized", "result": result}}
        assert settlement.parse_market_result(payload) == ("CANCELED", None)
    assert settlement.is_market_canceled({"market": {"status": "finalized", "result": None}}) is True
    assert settlement.is_market_canceled({"market": {"status": "finalized", "result": "yes"}}) is False


def test_parse_market_result_malformed_is_open_not_settled():
    for payload in ({}, {"market": None}, {"market": {"status": "finalized"}}, "nope", None):
        assert settlement.parse_market_result(payload) == ("OPEN", None)


def test_settle_prediction_row_settles_and_scores_both_briers():
    row = {"id": "abc", "our_prob": 0.7, "market_prob": 0.5}
    market = {"market": {"status": "finalized", "result": "yes"}}
    update = settlement.settle_prediction_row(row, market)
    assert update["id"] == "abc"
    assert update["status"] == "SETTLED"
    assert update["result"] == "yes"
    assert update["brier"] == pytest.approx(0.09)
    assert update["market_brier"] == pytest.approx(0.25)


def test_settle_prediction_row_missing_market_prob_gives_null_market_brier():
    row = {"id": "abc", "our_prob": 0.7, "market_prob": None}
    market = {"market": {"status": "finalized", "result": "no"}}
    update = settlement.settle_prediction_row(row, market)
    assert update["status"] == "SETTLED"
    assert update["result"] == "no"
    assert update["brier"] == pytest.approx(0.49)
    assert update["market_brier"] is None


def test_settle_prediction_row_open_market_returns_none():
    row = {"id": "abc", "our_prob": 0.7, "market_prob": 0.5}
    assert settlement.settle_prediction_row(row, {"market": {"status": "active", "result": None}}) is None


def test_settle_prediction_row_canceled_marks_canceled_without_fabricating_result():
    row = {"id": "abc", "our_prob": 0.7, "market_prob": 0.5}
    market = {"market": {"status": "finalized", "result": None}}
    update = settlement.settle_prediction_row(row, market)
    assert update == {"id": "abc", "status": "CANCELED"}
    assert "result" not in update and "brier" not in update
