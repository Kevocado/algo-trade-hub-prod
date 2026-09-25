import json
import math
from datetime import date
from pathlib import Path

import pytest

from tradehub.markets import event_month, parse_cpi_market, prob_in_interval, yes_interval

RAWS = {r["ticker"]: r for r in json.loads(
    (Path(__file__).parent / "fixtures" / "kalshi_cpi_markets_trimmed.json").read_text(encoding="utf-8"))}


def test_event_month_parses_month_only_tickers():
    assert event_month("KXCPI-26AUG") == date(2026, 8, 1)
    assert event_month("CPI-21DEC") == date(2021, 12, 1)
    assert event_month("KXCPICORE-26SEP") == date(2026, 9, 1)
    assert event_month("KXCPICORE-25DECT") == date(2025, 12, 1)  # real settled event ticker


def test_parse_cpi_market_keeps_modern_strikes():
    m = parse_cpi_market(RAWS["KXCPI-26AUG-T0.4"])
    assert m.strike_type == "greater" and m.floor_strike == pytest.approx(0.4)
    assert m.series_ticker == "KXCPI"
    lo, hi = yes_interval(m, 0.1)
    assert lo == pytest.approx(0.45) and hi == math.inf  # YES iff the one-decimal print is >= 0.5


def test_parse_cpi_market_infers_legacy_strikes_from_ticker():
    neg = parse_cpi_market(RAWS["CPI-22AUG-TN0.4"])
    pos = parse_cpi_market(RAWS["CPI-21JUN-T0.6"])
    assert neg.strike_type == "greater" and neg.floor_strike == pytest.approx(-0.4)
    assert pos.floor_strike == pytest.approx(0.6) and pos.series_ticker == "CPI"


def test_core_greater_market_with_cap_equal_floor_is_accepted():
    m = parse_cpi_market(RAWS["KXCPICORE-26SEP-T0.3"])
    assert m.cap_strike == pytest.approx(0.3)
    assert yes_interval(m, 0.1)[0] == pytest.approx(0.35)
    assert 0.0 < prob_in_interval(0.3, 0.1, yes_interval(m, 0.1)) < 0.5


def test_settled_results_agree_with_the_one_decimal_rule():
    # Aug 2026 printed 0.4: "more than 0.3" is YES, "more than 0.4" is NO.
    for ticker, expected in (("KXCPI-26AUG-T0.3", "yes"), ("KXCPI-26AUG-T0.4", "no")):
        lo, _ = yes_interval(parse_cpi_market(RAWS[ticker]), 0.1)
        assert ("yes" if 0.4 > lo else "no") == RAWS[ticker]["result"] == expected


def test_parse_cpi_market_rejects_unparseable_tickers():
    with pytest.raises(ValueError):
        parse_cpi_market(dict(RAWS["CPI-21JUN-T0.6"], ticker="CPI-21JUN-B0.6"))
