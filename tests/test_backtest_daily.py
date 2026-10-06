

def test_a_family_that_measured_nothing_is_reported_not_silently_succeeded(capsys, monkeypatch):
    """A replay that scored zero sessions exits 0 today.

    `main()` returned 1 only when a result carried an `"error"`. The sentiment meter returns
    `n == 0` with a `gaps` diagnosis instead -- `SP500` and `BAMLH0A0HYM2` have no ALFRED vintage
    coverage at all, measured against the live API -- and that is a SUCCESSFUL run of the code that
    correctly refuses to substitute current-vintage values. So the command printed a tidy JSON blob
    containing a full diagnosis, exited 0, and wrote nothing.

    Nobody reading that would know the model is permanently unmeasurable rather than merely absent.
    The exit code is the only signal that survives a cron, so it has to carry this.
    """
    from tradehub.scripts import backtest_daily

    empty = {"forecaster": "sentiment_meter", "forecaster_version": "meter-v1", "n": 0,
             "brier": None, "brier_baseline": None, "bss": None, "brier_diff": None,
             "brier_diff_se": None, "by_year": {}, "date_from": "2023-10-02", "date_to": "2026-09-30",
             "gaps": {"SP500": 753, "BAMLH0A0HYM2": 753}, "components_dropped": ["gdelt_tone"]}
    good = {"forecaster": "spy_quant", "forecaster_version": "spy-wf-v1", "n": 753, "brier": 0.2,
            "brier_baseline": 0.2, "bss": 0.0, "brier_diff": 0.01, "brier_diff_se": 0.002,
            "by_year": {}, "date_from": "2023-10-02", "date_to": "2026-09-30"}

    monkeypatch.setattr(backtest_daily, "CALENDARS", {})
    monkeypatch.setattr(backtest_daily, "run", lambda *a, **k: [good, empty])
    monkeypatch.setattr(backtest_daily, "SOURCES", {})

    rc = backtest_daily.main(["--dry-run"])
    cap = capsys.readouterr()

    # Assert on STDERR, not stdout. My first version asserted on stdout and passed: the results JSON
    # already contains "sentiment_meter", "SP500" and "753", so the assertions were satisfied by the
    # blob and proved nothing about the new summary. Mutation testing caught it -- emptying the loop
    # left the test green.
    err = cap.err
    assert "NO EVIDENCE" in err, "nothing states that a model measured nothing"
    assert "sentiment_meter" in err and "SP500" in err, "the unusable inputs are not named"
    assert "753" in err, "the diagnosis it produced is not shown"
    assert rc != 0, "a run that measured nothing reported success"
