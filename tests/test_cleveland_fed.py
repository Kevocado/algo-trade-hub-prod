import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from tradehub.data.cleveland_fed import NOWCAST_MONTH_URL, fetch_nowcast_history, parse_nowcast_month

PAYLOAD = json.loads((Path(__file__).parent / "fixtures" / "cleveland_nowcast_month_trimmed.json").read_text(encoding="utf-8"))


def test_parse_headline_path_and_actual():
    history = parse_nowcast_month(PAYLOAD)
    aug = history[date(2026, 8, 1)]
    assert [o.name for o in aug.path] == ["CPI:2026-08@2026-08-03", "CPI:2026-08@2026-09-10"]
    assert aug.path[-1].value == pytest.approx(0.359180537639179)
    # A value labelled Sep 10 is usable from 00:00 ET Sep 11 (04:00 UTC in EDT).
    assert aug.path[-1].published_at == datetime(2026, 9, 11, 4, 0, tzinfo=timezone.utc)
    assert aug.actual.name == "CPI:2026-08:actual"
    assert aug.actual.value == pytest.approx(0.396018184385816)
    assert aug.actual.published_at == datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc)  # 08:30 EDT


def test_vline_categories_do_not_shift_the_data():
    dec = parse_nowcast_month(PAYLOAD)[date(2021, 12, 1)]
    by_name = {o.name: o.value for o in dec.path}
    assert by_name["CPI:2021-12@2021-12-31"] == pytest.approx(0.388985413110369)  # after the "CPI Nov" vline
    assert dec.actual.value == pytest.approx(0.470453241537583)


def test_december_labels_roll_into_the_next_year():
    dec = parse_nowcast_month(PAYLOAD)[date(2021, 12, 1)]
    assert dec.path[-1].name == "CPI:2021-12@2022-01-11"
    assert dec.actual.published_at == datetime(2022, 1, 12, 13, 30, tzinfo=timezone.utc)  # 08:30 EST


def test_month_without_a_release_has_no_actual():
    oct25 = parse_nowcast_month(PAYLOAD)[date(2025, 10, 1)]  # Oct 2025 CPI was never published (shutdown)
    assert oct25.actual is None
    assert oct25.path[-1].name == "CPI:2025-10@2025-12-17"


def test_core_series():
    aug = parse_nowcast_month(PAYLOAD, "core")[date(2026, 8, 1)]
    assert aug.path[-1].name == "CORECPI:2026-08@2026-09-10"
    assert aug.path[-1].value == pytest.approx(0.203341742698412)
    assert aug.actual.value == pytest.approx(0.289795688101457)


def test_fetch_uses_the_keyless_json_url():
    calls = []

    def get_json(url, params=None):
        calls.append((url, params))
        return PAYLOAD

    history = fetch_nowcast_history(get_json=get_json)
    assert calls == [(NOWCAST_MONTH_URL, None)]
    assert set(history) == {date(2021, 12, 1), date(2025, 10, 1), date(2026, 8, 1)}
