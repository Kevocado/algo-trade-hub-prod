"""The engine catalogue: every engine the product has, and what each one has actually scored.

The failure this file exists to prevent is the one the whole redesign turns on: **an engine
missing from the page**. `backtest_runs` only holds engines somebody ran a backtest for, so a
catalogue that reads the board and renders what it finds has already lost half the product before
the first row is drawn. An absent engine reads as "this engine has nothing to show", which is a
claim about the engine that nobody made.

So the join is `engine_catalogue`, and the direction of the join is the argument:

- every CATALOGUE engine appears, measured or not, and an unmeasured one says `not_measured`
  rather than rendering as an empty row of dashes or, worse, as a zero;
- every engine that HAS a row appears too, even one the catalogue has never heard of -- a new
  engine is a reason to notice the catalogue is behind, not a reason to leave the page;
- every row lands in exactly one entry, and `measured + not_measured == total`, so "7 engines"
  cannot quietly become true of a board of three.

Pure, like `tradehub/scoreboard.py`, so all of it runs without a database.
"""
import copy
import inspect
import re

from tradehub.engine_catalogue import (
    CATALOGUE_ENGINES,
    CLAIM_UNLISTED,
    ENGINE_CATALOGUE,
    ENGINE_TOMBSTONES,
    STATUS_NOT_MEASURED,
    STATUS_RETIRED,
    catalogue_entry,
    engine_catalogue,
    engine_status,
    row_verdict,
    worst_brier_ratio,
)
from tradehub.scoreboard import (
    BEHIND_THE_MARKET,
    VERDICT_AHEAD,
    VERDICT_BEHIND,
    VERDICT_LEVEL,
    VERDICT_NOT_COMPARABLE,
    current_runs,
    market_verdict,
)


def _row(engine, *, mode="taker", version="gas-v1", ratio=4.29, verdict=VERDICT_BEHIND, **over):
    """A scoreboard row in the shape `current_runs` produces, with `promotion_status` attached."""
    row = {
        "engine": engine,
        "engine_version": version,
        "mode": mode,
        "date_from": "2026-06-01T00:00:00+00:00",
        "date_to": "2026-09-20T00:00:00+00:00",
        "created_at": "2026-09-20T00:00:00+00:00",
        "n_decisions": 1982,
        "n_fills": 274,
        "n_settled": 42,
        "brier_ours": 0.1148,
        "brier_market": 0.02676,
        "brier_ratio": ratio,
        "market_verdict": verdict,
        "pnl_after_fees": -3.84,
        "max_drawdown": 7.06,
        "gate_status": "SHADOW",
        "gate_reasons": ["only 42 settled contracts, need 200 (daily)"],
        "settled_distance": {
            "n_settled": 42, "required": 200, "required_source": "gate", "remaining": 158,
            "met": False, "pct": 21.0, "floor": 100, "floor_remaining": 58, "floor_met": False,
            "floor_pct": 42.0,
        },
        "promotion_status": "SHADOW",
    }
    row.update(over)
    return row


# ── the catalogue's own shape ──────────────────────────────────────────────────
class TestTheCatalogue:
    def test_it_declares_every_engine_the_product_settles(self):
        """The catalogue and the settlement cron enumerate the same engines, and they must not
        drift: an engine the cron settles and the catalogue does not name is invisible to the
        page that exists to explain the product.

        Pinned by test rather than imported, for the reason `tradehub/sports/scan.py` gives about
        its own three copies of the sports map: `settle_predictions` pulls the settlement and
        track-record stacks in at import time, and a catalogue that cannot be imported without a
        client is a catalogue that gets duplicated instead.
        """
        from tradehub.scripts.settle_predictions import ENGINES

        assert {engine for engine, _ in ENGINES} == CATALOGUE_ENGINES

    def test_the_cadence_is_the_gates_own_word_for_each_engine(self):
        """Cadence is why the two bars differ per engine (200 daily, 50 monthly), so a catalogue
        that disagreed with the settlement cron about it would put the wrong number beside the
        wrong bar."""
        from tradehub.scripts.settle_predictions import ENGINES

        assert {e["engine"]: e["cadence"] for e in ENGINE_CATALOGUE} == dict(ENGINES)

    def test_every_engine_carries_a_claim_a_reader_could_check(self):
        for entry in ENGINE_CATALOGUE:
            assert entry["claim"], entry
            assert entry["label"], entry
            # A claim is the sentence that names the market, not a category. "A macro engine" is
            # exactly what the owner said he did not understand, so it is refused here rather
            # than left to taste.
            assert len(entry["claim"]) > 60, entry

    def test_a_claim_names_a_kalshi_market_or_says_why_it_cannot(self):
        """A claim with no market attached is unfalsifiable. Sports and crypto legitimately have
        no `KX` contract to name -- one is scored on the shadow timeline, the other's probability
        comes from a predictor feed -- so what is required is that the claim says so."""
        for entry in ENGINE_CATALOGUE:
            claim = entry["claim"]
            if re.search(r"KX[A-Z]", claim):
                continue
            assert re.search(r"predictor feed|shadow timeline", claim), (
                f"{entry['engine']} names no market and does not say what it is scored against"
            )

    def test_every_version_a_writer_can_produce_is_reachable_from_its_engine(self):
        """`cpi_nowcast` writes two versions (headline and core) and they must both land on the
        one entry, or the core engine's record renders as a separate unknown engine."""
        from tradehub.engines.cpi import CPI_ENGINE_VERSION, CPI_CORE_ENGINE_VERSION
        from tradehub.engines.gas import GAS_ENGINE_VERSION
        from tradehub.engines.labor import LABOR_ENGINE_VERSION
        from tradehub.engines.weather import WEATHER_ENGINE_VERSION

        runs = [
            {"engine": "gas", "engine_version": GAS_ENGINE_VERSION, "mode": "taker",
             "gate_reasons": [], "gate_status": "SHADOW"},
            {"engine": "weather", "engine_version": WEATHER_ENGINE_VERSION, "mode": "taker",
             "gate_reasons": [], "gate_status": "SHADOW"},
            # Two VERSIONS of one engine need two MODES to both survive `current_runs`, which
            # keys on `(engine, mode)` and otherwise keeps only the newest run per pair. That
            # collapse is the scoreboard's existing, documented reduction and this page inherits
            # it rather than re-deriving anything; asserting it here is what keeps the page from
            # quietly promising two rows where the board produces one.
            {"engine": "cpi_nowcast", "engine_version": CPI_ENGINE_VERSION, "mode": "taker",
             "gate_reasons": [], "gate_status": "SHADOW"},
            {"engine": "cpi_nowcast", "engine_version": CPI_CORE_ENGINE_VERSION, "mode": "maker",
             "gate_reasons": [], "gate_status": "SHADOW"},
            {"engine": "labor_nowcast", "engine_version": LABOR_ENGINE_VERSION, "mode": "taker",
             "gate_reasons": [], "gate_status": "SHADOW"},
        ]
        rows = current_runs(runs)
        catalogue = engine_catalogue(rows)
        cpi = next(e for e in catalogue["entries"] if e["engine"] == "cpi_nowcast")

        assert cpi["measured_rows"] == 2, "headline and core are two rows of one engine"
        assert catalogue["engines_unlisted"] == 0
        assert {r["engine_version"] for r in cpi["rows"]} == {CPI_ENGINE_VERSION, CPI_CORE_ENGINE_VERSION}

    def test_it_holds_no_threshold_of_its_own(self):
        """The one number the module must not contain is a second copy of the market threshold.
        Parsed rather than grepped, so the docstring is allowed to NAME the rule while the code
        is held to it."""
        import ast

        import tradehub.engine_catalogue as module

        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and body
                    and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)):
                body[0].value.value = ""
        executable = ast.unparse(tree)

        assert "1.0" not in executable, "a literal 1.0 is a second copy of BEHIND_THE_MARKET"
        assert "market_verdict(" in executable, "the module stopped routing through the shared verdict"


# ── the join: nothing is dropped, and nothing is invented ──────────────────────
class TestTheJoin:
    def test_an_engine_with_no_backtest_is_present_and_says_it_was_not_measured(self):
        """The absence-is-not-zero rule, at the join rather than at the rendering.

        An engine with no row is ABSENT from `backtest_runs`, and an absent engine reads as "this
        engine has nothing to show" -- a claim about the engine that nobody made. So `crypto` and
        both sports engines are in the response with `measured: false` and their own status word.
        """
        catalogue = engine_catalogue([_row("gas")])
        by_engine = {e["engine"]: e for e in catalogue["entries"]}

        for engine in ("crypto", "sports_nfl", "sports_cfb"):
            entry = by_engine[engine]
            assert entry["measured"] is False
            assert entry["status"] == STATUS_NOT_MEASURED
            assert entry["rows"] == []
            # And a real claim, not a placeholder, because the claim is not a measurement.
            assert entry["claim"]

    def test_an_unmeasured_engine_carries_no_ratio_at_all(self):
        """`None`, never `0`. A ratio of zero would be a model that never misses, and the absence
        of a comparison is not that. `None` is also what the page's formatters dash, so the
        "measured as zero" reading cannot survive even if the page changed."""
        by_engine = {e["engine"]: e for e in engine_catalogue([])["entries"]}

        for entry in by_engine.values():
            assert entry["worst_brier_ratio"] is None
            assert entry["measured"] is False

    def test_an_empty_ledger_still_returns_every_engine(self):
        """The realistic first-run state, and the one this page exists for: the board is empty and
        the page must still answer the question. `runs_read: 0` and seven engines, none measured."""
        catalogue = engine_catalogue([])

        assert catalogue["engines_total"] == len(CATALOGUE_ENGINES)
        assert catalogue["engines_measured"] == 0
        assert catalogue["engines_not_measured"] == len(CATALOGUE_ENGINES)
        assert all(e["status"] == STATUS_NOT_MEASURED for e in catalogue["entries"])

    def test_every_row_lands_in_exactly_one_entry(self):
        """Conservation. A row quietly uncounted is how "7 engines" becomes true of a board of 3."""
        rows = [
            _row("gas"),
            _row("weather", mode="taker", version="weather-v1", ratio=1.2787),
            _row("weather", mode="maker", version="weather-v1", ratio=1.0954),
            _row("labor_nowcast", version="labor-v1", ratio=1.0802),
        ]

        entries = engine_catalogue(rows)["entries"]

        carried = [row for entry in entries for row in entry["rows"]]
        assert len(carried) == len(rows)
        # And the same objects, so the page cannot be handed a second, edited copy of a row.
        assert all(any(row is original for original in rows) for row in carried)

    def test_the_counts_conserve(self):
        rows = [_row("gas"), _row("weather", version="weather-v1", ratio=1.2)]
        catalogue = engine_catalogue(rows)

        assert catalogue["engines_measured"] + catalogue["engines_not_measured"] == (
            catalogue["engines_total"]
        )
        assert catalogue["engines_total"] == len(catalogue["entries"])
        assert catalogue["engines_measured"] == 2

    def test_an_engine_the_catalogue_has_never_heard_of_still_appears(self):
        """A new engine is a reason to notice the catalogue is behind, not a reason to leave the
        page. It arrives saying exactly that -- `claim: null` plus a note -- rather than with an
        empty cell a reader fills in themselves."""
        rows = [_row("gas"), _row("fx_carry", version="fx-v1")]

        catalogue = engine_catalogue(rows)
        unlisted = next(e for e in catalogue["entries"] if e["engine"] == "fx_carry")

        assert catalogue["engines_unlisted"] == 1
        assert unlisted["in_catalogue"] is False
        assert unlisted["claim"] is None
        assert unlisted["claim_note"] == CLAIM_UNLISTED
        # Still measured, and still carrying its row, because the run is real evidence.
        assert unlisted["measured"] is True
        assert unlisted["status"] == VERDICT_BEHIND
        assert unlisted["worst_brier_ratio"] == 4.29
        # Labelled by its own key rather than by something invented for it.
        assert unlisted["label"] == "fx_carry"
        assert unlisted["cadence"] is None

    def test_a_declared_engine_keeps_its_catalogue_order(self):
        """Stable order, so a reader who comes back to the page finds gas in the same place and
        an engine cannot be quietly reshuffled by an unrelated edit to the board."""
        entries = engine_catalogue([_row("labor_nowcast", version="labor-v1")])["entries"]
        assert [e["engine"] for e in entries] == [e["engine"] for e in ENGINE_CATALOGUE]

    def test_a_row_with_no_engine_name_is_skipped_rather_than_raising(self):
        """`current_runs` never produces one, so this is a guard on a hand-built row -- and a
        skip, not a raise, because a catalogue that crashed would take the whole page down."""
        catalogue = engine_catalogue([_row("gas"), _row(None), _row("")])

        assert sum(e["measured_rows"] for e in catalogue["entries"]) == 1

    def test_it_is_pure_and_does_not_mutate_its_input(self):
        rows = [_row("gas")]
        before = copy.deepcopy(rows)

        engine_catalogue(rows)

        assert rows == before

    def test_catalogue_entry_is_none_rather_than_a_synthesised_record(self):
        """An absent catalogue record and a present one with empty fields are different facts,
        and the join needs to be able to tell them apart."""
        assert catalogue_entry("gas") is not None
        assert catalogue_entry("fx_carry") is None
        assert catalogue_entry(None) is None
        assert catalogue_entry(7) is None

    def test_a_catalogue_entry_cannot_be_mutated_through_the_lookup(self):
        entry = catalogue_entry("gas")
        entry["claim"] = "rewritten"
        assert catalogue_entry("gas")["claim"] != "rewritten"


# ── the status roll-up, and the number it summarises ──────────────────────────
class TestTheStatusRollUp:
    def test_a_losing_engine_is_reported_at_its_worst_row(self):
        """Taker and maker are different fills and can disagree. Reporting the better one is
        choosing which row to lead with, and the choice would be made in a component, silently,
        in whichever direction its author preferred."""
        rows = [
            _row("weather", mode="taker", ratio=1.0954),
            _row("weather", mode="maker", ratio=1.2787),
        ]

        entry = engine_catalogue(rows)["entries"]
        weather = next(e for e in entry if e["engine"] == "weather")

        assert weather["status"] == VERDICT_BEHIND
        assert weather["worst_brier_ratio"] == 1.2787
        # And both rows still ride along, so the worst is never the only figure on offer.
        assert len(weather["rows"]) == 2

    def test_gas_is_reported_at_four_point_two_nine_and_not_at_its_better_run(self):
        """The concrete case this product is about: 4.29x at the production 2h and 2.16x at the
        12h experiment. The experiment is excluded upstream as a decision-lead version, but the
        failure mode survives in any other shape -- two fill modes, two configs -- and the rule
        is the same: the summary line is built from the worst measured row."""
        rows = [
            _row("gas", mode="taker", ratio=4.29),
            _row("gas", mode="maker", ratio=2.16),
        ]

        entry = next(e for e in engine_catalogue(rows)["entries"] if e["engine"] == "gas")

        assert entry["worst_brier_ratio"] == 4.29
        assert entry["status"] == VERDICT_BEHIND

    def test_a_row_with_no_ratio_is_not_comparable_and_not_a_loss(self):
        entry = next(
            e for e in engine_catalogue(
                [_row("weather", ratio=None, verdict=VERDICT_NOT_COMPARABLE, brier_market=None)]
            )["entries"]
            if e["engine"] == "weather"
        )

        assert entry["status"] == VERDICT_NOT_COMPARABLE
        assert entry["worst_brier_ratio"] is None
        # Measured: the run exists. Uncompared is a different fact from unmeasured.
        assert entry["measured"] is True

    def test_an_engine_ahead_of_the_market_says_ahead(self):
        entry = next(
            e for e in engine_catalogue(
                [_row("weather", ratio=0.5, verdict=VERDICT_AHEAD)]
            )["entries"]
            if e["engine"] == "weather"
        )

        assert entry["status"] == VERDICT_AHEAD
        assert entry["worst_brier_ratio"] == 0.5

    def test_a_tie_is_level_and_not_a_loss(self):
        entry = next(
            e for e in engine_catalogue(
                [_row("weather", ratio=1.0, verdict=VERDICT_LEVEL)]
            )["entries"]
            if e["engine"] == "weather"
        )

        assert entry["status"] == VERDICT_LEVEL

    def test_a_mixed_engine_is_reported_behind_not_ahead(self):
        rows = [
            _row("weather", mode="taker", ratio=0.5, verdict=VERDICT_AHEAD),
            _row("weather", mode="maker", ratio=3.0, verdict=VERDICT_BEHIND),
        ]
        assert engine_status(rows) == VERDICT_BEHIND

    def test_no_rows_is_not_measured_which_is_not_a_verdict(self):
        assert engine_status([]) == STATUS_NOT_MEASURED
        assert engine_status(None) == STATUS_NOT_MEASURED
        # And it is not one of the four verdicts: it is the absence of one.
        assert STATUS_NOT_MEASURED not in (
            VERDICT_AHEAD, VERDICT_BEHIND, VERDICT_LEVEL, VERDICT_NOT_COMPARABLE
        )


class TestRowVerdict:
    def test_it_passes_through_the_verdict_the_reducer_resolved(self):
        assert row_verdict({"market_verdict": VERDICT_BEHIND, "brier_ratio": 4.29}) == VERDICT_BEHIND

    def test_it_asks_the_shared_function_when_the_row_carries_no_verdict(self):
        """A hand-built or older row has no `market_verdict`, and falling through to a default
        would be a verdict nobody resolved. The fallback is `market_verdict()` itself, so the
        threshold is still applied in exactly one place."""
        assert row_verdict({"brier_ratio": 4.29}) == VERDICT_BEHIND
        assert row_verdict({"brier_ratio": 0.5}) == VERDICT_AHEAD
        assert row_verdict({}) == VERDICT_NOT_COMPARABLE

    def test_an_unrecognised_word_is_not_taken_at_face_value(self):
        # "close" is not a verdict this module knows, so the row's own ratio decides.
        assert row_verdict({"market_verdict": "close", "brier_ratio": 4.29}) == VERDICT_BEHIND

    def test_the_fallback_agrees_with_the_verdict_the_reducer_itself_would_produce(self):
        """Not a hope: the two are the same application of the same threshold, measured."""
        for ratio in (0.5, 1.0, 1.0001, 4.29, None):
            assert row_verdict({"brier_ratio": ratio}) == market_verdict(ratio)


class TestWorstBrierRatio:
    def test_it_is_the_largest_comparable_ratio(self):
        assert worst_brier_ratio([{"brier_ratio": 1.2}, {"brier_ratio": 4.29}]) == 4.29

    def test_it_is_none_rather_than_zero_when_nothing_was_compared(self):
        assert worst_brier_ratio([{"brier_ratio": None}]) is None
        assert worst_brier_ratio([{}]) is None
        assert worst_brier_ratio([]) is None
        assert worst_brier_ratio(None) is None

    def test_a_boolean_is_not_a_ratio(self):
        """`bool` is an `int`, so `True` would become 1.0 -- a tie invented out of a value that
        is not a measurement. `market_verdict` refuses booleans for the same reason."""
        assert worst_brier_ratio([{"brier_ratio": True}]) is None
        assert worst_brier_ratio([{"brier_ratio": 4.29}, {"brier_ratio": True}]) == 4.29

    def test_a_nan_is_not_a_ratio(self):
        """NaN compares false to itself, so a naive max() would return it and the page would
        print `NaNx the market's Brier`."""
        assert worst_brier_ratio([{"brier_ratio": float("nan")}]) is None

    def test_a_string_is_not_a_ratio(self):
        assert worst_brier_ratio([{"brier_ratio": "4.29"}]) is None

    def test_a_zero_ratio_survives_because_zero_is_a_measurement(self):
        """A measured Brier of 0.0 IS a real number, and it is not "not measured". The distinction
        this repo keeps is between a figure nobody took and a figure that came out zero."""
        assert worst_brier_ratio([{"brier_ratio": 0.0}]) == 0.0

    def test_it_does_not_re_derive_the_ratio_from_the_two_briers(self):
        """`brier_ratio` is the reducer's own arithmetic, already rounded once. Recomputing it
        here would be a second copy that could disagree about the rounding."""
        assert worst_brier_ratio([{"brier_ours": 0.1148, "brier_market": 0.02676}]) is None


def test_the_threshold_it_summarises_is_the_threshold_the_board_already_uses():
    """The roll-up reads `market_verdict`; it never compares a ratio to a number of its own. This
    is asserted structurally because the behavioural version cannot distinguish a re-derivation
    that happens to agree from one that does not."""
    import ast

    import tradehub.engine_catalogue as module

    tree = ast.parse(inspect.getsource(module.engine_status))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and body
                and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)):
            body[0].value.value = ""
    executable = ast.unparse(tree)

    assert str(BEHIND_THE_MARKET) not in executable
    assert "row_verdict(" in executable, "the roll-up stopped reading the reduced row's own verdict"


_GONE = {"engine": "macro_engine", "label": "Macro engine (retired)", "removed": "2026-10-15",
    "reason": "deleted with the legacy daemon; its quarantine ruling was superseded",
    "replaced_by": "cpi_nowcast"}


class TestRetiredEnginesLeaveATombstone:
    """Deleted engines do not vanish (v2 spec §9): they stay on the page as `retired`."""

    def test_no_engine_is_retired_until_a_pr_deletes_one(self):
        assert ENGINE_TOMBSTONES == ()
        assert engine_catalogue([_row("gas")])["engines_retired"] == 0

    def test_a_tombstone_is_a_retired_entry_with_what_happened_and_what_replaced_it(self):
        catalogue = engine_catalogue([_row("gas")], tombstones=[_GONE])
        entry = catalogue["entries"][-1]
        assert entry["engine"] == "macro_engine" and entry["status"] == STATUS_RETIRED
        assert entry["retired"] == {"removed": "2026-10-15", "reason": _GONE["reason"],
                                    "replaced_by": "cpi_nowcast"}
        assert entry["claim"] is None and entry["claim_note"].startswith("Retired: ")
        assert entry["measured"] is False and entry["rows"] == []

    def test_retired_engines_are_not_live_engines_in_the_counts(self):
        live = engine_catalogue([_row("gas")])
        with_ts = engine_catalogue([_row("gas")], tombstones=[_GONE])
        for key in ("engines_total", "engines_measured", "engines_not_measured", "engines_unlisted"):
            assert with_ts[key] == live[key], key
        assert with_ts["engines_retired"] == 1 and len(with_ts["entries"]) == len(live["entries"]) + 1

    def test_a_retired_engine_keeps_its_backtest_history_and_is_never_also_unlisted(self):
        catalogue = engine_catalogue([_row("gas"), _row("macro_engine", version="m-v1")], tombstones=[_GONE])
        retired = [e for e in catalogue["entries"] if e["engine"] == "macro_engine"]
        assert len(retired) == 1 and retired[0]["status"] == STATUS_RETIRED
        assert retired[0]["measured"] is True and retired[0]["worst_brier_ratio"] == 4.29
        assert catalogue["engines_unlisted"] == 0
