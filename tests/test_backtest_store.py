from datetime import datetime, timedelta, timezone

from tradehub.backtest.kalshi_history import Candle
from tradehub.backtest.pit import Decision, Observation
from tradehub.backtest.runner import MarketHistory, run_backtest
from tradehub.backtest.store import (
    build_backtest_run_row,
    data_snapshot_hash,
    record_backtest_run,
    stable_hash,
)

T0 = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
CLOSE = datetime(2026, 7, 25, 4, 59, tzinfo=timezone.utc)
MIGRATION_COLUMNS = {
    "engine", "engine_version", "mode", "config", "config_hash", "data_hash", "date_from", "date_to",
    "n_decisions", "n_fills", "n_settled", "pnl_after_fees", "max_drawdown", "turnover", "brier_ours",
    "brier_market", "log_loss", "cal_buckets", "max_cal_dev", "gate_status", "gate_reasons",
}


def _inputs():
    decisions = [Decision("A", T0, 0.7, (Observation("f", 1.0, T0 - timedelta(hours=2)),))]
    histories = {"A": MarketHistory("A", "yes", CLOSE, [Candle(T0 - timedelta(hours=1), 0.40, 0.44, 1.0)], [])}
    return decisions, histories


def test_stable_hash_is_key_order_independent():
    assert stable_hash({"a": 1, "b": 2}) == stable_hash({"b": 2, "a": 1})
    assert stable_hash({"a": 1}) != stable_hash({"a": 2})


def test_data_snapshot_hash_changes_with_inputs_but_not_order():
    decisions, histories = _inputs()
    h1 = data_snapshot_hash(decisions, histories)
    assert h1 == data_snapshot_hash(list(reversed(decisions)), dict(histories))
    changed = {"A": MarketHistory("A", "no", CLOSE, histories["A"].candles, [])}
    assert h1 != data_snapshot_hash(decisions, changed)


def test_build_row_matches_migration_columns():
    decisions, histories = _inputs()
    result = run_backtest(engine="weather", cadence="daily", decisions=decisions, histories=histories)
    row = build_backtest_run_row(result, engine_version="v1", config={"min_edge_pct": 0.0},
                                 data_hash=data_snapshot_hash(decisions, histories),
                                 date_from=T0, date_to=CLOSE)
    assert set(row) == MIGRATION_COLUMNS
    assert row["config_hash"] == stable_hash({"min_edge_pct": 0.0})
    assert row["gate_status"] == "SHADOW"
    assert row["n_fills"] == 1 and row["mode"] == "taker"
    assert row["date_from"] == T0.isoformat()
    assert row["log_loss"] == round(result.log_loss, 8)


def test_record_backtest_run_inserts():
    inserted = []

    class Table:
        def insert(self, row):
            inserted.append(row)
            return self

        def execute(self):
            return type("R", (), {"data": list(inserted)})()

    class Supa:
        def table(self, name):
            assert name == "backtest_runs"
            return Table()

    assert record_backtest_run(Supa(), {"engine": "weather"}) == {"engine": "weather"}
