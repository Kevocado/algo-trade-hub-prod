from datetime import UTC, datetime, timedelta

import pytest
from journal_fakes import FakeJournalDB

from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.forecasters.shrunk import ALLOWED_WEIGHTS, SHRINK_WEIGHT, SUFFIX, MarketShrunk
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
    run_journal(db, [inner, MarketShrunk(inner, lambda store=db: store)], NOW)
    f = next(r for r in db.tables["journal_forecasts"] if r["forecaster"] == "model_x_cautious")
    assert f["probability"] == pytest.approx(0.575)       # 0.50 + 0.25 * (0.80 - 0.50)
    assert f["market_prob"] == 0.50                        # graded against the same market price
    assert f["payload"] == {"k": 1, "raw_probability": 0.80, "weight": 0.25}   # k rides over


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
        want = pytest.approx(market + 0.25 * (model - market))
        assert rows["model_x_cautious"]["probability"] == want
        assert 0.0 <= rows["model_x_cautious"]["probability"] <= 1.0


def test_with_no_market_price_there_is_nothing_to_shrink_toward_so_it_is_a_gap_not_a_guess():
    db = FakeJournalDB(lambda: NOW)
    inner = Inner(market=None)
    out = run_journal(db, [inner, MarketShrunk(inner, lambda store=db: store)], NOW)
    assert not out["failures"], out["failures"]   # a throw would be swallowed into here, not seen as a gap
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
    run_journal(db, [inner, MarketShrunk(inner, lambda store=db: store)], NOW)
    later = CUTOFF + timedelta(hours=1)
    db.clock = lambda: later
    out = run_journal(db, [inner, MarketShrunk(inner, lambda store=db: store)], later)
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
    run_journal(db, [inner, MarketShrunk(inner, lambda store=db: store)], NOW)

    frozen = {r["forecaster"]: r for r in db.tables["journal_forecasts"]}
    cautious = frozen["model_x_cautious"]

    assert cautious["payload"]["raw_probability"] == frozen["model_x"]["probability"]
    assert cautious["probability"] == pytest.approx(
        0.50 + SHRINK_WEIGHT * (frozen["model_x"]["probability"] - 0.50), abs=1e-9)


def test_a_changed_live_read_of_the_model_does_not_change_the_cautious_row():
    """The F1 guard, and it only works if the model's read actually MOVES.

    A constant inner cannot tell a frozen-row wrapper from a live-read one: both see the same number.
    So this inner returns a different probability on every call, as a live quote would, and the
    cautious row must be the function of the first (frozen) read only.
    """
    class Moving:
        name, version, cadence = "model_x", "v1", "daily"

        def __init__(self):
            self.calls = 0

        def targets(self, now):
            return [CalendarEntry("kalshi:T1", "fam", "daily", CUTOFF, market_linked=True)]

        def forecast(self, entry, now):
            self.calls += 1
            return Forecast(self.name, self.version, entry.target, 0.70 if self.calls == 1 else 0.95,
                            market_prob=0.50, payload={})

        def settle(self, target, now):
            return Settlement(target, 1, "test")

    db = FakeJournalDB(lambda: NOW)
    inner = Moving()
    run_journal(db, [inner, MarketShrunk(inner, lambda store=db: store)], NOW)

    rows = {r["forecaster"]: r for r in db.tables["journal_forecasts"]}
    assert rows["model_x"]["probability"] == pytest.approx(0.70)
    # The inner was read ONCE, for its own row. A live-read wrapper reads it twice and would freeze
    # 0.95 here, which is the defect this whole change exists to remove.
    assert inner.calls == 1
    assert rows["model_x_cautious"]["payload"]["raw_probability"] == pytest.approx(0.70)
    assert rows["model_x_cautious"]["probability"] == pytest.approx(0.55)   # 0.50 + 0.25*(0.70-0.50)


def test_with_no_frozen_inner_row_it_is_a_gap_retried_next_hour_not_a_guess():
    """The runner runs the inner before the wrapper, so in production the row exists. When it does
    not -- a fresh deploy, an inner that missed its freeze -- there is nothing to shrink and the
    cautious target is a gap, frozen and scored on a later run rather than invented now."""
    db = FakeJournalDB(lambda: NOW)
    inner = Inner(prob=0.70, market=0.50)
    fc = MarketShrunk(inner, lambda store=db: store)
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


def test_the_inners_payload_is_carried_over_so_the_cost_gate_can_still_net_fees():
    """Regression guard for a real break: the wrapper replaced `{**raw.payload, ...}` with a bare
    `{"raw_probability", "weight"}`, so every cautious card scored `n_quoted == 0` and `scoring.py`
    closed its cost gate with "no frozen quotes recorded, so edge cannot be netted of fees and
    spread" -- for all ten cautious forecasters, whose baseline is the market. The payload lives on
    the frozen row, so carrying it costs nothing and F1 is untouched."""
    class Quoted(Inner):
        def forecast(self, entry, now):
            return Forecast(self.name, self.version, entry.target, self.prob, market_prob=self.market,
                            payload={"yes_bid": 0.54, "yes_ask": 0.56, "nowcast_obs": 0.3})

    db = FakeJournalDB(lambda: NOW)
    inner = Quoted(prob=0.75, market=0.55)
    run_journal(db, [inner, MarketShrunk(inner, lambda store=db: store)], NOW)

    row = next(r for r in db.tables["journal_forecasts"] if r["forecaster"] == "model_x_cautious")
    assert row["payload"]["yes_bid"] == 0.54 and row["payload"]["yes_ask"] == 0.56
    assert row["payload"]["raw_probability"] == pytest.approx(0.75)
    assert row["payload"]["nowcast_obs"] == 0.3

    from tradehub.journal.scoring import score
    frozen = {r["target"]: r for r in db.tables["journal_forecasts"]}
    settled = {"kalshi:T1": 1}
    calendar = {"kalshi:T1": {"cutoff_at": CUTOFF.isoformat(), "cadence": "daily"}}
    cautious_card = score([frozen["kalshi:T1"]], settled, calendar, "daily")
    assert cautious_card["costs"]["n_quoted"] == 1, cautious_card["costs"]
    assert not [r for r in cautious_card["gate_reasons"] if "frozen quotes" in r], cautious_card["gate_reasons"]


def test_the_store_must_be_a_callable_not_a_client():
    """PR #73's signature was `MarketShrunk(inner, weight=0.25)`, so `MarketShrunk(inner, 0.5)` from
    an old call site constructs silently -- store=0.5 -- and only fails mid-run. Fail at construction."""
    with pytest.raises(TypeError):
        MarketShrunk(Inner(), 0.5)


def test_the_store_history_is_read_once_an_hour_not_once_per_target(monkeypatch):
    """Counts `shrunk.fetch_forecasts` calls, which is precisely what the per-hour cache governs.

    Counting the client instead would also count the runner's own reads, which the cache has nothing
    to do with -- and counting the constructor's factory counted nothing at all once `bind_store` began
    overriding it, which is the correct behaviour and the reason this had to be measured differently.
    """
    import tradehub.journal.forecasters.shrunk as shrunk_mod

    db = FakeJournalDB(lambda: NOW)
    real = shrunk_mod.fetch_forecasts
    reads = []

    def counting(supa, forecaster, version):
        reads.append(forecaster)
        return real(supa, forecaster, version)

    monkeypatch.setattr(shrunk_mod, "fetch_forecasts", counting)
    inner = _ManyTargets(6)
    run_journal(db, [inner, MarketShrunk(inner, lambda: db)], NOW)

    assert len(reads) == 1, f"{len(reads)} store reads for 6 targets; the history should be read once"


class _ManyTargets(Inner):
    def __init__(self, n):
        super().__init__()
        self.n = n

    def targets(self, now):
        return [CalendarEntry(f"kalshi:T{i}", "fam", "daily", CUTOFF, market_linked=True) for i in range(self.n)]

    def forecast(self, entry, now):
        return Forecast(self.name, self.version, entry.target, 0.70, market_prob=0.50, payload={})


def test_the_version_names_the_weight_that_was_applied(monkeypatch):
    """Kills the resurrection of F3. With one weight in the allowlist, `ALLOWED_WEIGHTS[0]` and
    `self.weight` are the same number, so the version string cannot reveal which one the code used --
    and building the key from the allowlist entry would label a 0.5-weighted scorecard `w25` the moment
    a second weight is allowed, which is the collision this whole change exists to prevent. So allow a
    second weight HERE and require the version to follow the weight actually applied."""
    import tradehub.journal.forecasters.shrunk as shrunk_mod
    monkeypatch.setattr(shrunk_mod, "ALLOWED_WEIGHTS", (0.25, 0.5))

    assert MarketShrunk(Inner(), _no_store, 0.5).version == "v1+w50"
    assert MarketShrunk(Inner(), _no_store, 0.25).version == "v1+w25"


def test_the_headline_excludes_the_cautious_copy_by_the_wrappers_own_constant():
    """The four-copies defect: `SUFFIX` here, plus three hand-typed `"_cautious"` literals in
    `scoring.py`, `journalView.ts` and `forecasterLabels.ts`. Renaming the constant while the consumers
    kept the old string would return the double count that #78 fixed, with a fully green suite.
    `headline` must consult this module's constant, so the test holds whichever way the name goes."""
    from tradehub.journal.scoring import headline

    model = {"forecaster": "cpi_nowcast", "forecaster_version": "cpi-v1", "n_settled": 60,
             "calibration_ready": True, "gate_status": "SHADOW"}
    copy = {"forecaster": f"cpi_nowcast{SUFFIX}", "forecaster_version": "cpi-v1+w25", "n_settled": 60,
            "calibration_ready": True, "gate_status": "SHADOW"}

    assert headline([model, copy])["settled_calibrated"] == 60
    assert headline([model])["settled_calibrated"] == 60


def test_the_consumers_import_the_suffix_instead_of_retyping_it():
    """Runtime tests cannot catch this one: retyping the literal produces the same string and the same
    behaviour, so every assertion still passes. The defect only appears later, when someone renames
    `SUFFIX` -- at which point the consumers keep matching the old string and stop excluding copies.
    So this reads the source instead: each consumer must import the constant, and none may carry its
    own copy of the string.

    The frontend pair is checked by reading the two files as text; `tradehub/` by import."""
    import pathlib

    from tradehub.journal import scoring
    from tradehub.journal.forecasters import shrunk

    assert scoring._cautious(f"x{SUFFIX}") and not scoring._cautious("x")
    assert shrunk.SUFFIX == SUFFIX, "the test and the module disagree about the constant"

    # The TypeScript side is a separate build, so it needs its own constant -- but exactly ONE, which
    # lives in forecasterLabels (the same module the labels come from). journalView imports it rather
    # than retyping it, so a rename is one edit in two languages instead of four scattered ones.
    repo = pathlib.Path(__file__).resolve().parents[1] / "market_sentiment_tool" / "src"
    labels = (repo / "lib/forecasterLabels.ts").read_text()
    view = (repo / "lib/journalView.ts").read_text()
    assert f'CAUTIOUS_SUFFIX = "{SUFFIX}"' in labels, "forecasterLabels no longer defines the suffix"
    assert SUFFIX not in view, "journalView retypes the literal instead of importing it"
    assert "CAUTIOUS_SUFFIX" in view and "forecasterLabels" in view, "journalView must import it"


def test_the_cautious_row_reads_the_clients_the_run_was_given_not_the_singleton():
    """The wrapper is handed a `store` callable, and the registry wires it to `get_client`. So a run
    given a DIFFERENT client -- a test fake, a replay, a dry run against another project -- would write
    the pure rows to that client and read the cautious rows from production. Two stores, one scorecard.

    The runner therefore binds its own client onto any wrapper before driving it, so the cautious row
    is a function of the same store the pure row was frozen into.
    """
    run_db = FakeJournalDB(lambda: NOW)
    other_db = FakeJournalDB(lambda: NOW)
    inner = Inner(prob=0.70, market=0.50)
    wrapper = MarketShrunk(inner, lambda: other_db)          # deliberately the WRONG client

    out = run_journal(run_db, [inner, wrapper], NOW)

    assert not out["failures"], out["failures"]
    frozen = {r["forecaster"]: r for r in run_db.tables["journal_forecasts"]}
    assert frozen["model_x_cautious"]["payload"]["raw_probability"] == pytest.approx(0.70)
    assert not other_db.tables["journal_forecasts"], "the cautious row was frozen into the other store"
