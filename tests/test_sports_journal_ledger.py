from datetime import UTC, datetime, timedelta

from journal_fakes import FakeJournalDB

from tradehub.journal.forecasters.sports import FEED_VERSION
from tradehub.sports import scan as scan_mod
from tradehub.sports.journal_ledger import HUB_FEED_VERSION, journal_settled_ledger

NOW = datetime(2026, 9, 27, 2, 0, tzinfo=UTC)


def _seed(db, forecaster, target, prob, outcome, *, version=FEED_VERSION):
    """One frozen forecast and, when `outcome` is not None, its settlement, via the fake's own rules."""
    clock = db.clock
    if not any(c["target"] == target for c in db.tables["journal_calendars"]):
        db.insert("journal_calendars", {"target": target, "family": "f", "cadence": "daily",
                                        "cutoff_at": (NOW + timedelta(hours=10)).isoformat(),
                                        "market_linked": True, "climatology_prob": None})
    db.insert("journal_forecasts", {"forecaster": forecaster, "forecaster_version": version, "target": target,
                                    "probability": prob, "market_prob": None, "source_hash": None, "payload": {}})
    if outcome is not None:
        db.clock = lambda: NOW + timedelta(hours=11)
        if not any(s["target"] == target for s in db.tables["journal_settlements"]):
            db.insert("journal_settlements", {"target": target, "outcome": outcome, "realized_value": None,
                                              "source": "kalshi"})
        db.clock = clock


def _db():
    return FakeJournalDB(lambda: NOW)


def test_the_hub_reads_the_feed_version_the_journal_writes():
    assert HUB_FEED_VERSION == FEED_VERSION


def test_each_kind_is_read_from_its_own_forecaster_and_filed_under_the_hub_engine():
    db = _db()
    _seed(db, "sports_nfl", "kalshi:W1", 0.65, 1)
    _seed(db, "sports_nfl", "kalshi:W2", 0.62, 0)
    _seed(db, "sports_nfl_spread", "kalshi:S1", 0.30, 0)
    _seed(db, "sports_cfb_total", "kalshi:T1", 0.72, 1)
    _seed(db, "sports_cfb", "kalshi:W3", 0.40, 0)
    # never part of the record: a market baseline, another version, an unsettled forecast, a stranger
    _seed(db, "kalshi_implied_sports_nfl", "kalshi:W1", 0.5, 1)
    _seed(db, "sports_nfl", "kalshi:W4", 0.9, 1, version="feed-v0")
    _seed(db, "sports_nfl", "kalshi:W5", 0.55, None)
    _seed(db, "spy_quant", "kalshi:X", 0.5, 1)
    ledger = journal_settled_ledger(db)
    assert ledger.pairs_by_engine == {
        "sports_nfl": {"winner": [(0.65, True), (0.62, False)], "spread": [(0.30, False)]},
        "sports_cfb": {"winner": [(0.40, False)], "total": [(0.72, True)]},
    }
    assert ledger.unrecognised_by_engine == {} and ledger.read_failed is False


def test_a_probability_is_the_frozen_one_and_the_hit_is_the_settled_outcome_not_a_guess():
    db = _db()
    _seed(db, "sports_nfl", "kalshi:A", 0.2, 1)   # the model said 20% and YES happened
    assert journal_settled_ledger(db).pairs_by_engine == {"sports_nfl": {"winner": [(0.2, True)]}}


def test_a_failed_read_is_not_measured_not_empty():
    class Broken:
        def table(self, _name):
            raise RuntimeError("postgrest 500")

    ledger = journal_settled_ledger(Broken())
    assert ledger == scan_mod.HubLedger(read_failed=True) and ledger != scan_mod.HubLedger()


def test_a_missing_journal_table_is_not_measured_too():
    class NoTable:
        def table(self, _name):
            raise RuntimeError('relation "journal_forecasts" does not exist')

    assert journal_settled_ledger(NoTable()).read_failed is True


def test_the_cron_reads_the_journal_not_the_predictions_table(monkeypatch):
    seen = {}

    def fake_run(now, kalshi, **kw):
        seen["ledger"] = kw["hub_ledger"]
        return scan_mod.SportsRun([], [], {}, {})

    db = _db()
    _seed(db, "sports_nfl", "kalshi:A", 0.7, 1)
    monkeypatch.setattr(scan_mod, "run_sports_scan", fake_run)
    monkeypatch.setattr(scan_mod, "unrecorded", lambda supa, rows: rows)
    monkeypatch.setattr(scan_mod, "SupabaseReviewStore", lambda supa: None)
    scan_mod.run_sports_for_cron(NOW, db)
    assert seen["ledger"].pairs_by_engine == {"sports_nfl": {"winner": [(0.7, True)]}}

def test_the_ledger_asks_for_exactly_the_forecasters_the_journal_writes():
    """The reader composes forecaster names from `SPORTS_ENGINES` and `kinds.KINDS`; the writer
    composes them from its own copies in `journal.forecasters.sports`. Nothing else joins them, and
    a name that does not exist reads back zero rows rather than raising -- so drift would publish
    `settled_by_kind: {}`, which is the shape of "the read completed and there is nothing in it",
    for a wire that is permanently broken. This test is the join."""
    from tradehub.journal.forecasters.sports import build_sports
    from tradehub.sports.journal_ledger import _forecaster
    from tradehub.sports.kinds import KINDS
    from tradehub.sports.scan import SPORTS_ENGINES

    asked = {_forecaster(sport, kind) for sport in SPORTS_ENGINES for kind in KINDS}
    written = {f.name for f in build_sports()
               if f.version == FEED_VERSION and not f.name.startswith("kalshi_implied_")}

    assert asked == written


def test_a_read_failure_of_any_kind_is_not_measured_not_empty():
    """The promise is `except Exception`, and the other failure test in this file raises
    `RuntimeError` -- so narrowing that clause to `except RuntimeError` would leave every test here
    green while a client passed by mistake (no `.table`, an `AttributeError`) or a malformed
    probability (`TypeError`) escaped and took the whole scan down instead of falling back to the
    predictor's published calibration."""
    class NoTableAttribute:
        table = None  # a client that is not a Supabase stub at all

        def __getattr__(self, _name):
            raise AttributeError("'NoTableAttribute' object has no attribute 'table'")

    class MalformedRow:
        def table(self, _name):
            raise TypeError("a forecast row whose probability is not a number")

    assert journal_settled_ledger(NoTableAttribute()) == scan_mod.HubLedger(read_failed=True)
    assert journal_settled_ledger(MalformedRow()).read_failed is True
