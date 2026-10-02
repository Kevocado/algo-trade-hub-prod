from datetime import UTC, datetime, timedelta

import pytest
from journal_fakes import FakeJournalDB

from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.forecasters.shrunk import SHRINK_WEIGHT, MarketShrunk
from tradehub.journal.runner import run_journal

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
CUTOFF = NOW + timedelta(hours=10)


class Inner:
    name, version, cadence = "model_x", "v1", "daily"

    def __init__(self, prob=0.80, market=0.50, linked=True):
        self.prob, self.market, self.linked = prob, market, linked
        self.settled = []

    def targets(self, now):
        return [CalendarEntry("kalshi:T1", "fam", "daily", CUTOFF, market_linked=self.linked)]

    def forecast(self, entry, now):
        return Forecast(self.name, self.version, entry.target, self.prob, market_prob=self.market, payload={"k": 1})

    def settle(self, target, now):
        self.settled.append(target)
        return Settlement(target, 1, "test")


def test_the_weight_is_fixed_before_any_result_is_seen():
    assert SHRINK_WEIGHT == 0.25


def test_the_forecast_moves_a_quarter_of_the_way_from_the_market_to_the_model():
    fc = MarketShrunk(Inner(prob=0.80, market=0.50))
    f = fc.forecast(fc.targets(NOW)[0], NOW)
    assert f.probability == pytest.approx(0.575)          # 0.50 + 0.25 * (0.80 - 0.50)
    assert f.market_prob == 0.50                           # graded against the same market price
    assert f.payload == {"k": 1, "raw_probability": 0.80, "weight": 0.25}


def test_it_is_its_own_forecaster_so_the_pure_model_is_never_replaced():
    inner = Inner()
    fc = MarketShrunk(inner)
    assert (fc.name, fc.version, fc.cadence) == ("model_x_cautious", "v1+w25", "daily")
    assert (inner.name, inner.version) == ("model_x", "v1")


def test_it_stays_inside_zero_and_one_at_the_extremes():
    for model, market in ((1.0, 0.0), (0.0, 1.0), (1.0, 1.0)):
        f = MarketShrunk(Inner(model, market)).forecast(CalendarEntry("kalshi:T1", "f", "daily", CUTOFF), NOW)
        assert 0.0 <= f.probability <= 1.0


def test_with_no_market_price_there_is_nothing_to_shrink_toward_so_it_is_a_gap_not_a_guess():
    fc = MarketShrunk(Inner(market=None))
    assert fc.forecast(fc.targets(NOW)[0], NOW) is None


def test_only_market_linked_targets_are_forecast():
    assert MarketShrunk(Inner(linked=False)).targets(NOW) == []


def test_settlement_is_the_inner_forecasters_not_a_second_opinion():
    inner = Inner()
    assert MarketShrunk(inner).settle("kalshi:T1", NOW).outcome == 1 and inner.settled == ["kalshi:T1"]


def test_end_to_end_the_cautious_row_scores_beside_the_pure_one_on_the_same_target():
    db = FakeJournalDB(lambda: NOW)
    inner = Inner(prob=0.95, market=0.50)
    run_journal(db, [inner, MarketShrunk(inner)], NOW)
    later = CUTOFF + timedelta(hours=1)
    db.clock = lambda: later
    out = run_journal(db, [inner, MarketShrunk(inner)], later)
    assert not out["failures"]
    rows = {r["forecaster"]: r for r in db.tables["journal_forecasts"]}
    assert rows["model_x"]["probability"] == pytest.approx(0.95)
    assert rows["model_x_cautious"]["probability"] == pytest.approx(0.6125)
    cards = {r["forecaster"]: r for r in db.tables["journal_scores"]}
    assert cards["model_x_cautious"]["n_settled"] == cards["model_x"]["n_settled"] == 1
    # the event happened (outcome 1): the pure model is closer, so it must have the lower Brier here;
    # the point is that both are scored on identical targets and the market price is the baseline
    assert cards["model_x"]["baseline"] == cards["model_x_cautious"]["baseline"] == "market"


def test_the_registry_wraps_every_market_linked_model_and_no_pseudo_forecaster():
    from tradehub.journal.registry import FORECASTERS

    names = [f.name for f in FORECASTERS]
    for expected in ("cpi_nowcast_cautious", "labor_nowcast_cautious", "fomc_mapped_cautious",
                     "sports_nfl_cautious", "sports_cfb_spread_cautious", "sports_nfl_total_cautious"):
        assert expected in names
    assert not any(n.startswith("kalshi_implied_") and n.endswith("_cautious") for n in names)
    assert not any(n in names for n in ("spy_quant_cautious", "housing_direction_cautious"))  # no market price
    assert len(set((f.name, f.version) for f in FORECASTERS)) == len(FORECASTERS)