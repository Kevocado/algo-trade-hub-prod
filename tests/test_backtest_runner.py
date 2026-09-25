from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

import pytest

from tradehub.backtest import metrics as backtest_metrics
from tradehub.backtest.fills import Fill
from tradehub.backtest.kalshi_history import Candle, Trade
from tradehub.backtest.metrics import fill_pnl, market_mid, max_drawdown, prediction_row
from tradehub.backtest.pit import Decision, LeakageError, Observation
from tradehub.backtest.runner import MarketHistory, run_backtest, walk_forward
from tradehub.backtest.store import data_snapshot_hash

T0 = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
CLOSE = datetime(2026, 7, 25, 4, 59, tzinfo=timezone.utc)


def hist(ticker, result, bid=0.40, ask=0.44, trades=()):
    return MarketHistory(ticker, result, CLOSE, [Candle(T0 - timedelta(hours=1), bid, ask, 1.0)], list(trades))


def test_fill_pnl_win_and_loss():
    f = Fill("T", "yes", 0.44, 10, 0.18, T0, False)
    assert fill_pnl(f, "yes") == pytest.approx((1.0 - 0.44) * 10 - 0.18)
    assert fill_pnl(f, "no") == pytest.approx(-0.44 * 10 - 0.18)


def test_max_drawdown():
    assert max_drawdown([]) == 0.0
    assert max_drawdown([1.0, -2.0, 0.5, -1.0, 3.0]) == pytest.approx(2.5)
    assert max_drawdown([1.0, 1.0]) == 0.0


def test_market_mid():
    assert market_mid(Candle(T0, 0.40, 0.44, 0.0)) == pytest.approx(0.42)
    assert market_mid(None) is None


def test_prediction_row_scores_both_briers():
    row = prediction_row(0.7, 0.5, "yes")
    assert row["brier"] == pytest.approx(0.09)
    assert row["market_brier"] == pytest.approx(0.25)
    assert row["status"] == "SETTLED" and row["result"] == "yes"
    assert prediction_row(0.7, None, "no")["market_brier"] is None


def test_run_backtest_taker_scores_fills_and_feeds_gate():
    decisions = [Decision("A", T0, 0.70), Decision("B", T0 + timedelta(minutes=1), 0.20)]
    histories = {"A": hist("A", "yes"), "B": hist("B", "no")}
    res = run_backtest(engine="weather", cadence="daily", decisions=decisions, histories=histories)
    assert res.n_decisions == 2 and res.n_fills == 2
    expected = sum(fill_pnl(f, {"A": "yes", "B": "no"}[f.market_ticker]) for f in res.fills)
    assert res.pnl_after_fees == pytest.approx(expected)
    assert res.pnl_after_fees > 0
    assert res.turnover == pytest.approx(0.44 + 0.60)
    assert res.summary["n_settled"] == 2
    assert res.gate["status"] == "SHADOW"  # 2 contracts << 200 daily minimum
    assert any("200" in r for r in res.gate["reasons"])


def test_run_backtest_skips_canceled_markets():
    res = run_backtest(engine="weather", cadence="daily",
                       decisions=[Decision("C", T0, 0.7)], histories={"C": hist("C", None)})
    assert res.n_decisions == 0 and res.n_fills == 0
    assert res.pnl_after_fees == 0.0


def test_run_backtest_rejects_lookahead_features():
    late = Observation("forecast", 80.0, T0 + timedelta(hours=1))
    with pytest.raises(LeakageError):
        run_backtest(engine="weather", cadence="daily",
                     decisions=[Decision("A", T0, 0.7, (late,))], histories={"A": hist("A", "yes")})


def test_run_backtest_rejects_decision_after_close():
    with pytest.raises(LeakageError):
        run_backtest(engine="weather", cadence="daily",
                     decisions=[Decision("A", CLOSE, 0.7)], histories={"A": hist("A", "yes")})


def test_run_backtest_maker_mode_uses_trades():
    trades = [Trade(T0 + timedelta(minutes=5), 0.40, 0.60, 1.0, "no")]
    res = run_backtest(engine="weather", cadence="daily", mode="maker",
                       decisions=[Decision("A", T0, 0.70)], histories={"A": hist("A", "yes", trades=trades)})
    assert res.n_fills == 1 and res.fills[0].maker is True


def test_run_backtest_no_fills_passes_none_pnl_to_gate():
    res = run_backtest(engine="weather", cadence="daily",
                       decisions=[Decision("A", T0, 0.42)], histories={"A": hist("A", "yes")})
    assert res.n_fills == 0
    assert any("P&L" in r for r in res.gate["reasons"])


def test_walk_forward_only_fits_on_strictly_earlier_events():
    times = [T0 + timedelta(hours=h) for h in (0, 1, 1, 2)]
    seen = []

    def fit(history):
        seen.append(len(history))
        return len(history)

    out = walk_forward(
        times,
        time_of=lambda t: t,
        label_available_at=lambda t: t,
        fit=fit,
        predict=lambda model, t: model,
    )
    # The two events at hour 1 must not see each other.
    assert [p for _, p in out] == [1, 1, 3]
    assert seen == [1, 1, 3]


@dataclass(frozen=True)
class DelayedLabelEvent:
    decided_at: datetime
    label_available_at: datetime


def test_walk_forward_excludes_labels_that_settle_36h_after_their_decision():
    events = [
        DelayedLabelEvent(T0 + timedelta(hours=hours), T0 + timedelta(hours=hours + 36))
        for hours in (0, 24, 48, 72)
    ]
    seen = []

    out = walk_forward(
        events,
        time_of=lambda event: event.decided_at,
        label_available_at=lambda event: event.label_available_at,
        fit=lambda history: seen.append(len(history)) or len(history),
        predict=lambda model, event: model,
    )

    assert [prediction for _, prediction in out] == [1, 2]
    assert seen == [1, 2]


def test_max_drawdown_follows_market_settlement_order():
    histories = {
        "A": MarketHistory("A", "no", T0 + timedelta(hours=2), [Candle(T0 - timedelta(hours=1), 0.20, 0.80, 1.0)], []),
        "B": MarketHistory("B", "no", T0 + timedelta(hours=4), [Candle(T0 - timedelta(hours=1), 0.20, 0.80, 1.0)], []),
        "C": MarketHistory("C", "yes", T0 + timedelta(hours=3), [Candle(T0 - timedelta(hours=1), 0.30, 0.40, 1.0)], []),
    }
    decisions = [
        Decision("A", T0, 0.90),
        Decision("B", T0 + timedelta(minutes=1), 0.90),
        Decision("C", T0 + timedelta(minutes=2), 0.60),
    ]

    result = run_backtest(engine="weather", cadence="daily", decisions=decisions, histories=histories)

    assert [fill.market_ticker for fill in result.fills] == ["A", "B", "C"]
    # Decision order is [-0.82, -0.82, +0.58] with 1.64 drawdown;
    # settlement order is [-0.82, +0.58, -0.82] with 1.06 drawdown.
    assert result.max_drawdown == pytest.approx(1.06)


def test_max_drawdown_uses_explicit_settlement_time_not_market_close():
    histories = {
        "A": MarketHistory("A", "no", T0 + timedelta(hours=4), [Candle(T0 - timedelta(hours=1), 0.20, 0.80, 1.0)], [], T0 + timedelta(hours=1)),
        "B": MarketHistory("B", "no", T0 + timedelta(hours=5), [Candle(T0 - timedelta(hours=1), 0.20, 0.80, 1.0)], [], T0 + timedelta(hours=3)),
        "C": MarketHistory("C", "yes", T0 + timedelta(hours=6), [Candle(T0 - timedelta(hours=1), 0.30, 0.40, 1.0)], [], T0 + timedelta(hours=2)),
    }
    decisions = [
        Decision("A", T0, 0.90),
        Decision("B", T0 + timedelta(minutes=1), 0.90),
        Decision("C", T0 + timedelta(minutes=2), 0.60),
    ]

    result = run_backtest(engine="weather", cadence="daily", decisions=decisions, histories=histories)

    assert result.max_drawdown == pytest.approx(1.06)


def test_log_loss_is_numerically_clipped_and_propagates_to_result():
    assert backtest_metrics.log_loss(0.0, "yes") == pytest.approx(-math.log(1e-15))
    assert backtest_metrics.log_loss(1.0, "no") == pytest.approx(-math.log(1e-15))
    row = prediction_row(0.7, 0.5, "yes")
    assert row["log_loss"] == pytest.approx(backtest_metrics.log_loss(0.7, 1))

    decisions = [Decision("A", T0, 0.70), Decision("B", T0 + timedelta(minutes=1), 0.20)]
    histories = {"A": hist("A", "yes"), "B": hist("B", "no")}
    result = run_backtest(engine="weather", cadence="daily", decisions=decisions, histories=histories)
    expected = (backtest_metrics.log_loss(0.70, 1) + backtest_metrics.log_loss(0.20, 0)) / 2
    assert result.log_loss == pytest.approx(expected)


def test_equal_time_decisions_have_permutation_independent_fill_order_and_drawdown():
    decisions = [
        Decision("A", T0, 0.70, (Observation("a", 1.0, T0 - timedelta(hours=1)),)),
        Decision("B", T0, 0.20, (Observation("b", 2.0, T0 - timedelta(hours=1)),)),
    ]
    histories = {"A": hist("A", "yes"), "B": hist("B", "no")}
    first = run_backtest(engine="weather", cadence="daily", decisions=decisions, histories=histories)
    second = run_backtest(engine="weather", cadence="daily", decisions=list(reversed(decisions)), histories=histories)
    assert [fill.market_ticker for fill in first.fills] == [fill.market_ticker for fill in second.fills]
    assert first.max_drawdown == pytest.approx(second.max_drawdown)
    assert first.pnl_after_fees == pytest.approx(second.pnl_after_fees)
    assert data_snapshot_hash(decisions, histories) == data_snapshot_hash(list(reversed(decisions)), histories)


def test_unquoted_decisions_are_excluded_so_both_briers_cover_the_same_contracts():
    """A decision made before the market has any quote can't be traded or compared to the
    market; scoring it would leave market_brier missing and fail the gate closed forever."""
    quoted = hist("A", "yes")
    unquoted = MarketHistory("B", "no", CLOSE, [Candle(T0 + timedelta(hours=1), 0.40, 0.44, 1.0)], [])
    res = run_backtest(
        engine="gas", cadence="daily",
        decisions=[Decision("A", T0, 0.70), Decision("B", T0, 0.20)],
        histories={"A": quoted, "B": unquoted},
    )
    assert res.n_decisions == 1
    assert res.n_unquoted == 1
    assert res.summary["brier_market"] is not None
