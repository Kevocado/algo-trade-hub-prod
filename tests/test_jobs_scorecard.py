from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from tradehub.data.alfred_vintages import parse_alfred_csv
from tradehub.engines.labor import EstimatePath, estimate_path
from tradehub.jobs_scorecard import NowcastSnapshot, scorecard_row, upsert_scorecard

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "labor"
MIGRATION = Path(__file__).resolve().parents[1] / (
    "market_sentiment_tool/supabase/migrations/20260416000009_jobs_scorecard.sql"
)
LADDER = [(0.5, 0.9), (50.5, 0.5), (100.5, 0.1)]


def test_scorecard_row_scores_against_first_print():
    path = EstimatePath(first=60.0, first_vintage=date(2026, 7, 31), second=55.0, second_vintage=date(2026, 8, 31))
    row = scorecard_row(series="payrolls", month=date(2026, 6, 1), event_ticker="KXPAYROLLS-26JUN",
                        release=date(2026, 7, 2), close_time=datetime(2026, 7, 2, 12, 29, tzinfo=timezone.utc),
                        ladder_1h=LADDER, ladder_close=LADDER,
                        nowcast=NowcastSnapshot(80.0, 50.0, "labor-v1", {"pay_last": 100.0}), path=path)
    assert row["reference_month"] == "2026-06-01" and row["rev2"] == 55.0 and row["rev3"] is None
    assert row["kalshi_ladder_1h"] == [[0.5, 0.9], [50.5, 0.5], [100.5, 0.1]]
    assert row["nowcast_abs_err"] == pytest.approx(20.0)
    assert row["kalshi_abs_err"] == pytest.approx(abs(row["kalshi_mean_1h"] - 60.0))
    assert row["kalshi_brier"] == pytest.approx((0.01 + 0.25 + 0.01) / 3)
    assert 0.0 <= row["nowcast_brier"] <= 1.0 and row["nowcast_crps"] > 0
    assert row["n_strikes"] == 3


def test_scorecard_row_before_release_has_no_scores():
    row = scorecard_row(series="payrolls", month=date(2026, 9, 1), event_ticker="KXPAYROLLS-26SEP",
                        release=date(2026, 10, 2), close_time=None, ladder_1h=[], ladder_close=[],
                        nowcast=NowcastSnapshot(90.0, 60.0, "labor-v1", {}), path=EstimatePath())
    assert row["first_print"] is None and row["nowcast_abs_err"] is None and row["kalshi_mean_1h"] is None
    assert row["nowcast_mu"] == 90.0


def test_scorecard_row_from_recorded_vintages_shows_revisions():
    vintages = parse_alfred_csv((FIXTURES / "payems_2024_2025.csv").read_text(encoding="utf-8"))
    row = scorecard_row(series="payrolls", month=date(2024, 12, 1), event_ticker="KXPAYROLLS-24DEC",
                        release=date(2025, 1, 10), close_time=None, ladder_1h=[], ladder_close=[], nowcast=None,
                        path=estimate_path(vintages, date(2024, 12, 1)))
    assert (row["first_print"], row["rev2"], row["rev3"], row["benchmark"]) == (256.0, 307.0, 323.0, 307.0)
    assert row["benchmark_vintage"] == "2025-02-28"


def test_upsert_scorecard_is_keyed_and_stamped():
    sent = {}

    class Table:
        def upsert(self, rows, on_conflict):
            sent.update(rows=rows, on_conflict=on_conflict)
            return self

        def execute(self):
            return None

    supa = type("S", (), {"table": lambda self, name: sent.setdefault("table", name) and Table()})()
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    assert upsert_scorecard(supa, [{"series": "payrolls"}], now) == 1
    assert sent["table"] == "jobs_scorecard" and sent["on_conflict"] == "series,reference_month"
    assert sent["rows"][0]["updated_at"] == now.isoformat()
    assert upsert_scorecard(supa, [], now) == 0


def test_jobs_scorecard_migration():
    sql = MIGRATION.read_text(encoding="utf-8")
    for needle in (
        "CREATE TABLE IF NOT EXISTS jobs_scorecard",
        "PRIMARY KEY (series, reference_month)",
        "CHECK (series IN ('payrolls', 'unemployment'))",
        "ENABLE ROW LEVEL SECURITY",
        'CREATE POLICY "jobs_scorecard_owner_read" ON jobs_scorecard FOR SELECT',
    ):
        assert needle in sql, needle
    assert "FOR ALL" not in sql
