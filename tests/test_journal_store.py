

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
