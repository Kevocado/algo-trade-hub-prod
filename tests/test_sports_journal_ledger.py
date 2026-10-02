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