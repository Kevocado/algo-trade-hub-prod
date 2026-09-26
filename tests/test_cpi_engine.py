from datetime import date, datetime, timedelta, timezone

import pytest

from tradehub.backtest.pit import Observation
from tradehub.data.cleveland_fed import MonthNowcast
from tradehub.engines.cpi import (
    CPI_TARGETS,
    DEFAULT_CPI_ERROR,
    MIN_CPI_SIGMA,
    CpiErrorModel,
    cpi_prob,
    fit_cpi_error,
    latest_nowcast,
    training_pairs,
)
from tradehub.markets import parse_cpi_market

UTC = timezone.utc


def _month(year, mon, nowcast, actual, release_day=12):
    """A month whose nowcast is known from the 1st and 10th of the next month, printed on `release_day`."""
    month = date(year, mon, 1)
    nxt = date(year + (mon == 12), mon % 12 + 1, 1)
    tag = f"CPI:{month:%Y-%m}"
    path = (
        Observation(f"{tag}@a", nowcast - 0.2, datetime(nxt.year, nxt.month, 1, 4, tzinfo=UTC)),
        Observation(f"{tag}@b", nowcast, datetime(nxt.year, nxt.month, 10, 4, tzinfo=UTC)),
    )
    released = datetime(nxt.year, nxt.month, release_day, 12, 30, tzinfo=UTC)
    return MonthNowcast(month, path, None if actual is None else Observation(f"{tag}:actual", actual, released))


def _market(strike, event="KXCPI-26AUG", close="2026-09-11T12:25:00Z"):
    return parse_cpi_market({"ticker": f"{event}-T{strike}", "event_ticker": event, "strike_type": "greater",
                             "floor_strike": strike, "open_time": "2026-07-23T21:00:00Z", "close_time": close,
                             "title": "CPI"})


def test_targets_cover_headline_and_core():
    assert CPI_TARGETS == {"KXCPI": ("headline", "cpi-v1"), "KXCPICORE": ("core", "cpi-core-v1")}


def test_latest_nowcast_respects_publication_time():
    m = _month(2026, 8, 0.36, 0.40)
    assert latest_nowcast(m, datetime(2026, 9, 5, tzinfo=UTC)).name == "CPI:2026-08@a"
    assert latest_nowcast(m, datetime(2026, 9, 11, tzinfo=UTC)).name == "CPI:2026-08@b"
    assert latest_nowcast(m, datetime(2026, 8, 20, tzinfo=UTC)) is None
    assert latest_nowcast(None, datetime(2026, 9, 11, tzinfo=UTC)) is None


def test_training_pairs_only_use_released_months_at_the_same_horizon():
    history = {m.month: m for m in (_month(2026, 6, 0.20, 0.30), _month(2026, 7, 0.10, 0.10),
                                    _month(2026, 8, 0.36, 0.40))}
    as_of = datetime(2026, 9, 1, tzinfo=UTC)  # July printed Aug 12; August not printed yet
    pairs = training_pairs(history, as_of, timedelta(minutes=25))
    assert [a.name for _, a in pairs] == ["CPI:2026-06:actual", "CPI:2026-07:actual"]
    assert all(n.published_at <= as_of and a.published_at <= as_of for n, a in pairs)
    assert [n.name for n, _ in pairs] == ["CPI:2026-06@b", "CPI:2026-07@b"]
    # Five days before release, only the early nowcast ("@a", known on the 1st) was available.
    early = training_pairs(history, as_of, timedelta(days=5))
    assert [n.name for n, _ in early] == ["CPI:2026-06@a", "CPI:2026-07@a"]


def _pairs(errors):
    out = []
    for i, err in enumerate(errors):
        t = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=31 * i)
        out.append((Observation(f"n{i}", 0.2, t), Observation(f"a{i}", 0.2 + err, t + timedelta(days=1))))
    return out


def test_fit_defaults_until_enough_history():
    assert fit_cpi_error(_pairs([0.1] * 11)) == DEFAULT_CPI_ERROR


def test_fit_is_rms_error_without_bias_and_uses_the_recent_window():
    model = fit_cpi_error(_pairs([0.5] * 10 + [0.1, -0.1] * 12), window=24)
    assert model.bias == 0.0
    assert model.sigma == pytest.approx(0.1)  # the ten old 0.5 errors fall outside the window
    biased = fit_cpi_error(_pairs([0.2, 0.0] * 12), use_bias=True)
    assert biased.bias == pytest.approx(0.1) and biased.sigma == pytest.approx(0.1)


def test_fit_floors_sigma():
    assert fit_cpi_error(_pairs([0.0] * 24)).sigma == MIN_CPI_SIGMA


def test_cpi_prob_uses_one_decimal_thresholds():
    model = CpiErrorModel(bias=0.0, sigma=0.1)
    # "more than 0.3" is YES iff the print rounds to >= 0.4, i.e. unrounded > 0.35.
    assert cpi_prob(_market(0.3), 0.35, model) == pytest.approx(0.5)
    assert cpi_prob(_market(0.4), 0.36, model) < 0.2
    assert cpi_prob(_market(-0.4), 0.36, model) > 0.999
    assert cpi_prob(_market(0.3), 0.30, CpiErrorModel(bias=0.05, sigma=0.1)) == pytest.approx(0.5)
