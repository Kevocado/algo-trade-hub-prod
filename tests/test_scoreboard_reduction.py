"""Reduce many backtest_runs rows to one honest row per engine.

The rule that matters most: a run whose `engine_version` carries a decision lead
(`gas-v1-lead12h`, from PR #25) is an EXPERIMENT, not the engine's record. Gas is
4.29x behind the market at the production 2h and 2.16x behind at 12h, so the two
disagree about the engine -- and the scoreboard's whole purpose is to tell a reader
whether to trust an engine. Presenting a 12h run as the record would make the page
wrong in the direction that flatters the engine.

So experiments are excluded from `current_runs` rather than shown with a footnote.
A footnote is a thing a reader skips; an absent row is a thing they cannot
misread. They remain in `backtest_runs` and remain reproducible from the CLI.
"""
import pytest

from tradehub.scoreboard import (
    SOURCE_ENGINE,
    SOURCE_GATE,
    SOURCE_UNKNOWN,
    brier_ratio,
    current_runs,
    is_experiment_version,
    required_settled,
    settled_distance,
    stated_settled_bar,
)
from tradehub.sports.scorecard import MIN_SETTLED
from tradehub.track_record import MIN_CONTRACTS, check_promotion_gate

# The real strings `check_promotion_gate` emits. Copied from
# `tradehub/track_record.py:check_promotion_gate` and asserted against that function
# in TestGateWording below, so a change in the gate cannot silently stop parsing.
NEEDS_200_DAILY = "only 42 settled contracts, need 200 (daily)"
NEEDS_50_MONTHLY = "only 0 settled contracts, need 50 (monthly)"
NO_MARKET_BRIER = "no market Brier recorded; gate cannot be evaluated"
BRIER_REASON = "model Brier 0.1242 is not below market Brier 0.09713"
P_AND_L_REASON = "simulated P&L after fees/spread is not positive"
CALIBRATION_REASON = "calibration miss 20.0% in bucket 70-80 (limit 10pp)"


def _run(engine, *, version, brier_ours=0.1242, brier_market=0.09713, n_settled=672,
         reasons=None, created_at="2026-09-27T00:00:00+00:00", mode="taker"):
    return {
        "engine": engine,
        "engine_version": version,
        "mode": mode,
        "date_from": "2026-06-01T00:00:00+00:00",
        "date_to": "2026-09-20T00:00:00+00:00",
        "n_decisions": 672,
        "n_fills": 232,
        "n_settled": n_settled,
        "pnl_after_fees": -7.62,
        "max_drawdown": 8.87,
        "brier_ours": brier_ours,
        "brier_market": brier_market,
        "gate_status": "SHADOW",
        "gate_reasons": reasons if reasons is not None else [BRIER_REASON],
        "created_at": created_at,
    }


def _gate_reasons(**kwargs):
    """The gate's real output, so the parser is tested against its real producer."""
    defaults = {
        "engine": "cpi_nowcast",
        "cadence": "daily",
        "summary": {"n_settled": 42, "brier_ours": 0.1242, "brier_market": 0.09713},
        "cal_buckets": [],
        "simulated_pnl_after_fees": -7.62,
    }
    defaults.update(kwargs)
    return check_promotion_gate(**defaults)["reasons"]


class TestExperimentVersions:
    def test_a_tagged_lead_is_recognised(self):
        assert is_experiment_version("gas-v1-lead12h") is True
        assert is_experiment_version("gas-v1-lead6.5h") is True

    def test_the_production_version_is_not_an_experiment(self):
        assert is_experiment_version("gas-v1") is False

    def test_an_unrecognised_version_is_not_silently_treated_as_production(self):
        # Fail safe in the direction that matters: anything unexpected is not the plain engine.
        assert is_experiment_version("") is True
        assert is_experiment_version(None) is True
        assert is_experiment_version(123) is True

    def test_a_malformed_tag_still_counts_as_an_experiment(self):
        # The hole that made this unanchored: `-lead<number>h` does not match `gas-v1-lead`, so a
        # hand-edited or truncated tag would have read as the production engine.
        assert is_experiment_version("gas-v1-lead") is True
        assert is_experiment_version("gas-v1-lead12") is True

    @pytest.mark.parametrize("version", ["gas-v1", "weather-v1", "cpi-v1", "cpi-core-v1", "labor-v1"])
    def test_every_real_production_version_is_not_an_experiment(self, version):
        # These are the only five `engine_version` values any backtest_runs writer can produce:
        # GAS_ENGINE_VERSION / WEATHER_ENGINE_VERSION / CPI_ENGINE_VERSION /
        # CPI_CORE_ENGINE_VERSION / LABOR_ENGINE_VERSION. TestBacktestRunsProvenance below
        # proves the writers cannot produce another one.
        assert is_experiment_version(version) is False


class TestCurrentRuns:
    def test_an_experiment_never_becomes_the_engines_record(self):
        runs = [
            _run("gas", version="gas-v1", brier_ours=0.1148, brier_market=0.02676,
                 created_at="2026-09-20T00:00:00+00:00"),
            # Later, and better-looking. Must still lose.
            _run("gas", version="gas-v1-lead12h", brier_ours=0.11216, brier_market=0.0519,
                 created_at="2026-09-27T00:00:00+00:00"),
        ]

        rows = current_runs(runs)

        assert len(rows) == 1
        assert rows[0]["engine_version"] == "gas-v1"
        assert float(rows[0]["brier_ours"]) == pytest.approx(0.1148)

    def test_the_latest_production_run_wins(self):
        runs = [
            _run("weather", version="weather-v1", brier_ours=0.13, created_at="2026-09-01T00:00:00+00:00"),
            _run("weather", version="weather-v1", brier_ours=0.1242, created_at="2026-09-20T00:00:00+00:00"),
        ]

        rows = current_runs(runs)

        assert len(rows) == 1
        assert float(rows[0]["brier_ours"]) == pytest.approx(0.1242)

    def test_recency_is_read_as_a_time_not_as_a_string(self):
        """`created_at` is a timestamptz, and PostgREST renders it in the response's own offset.

        `2026-09-19T20:00:00-05:00` is 2026-09-20T01:00Z, i.e. LATER than the UTC midnight it sorts
        before. Comparing the strings would present the older run as the engine's record.
        """
        runs = [
            _run("weather", version="weather-v1", brier_ours=0.13,
                 created_at="2026-09-20T00:00:00+00:00"),
            _run("weather", version="weather-v1", brier_ours=0.1242,
                 created_at="2026-09-19T20:00:00-05:00"),
        ]

        rows = current_runs(runs)

        assert len(rows) == 1
        assert float(rows[0]["brier_ours"]) == pytest.approx(0.1242), rows

    def test_an_unparseable_timestamp_still_picks_a_row(self):
        """A timestamp the reducer cannot read must not cost the engine its row."""
        runs = [
            _run("weather", version="weather-v1", brier_ours=0.13, created_at="not a timestamp"),
            _run("weather", version="weather-v1", brier_ours=0.1242,
                 created_at="2026-09-20T00:00:00+00:00"),
        ]

        assert len(current_runs(runs)) == 1

    def test_taker_and_maker_are_kept_apart(self):
        # They are different fills and different economics; collapsing them would mix two
        # experiments into one number that means neither.
        runs = [
            _run("weather", version="weather-v1", mode="taker", brier_ours=0.1242),
            _run("weather", version="weather-v1", mode="maker", brier_ours=0.1180),
        ]

        rows = current_runs(runs)

        assert {r["mode"] for r in rows} == {"taker", "maker"}

    def test_one_row_per_engine_and_mode(self):
        runs = [
            _run("weather", version="weather-v1", mode="taker"),
            _run("gas", version="gas-v1", mode="taker"),
            _run("cpi_nowcast", version="cpi-v1", mode="taker"),
        ]

        assert len(current_runs(runs)) == 3

    def test_a_losing_engine_is_never_dropped(self):
        """The page exists to show losses. Omitting one would defeat it."""
        runs = [
            _run("gas", version="gas-v1", brier_ours=0.1148, brier_market=0.02676),
            _run("weather", version="weather-v1", brier_ours=0.1242),
            _run("labor_nowcast", version="labor-v1", brier_ours=0.1792, brier_market=0.1659),
        ]

        assert {r["engine"] for r in current_runs(runs)} == {"gas", "weather", "labor_nowcast"}

    def test_a_losing_engine_keeps_its_numbers_verbatim(self):
        """The page exists to answer whether to trust an engine, so a bad ratio, a negative P&L
        and a SHADOW badge all have to survive the reduction. Softening any of them would be the
        page flattering an engine."""
        runs = [_run("gas", version="gas-v1", brier_ours=0.1148, brier_market=0.02676)]

        row = current_runs(runs)[0]

        assert row["brier_ratio"] == pytest.approx(4.29, abs=0.01), "4.29x behind is the finding"
        assert row["pnl_after_fees"] == pytest.approx(-7.62)
        assert row["max_drawdown"] == pytest.approx(8.87)
        assert row["gate_status"] == "SHADOW"

    def test_a_run_with_no_brier_still_gets_a_row(self):
        """The gate emits "no market Brier recorded" for a run with nothing to compare against.
        That engine is the least trustworthy one on the page, so it is the one that must not
        disappear."""
        runs = [_run("labor_nowcast", version="labor-v1", brier_ours=None, brier_market=None,
                     reasons=[NO_MARKET_BRIER], n_settled=0)]

        rows = current_runs(runs)

        assert len(rows) == 1
        assert rows[0]["brier_ratio"] is None
        assert rows[0]["brier_ours"] is None

    def test_gate_reasons_are_carried_through_for_the_page_to_explain_itself(self):
        runs = [_run("cpi_nowcast", version="cpi-v1", reasons=[NEEDS_200_DAILY, P_AND_L_REASON],
                     n_settled=42)]

        assert current_runs(runs)[0]["gate_reasons"] == [NEEDS_200_DAILY, P_AND_L_REASON]

    def test_every_real_engine_reaches_the_page(self):
        """The failure this page must not have: an engine the plan did not list, permanently
        invisible. Every version a backtest_runs writer can produce, in one call."""
        versions = ["gas-v1", "weather-v1", "cpi-v1", "cpi-core-v1", "labor-v1"]
        runs = [
            _run("gas", version="gas-v1"),
            _run("weather", version="weather-v1"),
            _run("cpi_nowcast", version="cpi-v1"),
            _run("cpi_nowcast", version="cpi-core-v1", mode="maker"),
            _run("labor_nowcast", version="labor-v1"),
        ]

        rows = current_runs(runs)

        assert [r["engine_version"] for r in rows] == sorted(versions), rows
        assert len(rows) == 5


class TestBrierRatio:
    def test_the_ratio_is_how_far_behind_we_are(self):
        assert brier_ratio(0.1148, 0.02676) == pytest.approx(4.29, abs=0.01)

    def test_a_better_model_than_the_market_is_below_one(self):
        assert brier_ratio(0.05, 0.10) == pytest.approx(0.5)

    def test_missing_or_unusable_values_return_none_rather_than_guessing(self):
        assert brier_ratio(None, 0.1) is None
        assert brier_ratio(0.1, None) is None
        assert brier_ratio(0.1, 0) is None, "a zero market Brier has no defined ratio"
        assert brier_ratio(0.1, -0.1) is None, "nor does a negative one"
        assert brier_ratio("0.1", "0.2") is None, "a string is not a Brier"
        assert brier_ratio(None, None) is None


class TestGateDistance:
    def test_the_required_count_is_read_out_of_the_gate_reason(self):
        # The gate states its own requirement in words (tradehub/track_record.py:144):
        # "only 42 settled contracts, need 200 (daily)".
        assert required_settled([NEEDS_200_DAILY], None) == 200

    def test_the_bars_genuinely_differ_by_cadence_so_none_of_them_is_hardcoded(self):
        assert required_settled([NEEDS_50_MONTHLY], None) == 50
        assert MIN_CONTRACTS == {"daily": 200, "monthly": 50}

    def test_the_words_the_gate_might_phrase_it_the_other_way_are_also_read(self):
        assert required_settled(["only 42 settled contracts, need 200 settled (daily)"], None) == 200

    def test_the_required_count_is_found_among_several_reasons(self):
        assert required_settled([NO_MARKET_BRIER, P_AND_L_REASON, NEEDS_200_DAILY], None) == 200

    def test_an_explicit_minimum_wins_when_the_reason_does_not_state_one(self):
        assert required_settled([NO_MARKET_BRIER], 100) == 100

    def test_a_stated_requirement_beats_the_minimum(self):
        assert required_settled([NEEDS_50_MONTHLY], 100) == 50

    def test_no_requirement_anywhere_is_none_not_zero(self):
        # Zero would render as "0 of 0", i.e. as having met the gate.
        assert required_settled([BRIER_REASON], None) is None
        assert required_settled([], None) is None
        assert required_settled(None, None) is None
        assert required_settled([P_AND_L_REASON, CALIBRATION_REASON], None) is None
        assert required_settled([NO_MARKET_BRIER], 0) is None, "a zero minimum states no bar"

    def test_a_reason_that_is_not_a_string_is_skipped_rather_than_crashing(self):
        assert required_settled([None, 7, NEEDS_50_MONTHLY], None) == 50
        assert stated_settled_bar([None, 7, NEEDS_50_MONTHLY]) == 50

    def test_a_stated_bar_of_zero_is_silence_rather_than_a_bar(self):
        # Same rule as a floor of zero: a bar of 0 is not a bar, so it must not be read as one
        # met at zero, and must not shadow the floor either.
        assert stated_settled_bar(["only 0 settled contracts, need 0 (monthly)"]) is None
        assert required_settled(["only 0 settled contracts, need 0 (monthly)"], 100) == 100

    def test_the_stated_bar_never_falls_back_to_a_floor(self):
        """This is the whole distinction between the two bars: `stated_settled_bar` returning
        None means 'the gate named no bar', which is a fact about the engine, and must not be
        laundered into the reviewer's floor by the same helper that reports a flat number."""
        assert stated_settled_bar([BRIER_REASON]) is None
        assert required_settled([BRIER_REASON], MIN_SETTLED) == MIN_SETTLED

    def test_distance_reports_what_is_still_needed(self):
        assert settled_distance(42, 200) == {"n_settled": 42, "required": 200,
                                             "required_source": "gate", "remaining": 158,
                                             "met": False, "pct": 21.0,
                                             "floor": None, "floor_remaining": None,
                                             "floor_met": None, "floor_pct": None}

    def test_a_met_gate_says_so(self):
        assert settled_distance(120, 100) == {"n_settled": 120, "required": 100,
                                              "required_source": "gate", "remaining": 0,
                                              "met": True, "pct": 100.0,
                                              "floor": None, "floor_remaining": None,
                                              "floor_met": None, "floor_pct": None}

    def test_a_run_well_past_the_bar_does_not_render_over_a_hundred_percent(self):
        assert settled_distance(672, 200)["pct"] == 100.0
        assert settled_distance(672, 200)["met"] is True
        assert settled_distance(672, 200)["remaining"] == 0

    def test_an_unknown_requirement_yields_no_distance(self):
        assert settled_distance(42, None) is None, "a gate-sourced verdict needs a bar to judge"
        assert settled_distance(None, 200) is None
        assert settled_distance(42, 0) is None, "a bar of zero is no bar, not a met one"
        assert settled_distance(42, -5) is None

    def test_an_unrecognised_source_yields_no_distance_rather_than_a_guess(self):
        assert settled_distance(42, 200, required_source="floor") is None
        assert settled_distance(42, 200, required_source="") is None

    def test_a_bar_attributed_to_the_wrong_source_is_refused(self):
        """The one combination that must never render: a number filed as the engine's own bar
        when it is really somebody else's. A caller that disagrees with itself gets no number,
        not a correction this module has no basis to make."""
        assert settled_distance(70, 100, required_source="engine") is None
        assert settled_distance(70, 50, required_source="unknown") is None
        # ...and the coherent spelling of the same fact is accepted:
        assert settled_distance(70, None, required_source="engine")["met"] is True


class TestGateWording:
    """The two constants the module's correctness rests on, checked against the live source.

    `required_settled` parses a number out of prose. Prose is not a contract, so these
    assert against the function that actually writes the prose: if the gate is reworded,
    this fails rather than the page quietly rendering "no requirement stated".
    """

    def test_the_only_reason_that_states_a_requirement_is_parsed(self):
        assert required_settled(_gate_reasons(cadence="daily"), None) == 200

    def test_a_monthly_engine_states_its_own_lower_bar(self):
        reasons = _gate_reasons(cadence="monthly",
                                summary={"n_settled": 0, "brier_ours": None, "brier_market": None})
        assert required_settled(reasons, None) == 50

    def test_no_other_reason_is_mistaken_for_a_settled_requirement(self):
        # "10pp" and a percentage in a calibration miss are the plausible false positives.
        reasons = _gate_reasons(cal_buckets=[{"bucket": "70-80", "n": 30, "predicted": 0.75,
                                              "observed": 0.55}],
                                summary={"n_settled": 300, "brier_ours": 0.2, "brier_market": 0.1},
                                simulated_pnl_after_fees=-1.0)
        assert CALIBRATION_REASON in reasons
        assert required_settled(reasons, None) is None

    def test_the_fixtures_in_this_file_are_the_gate_s_actual_wording(self):
        for cadence, n_settled, expected in (("daily", 42, NEEDS_200_DAILY),
                                             ("monthly", 0, NEEDS_50_MONTHLY)):
            reasons = _gate_reasons(cadence=cadence,
                                    summary={"n_settled": n_settled, "brier_ours": 0.1242,
                                             "brier_market": 0.09713})
            assert expected in reasons, (cadence, reasons)


class TestSettledFloor:
    """`MIN_SETTLED` is imported, never written out: it is the reviewer's number in
    `tradehub/sports/scorecard.py`, and a second copy here is a second place to be wrong.

    The floor is reported on its own fields and is never the bar `met` is judged against --
    TestTwoBars covers that half. What is pinned here is that it is always present."""

    def test_a_run_that_owes_nothing_still_reports_the_products_own_floor(self):
        runs = [_run("weather", version="weather-v1", reasons=[BRIER_REASON], n_settled=672)]

        distance = current_runs(runs)[0]["settled_distance"]

        assert distance["floor"] == MIN_SETTLED
        assert distance["floor_met"] is True
        assert distance["floor_remaining"] == 0
        assert distance["floor_pct"] == 100.0

    def test_a_run_short_of_the_gates_own_bar_reports_that_bar_not_the_floor(self):
        runs = [_run("cpi_nowcast", version="cpi-v1", reasons=[NEEDS_200_DAILY], n_settled=42)]

        distance = current_runs(runs)[0]["settled_distance"]

        assert distance["required"] == 200
        assert distance["required_source"] == SOURCE_GATE
        assert distance["floor"] == MIN_SETTLED, "the floor is still reported, separately"

    def test_the_floor_is_the_live_constant(self):
        assert MIN_SETTLED == 100
        assert required_settled([BRIER_REASON], MIN_SETTLED) == MIN_SETTLED


class TestTwoBars:
    """The defect this class exists for: a RIGHT NUMBER UNDER THE WRONG LABEL.

    A monthly-cadence engine's own bar is 50 (`MIN_CONTRACTS`). At 70 settled it has met that
    bar, and the single-bar shape reported it as 70/100, met=False -- a verdict against the
    reviewer's floor dressed as the bar the engine owed. Every case below is built from the
    LIVE `check_promotion_gate`, so the premise (that the gate is silent at 70) is measured
    rather than assumed.
    """

    @staticmethod
    def _monthly_cleared_run():
        """A monthly engine holding 70 settled: past its own 50 bar, short of the 100 floor."""
        return _run(
            "cpi_nowcast", version="cpi-v1", n_settled=70,
            reasons=_gate_reasons(cadence="monthly",
                                  summary={"n_settled": 70, "brier_ours": 0.2,
                                           "brier_market": 0.1},
                                  simulated_pnl_after_fees=-1.0),
        )

    def test_the_premise_the_whole_shape_rests_on_is_true_of_the_live_gate(self):
        """`check_promotion_gate` names a settled bar only when n_settled < min_contracts, so a
        gate that ran and named none is positive evidence the engine cleared its own bar. If this
        stops holding, `SOURCE_ENGINE` becomes a guess and the shape should be rebuilt."""
        for cadence, bar in MIN_CONTRACTS.items():
            short = _gate_reasons(cadence=cadence,
                                  summary={"n_settled": bar - 1, "brier_ours": 0.2,
                                           "brier_market": 0.1})
            cleared = _gate_reasons(cadence=cadence,
                                    summary={"n_settled": bar, "brier_ours": 0.2,
                                             "brier_market": 0.1})
            assert stated_settled_bar(short) == bar, (cadence, short)
            assert stated_settled_bar(cleared) is None, (cadence, cleared)

        # The case the ruling is about, with the numbers spelled out:
        assert MIN_CONTRACTS["monthly"] == 50
        assert 70 >= MIN_CONTRACTS["monthly"], "70 settled clears a 50 bar"

    def test_a_reader_can_tell_which_bar_the_verdict_was_made_against(self):
        """Requirement 1. No prose: `required_source` names the bar, and each case puts its own
        number under the field that belongs to it."""
        cleared = current_runs([self._monthly_cleared_run()])[0]["settled_distance"]
        short = current_runs([
            _run("cpi_nowcast", version="cpi-v1", n_settled=42,
                 reasons=_gate_reasons(cadence="daily",
                                       summary={"n_settled": 42, "brier_ours": 0.2,
                                                "brier_market": 0.1}))
        ])[0]["settled_distance"]

        # The engine that met its own gate: the verdict is against its own bar, which is not
        # stated anywhere, and the 100 is visibly filed as the floor.
        assert cleared["required_source"] == SOURCE_ENGINE
        assert cleared["required"] is None
        assert cleared["floor"] == MIN_SETTLED

        # The engine short of its own gate: the verdict is against the gate's own number, and
        # the floor is again visibly the floor.
        assert short["required_source"] == SOURCE_GATE
        assert short["required"] == MIN_CONTRACTS["daily"]
        assert short["floor"] == MIN_SETTLED

        assert {cleared["required_source"], short["required_source"]} == {SOURCE_GATE, SOURCE_ENGINE}

    def test_an_engine_that_met_its_own_gate_is_not_reported_as_failing_a_number(self):
        """Requirement 2. This is the exact row the single-bar shape got wrong: 70 settled, its
        own bar 50, met -- rendered as 70/100, met=False, need 30 more."""
        row = current_runs([self._monthly_cleared_run()])[0]

        assert row["settled_distance"]["met"] is True
        assert row["settled_distance"]["remaining"] == 0
        assert row["settled_distance"]["required"] is None, "no bar was ever named to fail"

        # The number that would have produced met=False is still here -- as a floor, on its own
        # fields, where it cannot be read as the bar the engine owed.
        assert row["settled_distance"]["floor"] == MIN_SETTLED
        assert row["settled_distance"]["floor_met"] is False
        assert row["settled_distance"]["floor_remaining"] == 30
        assert row["settled_distance"]["floor_pct"] == 70.0

        # And the row still says what is actually blocking it, which was never the settled count.
        assert any("Brier" in r for r in row["gate_reasons"])
        assert not any("settled contracts" in r for r in row["gate_reasons"])

    def test_the_reviewers_floor_still_appears_even_when_the_gate_states_its_own_bar(self):
        """Requirement 3. The floor is reported on every row, gate-stated or not: "distance to
        the gate" is half the approval, and the reviewer is the component that will make the
        keep-or-drop call. Suppressing it behind a stated bar would lose that."""
        runs = [_run("cpi_nowcast", version="cpi-v1", n_settled=42,
                     reasons=_gate_reasons(cadence="daily",
                                           summary={"n_settled": 42, "brier_ours": 0.2,
                                                    "brier_market": 0.1}))]

        distance = current_runs(runs)[0]["settled_distance"]

        assert distance["required"] == 200 and distance["met"] is False
        assert distance["pct"] == 21.0, "42 of the gate's own 200"
        assert distance["floor"] == MIN_SETTLED
        assert distance["floor_remaining"] == 58
        assert distance["floor_met"] is False
        assert distance["floor_pct"] == 42.0, "42 of the reviewer's 100 -- a different bar"

    def test_every_row_carries_both_bars_and_a_source(self):
        """The shape holds for all three states, so no engine can render with one bar and no
        attribution -- which is the state the single-bar version had no way to express."""
        runs = [
            self._monthly_cleared_run(),                                     # met its own gate
            _run("cpi_nowcast", version="cpi-core-v1", n_settled=42, mode="maker",
                 reasons=_gate_reasons(cadence="daily",
                                       summary={"n_settled": 42, "brier_ours": 0.2,
                                                "brier_market": 0.1})),      # short of its own
            _run("gas", version="gas-v1", n_settled=672, reasons=[]),        # promoted, silent
        ]

        rows = {r["engine_version"]: r["settled_distance"] for r in current_runs(runs)}

        assert len(rows) == 3
        assert rows["cpi-v1"]["required_source"] == SOURCE_ENGINE
        assert rows["cpi-core-v1"]["required_source"] == SOURCE_GATE
        assert rows["gas-v1"]["required_source"] == SOURCE_ENGINE, "promoted with no complaints"
        for distance in rows.values():
            assert distance["floor"] == MIN_SETTLED
            assert distance["n_settled"] is not None

    def test_a_row_with_no_evidence_the_gate_ever_ran_claims_nothing(self):
        """Fail closed. `gate_reasons` is jsonb NOT NULL DEFAULT '[]' on a real row, so this is
        defensive -- but reading an absent gate as a met one is the one claim in this cell that
        would have no evidence behind it."""
        run = _run("labor_nowcast", version="labor-v1", n_settled=70, reasons=[])
        del run["gate_reasons"]

        distance = current_runs([run])[0]["settled_distance"]

        assert distance["required_source"] == SOURCE_UNKNOWN
        assert distance["met"] is None, "silence is not a pass"
        assert distance["required"] is None
        assert distance["floor"] == MIN_SETTLED, "the floor is still the reviewer's to read"

    def test_a_promoted_row_counts_as_evidence_the_gate_ran(self):
        """An all-clear is an empty list, not an absent one: the gate ran and found nothing
        outstanding, which is exactly the case where the engine met its own bar."""
        run = _run("gas", version="gas-v1", n_settled=672, reasons=[])
        run["gate_status"] = "PROMOTED"

        assert current_runs([run])[0]["settled_distance"]["required_source"] == SOURCE_ENGINE

    def test_a_stated_bar_the_run_has_already_met_is_reported_as_met_against_the_gate(self):
        """A stale row whose reasons name a bar the run went on to clear. The verdict still gets
        a bar to be against, and it is still the gate's -- so the row is self-consistent rather
        than quietly re-interpreted."""
        run = _run("cpi_nowcast", version="cpi-v1", n_settled=250, reasons=[NEEDS_200_DAILY])

        distance = current_runs([run])[0]["settled_distance"]

        assert distance["required_source"] == SOURCE_GATE
        assert distance["required"] == 200
        assert distance["met"] is True
        assert distance["pct"] == 100.0


class TestBacktestRunsProvenance:
    """Which `engine_version` values a `backtest_runs` row can actually carry.

    The plan asserted a list of five. If a writer can emit a sixth, the sixth engine is
    invisible on the page -- the one failure this page must not have -- so the list is
    pinned to the writers rather than to a comment.
    """

    def test_the_two_writers_emit_exactly_the_five_production_versions(self):
        from tradehub.engines.cpi import CPI_TARGETS
        from tradehub.scripts.backtest_engines import gas_version_for_lead
        from tradehub.scripts.backtest_labor import LABOR_ENGINE_VERSION

        # Every value `backtest_engines.py` or `backtest_labor.py` can pass as engine_version:
        # gas at the production lead and at an experimental one, weather, both CPI targets,
        # and labor. Nothing else reaches `backtest_runs` (no trigger, no other writer).
        produced = {
            gas_version_for_lead(2.0),
            gas_version_for_lead(2.5),
            "weather-v1",                                       # backtest_engines.py:321
            *(version for _, version in CPI_TARGETS.values()),  # backtest_engines.py:287
            LABOR_ENGINE_VERSION,                               # backtest_labor.py:163
        }
        assert produced == {"gas-v1", "gas-v1-lead2.5h", "weather-v1", "cpi-v1", "cpi-core-v1",
                            "labor-v1"}

    def test_the_production_versions_are_exactly_the_ones_the_predators_declare(self):
        from tradehub.engines.cpi import CPI_CORE_ENGINE_VERSION, CPI_ENGINE_VERSION
        from tradehub.engines.gas import GAS_ENGINE_VERSION
        from tradehub.engines.labor import LABOR_ENGINE_VERSION
        from tradehub.engines.weather import WEATHER_ENGINE_VERSION

        declared = {GAS_ENGINE_VERSION, WEATHER_ENGINE_VERSION, CPI_ENGINE_VERSION,
                    CPI_CORE_ENGINE_VERSION, LABOR_ENGINE_VERSION}

        assert declared == {"gas-v1", "weather-v1", "cpi-v1", "cpi-core-v1", "labor-v1"}
        assert not any(is_experiment_version(v) for v in declared)

    def test_no_production_version_contains_the_experiment_marker(self):
        """`-lead` is safe to key on only because no real version contains it."""
        for version in ("gas-v1", "weather-v1", "cpi-v1", "cpi-core-v1", "labor-v1"):
            assert "-lead" not in version
