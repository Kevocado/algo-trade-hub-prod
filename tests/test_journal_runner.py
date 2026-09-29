from datetime import UTC, datetime, timedelta

import pytest
from journal_fakes import FakeJournalDB

from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.runner import run_journal

T0 = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class StubForecaster:
    """Three daily targets, one per day; forecasts 0.8 unless told otherwise; settles to 1."""

    name, version, cadence = "stub", "v1", "daily"

    def __init__(self, prob=0.8, missing=(), outcome=1):
        self.prob, self.missing, self.outcome = prob, set(missing), outcome

    def targets(self, now):
        return [CalendarEntry(f"test:day{i}", "test", "daily", T0 + timedelta(days=i), market_linked=True)
                for i in range(1, 4)]

    def forecast(self, entry, now):
        if entry.target in self.missing:
            return None
        return Forecast(self.name, self.version, entry.target, self.prob, market_prob=0.6, payload={"t": entry.target})

    def settle(self, target, now):
        return Settlement(target, self.outcome, "stub-source")


class Boom(StubForecaster):
    name = "boom"

    def targets(self, now):
        raise RuntimeError("feed down")


def test_freezes_every_open_target_once_and_never_twice():
    clock = Clock(T0)
    db = FakeJournalDB(clock)
    first = run_journal(db, [StubForecaster()], clock())
    again = run_journal(db, [StubForecaster()], clock())
    assert first["forecasters"]["stub@v1"]["frozen"] == 3
    assert again["forecasters"]["stub@v1"]["frozen"] == 0
    assert len(db.tables["journal_forecasts"]) == 3


def test_a_missing_input_is_a_gap_not_a_backfill():
    clock = Clock(T0)
    db = FakeJournalDB(clock)
    out = run_journal(db, [StubForecaster(missing={"test:day2"})], clock())
    assert out["forecasters"]["stub@v1"]["missed"] == 1
    clock.t = T0 + timedelta(days=5)  # day2's cutoff is long gone; the input "arrives" now
    later = run_journal(db, [StubForecaster()], clock())
    assert later["forecasters"]["stub@v1"]["frozen"] == 0
    assert "test:day2" not in {r["target"] for r in db.tables["journal_forecasts"]}


def test_settles_only_after_the_cutoff_and_scores_idempotently():
    clock = Clock(T0)
    db = FakeJournalDB(clock)
    run_journal(db, [StubForecaster()], clock())
    clock.t = T0 + timedelta(days=1, hours=1)  # only day1's cutoff has passed
    out = run_journal(db, [StubForecaster()], clock())
    assert out["forecasters"]["stub@v1"]["settled"] == 1
    card = db.tables["journal_scores"][0]
    assert card["n_settled"] == 1 and card["brier"] == pytest.approx(0.04)
    assert card["baseline"] == "market" and card["bss"] == pytest.approx(1 - 0.04 / 0.16)
    run_journal(db, [StubForecaster()], clock())
    assert len(db.tables["journal_scores"]) == 1 and db.tables["journal_scores"][0]["brier"] == card["brier"]


def test_one_failing_forecaster_does_not_stop_the_others():
    clock = Clock(T0)
    db = FakeJournalDB(clock)
    out = run_journal(db, [Boom(), StubForecaster()], clock())
    assert out["failures"] == ["boom@v1"]
    assert out["forecasters"]["stub@v1"]["frozen"] == 3


def test_now_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        run_journal(FakeJournalDB(lambda: T0), [], datetime(2026, 10, 1, 8))  # noqa: DTZ001
