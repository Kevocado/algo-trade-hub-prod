from datetime import date
from pathlib import Path

import pytest

from tradehub.data.alfred_vintages import ALFRED_GRAPH_CSV, VINTAGES_PER_REQUEST, fetch_vintages, parse_alfred_csv

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "labor"
PAYEMS_CSV = (FIXTURES / "payems_2024_2025.csv").read_text(encoding="utf-8")


def test_parse_multi_vintage_csv_skips_blank_cells():
    vintages = parse_alfred_csv(PAYEMS_CSV)
    assert sorted(vintages) == [date(2024, 12, 31), date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31)]
    assert date(2024, 12, 1) not in vintages[date(2024, 12, 31)]  # not yet published
    assert vintages[date(2025, 1, 31)][date(2024, 12, 1)] == 159536.0
    assert vintages[date(2025, 2, 28)][date(2024, 12, 1)] == 158926.0  # after the Feb-2025 benchmark


def test_parse_rejects_non_csv():
    with pytest.raises(ValueError):
        parse_alfred_csv("<html>Access Denied</html>")


def _fake_server(calls):
    def get_text(url, params):
        assert url == ALFRED_GRAPH_CSV
        days = params["vintage_date"].split(",")
        assert params["id"].split(",") == ["PAYEMS"] * len(days)
        calls.append(days)
        header = "observation_date," + ",".join(f"PAYEMS_{d.replace('-', '')}" for d in days)
        return header + "\n2024-01-01," + ",".join(str(100 + i) for i in range(len(days))) + "\n"
    return get_text


def test_fetch_batches_requests_and_caches_past_vintages(tmp_path):
    calls = []
    days = [date(2024, 1, 1) + (date(2024, 1, 2) - date(2024, 1, 1)) * i for i in range(VINTAGES_PER_REQUEST + 3)]
    out = fetch_vintages("PAYEMS", days, get_text=_fake_server(calls), cache_dir=tmp_path, today=date(2026, 1, 1))
    assert [len(c) for c in calls] == [VINTAGES_PER_REQUEST, 3]
    assert out[days[0]] == {date(2024, 1, 1): 100.0}
    assert (tmp_path / "PAYEMS" / f"{days[0].isoformat()}.csv").is_file()
    again = fetch_vintages("PAYEMS", days, get_text=_fake_server(calls), cache_dir=tmp_path, today=date(2026, 1, 1))
    assert again == out and len(calls) == 2  # served from the cache


def test_fetch_never_requests_today_or_future(tmp_path):
    calls = []
    out = fetch_vintages("PAYEMS", [date(2026, 1, 1), date(2026, 2, 1), date(2025, 12, 31)],
                         get_text=_fake_server(calls), cache_dir=tmp_path, today=date(2026, 1, 1))
    assert calls == [["2025-12-31"]]
    assert list(out) == [date(2025, 12, 31)]
