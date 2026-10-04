import pytest
from fastapi.testclient import TestClient
from journal_fakes import FakeJournalDB

from tradehub.api.dependencies import get_supabase
from tradehub.api.main import app
from tradehub.journal.legacy import journal_engines, journal_scores, journal_track_row, merge_track_record

LEGACY = [
    {"engine": "weather", "engine_version": "w-v1", "n_settled": 40, "gate_status": "SHADOW"},
    {"engine": "cpi_nowcast", "engine_version": "cpi-v1", "n_settled": 12, "gate_status": "SHADOW"},
    {"engine": "cpi_nowcast", "engine_version": "cpi-core-v1", "n_settled": 9, "gate_status": "SHADOW"},
]
SCORE = {"forecaster": "cpi_nowcast", "forecaster_version": "cpi-v1", "baseline": "market", "n_settled": 7,
         "brier": 0.07, "brier_baseline": 0.068, "bss": -0.03, "reliability": [{"bucket": "60-70", "n": 7}],
         "gate_status": "SHADOW", "calibration_ready": False, "computed_at": "2026-10-01T13:00:00+00:00"}


def test_a_journal_scorecard_becomes_one_legacy_shaped_row_tagged_with_its_source():
    row = journal_track_row(SCORE)
    assert (row["engine"], row["engine_version"], row["source"]) == ("cpi_nowcast", "cpi-v1", "journal")
    # SCORE has no `n_baseline` -- it predates migration 20260428000020 -- so there is no matched
    # sample to pair. `n_settled`/`brier_all` carry the all-settled figures and the comparison stays
    # unset, rather than pairing a 7-target ours with a 3-target market.
    assert row["n_settled"] == 7 and row["brier_all"] == 0.07
    assert row["brier_ours"] is None and row["brier_market"] is None
    assert row["cal_buckets"] == [{"bucket": "60-70", "n": 7}] and row["bss"] == -0.03
    clim = journal_track_row({**SCORE, "baseline": "climatology"})
    assert clim["brier_market"] is None  # a climatology baseline is not "the market's Brier"


def test_the_row_pairs_ours_with_market_over_ONE_sample_so_the_ratio_is_its_own_bss():
    """Three denominators in one row, and the row's own `bss` computed from a fourth.

    `n_settled`/`brier` cover every settled target; `brier_baseline`/`brier_on_baseline`/`n_baseline`
    cover only the targets that HAVE a baseline. Pairing the all-targets `brier` with the matched
    `brier_baseline` puts a 7-target mean beside a 3-target mean, so `1 - brier_ours/brier_market` --
    the one thing every reader of this shape computes -- is not the `bss` the row also carries. The row
    was not sign-flipped (PR #113 put the correct `bss` in it) but self-contradictory, which is worse to
    debug and easier to trust. The three legacy keys are ONE comparison in the legacy shape
    (`track_record._upsert_version` writes all three from one sample), so all three get the matched one.
    """
    three_ways = {**SCORE, "n_settled": 7, "brier": 0.21, "brier_on_baseline": 0.07,
                  "n_baseline": 3, "brier_baseline": 0.068, "bss": -0.029412}
    row = journal_track_row(three_ways)

    assert (row["n_settled"], row["brier_ours"], row["brier_market"]) == (3, 0.07, 0.068), row
    assert row["bss"] == pytest.approx(1 - 0.07 / 0.068, abs=5e-7), (
        f"the row's two Briers do not produce its own bss: {row}")


def test_the_all_settled_figures_are_still_there_under_names_that_say_which_sample_they_cover():
    """Dropping them would lose the wider sample; keeping them under `brier_ours` would be the bug again.

    The second case is a scorecard written before migration 20260428000020, which carries no matched
    pair at all. It falls back to the all-settled pair, which is internally consistent on its own -- and
    says so, rather than reporting `n_settled: null` for a card with 300 settled targets.
    """
    three_ways = {**SCORE, "n_settled": 7, "brier": 0.21, "brier_on_baseline": 0.07,
                  "n_baseline": 3, "brier_baseline": 0.068, "bss": -0.029412}
    row = journal_track_row(three_ways)
    assert (row["n_settled_all"], row["brier_all"]) == (7, 0.21)

    pre_migration = {k: v for k, v in three_ways.items() if k not in ("brier_on_baseline", "n_baseline")}
    old = journal_track_row(pre_migration)
    # CodeRabbit, on #119: the fallback used to put the all-settled 0.21 under `brier_ours`, beside a
    # `brier_market` and `bss` computed on the MATCHED sample. That published a comparison across two
    # denominators -- the defect #119 corrected in this row, reintroduced by its own fallback. The
    # honest all-settled figure lives under `brier_all`; `brier_ours` stays unset.
    assert (old["n_settled"], old["n_settled_all"], old["brier_all"]) == (7, 7, 0.21)
    assert old["brier_ours"] is None and old["brier_market"] is None, (
        "a pre-migration card must not publish a half-matched comparison")


def test_an_engine_on_the_journal_is_served_once_from_the_journal_whatever_the_legacy_version():
    rows = merge_track_record(LEGACY, [SCORE])
    assert [(r["engine"], r["engine_version"], r["source"]) for r in rows] == [
        ("cpi_nowcast", "cpi-v1", "journal"), ("weather", "w-v1", "legacy")]
    assert journal_engines([SCORE]) == {"cpi_nowcast"}  # both legacy cpi versions are dropped, not just one


def test_with_no_journal_scorecards_the_legacy_record_is_served_unchanged_but_tagged():
    rows = merge_track_record(LEGACY, [])
    assert len(rows) == 3 and all(r["source"] == "legacy" for r in rows)


def test_a_missing_journal_table_reads_as_no_scorecards_and_any_other_fault_raises():
    class NoTable(FakeJournalDB):
        def table(self, name):
            raise RuntimeError("Could not find the table 'public.journal_scores' in the schema cache")

    class Broken(FakeJournalDB):
        def table(self, name):
            raise RuntimeError("connection reset")

    assert journal_scores(NoTable(lambda: None)) == []
    try:
        journal_scores(Broken(lambda: None))
    except RuntimeError as exc:
        assert "connection reset" in str(exc)
    else:
        raise AssertionError("a real fault must not be read as an empty journal")


def test_the_track_record_endpoint_serves_one_record_per_engine():
    db = FakeJournalDB(lambda: None)
    db.tables["track_record"] += [dict(r) for r in LEGACY]
    db.tables["journal_scores"].append(dict(SCORE))
    app.dependency_overrides[get_supabase] = lambda: db
    try:
        body = TestClient(app).get("/api/track-record").json()
    finally:
        app.dependency_overrides.clear()
    assert [(r["engine"], r["source"]) for r in body] == [("cpi_nowcast", "journal"), ("weather", "legacy")]


def test_a_pre_migration_card_does_not_publish_a_half_matched_comparison():
    """CodeRabbit on #119.

    A card with no `n_baseline` predates migration 20260428000020. `brier_market` and `bss` still come
    from the MATCHED-baseline sample, so falling `brier_ours` back to the all-settled score published a
    comparison across two denominators -- the same defect #119 corrected in this row, and the same one
    `market_skill()` had. A reader dividing one by the other would compute a number that means nothing.

    So the comparison is left unset and the all-settled figures stay available under the `_all` keys.
    An absent number is honest; a mixed-sample one is not.
    """
    from tradehub.journal.legacy import journal_track_row

    pre_migration = {
        "forecaster": "sports_nfl", "forecaster_version": "feed-v1", "baseline": "market",
        "gate_status": "SHADOW", "reliability": [], "computed_at": "x", "calibration_ready": True,
        # all-settled sample
        "n_settled": 7, "brier": 0.21,
        # matched-baseline sample only -- and no n_baseline to pair it with
        "brier_baseline": 0.068, "bss": 0.02,
    }
    row = journal_track_row(pre_migration)
    assert row["brier_ours"] is None, "published an all-settled ours against a matched market"
    assert row["brier_market"] is None, "published a market score with no ours to pair it with"
    # ...and the wider figures are still there for anyone who wants the honest one.
    assert row["n_settled"] == 7 and row["brier_all"] == 0.21 and row["n_settled_all"] == 7
