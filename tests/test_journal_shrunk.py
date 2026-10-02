from datetime import UTC, datetime, timedelta

import pytest
from journal_fakes import FakeJournalDB

from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.forecasters.shrunk import ALLOWED_WEIGHTS, SHRINK_WEIGHT, MarketShrunk
from tradehub.journal.runner import run_journal

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
CUTOFF = NOW + timedelta(hours=10)


def _no_store():
    """For the tests that must never read the store (names, cadence, targets, settlement)."""
    raise AssertionError("this test should not reach the store")


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
    db = FakeJournalDB(lambda: NOW)
    inner = Inner(prob=0.80, market=0.50)
    run_journal(db, [inner, MarketShrunk(inner, lambda: db)], NOW)
    f = next(r for r in db.tables["journal_forecasts"] if r["forecaster"] == "model_x_cautious")
    assert f["probability"] == pytest.approx(0.575)       # 0.50 + 0.25 * (0.80 - 0.50)
    assert f["market_prob"] == 0.50                        # graded against the same market price
    assert f["payload"] == {"raw_probability": 0.80, "weight": 0.25}


def test_it_is_its_own_forecaster_so_the_pure_model_is_never_replaced():
    inner = Inner()
    fc = MarketShrunk(inner, _no_store)
    assert (fc.name, fc.version, fc.cadence) == ("model_x_cautious", "v1+w25", "daily")
    assert (inner.name, inner.version) == ("model_x", "v1")


def test_it_stays_inside_zero_and_one_at_the_extremes():
    """Through a real store now: the extremes are a property of `m + w*(p - m)`, and the store is the
    only place those numbers come from."""
    for model, market in ((1.0, 0.0), (0.0, 1.0), (1.0, 1.0)):
        db = FakeJournalDB(lambda: NOW)
        inner = Inner(prob=model, market=market)
        run_journal(db, [inner, MarketShrunk(inner, lambda store=db: store)], NOW)   # bound, not closed over
        rows = {r["forecaster"]: r for r in db.tables["journal_forecasts"]}
        assert 0.0 <= rows["model_x_cautious"]["probability"] <= 1.0


def test_with_no_market_price_there_is_nothing_to_shrink_toward_so_it_is_a_gap_not_a_guess():
    db = FakeJournalDB(lambda: NOW)
    inner = Inner(market=None)
    run_journal(db, [inner, MarketShrunk(inner, lambda: db)], NOW)
    frozen = {r["forecaster"] for r in db.tables["journal_forecasts"]}
    assert "model_x_cautious" not in frozen and "model_x" in frozen


def test_only_market_linked_targets_are_forecast():
    assert MarketShrunk(Inner(linked=False), _no_store).targets(NOW) == []


def test_settlement_is_the_inner_forecasters_not_a_second_opinion():
    inner = Inner()
    assert MarketShrunk(inner, _no_store).settle("kalshi:T1", NOW).outcome == 1 and inner.settled == ["kalshi:T1"]


def test_end_to_end_the_cautious_row_scores_beside_the_pure_one_on_the_same_target():
    db = FakeJournalDB(lambda: NOW)
    inner = Inner(prob=0.95, market=0.50)
    run_journal(db, [inner, MarketShrunk(inner, lambda: db)], NOW)
    later = CUTOFF + timedelta(hours=1)
    db.clock = lambda: later
    out = run_journal(db, [inner, MarketShrunk(inner, lambda: db)], later)
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
    assert len({(f.name, f.version) for f in FORECASTERS}) == len(FORECASTERS)


def test_raw_probability_is_the_inner_frozen_row_not_a_second_live_read():
    """A cautious row is a pure function of the pure model's FROZEN row. Reading the model a second
    time made `raw_probability` disagree with the row an auditor would compare it against: the
    runner drives the inner once for itself and again for the wrapper, at two different instants, so
    a moving quote or a refetched nowcast gave two different answers for the same contract."""
    db = FakeJournalDB(lambda: NOW)
    inner = Inner(prob=0.70, market=0.50)
    run_journal(db, [inner, MarketShrunk(inner, lambda: db)], NOW)

    frozen = {r["forecaster"]: r for r in db.tables["journal_forecasts"]}
    cautious = frozen["model_x_cautious"]

    assert cautious["payload"]["raw_probability"] == frozen["model_x"]["probability"]
    assert cautious["probability"] == pytest.approx(
        0.50 + SHRINK_WEIGHT * (frozen["model_x"]["probability"] - 0.50), abs=1e-9)


def test_a_changed_live_read_of_the_model_does_not_change_the_cautious_row():
    db = FakeJournalDB(lambda: NOW)
    inner = Inner(prob=0.70, market=0.50)
    run_journal(db, [inner, MarketShrunk(inner, lambda: db)], NOW)
    before = {r["forecaster"]: r["probability"] for r in db.tables["journal_forecasts"]}

    # Everything the model would read on a later call has moved. The cautious row is already frozen,
    # so this must change nothing; and if the target were re-judged it would not match `before`.
    inner.prob, inner.market = 0.95, 0.05
    later = CUTOFF + timedelta(hours=1)
    db.clock = lambda: later
    run_journal(db, [inner, MarketShrunk(inner, lambda: db)], later)

    after = {r["forecaster"]: r["probability"] for r in db.tables["journal_forecasts"]}
    assert after["model_x_cautious"] == before["model_x_cautious"]


def test_with_no_frozen_inner_row_it_is_a_gap_retried_next_hour_not_a_guess():
    """The runner runs the inner before the wrapper, so in production the row exists. When it does
    not -- a fresh deploy, an inner that missed its freeze -- there is nothing to shrink and the
    cautious target is a gap, frozen and scored on a later run rather than invented now."""
    db = FakeJournalDB(lambda: NOW)
    inner = Inner(prob=0.70, market=0.50)
    fc = MarketShrunk(inner, lambda: db)
    entry = fc.targets(NOW)[0]
    assert fc.forecast(entry, NOW) is None

    run_journal(db, [inner, fc], NOW)
    frozen = {r["forecaster"]: r for r in db.tables["journal_forecasts"]}
    assert frozen["model_x_cautious"]["payload"]["raw_probability"] == frozen["model_x"]["probability"]


def test_only_the_one_ruled_weight_is_allowed():
    """The weight is not free. Two weights within 0.005 of each other used to round to the same
    version string, and with UNIQUE (forecaster, forecaster_version, target) the second wrapper's
    freezes were refused while both models' rows blended into one scorecard."""
    assert ALLOWED_WEIGHTS == (0.25,)
    assert MarketShrunk.__init__.__defaults__ == (0.25,)
    for bad in (0.0, 0.1, 0.2, 0.24, 0.2510, 0.3, 0.5, 0.2549, 1.0):
        with pytest.raises(ValueError):
            MarketShrunk(Inner(), _no_store, bad)


def test_the_version_names_the_allowlisted_weight_not_a_rounded_arbitrary_one():
    inner = Inner()
    assert MarketShrunk(inner, _no_store).version == "v1+w25" == f"v1+w{round(ALLOWED_WEIGHTS[0] * 100)}"
