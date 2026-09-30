import random
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from journal_fakes import FakeJournalDB

from tradehub.journal.forecasters.housing import (
    HousingForecaster,
    add_months,
    release_cutoff,
    release_day,
    target_for,
)
from tradehub.journal.runner import run_journal
from tradehub.models.monthly_direction import climatology, features_for, training_set
from tradehub.models.spy_direction.model import ArtifactStore

# The 30 real FRED vintage dates of CSUSHPISA seen on 2026-09-30 (2024-03 .. 2026-08): every one is the
# last Tuesday of its month, and each published the index for two months earlier.
REAL_RELEASES = [
    "2024-03-26", "2024-04-30", "2024-05-28", "2024-06-25", "2024-07-30", "2024-08-27", "2024-09-24",
    "2024-10-29", "2024-11-26", "2024-12-31", "2025-01-28", "2025-02-25", "2025-03-25", "2025-04-29",
    "2025-05-27", "2025-06-24", "2025-07-29", "2025-08-26", "2025-09-30", "2025-10-28", "2025-11-25",
    "2025-12-30", "2026-01-27", "2026-02-24", "2026-03-31", "2026-04-28", "2026-05-26", "2026-06-30",
    "2026-07-28", "2026-08-25",
]


def _levels(last=date(2026, 6, 1), seed=11):
    rng, level, out, month = random.Random(seed), 60.0, {}, date(1987, 1, 1)
    while month <= last:
        level *= 1.0 + (0.004 if rng.random() < 0.72 else -0.003) + rng.gauss(0, 0.001)
        out[month] = level
        month = add_months(month, 1)
    return out


def test_the_release_rule_reproduces_every_real_release_date():
    for text in REAL_RELEASES:
        published = date.fromisoformat(text)
        data_month = add_months(date(published.year, published.month, 1), -2)
        assert release_day(data_month) == published, text
    assert release_day(date(2026, 7, 1)) == date(2026, 9, 29)
    assert release_cutoff(date(2026, 8, 1)) == datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/New_York"))


def test_features_and_training_use_only_months_before_the_target():
    levels = _levels()
    month = date(2026, 7, 1)
    row, newest = features_for(levels, month)
    assert newest == date(2026, 6, 1)
    assert features_for({**levels, month: levels[date(2026, 6, 1)] * 5}, month)[0] == row  # its own value is invisible
    x, y, days = training_set(levels, before=month)
    assert max(days) < month and len(x) == len(y) > 300
    assert climatology(levels, month) == pytest.approx(0.72, abs=0.1)
    assert climatology({m: v for m, v in list(levels.items())[:40]}, month) is None


def _forecaster(tmp_path, levels, vintages=None):
    calls = []

    def vintages_fn(series, days, **kwargs):
        calls.append((series, list(days)))
        return (vintages or {})

    fc = HousingForecaster(levels_fn=lambda start: dict(levels), vintages_fn=vintages_fn,
                           store=ArtifactStore(tmp_path, "housing_direction"))
    return fc, calls


def test_the_target_is_the_first_unpublished_month_and_freezes_only_just_before_its_release(tmp_path):
    fc, _ = _forecaster(tmp_path, _levels())  # published through June (released 2026-08-25)
    et = ZoneInfo("America/New_York")
    assert fc.targets(datetime(2026, 8, 26, 12, tzinfo=et)) == []  # a month early
    [entry] = fc.targets(datetime(2026, 9, 25, 12, tzinfo=et))  # inside the five days before Sep 29
    assert entry.target == "housing:2026-07:up" and entry.cadence == "monthly" and not entry.market_linked
    assert entry.cutoff_at == datetime(2026, 9, 29, 9, 0, tzinfo=et) and entry.climatology_prob is not None
    assert fc.targets(datetime(2026, 9, 29, 10, tzinfo=et)) == []  # the cutoff has passed


def test_a_month_that_is_already_published_or_has_a_hole_is_a_gap_not_a_guess(tmp_path):
    levels = _levels(last=date(2026, 7, 1))  # July is already out
    fc, _ = _forecaster(tmp_path, levels)
    entry = type("E", (), {"target": target_for(date(2026, 7, 1))})()
    assert fc.forecast(entry, datetime(2026, 9, 25, tzinfo=UTC)) is None  # never forecast a known value
    holed = _levels()
    del holed[date(2026, 5, 1)]
    fc, _ = _forecaster(tmp_path, holed)
    entry = type("E", (), {"target": target_for(date(2026, 7, 1))})()
    assert fc.forecast(entry, datetime(2026, 9, 25, tzinfo=UTC)) is None


def test_settlement_is_the_first_print_and_waits_for_release_day(tmp_path):
    before = {date(2026, 5, 1): 100.0, date(2026, 6, 1): 101.0}
    on_release = {**before, date(2026, 7, 1): 101.5}  # the first print says up
    fc, calls = _forecaster(tmp_path, _levels(), {date(2026, 9, 28): before, date(2026, 9, 29): on_release})
    assert fc.settle("housing:2026-07:up", datetime(2026, 9, 29, 15, tzinfo=UTC)) is None  # release day itself: too early
    assert calls == []
    settlement = fc.settle("housing:2026-07:up", datetime(2026, 9, 30, 15, tzinfo=UTC))
    assert settlement.outcome == 1 and settlement.realized_value == pytest.approx(0.5)
    assert calls[-1][1] == [date(2026, 9, 28), date(2026, 9, 29)]  # exactly the two vintages needed
    flat = {**before, date(2026, 7, 1): 101.0}
    fc, _ = _forecaster(tmp_path, _levels(), {date(2026, 9, 28): before, date(2026, 9, 29): flat})
    assert fc.settle("housing:2026-07:up", datetime(2026, 9, 30, 15, tzinfo=UTC)).outcome == 0  # unchanged is not up
    fc, _ = _forecaster(tmp_path, _levels(), {date(2026, 9, 28): before, date(2026, 9, 29): before})
    assert fc.settle("housing:2026-07:up", datetime(2026, 9, 30, 15, tzinfo=UTC)) is None  # not printed yet


def test_housing_freezes_before_the_release_and_settles_after_it(tmp_path):
    et = ZoneInfo("America/New_York")
    levels = _levels()
    before = {date(2026, 5, 1): levels[date(2026, 5, 1)], date(2026, 6, 1): levels[date(2026, 6, 1)]}
    vintages = {date(2026, 9, 28): before,
                date(2026, 9, 29): {**before, date(2026, 7, 1): levels[date(2026, 6, 1)] * 1.004}}
    fc, _ = _forecaster(tmp_path, levels, vintages)
    clock = [datetime(2026, 9, 25, 12, tzinfo=et)]
    db = FakeJournalDB(lambda: clock[0])
    out = run_journal(db, [fc], clock[0])
    assert out["forecasters"]["housing_direction@housing-wf-v1"]["frozen"] == 1
    [row] = db.tables["journal_forecasts"]
    assert row["target"] == "housing:2026-07:up" and row["payload"]["release_day"] == "2026-09-29"
    assert row["payload"]["train_end"] < "2026-07-01" and len(row["payload"]["artifact_sha256"]) == 64
    clock[0] = datetime(2026, 9, 30, 12, tzinfo=et)
    out = run_journal(db, [fc], clock[0])
    assert out["forecasters"]["housing_direction@housing-wf-v1"]["settled"] == 1
    assert db.tables["journal_settlements"][0]["outcome"] == 1
    assert db.tables["journal_scores"][0]["baseline"] == "climatology"


def test_the_registry_runs_housing():
    from tradehub.journal.registry import FORECASTERS

    keys = [(f.name, f.version) for f in FORECASTERS]
    assert ("housing_direction", "housing-wf-v1") in keys and len(set(keys)) == len(keys)
    assert timedelta(days=5) > timedelta(0)
