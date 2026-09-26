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


def test_the_cache_round_trips_seven_digit_values_exactly(tmp_path):
    """`_write_cache` used `{v:g}`, which is SIX significant digits. CCSA 1,897,123 was cached as
    `1.897e+06` and read back as 1897000.0 — so a cached run and a fresh run produced different
    nowcasts, and the difference was invisible unless you diffed two runs by hand.
    """
    from tradehub.data.alfred_vintages import _write_cache

    vintage = date(2026, 8, 31)
    values = {
        date(2026, 8, 1): 1897123.0,      # 7 digits: the CCSA case
        date(2026, 7, 1): 1_234_567.0,
        date(2026, 6, 1): 0.1,
        date(2026, 5, 1): -23.0,
        date(2026, 4, 1): 0.000123,
        date(2026, 3, 1): 1234567.5,
    }
    _write_cache(tmp_path / "CCSA" / f"{vintage}.csv", "CCSA", vintage, values)
    text = (tmp_path / "CCSA" / f"{vintage}.csv").read_text(encoding="utf-8")
    assert "1897123" in text and "e+0" not in text, text
    assert parse_alfred_csv(text)[vintage] == values, parse_alfred_csv(text)[vintage]


def test_a_warm_cache_gives_the_same_values_as_a_cold_one(tmp_path):
    """The property the precision bug broke: fetch_vintages must be a pure function of the
    requested vintage dates, whether or not they were already on disk."""
    big = {date(2026, 8, 1): 1897123.0, date(2026, 7, 1): 1_234_567.0}
    header = "observation_date,CCSA_20260831"

    def server(url, params):
        return header + "\n" + "\n".join(f"{obs.isoformat()},{value}" for obs, value in big.items()) + "\n"

    days = [date(2026, 8, 31)]
    cold = fetch_vintages("CCSA", days, get_text=server, cache_dir=tmp_path, today=date(2026, 9, 5))
    warm = fetch_vintages("CCSA", days, get_text=server, cache_dir=tmp_path, today=date(2026, 9, 5))
    assert cold == warm
    assert warm[date(2026, 8, 31)] == big
