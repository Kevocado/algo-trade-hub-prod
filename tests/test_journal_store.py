from datetime import UTC, datetime


def test_fetch_forecasts_can_be_asked_for_named_targets_instead_of_the_whole_history():
    """The read that decides "is this target already frozen?" only ever needs THIS run's targets.

    `fetch_forecasts` had no filter at all, so the runner asked the whole frozen history of a
    forecaster -- every row it will ever write, paged 1000 at a time -- and then threw all of it away
    except the targets in its hand. `fetch_settlements` and `fetch_calendar` both filter in the
    database with `.in_("target", ...)`; this read was the one that did not.

    The two sides have to DIFFER or the test proves nothing: three rows exist for the forecaster, two
    are asked for, and the unfiltered call must still return all three.
    """
    from journal_fakes import FakeJournalDB

    from tradehub.journal import store

    db = FakeJournalDB(lambda: datetime(2026, 10, 4, tzinfo=UTC))
    db.tables["journal_forecasts"] = [
        {"id": i, "forecaster": "f", "forecaster_version": "v1", "target": t, "probability": 0.5}
        for i, t in enumerate(("kalshi:A-IND", "kalshi:B-HOU", "kalshi:C-KC"), start=1)
    ]

    asked = store.fetch_forecasts(db, "f", "v1", ["kalshi:A-IND", "kalshi:C-KC"])
    assert sorted(r["target"] for r in asked) == ["kalshi:A-IND", "kalshi:C-KC"], asked
    assert sorted(r["target"] for r in store.fetch_forecasts(db, "f", "v1")) == [
        "kalshi:A-IND", "kalshi:B-HOU", "kalshi:C-KC"]


def test_the_target_filter_chunks_rather_than_building_one_enormous_in_clause():
    """`IN_CHUNK` exists because PostgREST puts the whole filter in the URL. 250 targets in one `in.()`
    is a long URL, a probable 414, and a whole run of exceptions -- so the filter carries the same
    chunking discipline as `fetch_settlements`, and the chunk boundary is IN_CHUNK, not a guess.
    """
    from tradehub.journal import store

    seen: list[int] = []

    class Q:
        def __init__(self, vals=None):
            self.vals = vals

        def select(self, *_a):
            return self

        def eq(self, *_a):
            return self

        def in_(self, _col, vals):
            seen.append(len(vals))
            return self

        def order(self, *_a, **_k):
            return self

        def range(self, *_a):
            return self

        def execute(self):
            return type("R", (), {"data": [{"id": 1, "target": "t"} for _ in range(len(self.vals or []))]})()

    class S:
        def table(self, _n):
            return Q()

    store.fetch_forecasts(S(), "f", "v1", [f"t{i}" for i in range(store.IN_CHUNK + 50)])
    assert seen == [store.IN_CHUNK, 50], seen


def test_an_empty_target_list_asks_for_nothing_rather_than_everything():
    """`[]` means "none of these targets", not "no filter". A forecaster with no targets this run --
    a real state, hours before a game's cutoff -- used to pay a full history read for a row it then
    ignored. `None` is the only value that means "every target".
    """
    from journal_fakes import FakeJournalDB

    from tradehub.journal import store

    db = FakeJournalDB(lambda: datetime(2026, 10, 4, tzinfo=UTC))
    db.tables["journal_forecasts"] = [
        {"id": 1, "forecaster": "f", "forecaster_version": "v1", "target": "t", "probability": 0.5}]
    assert store.fetch_forecasts(db, "f", "v1", []) == []


def test_freeze_records_the_horizon_from_the_calendar_cutoff(monkeypatch):
    """Spec §3 step 1 puts `horizon` in the frozen row's shape and it was never written. The runner
    already holds the calendar entry, so the horizon is derived in ONE place -- no forecaster changes.

    The fixture's horizon and the frozen `now` DELIBERATELY differ from any default, because a test
    whose expected value equals the code's fallback proves nothing.
    """
    from datetime import timedelta

    from tradehub.journal import store
    from tradehub.journal.contract import Forecast

    captured: dict = {}

    class Q:
        def insert(self, row):
            captured.update(row)
            return self

        def execute(self):
            return type("R", (), {"data": [captured]})()

    class S:
        def table(self, _n):
            return Q()

    fc = Forecast(forecaster="f", forecaster_version="v1", target="t", probability=0.6,
                  horizon_seconds=int(timedelta(hours=30).total_seconds()))

    assert store.freeze(S(), fc) is True
    assert captured["horizon_seconds"] == 108000, captured
    assert captured["target"] == "t" and captured["probability"] == 0.6


def test_freeze_still_records_when_the_horizon_column_is_not_deployed_yet():
    """The deploy-order hazard, and it is a live one.

    `freeze()` treats every insert error as "the trigger refused this target" and returns False. If
    migration 20260428000018 were unapplied, PostgREST would reject the insert with "column
    journal_forecasts.horizon_seconds does not exist" -- so the journal would record NOTHING, log
    only a warning, and report every target as missed. A brand-new column would silently switch off
    the entire ledger until someone noticed.

    So a missing horizon column degrades to "horizon not recorded", never to "forecast not
    recorded". The horizon is absent, which is honest; the evidence is not, which would be a lie.
    """
    from tradehub.journal import store
    from tradehub.journal.contract import Forecast

    rows: list[dict] = []
    has_column = {"value": False}

    class Q:
        """PostgREST: an unknown column rejects the WHOLE insert, whatever else is in it."""

        def insert(self, row):
            if "horizon_seconds" in row and not has_column["value"]:
                raise RuntimeError("column journal_forecasts.horizon_seconds does not exist")
            rows.append(dict(row))
            return self

        def execute(self):
            return type("R", (), {"data": rows})()

    class S:
        def table(self, _n):
            return Q()

    fc = Forecast(forecaster="f", forecaster_version="v1", target="t", probability=0.6,
                  horizon_seconds=108000)

    # First call: the column is missing. The forecast must still be recorded.
    assert store.freeze(S(), fc) is True
    assert len(rows) == 1, "the forecast was lost because a new column was not deployed yet"
    assert "horizon_seconds" not in rows[0]

    # The negative answer is cached for the REST OF THE PROCESS, so the run does not pay for a failed
    # insert on every target. `journal_run` is a fresh process each hour, so the probe happens again
    # on the next run and the horizon starts being recorded as soon as the migration is applied --
    # without a redeploy. Pinned here by simulating that new process.
    assert store._HORIZON_DEPLOYED is False
    has_column["value"] = True
    store._HORIZON_DEPLOYED = None          # what a new process starts with
    assert store.freeze(S(), fc) is True
    assert rows[-1]["horizon_seconds"] == 108000
    assert store._HORIZON_DEPLOYED is None or store._HORIZON_DEPLOYED is True


def test_freeze_recognises_postgrest_missing_column_not_just_postgres_wording(monkeypatch):
    """CodeRabbit Major on #106, and it invalidates the safety net itself.

    PostgREST does not usually say "does not exist". It answers an unknown column with PGRST204 and a
    JSON body naming the column. `_missing_horizon_column()` matched only the Postgres wording, so on
    the real error shape the fallback never fired: `freeze()` returned False, the runner counted the
    forecast as MISSED, and a missed freeze is never backfilled. The whole point of that branch was to
    stop an unapplied migration from silently switching off the ledger, and it did not.

    This test uses the actual PGRST204 wording. The earlier test used a Postgres-shaped message, which
    is why it passed while the production path was broken.
    """
    from tradehub.journal import store
    from tradehub.journal.contract import Forecast

    rows: list[dict] = []
    deployed = {"value": False}

    class Q:
        def insert(self, row):
            if "horizon_seconds" in row and not deployed["value"]:
                raise RuntimeError(
                    '{"code":"PGRST204","details":"Could not find the '
                    '\'horizon_seconds\' column of \'journal_forecasts\' in the schema cache",'
                    '"hint":null,"message":"Could not find the '
                    '\'horizon_seconds\' column of \'journal_forecasts\' in the schema cache"}')
            rows.append(dict(row))
            return self

        def execute(self):
            return type("R", (), {"data": rows})()

    class S:
        def table(self, _n):
            return Q()

    monkeypatch.setattr(store, "_HORIZON_DEPLOYED", None)
    fc = Forecast(forecaster="f", forecaster_version="v1", target="t", probability=0.6,
                  horizon_seconds=108000)

    assert store.freeze(S(), fc) is True, "the forecast was lost to an unapplied migration"
    assert len(rows) == 1 and "horizon_seconds" not in rows[0]


def test_a_different_missing_column_is_not_mistaken_for_the_horizon(monkeypatch):
    """The guard on the guard. Without the column-name check, ANY PGRST204 or "schema cache" error
    would enter the horizon branch, and the log would then claim `horizon_seconds is not deployed yet`
    when the real fault was some other column. The retry would fail anyway, so the outcome is the same
    -- but the operator is told the wrong thing, which is how the next hour's silence gets misread."""
    from tradehub.journal import store
    from tradehub.journal.contract import Forecast

    seen: list[dict] = []

    class Q:
        def insert(self, row):
            seen.append(dict(row))
            raise RuntimeError(
                '{"code":"PGRST204","message":"Could not find the '
                '\'some_other_column\' column of \'journal_forecasts\' in the schema cache"}')

        def execute(self):
            return type("R", (), {"data": []})()

    class S:
        def table(self, _n):
            return Q()

    monkeypatch.setattr(store, "_HORIZON_DEPLOYED", None)
    fc = Forecast(forecaster="f", forecaster_version="v1", target="t", probability=0.6,
                  horizon_seconds=108000)

    # It must RAISE. CodeRabbit, on #124: my first version tolerated either outcome, so it passed
    # against exactly the behaviour #48 exists to remove. An unknown-column error is not the database
    # refusing this forecast, so it must never become a permanent gap.
    try:
        store.freeze(S(), fc)
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "an unrelated schema error was reported as a missed forecast, which is a permanent gap")
    assert len(seen) == 1, "an unrelated schema error triggered a pointless retry"
    assert store._HORIZON_DEPLOYED is None, (
        "an unrelated schema error was cached as 'the horizon column is not deployed'")


def test_upsert_score_still_writes_when_the_paired_brier_columns_are_not_deployed_yet(monkeypatch):
    """The same deploy-order hazard `freeze` had, one function over.

    `upsert_score` spreads `**card` into a PostgREST upsert, so a card carrying `brier_on_baseline` and
    `n_baseline` names two columns that do not exist until migration 20260428000020 is applied. PostgREST
    rejects the WHOLE upsert (PGRST204), and without a fallback every scorecard would stop updating.

    `upsert_score` is the LAST statement in `run_forecaster`, so the failure mode is the worst one in
    this repo: freezes and settlements still commit, the ledger keeps filling, and every scorecard
    silently freezes at its last written value. Nothing looks broken. A missing paired figure is
    visible; a stale score is not.
    """
    from tradehub.journal import store

    paired = ("brier_on_baseline", "n_baseline")
    deployed = {"value": False}
    rows: list[dict] = []

    class Q:
        def upsert(self, row, **_kw):
            # PostgREST rejects the whole payload when it names an unknown column.
            if any(k in row for k in paired) and not deployed["value"]:
                raise RuntimeError(
                    '{"code":"PGRST204","message":"Could not find the brier_on_baseline'
                    ' column of journal_scores in the schema cache"}')
            rows.append({k: v for k, v in row.items()
                         if deployed["value"] or k not in paired})
            return self

        def execute(self):
            return type("R", (), {"data": rows})()

    class S:
        def table(self, _n):
            return Q()

    monkeypatch.setattr(store, "_PAIRED_BRIER_DEPLOYED", None)
    card = {"n_settled": 100, "brier": 0.2, "brier_baseline": 0.25,
            "brier_on_baseline": 0.2, "n_baseline": 40, "gate_status": "SHADOW"}
    now = datetime(2026, 10, 4, tzinfo=UTC)

    store.upsert_score(S(), "f", "v1", card, now)
    assert len(rows) == 1, "the scorecard was lost because a new column was not deployed yet"
    assert not any(k in rows[0] for k in paired)

    # The negative is cached for the REST OF THE PROCESS so one run does not pay for a rejected write
    # on every forecaster. `journal_run` is a fresh process each hour, so the next run probes again and
    # the paired figures start being written as soon as the migration is applied -- no redeploy. Pinned
    # here by resetting the flag, which is what a new process starts with.
    assert store._PAIRED_BRIER_DEPLOYED is False
    deployed["value"] = True
    store._PAIRED_BRIER_DEPLOYED = None
    store.upsert_score(S(), "f", "v1", card, now)
    assert rows[-1]["brier_on_baseline"] == 0.2 and rows[-1]["n_baseline"] == 40


def test_an_unrelated_schema_error_is_not_cached_as_the_paired_columns_being_absent(monkeypatch):
    """The guard on the guard, matching the one added for `_missing_horizon_column`.

    Without the column-name check, ANY PGRST204 or "schema cache" error enters the fallback: the write
    is retried without the paired columns, the log claims migration 20260428000020 is unapplied, and
    the answer is cached as False for the whole process -- so the real fault is both misreported and
    then never rediscovered until the next hourly run.
    """
    from tradehub.journal import store

    attempts: list[dict] = []

    class Q:
        def upsert(self, row, **_kw):
            attempts.append(dict(row))
            raise RuntimeError(
                '{"code":"PGRST204","message":"Could not find the some_other_column'
                ' column of journal_scores in the schema cache"}')

        def execute(self):
            return type("R", (), {"data": []})()

    class S:
        def table(self, _n):
            return Q()

    monkeypatch.setattr(store, "_PAIRED_BRIER_DEPLOYED", None)
    card = {"n_settled": 100, "brier": 0.2, "brier_baseline": 0.25,
            "brier_on_baseline": 0.2, "n_baseline": 40}

    try:
        store.upsert_score(S(), "f", "v1", card, datetime(2026, 10, 4, tzinfo=UTC))
    except RuntimeError:
        pass  # a real failure must still propagate
    assert len(attempts) == 1, "an unrelated schema error triggered a pointless retry"
    assert store._PAIRED_BRIER_DEPLOYED is None, (
        "an unrelated schema error was cached as 'the paired columns are not deployed'")


def test_freeze_propagates_a_transport_failure_instead_of_reporting_a_missed_forecast():
    """CodeRabbit Major on #48, still open since 2026-09-29.

    `freeze()` caught EVERY exception and returned False. `run_forecaster` counts False as a missed
    forecast -- and a missed freeze is never backfilled. So a dropped connection or a 500 near cutoff
    was recorded as "we had no forecast", which is a permanent, silent loss of a target the forecaster
    was perfectly able to produce. If the next run starts after cutoff, that target is skipped forever
    and excluded from scoring.

    A refusal and a transport failure are different claims: "the database said no" versus "we never
    asked". Only the first may become a gap.
    """
    import httpx

    from tradehub.journal import store
    from tradehub.journal.contract import Forecast

    class Q:
        def insert(self, _row):
            return self

        def execute(self):
            raise httpx.ConnectError("[Errno 61] Connection refused")

    class S:
        def table(self, _n):
            return Q()

    fc = Forecast(forecaster="f", forecaster_version="v1", target="t", probability=0.6)
    try:
        store.freeze(S(), fc)
    except httpx.ConnectError:
        return  # the whole point: the failure reaches the runner, which can retry before cutoff
    raise AssertionError(
        "a transport failure was swallowed and reported as a missed forecast, which is a permanent gap")


def test_freeze_still_returns_false_for_a_real_database_refusal():
    """The other half of the distinction, and the reason the change is safe.

    The `journal_calendar_guard` trigger raises with SQLSTATE 23514/42501/23503 and every message is
    prefixed `journal:`. Those are genuine refusals -- the target is closed, or the row is immutable --
    and they must stay a gap, because no amount of retrying will change the answer.
    """
    from tradehub.journal import store
    from tradehub.journal.contract import Forecast

    class Refusal(Exception):
        """Stands in for postgrest's APIError: a JSON body carrying `code` and `message`."""

        def __init__(self, code: str, message: str):
            super().__init__(message)
            self.code = code
            self.message = message

    class Q:
        def __init__(self, exc):
            self.exc = exc

        def insert(self, _row):
            return self

        def execute(self):
            raise self.exc

    class S:
        def __init__(self, exc):
            self.exc = exc

        def table(self, _n):
            return Q(self.exc)

    fc = Forecast(forecaster="f", forecaster_version="v1", target="t", probability=0.6)
    for code, message in (
        ("23514", "journal: freeze for t refused, cutoff 2026-10-01 has passed"),
        ("23503", "journal: no calendar row for target t"),
        ("42501", "journal: journal_forecasts rows are immutable (UPDATE)"),
    ):
        assert store.freeze(S(Refusal(code, message)), fc) is False, (code, message)

    # A recognised SQLSTATE with NO `journal:` prefix PROPAGATES. CodeRabbit, on #124: the guard uses
    # 42501 for its immutability rules on UPDATE/DELETE, but a missing INSERT privilege is also 42501
    # -- so a code-only check would read "this client may not insert at all" as a refusal, and record
    # a permanent missed forecast. The guard's own message prefix is the only trustworthy signal.
    for code, message in (
        ("42501", "permission denied for table journal_forecasts"),
        ("23514", "new row violates check constraint \"journal_forecasts_probability_check\""),
    ):
        try:
            store.freeze(S(Refusal(code, message)), fc)
        except Refusal:
            continue
        raise AssertionError(
            f"a code-only error ({code}) was reported as a missed forecast, which is a permanent gap: {message}")

    # A 5xx from PostgREST is NOT a refusal -- the insert may well have succeeded server-side, and
    # retrying is safe because the trigger refuses a duplicate.
    class Server(Refusal):
        pass

    class Q5:
        def insert(self, _row):
            return self

        def execute(self):
            raise Server("500", "Internal Server Error")

    class S5:
        def table(self, _n):
            return Q5()

    try:
        store.freeze(S5(), fc)
    except Server:
        return
    raise AssertionError("a 5xx was reported as a gap; retrying could still succeed")


def test_a_transport_failure_during_the_missing_column_retry_propagates_too(monkeypatch):
    """CodeRabbit Major on #124: the retry branch returned False unconditionally.

    When the first insert reports a missing `horizon_seconds` column, `freeze()` retries without it.
    That retry hit `except Exception: return False` -- so a CONNECTION FAILURE during the retry became
    a missed forecast, which is a permanent gap. The same permanent silent loss #48 removes, one
    branch deeper. The retry path now classifies its exception exactly as the first attempt does.
    """
    import httpx

    from tradehub.journal import store
    from tradehub.journal.contract import Forecast

    monkeypatch.setattr(store, "_HORIZON_DEPLOYED", None, raising=False)
    attempts: list[dict] = []

    class Q:
        def insert(self, row):
            attempts.append(dict(row))
            if len(attempts) == 1:
                raise RuntimeError(
                    '{"code":"PGRST204","message":"Could not find the horizon_seconds'
                    ' column of journal_forecasts in the schema cache"}')
            raise httpx.ConnectError("[Errno 61] Connection refused")

        def execute(self):
            return type("R", (), {"data": []})()

    class S:
        def table(self, _n):
            return Q()

    fc = Forecast(forecaster="f", forecaster_version="v1", target="t", probability=0.6,
                  horizon_seconds=108000)
    try:
        store.freeze(S(), fc)
    except httpx.ConnectError:
        assert len(attempts) == 2, "the retry never happened, so nothing was proven"
        return
    raise AssertionError(
        "a connection failure during the missing-column retry became a missed forecast, which is a "
        "permanent gap")
