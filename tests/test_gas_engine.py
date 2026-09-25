import math
import statistics
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from tradehub.backtest.pit import Observation
from tradehub.data.rbob import front_month_roll_dates, rbob_closes
from tradehub.engines.gas import (
    DEFAULT_GAS,
    MIN_GAS_SIGMA,
    GasModel,
    fit_gas_model,
    gas_prob,
    gas_training_pairs,
    rbob_change,
    rbob_change_window,
)
from tradehub.markets import parse_market, prob_in_interval

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
GAS = {"ticker": "KXAAAGASD-26SEP25-4.5200", "event_ticker": "KXAAAGASD-26SEP25", "strike_type": "greater",
       "floor_strike": 4.52, "cap_strike": None, "open_time": "2026-09-24T14:00:00Z",
       "close_time": "2026-09-25T03:59:00Z", "title": "US gas price"}


def test_rbob_closes_publishes_at_1800_new_york():
    frame = pd.DataFrame({"Close": [3.30, 3.40]},
                         index=pd.DatetimeIndex(["2026-09-22", "2026-09-23"]).tz_localize("America/New_York"))
    obs = rbob_closes(history_fn=lambda: frame)
    assert [o.name for o in obs] == ["RBOB:RBV26.NYM:2026-09-22", "RBOB:RBV26.NYM:2026-09-23"]
    assert obs[0].published_at == datetime(2026, 9, 22, 22, 0, tzinfo=timezone.utc)  # 18:00 EDT
    assert obs[1].value == pytest.approx(3.40)


def test_rbob_closes_assigns_front_month_by_nymex_roll_without_metadata():
    frame = pd.DataFrame(
        {"Close": [3.30, 3.40]},
        index=pd.DatetimeIndex(["2026-08-31", "2026-09-01"]).tz_localize("America/New_York"),
    )

    obs = rbob_closes(history_fn=lambda: frame)

    assert [o.name for o in obs] == ["RBOB:RBU26.NYM:2026-08-31", "RBOB:RBV26.NYM:2026-09-01"]
    roll_dates = front_month_roll_dates(date(2026, 8, 1), date(2026, 9, 30))
    assert rbob_change(obs, datetime(2026, 9, 2, tzinfo=timezone.utc), window=1, roll_dates=roll_dates) is None


def test_front_month_roll_dates_are_last_business_days_before_delivery():
    assert front_month_roll_dates(date(2026, 7, 1), date(2026, 10, 1)) == [
        date(2026, 7, 31),
        date(2026, 8, 31),
        date(2026, 9, 30),
    ]


def test_rbob_closes_preserves_explicit_contract_metadata():
    frame = pd.DataFrame(
        {"Close": [3.30, 3.40], "Contract": ["RBU26.NYM", "RBV26.NYM"]},
        index=pd.DatetimeIndex(["2026-08-31", "2026-09-01"]).tz_localize("America/New_York"),
    )

    obs = rbob_closes(history_fn=lambda: frame)

    assert [o.name for o in obs] == ["RBOB:RBU26.NYM:2026-08-31", "RBOB:RBV26.NYM:2026-09-01"]


def test_rbob_closes_passes_backtest_bounds_to_history():
    calls = []
    frame = pd.DataFrame(
        {"Close": [3.3]},
        index=pd.DatetimeIndex(["2026-07-01"]).tz_localize("America/New_York"),
    )

    def history_fn(start=None, end=None):
        calls.append({"start": start, "end": end})
        return frame

    rbob_closes(start=date(2026, 7, 1), end=date(2026, 7, 24), history_fn=history_fn)

    assert calls == [{"start": date(2026, 7, 1), "end": date(2026, 7, 24)}]


def _rbob(values):
    return [Observation(f"RBOB:RBU26.NYM:{i}", v, T0 + timedelta(days=i)) for i, v in enumerate(values)]


def test_rbob_change_uses_only_known_closes():
    closes = _rbob([3.0, 3.1, 3.2, 3.3, 3.4, 3.5, 9.9])
    assert rbob_change(closes, T0 + timedelta(days=5), window=5) == pytest.approx(0.5)
    assert rbob_change(closes, T0 + timedelta(days=4), window=5) is None


def test_rbob_change_drops_windows_spanning_a_front_month_roll():
    closes = [
        Observation("RBOB:RBU26.NYM:2026-08-17", 3.20, T0),
        Observation("RBOB:RBU26.NYM:2026-08-18", 3.30, T0 + timedelta(days=1)),
        Observation("RBOB:RBU26.NYM:2026-08-19", 3.40, T0 + timedelta(days=2)),
        Observation("RBOB:RBV26.NYM:2026-08-20", 3.00, T0 + timedelta(days=3)),
        Observation("RBOB:RBV26.NYM:2026-08-21", 3.10, T0 + timedelta(days=4)),
        Observation("RBOB:RBV26.NYM:2026-08-24", 3.10, T0 + timedelta(days=5)),
        Observation("RBOB:RBV26.NYM:2026-08-25", 3.20, T0 + timedelta(days=6)),
        Observation("RBOB:RBV26.NYM:2026-08-26", 3.30, T0 + timedelta(days=7)),
        Observation("RBOB:RBV26.NYM:2026-08-27", 3.40, T0 + timedelta(days=8)),
    ]

    assert rbob_change(closes, T0 + timedelta(days=5), window=5) is None
    assert rbob_change(closes, T0 + timedelta(days=8), window=5) == pytest.approx(0.40)
    assert rbob_change_window(closes, T0 + timedelta(days=8), window=5)[1][0].name.startswith("RBOB:RBV26.NYM:")


def test_rbob_change_allows_same_contract_window_ending_on_roll_date():
    closes = [
        Observation("RBOB:RBU26.NYM:2026-08-27", 3.10, T0),
        Observation("RBOB:RBU26.NYM:2026-08-28", 3.20, T0 + timedelta(days=1)),
        Observation("RBOB:RBU26.NYM:2026-08-31", 3.30, T0 + timedelta(days=2)),
    ]

    result = rbob_change_window(
        closes,
        T0 + timedelta(days=2),
        window=2,
        roll_dates=[date(2026, 8, 31)],
    )

    assert result is not None and result[0] == pytest.approx(0.20)


def test_gas_training_pairs_consecutive_days_only():
    rbob = _rbob([3.0] * 6 + [3.5] * 10)
    aaa = [Observation("KXAAAGASD-26SEP10", 4.40, T0 + timedelta(days=9, hours=12)),
           Observation("KXAAAGASD-26SEP11", 4.42, T0 + timedelta(days=10, hours=12)),
           Observation("KXAAAGASD-26SEP13", 4.50, T0 + timedelta(days=12, hours=12))]  # gap: no pair
    pairs = gas_training_pairs(aaa, rbob)
    assert len(pairs) == 1
    x, y, published = pairs[0]
    assert y == pytest.approx(0.02) and published == aaa[1].published_at
    assert x == pytest.approx(rbob_change(rbob, aaa[0].published_at))


def test_fit_gas_model_recovers_linear_relation_and_defaults():
    assert fit_gas_model([(0.1, 0.01)] * 5) == DEFAULT_GAS
    pairs = [(x / 100, 0.001 + 0.05 * (x / 100) + (0.003 if x % 2 else -0.003)) for x in range(-20, 21)]
    model = fit_gas_model(pairs)
    assert model.beta == pytest.approx(0.05, abs=0.01)
    assert model.alpha == pytest.approx(0.001, abs=0.001)
    assert model.sigma >= MIN_GAS_SIGMA


def test_fit_gas_model_without_rbob_uses_aaa_daily_sigma_with_zero_beta():
    start = date(2026, 9, 1)
    aaa = [
        Observation(
            f"KXAAAGASD-{(start + timedelta(days=index)).strftime('%y%b%d').upper()}",
            4.0 + index * 0.001 + (0.01 if index % 2 else -0.01),
            T0 + timedelta(days=index, hours=12),
        )
        for index in range(41)
    ]
    changes = [current.value - previous.value for previous, current in zip(aaa, aaa[1:])]

    model = fit_gas_model([], aaa=aaa)

    assert model.alpha == pytest.approx(statistics.fmean(changes))
    assert model.beta == 0.0
    assert model.sigma == pytest.approx(max(MIN_GAS_SIGMA, statistics.stdev(changes)))
    assert model.sigma != pytest.approx(DEFAULT_GAS.sigma)


def test_gas_prob_normal_model_and_horizon_scaling():
    m = parse_market(GAS)
    model = GasModel(alpha=0.0, beta=0.1, sigma=0.01)
    p1 = gas_prob(m, 4.51, 1, 0.1, model)  # mu = 4.52
    assert p1 == pytest.approx(prob_in_interval(4.52, 0.01, (4.52005, math.inf)))
    assert gas_prob(m, 4.51, 1, None, model) < p1
    with pytest.raises(ValueError):
        gas_prob(m, 4.51, 0, 0.1, model)
