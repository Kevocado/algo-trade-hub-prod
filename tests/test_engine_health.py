"""The ruling that a stopped engine must not read as a quiet one.

`tradehub/engine_health.py` is pure, so every rule here runs without a database and without a
network. What is under test is not arithmetic -- it is whether a reader of `/api/engine-health` can
tell these two things apart, which they must never be able to do:

    an engine that RAN and found no qualifying opportunity  -- a measurement
    an engine that COULD NOT RUN at all                    -- the absence of one

The prior art is `market_sentiment_tool/src/lib/displayOnlyEngines.ts` and its comment on the
sports path: "A READ THAT DROPS A ROW SILENTLY IS INDISTINGUISHABLE FROM THERE HAVING BEEN NO
ROWS." These are the same tests for a run that produces no row to drop.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from tradehub.engine_health import (
    EDGE_TYPE_LABELS,
    EDGE_TYPES,
    OPPORTUNITIES_NOT_COUNTED,
    OPPORTUNITIES_NOT_MEASURED,
    STATE_COULD_NOT_RUN,
    STATE_RAN,
    STOPPED_SITES,
    UNWIRED_STOPPED_SITES,
    WIRED_STOPPED_SITES,
    edge_type_entry,
    edge_type_state,
    engine_health,
    partition_edge_types,
    stopped_reason,
    stopped_sites_for,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# The exact read that is stopped, per site, quoted rather than pattern-matched. Kalshi moved these
# fields and the readers moved with it in neither case; this map is what makes "the ruling is
# stale" a test failure rather than an opinion.
OFFENDING_READS = {
    "tradehub/engines/weather_engine.py:214": "market.get('yes_ask', 0)",
    "tradehub/engines/macro_engine.py:453": "market.get('yes_ask', 0)",
    "tradehub/engines/weather_maker.py:258": 'market.get("price", 50)',
    "tradehub/core/kalshi_feed.py:284": "m.get('yes_ask', 0)",
}


# ── a broken engine reads as broken, with a reason ────────────────────────────────────────

class TestStoppedEnginesReadAsBroken:
    def test_weather_is_reported_as_could_not_run(self):
        assert edge_type_state("WEATHER") == STATE_COULD_NOT_RUN

    def test_macro_is_reported_as_could_not_run(self):
        assert edge_type_state("MACRO") == STATE_COULD_NOT_RUN

    def test_a_stopped_edge_type_carries_a_reason_and_never_an_empty_one(self):
        """A bare flag is jargon. The reason is the finding: it has to say the engine did not run
        and why, because "could_not_run" on a screen is a word nobody outside this repo knows."""
        reason = stopped_reason("WEATHER")
        assert reason, "a stopped engine with no reason is indistinguishable from a broken response"
        assert "yes_ask" in reason
        # The copy has to distinguish this from a search that ran. "Found nothing" is the one
        # phrase that would collapse the two states back together.
        assert "found no opportunity" not in reason.lower()

    def test_the_stopped_state_is_not_the_scoreboards_verdict_vocabulary(self):
        """`VERDICT_*` words are verdicts on a MEASUREMENT. An engine that never ran has none, so
        reusing them would imply a comparison nobody made."""
        from tradehub.scoreboard import VERDICT_AHEAD, VERDICT_BEHIND, VERDICT_LEVEL

        for state in (STATE_RAN, STATE_COULD_NOT_RUN):
            assert state not in {VERDICT_AHEAD, VERDICT_BEHIND, VERDICT_LEVEL}

    def test_a_stopped_engine_is_named_by_a_greppable_module_and_line(self):
        """The reason is only checkable if the reader can go and look. A ruling nobody can verify
        is a rumour with a status field."""
        for site in STOPPED_SITES:
            assert site.module, site
            path = REPO_ROOT / site.module
            assert path.is_file(), f"{site.module} does not exist; the ruling points at nothing"
            module, _, line = site.site.partition(":")
            assert module == site.module, site.site
            source = path.read_text().splitlines()
            assert 0 < int(line) <= len(source), site.site
            # The offending line must still BE the offending read, and the exact read is pinned
            # rather than pattern-matched: a ruling that has gone stale in the worst way keeps
            # calling a repaired engine stopped, and one that has drifted the other way stops
            # calling a broken engine anything at all.
            assert OFFENDING_READS[site.site] in source[int(line) - 1], (
                f"{site.site} no longer contains {OFFENDING_READS[site.site]!r}; the ruling is stale"
            )


# ── the two states stay distinguishable ─────────────────────────────────────────────────────

class TestRanAndFoundNothingIsStillQuiet:
    """The other direction, and the one a fix that only ever renders the failure would break. An
    engine that ran, looked and found nothing really is quiet, and hiding that would be its own
    kind of lie: it would make every unfashionable engine look broken and train the reader to
    ignore the label."""

    def test_sports_crypto_and_energy_are_reported_as_ran(self):
        for edge_type in ("SPORTS", "CRYPTO", "ENERGY"):
            assert edge_type_state(edge_type) == STATE_RAN, edge_type

    def test_a_running_edge_type_carries_no_reason(self):
        """`None`, not a string. A reason on a running engine would be a reason to distrust it, and
        the two states must not be able to look alike."""
        assert stopped_reason("SPORTS") is None

    def test_every_declared_edge_type_is_in_exactly_one_state(self):
        for edge_type, _label in EDGE_TYPES:
            entry = edge_type_entry(edge_type)
            assert entry["state"] in {STATE_RAN, STATE_COULD_NOT_RUN}, entry

    def test_the_ruling_does_not_contain_any_engine_that_actually_runs(self):
        """The engines that write to the ledger from `tradehub/scripts/scan.py` all run, and two of
        them publish to the SAME edge types as the stopped engines. Labelling one of those broken
        because its tab is empty would be a false claim about a working engine, and this is the
        test that says so."""
        running = {"gas", "weather", "cpi_nowcast", "labor_nowcast", "crypto", "sports_nfl", "sports_cfb"}
        for site in STOPPED_SITES:
            assert site.name not in running, (
                f"{site.name} is stopped, and the catalogue measures it -- a stopped engine with a "
                "backtest run and a Brier is a claim that its LIVE path is dead, which needs the "
                "live path named separately from the measured one"
            )

    def test_a_case_or_space_does_not_decide_whether_an_engine_is_stopped(self):
        """`upsert_opportunities` upper-cases `edge_type` before writing it, and a hand-built row
        may not have been. The state cannot depend on which shape turned up."""
        for variant in ("weather", "WEATHER", " Weather ", "WeAtHeR"):
            assert edge_type_state(variant) == STATE_COULD_NOT_RUN, variant
        assert edge_type_state("sports") == STATE_RAN


# ── a missing figure is never a number ──────────────────────────────────────────────────────

class TestAMissingFigureIsNeverZero:
    def test_a_stopped_edge_type_publishes_no_opportunity_count(self):
        """`0` here would read as "we looked and there was nothing here", which is the exact
        opposite of what happened, and it is the most damaging single value this product could
        print about a broken engine."""
        entry = edge_type_entry("WEATHER")
        assert entry["opportunities_found"] is None, entry
        assert entry["opportunities_found"] != 0

    def test_the_null_carries_a_reason_that_says_it_was_not_measured(self):
        for edge_type in ("WEATHER", "MACRO"):
            reason = edge_type_entry(edge_type)["opportunities_found_reason"]
            assert reason == OPPORTUNITIES_NOT_MEASURED, reason
            assert "zero" in reason.lower(), "the null has to say what it is not"

    def test_a_running_edge_type_is_null_for_the_other_reason_and_says_so(self):
        """Not counted here is a DIFFERENT fact from not measured, and conflating them would leave
        a reader unsure whether a running engine had nothing to report either."""
        entry = edge_type_entry("SPORTS")
        assert entry["opportunities_found"] is None
        assert entry["opportunities_found_reason"] == OPPORTUNITIES_NOT_COUNTED
        assert entry["opportunities_found_reason"] != OPPORTUNITIES_NOT_MEASURED

    def test_no_entry_anywhere_in_the_response_carries_a_numeric_zero(self):
        """The response-level version of the rule, so a future field added to an entry cannot
        reintroduce it without this failing."""
        body = engine_health()

        def walk(node, path="engine_health"):
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0:
                        raise AssertionError(f"{path}.{key} is 0; a missing figure is never a number")
                    walk(value, f"{path}.{key}")
            elif isinstance(node, (list, tuple)):
                for i, value in enumerate(node):
                    walk(value, f"{path}[{i}]")

        walk(body)


# ── conservation: nothing is dropped ────────────────────────────────────────────────────────

class TestConservation:
    def test_partition_keeps_every_input_exactly_once(self):
        names = [edge_type for edge_type, _label in EDGE_TYPES]
        result = partition_edge_types(names)
        assert len(result) == len(names)
        assert sorted(result.ran + result.could_not_run) == sorted(names)
        assert set(result.could_not_run) == {"WEATHER", "MACRO"}

    def test_partition_conserves_duplicates_rather_than_using_a_set(self):
        """A set operation would collapse a repeated edge type into one, and the caller is entitled
        to know it was handed two."""
        result = partition_edge_types(["SPORTS", "SPORTS", "WEATHER"])
        assert result.ran == ("SPORTS", "SPORTS")
        assert result.could_not_run == ("WEATHER",)
        assert len(result) == 3

    def test_an_empty_input_partitions_to_two_empty_buckets(self):
        result = partition_edge_types([])
        assert result.ran == () and result.could_not_run == () and len(result) == 0

    def test_no_input_partitions_to_no_buckets(self):
        result = partition_edge_types(None)
        assert len(result) == 0

    def test_a_hand_built_edge_type_does_not_raise(self):
        """This is called from a read. A read that dies on a row it was handed reports the fault
        as a crash, and a crash looks identical to a board with nothing on it."""
        assert edge_type_state(None) == STATE_RAN
        assert edge_type_state(17) == STATE_RAN
        assert stopped_sites_for(object()) == ()

    def test_the_counts_in_the_response_agree_with_the_entries(self):
        body = engine_health()
        entries = body["edge_types"]
        assert body["edge_types_total"] == len(entries) == len(EDGE_TYPES)
        assert body["edge_types_could_not_run"] + body["edge_types_ran"] == body["edge_types_total"]
        assert body["edge_types_could_not_run"] == sum(
            1 for e in entries if e["state"] == STATE_COULD_NOT_RUN
        )
        assert len(body["sites"]) == body["sites_total"] == len(STOPPED_SITES)
        assert body["sites_wired"] == len(WIRED_STOPPED_SITES)
        assert body["sites_unwired"] == len(UNWIRED_STOPPED_SITES)
        assert body["sites_wired"] + body["sites_unwired"] == body["sites_total"]

    def test_the_whole_board_carries_one_state_and_it_is_derived_here(self):
        """The unfiltered view is where a reader lands first, and asking the page "is any of these
        stopped" would be a rule in a second language with no test on it."""
        body = engine_health()
        assert body["board_state"] == STATE_COULD_NOT_RUN
        assert body["board_reason"]
        # And it agrees with the entries it summarises, so the two can never disagree.
        assert (body["board_state"] == STATE_COULD_NOT_RUN) == (body["edge_types_could_not_run"] > 0)
        # The board reason is the wired reasons in the entries' own order, so the unfiltered view
        # quotes the same sentences the per-tab view does rather than a paraphrase of them.
        wired = [e["reason"] for e in body["edge_types"] if e["state"] == STATE_COULD_NOT_RUN]
        assert body["board_reason"] == " ".join(wired)

    def test_a_board_with_nothing_stopped_says_so_rather_than_carrying_a_reason(self):
        """The mirror of the rule above: `None` on a clean board, so the two states cannot look
        alike. Exercised through the same function with the ruling emptied, because a healthy
        product must render as healthy -- see the tests above for the direction that matters."""
        from tradehub import engine_health as module

        original = module.STOPPED_SITES
        module.STOPPED_SITES = ()
        module.WIRED_STOPPED_SITES = ()
        module.UNWIRED_STOPPED_SITES = ()
        try:
            body = module.engine_health()
        finally:
            module.STOPPED_SITES = original
            module.WIRED_STOPPED_SITES = tuple(s for s in original if s.wired_to_a_scanner)
            module.UNWIRED_STOPPED_SITES = tuple(s for s in original if not s.wired_to_a_scanner)
        assert body["board_state"] == STATE_RAN
        assert body["board_reason"] is None
        assert body["edge_types_could_not_run"] == 0

    def test_every_entry_is_labelled(self):
        """An undeclared edge type is labelled by its own key, the way `engine_catalogue` does it.
        A blank cell is a gap, and a gap on this page is a board with no state at all."""
        for edge_type, _label in EDGE_TYPES:
            assert edge_type_entry(edge_type)["label"] == EDGE_TYPE_LABELS[edge_type]
        assert edge_type_entry("NOT_A_THING")["label"] == "NOT_A_THING"


# ── an unwired helper cannot be blamed for an empty board ───────────────────────────────────

class TestUnwiredSitesAreNotBlameable:
    def test_a_site_no_scanner_calls_does_not_set_the_state(self):
        """The question is not "is there unfixed code for this tab" but "did the thing that runs
        against this tab run". `WeatherMaker` is unfixed and feeds no scan."""
        assert any(s.name == "WeatherMaker" for s in UNWIRED_STOPPED_SITES)
        assert not any(s.name == "WeatherMaker" for s in WIRED_STOPPED_SITES)

    def test_a_helper_that_feeds_no_board_is_in_the_ruling_but_in_no_board(self):
        """`clean_market_data` is a shared-feed helper with no caller. It is on the ruling so the
        fourth site of the same drift is visible, and off every edge type so it cannot be quoted as
        the reason a live board is empty."""
        names = {s.name for s in stopped_sites_for("MACRO")}
        assert "clean_market_data" not in names
        assert any(s.name == "clean_market_data" for s in STOPPED_SITES)
        assert edge_type_entry("MACRO")["stopped_sites"], "the wired macro engine must still be there"

    def test_an_unwired_site_is_still_listed_under_the_edge_type_it_would_feed(self):
        """Dropping it from the payload would hide a real defect from whoever fixes it. The flag,
        not the count, is what stops it being misread as a cause."""
        names = {s["name"] for s in edge_type_entry("WEATHER")["stopped_sites"]}
        assert names == {"WeatherEngine", "WeatherMaker"}
        wired = [s for s in edge_type_entry("WEATHER")["stopped_sites"] if s["wired_to_a_scanner"]]
        assert [s["name"] for s in wired] == ["WeatherEngine"]

    def test_the_reason_quoted_for_an_empty_board_never_names_an_unwired_site(self):
        for edge_type, _label in EDGE_TYPES:
            reason = stopped_reason(edge_type) or ""
            for site in UNWIRED_STOPPED_SITES:
                assert site.name not in reason, (
                    f"{site.name} is not wired to a scanner, so it cannot be the reason "
                    f"{edge_type} is empty"
                )


# ── it is a ruling about the LIVE path, not a verdict on a measured engine ──────────────────

class TestTheRulingIsAboutTheLivePath:
    def test_weather_the_measured_engine_is_not_the_stopped_site(self):
        """This is the tension, stated as a test rather than as a footnote.

        `weather` is the catalogue's measured engine: 672 settled contracts, a real Brier, a real
        verdict against the market, all produced by `tradehub/scripts/scan.py`. `WeatherEngine` is
        the Tier-1 engine behind `background_scanner.py`, which cannot run. They are different
        engines that write the SAME `engine` key and the same WEATHER edge type, and the product
        reports the first as measured-and-losing while the second emits nothing at all.

        So the ruling names the CLASS and the MODULE, never the `kalshi_edges.engine` value. Join
        the two and the Models page would put "stopped" beside a 1.45x backtest, which is a claim
        about an engine that demonstrably runs.
        """
        stopped = {s.name for s in STOPPED_SITES}
        assert "WeatherEngine" in stopped
        assert "weather" not in stopped

        from tradehub.core.supabase_client import upsert_opportunities
        from tradehub.engines.weather_engine import WeatherEngine

        # The collision itself, pinned at both ends so nobody "fixes" the ruling by joining on the
        # `engine` column: the stopped engine writes 'Weather', and the writer lower-cases it.
        assert "'engine': 'Weather'" in inspect.getsource(WeatherEngine.find_opportunities)
        assert 'str(op["engine"]).strip().lower()' in inspect.getsource(upsert_opportunities)

    def test_the_note_in_the_response_says_a_stopped_engine_found_nothing_not(self):
        assert "not a finding" in engine_health()["note"]


# ── the endpoint ────────────────────────────────────────────────────────────────────────────

class TestEngineHealthEndpoint:
    def _client(self):
        from fastapi.testclient import TestClient
        from tradehub.api import main

        return main, TestClient(main.app)

    def test_it_serves_the_ruling_with_no_database_at_all(self):
        """A ruling that needs a credential to be read is a ruling that will be duplicated in the
        browser instead, and the copy is the thing that can then disagree with the server about
        which engines are switched off."""
        main, client = self._client()
        response = client.get("/api/engine-health")
        assert response.status_code == 200
        body = response.json()
        assert body["edge_types_total"] == len(EDGE_TYPES)
        assert body["edge_types_could_not_run"] >= 1
        assert {e["edge_type"] for e in body["edge_types"] if e["state"] == STATE_COULD_NOT_RUN}
        assert body["as_of"]

    def test_it_works_with_no_supabase_configured(self):
        """It reads no table, so a missing Supabase must not turn the ruling into a 503. A reader
        who cannot see which engines are stopped is exactly the reader this endpoint is for."""
        from tradehub.api.dependencies import get_supabase

        main, client = self._client()
        main.app.dependency_overrides[get_supabase] = lambda: None
        try:
            assert client.get("/api/engine-health").status_code == 200
        finally:
            main.app.dependency_overrides.clear()

    def test_it_answers_json_even_with_the_spa_mounted_over_it(self):
        """`mount_frontend` mounts the SPA at "/", so a route registered after it is shadowed and
        this endpoint would answer with the app shell.

        The property itself is pinned for EVERY route by
        `tests/test_cpi_display.py::test_every_api_route_is_registered_before_the_spa_catch_all`,
        which drives a temp dist so the mount happens whether or not this machine has ever run
        `npm run build`. Asserting the order here as well would be a second copy of one rule that
        only runs in some environments -- and the version that ran in the fewest environments is
        precisely how the ordering bug survived a merge.
        """
        from tradehub.api import main

        paths = [getattr(route, "path", None) for route in main.app.routes]
        assert "/api/engine-health" in paths, paths
