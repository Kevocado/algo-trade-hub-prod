import random
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from journal_fakes import FakeJournalDB

from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.engines.labor import CORE_FEATURES, LaborFeatures, add_months
from tradehub.engines.labor_direction import (
    UNRATE_UP,
    DirectionNowcast,
    climatology,
    direction_nowcast,
    up_probability,
    with_quits_feature,
)
from tradehub.journal.forecasters.labor import (
    LaborData,
    PayrollsForecaster,
    QuitsDirection,
    UnrateDirection,
    last_completed_month,
)
from tradehub.journal.runner import run_journal
from tradehub.markets import parse_market

NOW = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)  # 09:00 ET; September has ended
RELEASE = "2026-10-02T12:25:00Z"  # the KXPAYROLLS close, 5 minutes before the 08:30 ET release


def _pay(floor, bid=0.40, ask=0.44, close=RELEASE):
    event = "KXPAYROLLS-26SEP"
    market = parse_market({"ticker": f"{event}-T{floor}", "event_ticker": event, "strike_type": "greater",
                           "floor_strike": floor, "open_time": "2026-09-01T00:00:00Z", "close_time": close,
                           "title": f"payrolls > {floor}"})
    return LiveMarket(market, Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=10.0, yes_ask_size=10.0))


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def _table(n=96, seed=7):  # 2012-01..2019-12: clear of the COVID exclusion
    """Synthetic point-in-time features whose target is a known linear function plus noise."""
    rng = random.Random(seed)
    table, prints, month = {}, {}, date(2012, 1, 1)
    for _ in range(n):
        values = {f: rng.gauss(0, 1) for f in CORE_FEATURES}
        table[month] = LaborFeatures(month, values, ())
        prints[month] = 0.08 * values["icsa_ref_chg"] + rng.gauss(0, 0.05)
        month = add_months(month, 1)
    return table, prints, month


def test_up_probability_is_the_normal_tail_and_never_certain():
    assert up_probability(0.05, 0.1, 0.05) == pytest.approx(0.5)
    assert up_probability(10.0, 0.01, 0.05) < 1.0 and up_probability(-10.0, 0.01, 0.05) > 0.0


def test_climatology_needs_history_and_is_bounded():
    prints = {add_months(date(2012, 1, 1), k): 1.0 for k in range(30)}
    assert climatology(prints, date(2030, 1, 1), 0.5) == 0.98  # always up -> clamped, never certain
    assert climatology(dict(list(prints.items())[:10]), date(2030, 1, 1), 0.5) is None


def test_direction_nowcast_is_walk_forward_and_follows_the_features():
    table, prints, month = _table()
    table[month] = LaborFeatures(month, {f: 0.0 for f in CORE_FEATURES} | {"icsa_ref_chg": 3.0}, ())
    nc = direction_nowcast(table, prints, month, threshold=UNRATE_UP, min_sigma=0.05)
    assert nc.prob_up > 0.8  # claims surged -> unemployment likely up
    assert nc.model.n_train == 96  # only months strictly before `month`
    table[month] = LaborFeatures(month, {f: 0.0 for f in CORE_FEATURES} | {"icsa_ref_chg": -3.0}, ())
    assert direction_nowcast(table, prints, month, threshold=UNRATE_UP, min_sigma=0.05).prob_up < 0.2
    assert direction_nowcast(table, prints, add_months(month, 1), threshold=UNRATE_UP, min_sigma=0.05) is None


def test_quits_feature_is_the_latest_change_in_the_same_vintage():
    feats = LaborFeatures(date(2026, 9, 1), {"pay_last": 1.0}, ())
    vintage = {date(2026, 6, 1): 3200.0, date(2026, 7, 1): 3150.0}
    assert with_quits_feature(feats, vintage).values["quits_last"] == pytest.approx(-50.0)
    assert with_quits_feature(feats, {}) is None


def test_first_print_change_reads_the_first_vintage_that_contains_the_month():
    calls = []

    def fetch(series, days, **_):
        calls.append((series, days[0], days[-1]))
        before = {date(2026, 8, 1): 4.3}
        released = {date(2026, 8, 1): 4.3, date(2026, 9, 1): 4.5}
        revised = {date(2026, 8, 1): 4.3, date(2026, 9, 1): 4.4, date(2026, 10, 1): 4.4}
        return {d: (before if d < date(2026, 10, 2) else released if d < date(2026, 11, 6) else revised)
                for d in days}

    data = LaborData(load=None, fetch=fetch)
    assert data.first_print_change("UNRATE", date(2026, 9, 1), datetime(2026, 10, 2, 11, tzinfo=UTC)) is None
    later = datetime(2026, 11, 20, 12, tzinfo=UTC)  # after a revision: still the FIRST print
    assert data.first_print_change("UNRATE", date(2026, 9, 1), later) == pytest.approx(0.2)
    assert calls[-1][1] == date(2026, 9, 30)


def _nc(prob, clim=0.3):
    model = SimpleNamespace(n_train=100, features=("icsa_ref_chg",), coef=(0.1,))
    return DirectionNowcast(date(2026, 9, 1), 0.02, 0.1, prob, clim, model)


def test_payrolls_publish_the_existing_nowcast_on_every_strike():
    live = FakeLive([_pay(50000), _pay(100000)])
    nowcast = SimpleNamespace(mu=120.0, sigma=60.0, model=SimpleNamespace(n_train=150))
    fc = PayrollsForecaster(live, lambda t: {}, LaborData(load=None, fetch=None),
                            nowcasts_fn=lambda months, now: {date(2026, 9, 1): nowcast})
    entries = fc.targets(NOW)
    assert {e.target for e in entries} == {"kalshi:KXPAYROLLS-26SEP-T50000", "kalshi:KXPAYROLLS-26SEP-T100000"}
    probs = {e.target: fc.forecast(e, NOW).probability for e in entries}
    assert probs["kalshi:KXPAYROLLS-26SEP-T50000"] > probs["kalshi:KXPAYROLLS-26SEP-T100000"] > 0.5
    assert (fc.name, fc.version) == ("labor_nowcast", "labor-v1")


def test_payrolls_wait_for_the_reference_month_to_end():
    early = datetime(2026, 9, 30, 13, 0, tzinfo=UTC)
    fc = PayrollsForecaster(FakeLive([_pay(50000, close="2026-10-01T12:25:00Z")]), lambda t: {},
                            LaborData(load=None, fetch=None), nowcasts_fn=lambda months, now: {})
    assert fc.targets(early) == []


def test_unrate_direction_freezes_before_the_release_and_settles_on_the_first_print():
    clock = [NOW]
    db = FakeJournalDB(lambda: clock[0])
    fc = UnrateDirection(FakeLive([_pay(50000), _pay(100000)]), LaborData(load=None, fetch=None),
                         nowcast_fn=lambda month, now: _nc(0.7),
                         settle_fn=lambda month, now: 0.1 if now > datetime(2026, 10, 2, 13, tzinfo=UTC) else None)
    run_journal(db, [fc], clock[0])
    [cal] = db.tables["journal_calendars"]
    assert cal["target"] == "labor:unrate:2026-09:up" and cal["cutoff_at"] == "2026-10-02T12:25:00+00:00"
    assert cal["climatology_prob"] == 0.3 and cal["market_linked"] is False
    clock[0] = datetime(2026, 10, 3, 13, 0, tzinfo=UTC)
    out = run_journal(db, [fc], clock[0])
    assert out["forecasters"]["unrate_direction@unrate-dir-v1"]["settled"] == 1
    [settlement] = db.tables["journal_settlements"]
    assert settlement["outcome"] == 1 and settlement["realized_value"] == 0.1
    card = db.tables["journal_scores"][0]
    assert card["baseline"] == "climatology" and card["brier"] == pytest.approx(0.09)


def test_quits_direction_has_a_conservative_cutoff_and_no_market():
    fc = QuitsDirection(LaborData(load=None, fetch=None), nowcast_fn=lambda month, now: _nc(0.55),
                        settle_fn=lambda month, now: None)
    [entry] = fc.targets(NOW)
    assert entry.target == "labor:quits:2026-09:up" and not entry.market_linked
    assert entry.cutoff_at == datetime(2026, 10, 25, 0, 0, tzinfo=entry.cutoff_at.tzinfo)
    assert fc.forecast(entry, NOW).market_prob is None
    assert fc.targets(datetime(2026, 10, 26, tzinfo=UTC)) == []  # past the cutoff: nothing new
    assert last_completed_month(NOW) == date(2026, 9, 1)
    assert last_completed_month(NOW - timedelta(hours=10)) == date(2026, 8, 1)  # 23:00 ET on Sep 30


def test_the_registry_runs_the_labor_forecasters():
    from tradehub.journal.registry import FORECASTERS

    keys = {(f.name, f.version) for f in FORECASTERS}
    assert {("labor_nowcast", "labor-v1"), ("kalshi_implied_labor", "v1"), ("unrate_direction", "unrate-dir-v1"),
            ("quits_direction", "quits-dir-v1")} <= keys
