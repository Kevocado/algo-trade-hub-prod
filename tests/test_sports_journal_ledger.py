from datetime import UTC, datetime, timedelta

from journal_fakes import FakeJournalDB

from tradehub.journal.forecasters.sports import FEED_VERSION
from tradehub.sports import scan as scan_mod
from tradehub.sports.journal_ledger import HUB_FEED_VERSION, HUB_LEDGER_KINDS, journal_settled_ledger
from tradehub.sports.kinds import KINDS

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
    # spread and total are seeded here to prove they are read and then NOT filed: see
    # test_spread_and_total_never_enter_the_hub_record, which states the ruling.
    assert ledger.pairs_by_engine == {
        "sports_nfl": {"winner": [(0.65, True), (0.62, False)]},
        "sports_cfb": {"winner": [(0.40, False)]},
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
    """The reader composes forecaster names from `SPORTS_ENGINES` and `HUB_LEDGER_KINDS`; the writer
    composes them from its own copies in `journal.forecasters.sports`. Nothing else joins them, and
    a name that does not exist reads back zero rows rather than raising -- so drift would publish
    `settled_by_kind: {}`, which is the shape of "the read completed and there is nothing in it", for
    a wire that is permanently broken. This test is the join.

    It must pin what the LEDGER asks for, not what `KINDS` would compose: an earlier version built the
    expected set from `kinds.KINDS` while the reader iterated the narrower `HUB_LEDGER_KINDS` (ruling
    2026-10-02, winner only), so it pinned a SUPERSET and would have stayed green if the reader had
    stopped asking for spread and total entirely.
    """
    from tradehub.journal.forecasters.sports import build_sports
    from tradehub.sports.journal_ledger import _forecaster
    from tradehub.sports.scan import SPORTS_ENGINES

    asked = {_forecaster(sport, kind) for sport in SPORTS_ENGINES for kind in HUB_LEDGER_KINDS}
    written = {f.name for f in build_sports()
               if f.version == FEED_VERSION and not f.name.startswith("kalshi_implied_")}

    assert asked, "the ledger asks for nothing, so the test pins nothing"
    assert asked <= written, f"the ledger asks for forecasters the journal never writes: {asked - written}"

    # and the ruling: the ledger is narrower than the full kind set ON PURPOSE, because the settled
    # spread/total rungs cluster near 0.5 (one_rung) and cannot describe the 0.9-priced rungs the
    # bands would then be applied to. Widening this is deliberate and must be measured first.
    assert HUB_LEDGER_KINDS == ("winner",)
    assert set(HUB_LEDGER_KINDS) < set(KINDS), "if this is no longer a narrowing, update the ruling"

    # the reader really does ask for exactly `asked`, not merely a subset of the written names
    queried = []

    class Recording:
        def __init__(self, inner):
            self.inner = inner

        def table(self, name):
            self.inner.tables[name] = self.inner.tables.get(name, [])
            return _Passthrough(self.inner)

    class _Passthrough:
        def __init__(self, db):
            self.db = db

        def select(self, *_a, **kw):
            return self

        def eq(self, k, v):
            if k == "forecaster":
                queried.append(v)
            return self

        def order(self, *_a):
            return self

        def limit(self, *_a):
            return self

        def range(self, *_a):
            return self

        def execute(self):
            return type("R", (), {"data": []})()

    db = _db()
    journal_settled_ledger(Recording(db))
    assert set(queried) == asked, (sorted(set(queried)), sorted(asked))


def test_a_read_failure_of_any_kind_is_not_measured_not_empty():
    """The promise is `except Exception`, and the other failure test in this file raises
    `RuntimeError` -- so narrowing that clause to `except RuntimeError` would leave every test here
    green while a client passed by mistake (no `.table`, an `AttributeError`) or a malformed
    probability (`TypeError`) escaped and took the whole scan down instead of falling back to the
    predictor's published calibration."""
    class NoTableAttribute:
        table = None   # a client that is not a Supabase stub: calling `.table` raises TypeError

    class MalformedRow:
        def table(self, _name):
            raise TypeError("a forecast row whose probability is not a number")

    assert journal_settled_ledger(NoTableAttribute()) == scan_mod.HubLedger(read_failed=True)
    assert journal_settled_ledger(MalformedRow()).read_failed is True


def test_spread_and_total_never_enter_the_hub_record():
    """Kevin's ruling: the hub's own settled record applies to WINNER markets only.

    `one_rung` freezes only the rung whose Kalshi mid is nearest 0.5, so the settled spread/total
    probabilities cluster there by construction. Bands cut from that cannot describe the 0.9-priced
    rungs they would then be applied to, so the scan keeps the predictor's published calibration
    for those two kinds however much the journal holds. Revisit once a season of settled rungs
    covers the whole price range.
    """
    db = _db()
    _seed(db, "sports_nfl", "kalshi:W1", 0.65, 1)
    _seed(db, "sports_nfl_spread", "kalshi:S1", 0.51, 1)
    _seed(db, "sports_nfl_total", "kalshi:T1", 0.49, 0)
    ledger = journal_settled_ledger(db)

    assert ledger.pairs_by_engine == {"sports_nfl": {"winner": [(0.65, True)]}}
    assert ledger.read_failed is False


def test_a_spread_edge_is_still_judged_on_the_predictors_calibration_not_the_journals():
    """The ruling is about what the ledger holds, so this asserts the consequence: with a settled
    spread record present, the scan still gets no hub pairs for `spread` and keeps the feed's own."""
    db = _db()
    _seed(db, "sports_nfl", "kalshi:W1", 0.65, 1)
    _seed(db, "sports_nfl_spread", "kalshi:S1", 0.51, 1)
    ledger = journal_settled_ledger(db)

    assert "spread" not in ledger.pairs_by_engine.get("sports_nfl", {})
    # the band builder reads per kind, so a missing kind is the whole of the fallback condition
    assert ledger.pairs_by_engine["sports_nfl"].get("spread") is None
