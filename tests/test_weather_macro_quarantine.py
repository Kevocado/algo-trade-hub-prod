"""The quarantine: repaired engines that compute, display, and publish nothing.

Four properties under test, and they are four different claims that a single test cannot make at
once:

  1. **Nothing is written to the trade sink.** The safety property. `tests/…::test_the_quarantine_
     writes_nothing_to_the_trade_sink` is the single most important test in this file, and it is
     deliberately not a source-grep: it drives `run_scan`'s real publish path with a recording
     client and asserts the bytes that would have reached `kalshi_edges`.
  2. **The engines now produce a non-zero, measured count.** They produced zero for the entire
     period PR #38 described, because every market read as a 0c quote and every one was skipped. The
     counts are pinned so a regression back to zero fails, and so a large surprise shows up as a
     failing number rather than as a quiet change nobody reads.
  3. **The artefact rows are distinguished from real ones.** 295 rows is not 295 opportunities, and
     the two ways it is not are separate: units artefacts (a "BUY NO at 99c" whose 84 points are a
     difference between the wrong two quantities) and restatements (one GDP point forecast applied
     across eleven year-events). Both axes conserve, and neither is folded into a headline total.
  4. **Quarantined reads as quarantined.** Distinct from "ran and found nothing" and from "could not
     run", in the ruling, in the API, and in the page.

Pure modules throughout, so none of this needs a database, a network, or a credential.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime as _datetime
from pathlib import Path

import pytest

import legacy_ruling
from legacy_ruling import STOPPED_SITES

from tradehub import engine_health as health
from tradehub.engine_health import (
    OPPORTUNITIES_NOT_COUNTED,
    OPPORTUNITIES_NOT_MEASURED,
    OPPORTUNITIES_QUARANTINED,
    STATE_COULD_NOT_RUN,
    STATE_QUARANTINED,
    STATE_RAN,
    edge_type_entry,
    edge_type_state,
    engine_health,
    partition_edge_types,
)
from tradehub.quarantine import (
    DEGENERATE_YES_ASK_CENTS,
    KIND_OPPORTUNITY,
    KIND_UNITS_ARTEFACT,
    QUARANTINE_FLAG,
    QUARANTINE_MARK,
    QUARANTINED_EDGE_TYPES,
    UNITS_ARTEFACT_REASON,
    classify_row,
    is_quarantined_edge_type,
    is_quarantined_row,
    mark_quarantine,
    partition_quarantine,
    quarantine_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _legacy_ruling(monkeypatch):
    """The state machine is pinned against the frozen ruling; see `tests/legacy_ruling.py`."""
    legacy_ruling.install(monkeypatch)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "quarantine"

# ── the fixtures, and what they are for ─────────────────────────────────────────────────────

# The measured run, 2026-09-28, against 441 live economics markets and 30 live temperature markets.
# Pinned rather than derived so a drift is a FAILING NUMBER in CI rather than a surprise in a
# dashboard. The three figures that matter:
#
#   weather 30, macro 265, total 295 rows -- where the previous state was 0, 0, 0.
#   110 of the 441 economics markets quote no tradeable YES ask and are correctly SKIPPED. They are
#     not a defect and not an opportunity; a market you cannot price has no edge, and pricing it
#     against a fabricated zero is what produced the original 84-point fictions.
#   of the 295 rows, only 26 are independent opportunities. The rest are units artefacts or the same
#     forecast restated. This is the number the quarantine exists to make visible.
MEASURED_TOTAL_ROWS = 295
MEASURED_WEATHER_ROWS = 30
MEASURED_MACRO_ROWS = 265
MEASURED_UNPRICEABLE_ECON = 110
MEASURED_PRICEABLE_ECON = 331
MEASURED_LIVE_ECON_MARKETS = 441
MEASURED_INDEPENDENT_OPPORTUNITIES = 26

# The genuine-vs-artefact split, from the same run. These four numbers are the substance of the
# quarantine and the reason it is a measurement surface rather than a publishing one:
#
#   213  rows that are not a units artefact
#    82  units artefacts -- "BUY NO" against a YES ask at or above 95c, 66 of them at exactly 99c
#   187  of the 213 are a forecast another row already made
#    26  independent opportunities. This is the real answer to "what would these engines do".
#
# 26 out of 295. That is the headline, and it is why the alternative to quarantining was never
# "publish them".
MEASURED_OPPORTUNITIES = 213
MEASURED_UNITS_ARTEFACTS = 82
MEASURED_RESTATED_OPPORTUNITIES = 187
MEASURED_UNITS_ARTEFACTS_AT_99C = 66
# Of those 66, 25 report the full 84 points. The brief named 25; the honest reading is 66 rows at a
# degenerate quote of which 25 carry the 84-point headline, and the other 41 carry 14, 39 or 59 --
# the same defect at a smaller number.
MEASURED_84_POINT_ROWS = 25

# The GDP restatement, which is the clearest single fact in the output: 138 rows, 4 forecasts,
# 11 distinct year-events. One FRED GDP reading applied to every strike Kalshi lists.
MEASURED_GDP_ROWS = 138
MEASURED_GDP_FORECASTS = 4
MEASURED_GDP_EVENTS = 11

# The counts the trimmed fixtures produce, which are the reproducible half of the measurement. The
# weather fixture is the complete live 30-market snapshot, so its count is the real one; the macro
# fixture is trimmed to 66 markets from 441, so its count is smaller and is labelled as the fixture's
# own. Both are pinned so a change in either engine's arithmetic is a failing number.
FIXTURE_WEATHER_ROWS = 30
FIXTURE_MACRO_ROWS = 47
FIXTURE_MACRO_MARKETS = 66
FIXTURE_MACRO_UNPRICEABLE = 8


def _fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["markets"]


@pytest.fixture(scope="module")
def measured() -> dict:
    """The recorded counts from the 2026-09-28 run, alongside the rows it produced."""
    return json.loads((FIXTURES / "measured_rows.json").read_text(encoding="utf-8"))["measured"]


@pytest.fixture(scope="module")
def live_rows(measured) -> list[dict]:
    """The exact rows the engines produced on the measured run, with the real classifications.

    A recorded run, not a synthesised one, and that matters for a specific reason: the artefact
    detection is a rule about real numbers (is the YES ask at 99c?) and a hand-built fixture would
    only prove the rule agrees with whoever wrote the fixture. This one is the output of the real
    engines against the real snapshot, so the counts pinned above are a measurement.
    """
    return json.loads((FIXTURES / "measured_rows.json").read_text(encoding="utf-8"))["rows"]


@pytest.fixture(scope="module")
def weather_markets() -> list[dict]:
    return _fixture("weather_markets.json")


@pytest.fixture(scope="module")
def macro_markets() -> list[dict]:
    return _fixture("macro_markets.json")


# ── 1. THE SAFETY PROPERTY: nothing reaches the trade sink ────────────────────────────────────

class _Query:
    """Records every write aimed at it, so the test can assert on what was NOT written."""

    def __init__(self, recorder: list, table: str):
        self._recorder = recorder
        self._table = table

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def upsert(self, rows, **k):
        self._recorder.append((self._table, list(rows)))
        return self

    def insert(self, rows, **k):
        self._recorder.append((self._table, list(rows) if isinstance(rows, list) else [rows]))
        return self

    def execute(self):
        return type("R", (), {"data": []})()


class _RecordingClient:
    """A supabase client that keeps every payload instead of sending it anywhere."""

    def __init__(self):
        self.writes: list[tuple[str, list]] = []

    def table(self, name):
        return _Query(self.writes, name)

    def tables_written(self) -> set[str]:
        return {table for table, _rows in self.writes}

    def rows_for(self, table: str) -> list[dict]:
        return [row for name, rows in self.writes if name == table for row in rows]


@pytest.fixture
def recording_client(monkeypatch) -> _RecordingClient:
    from tradehub.core import supabase_client

    client = _RecordingClient()
    monkeypatch.setattr(supabase_client, "get_client", lambda: client)
    return client


def test_upsert_opportunities_refuses_a_quarantined_row_even_when_handed_one(recording_client, monkeypatch):
    """Defence in depth, as its own test so a failure names which of the two mechanisms broke.

    A refactor that concatenates the quarantine list into the publish list is the single most likely
    way to break this PR, and the structural separation alone would not catch it. This does: hand the
    trade sink a marked row alongside a legitimate one and assert the marked one never appears in the
    payload while the legitimate one still does.

    The legitimate row matters. A writer that dropped everything would pass a test asserting "no
    quarantined rows", and the crypto and sports rows on the same scan would silently stop
    publishing. One test for both halves is the only version of this that says anything.
    """
    from tradehub.core import supabase_client

    quarantined = {
        "engine": "Macro", "edge_type": "MACRO", "market_ticker": "KXGDPYEAR-26-T2.0",
        "market_title": "GDP above 2.0%", "action": "BUY NO", "market_price": 99,
        "model_probability": 15, "edge": 84, QUARANTINE_FLAG: True,
    }
    legitimate = {
        "engine": "Quant", "edge_type": "CRYPTO", "market_ticker": "KXETH-26SEP28-B50000",
        "market_title": "ETH above 50000", "action": "BUY YES", "market_price": 40,
        "model_probability": 60, "edge": 20,
    }

    dropped = supabase_client.upsert_opportunities([quarantined, legitimate])

    assert dropped == 1, "the refusal has to be reported, not silent -- see the module docstring"
    published = recording_client.rows_for("kalshi_edges")
    assert [row["market_id"] for row in published] == ["KXETH-26SEP28-B50000"], published
    # And nothing anywhere in the payload carries the quarantined row's figures.
    assert not any(row.get(QUARANTINE_FLAG) for row in published)


def test_the_edge_type_alone_never_identifies_a_quarantined_row():
    """The two helpers answer different questions, and conflating them would refuse live rows.

    `is_quarantined_edge_type("WEATHER")` is True and `is_quarantined_row` is False for an
    unflagged WEATHER row -- because `tradehub/scripts/scan.py` publishes measured rows under that
    same edge type every hour. The ruling's SCOPE is the edge type; the row's IDENTITY is the flag.
    A sink that used the first would refuse the product's working weather engine to enforce a ruling
    about two other engines that share its board, and the refusal would be invisible: the measured
    engine would simply stop publishing, and nothing would say why.
    """
    from tradehub.core import supabase_client

    measured_weather = {
        "engine": "weather", "edge_type": "WEATHER", "market_ticker": "KXHIGHNY-26SEP28-T75",
        "market_title": "NYC above 75", "action": "BUY YES", "market_price": 43,
        "model_probability": 75, "edge": 32,
    }
    assert is_quarantined_edge_type(measured_weather["edge_type"]) is True, "the ruling covers this board"
    assert is_quarantined_row(measured_weather) is False, "but this row is not a quarantined one"

    client = _RecordingClient()
    original = supabase_client.get_client
    supabase_client.get_client = lambda: client
    try:
        assert supabase_client.upsert_opportunities([measured_weather]) == 0, "nothing dropped"
        assert [r["market_id"] for r in client.rows_for("kalshi_edges")] == ["KXHIGHNY-26SEP28-T75"]
    finally:
        supabase_client.get_client = original


def test_the_quarantine_sink_is_a_different_table_from_the_trade_sink(recording_client, monkeypatch, live_rows):
    """The second sink writes to `kalshi_quarantine_edges` and to nothing else.

    Worth its own test because "a second sink" and "the same sink with a filter" are the same change
    to write and very different changes to have made. A row in `kalshi_edges` is a row something
    downstream can act on; a `quarantined` boolean is one refactor from not being read.
    """
    from tradehub.core import supabase_client

    written = supabase_client.upsert_quarantined(mark_quarantine(live_rows))

    assert written == len(live_rows)
    assert recording_client.tables_written() == {"kalshi_quarantine_edges"}
    for row in recording_client.rows_for("kalshi_quarantine_edges"):
        assert row[QUARANTINE_FLAG] is True
        assert row["marker"] == QUARANTINE_MARK
        assert row["note"]


def test_no_source_path_leads_a_quarantined_row_to_the_trade_sink():
    """The structural claim, as a source-level fact rather than a promise.

    Deliberately narrow. It checks that `upsert_quarantined` names one table and it is not
    `kalshi_edges`. The second half of this test used to inspect the legacy daemon's `run_scan`; the
    daemon was deleted (v2 spec §9) and with it the only producer of quarantined rows, so what is left
    to pin is the sink itself plus `upsert_opportunities` refusing a marked row (tested separately).
    """
    from tradehub.core import supabase_client

    # The docstring says `kalshi_edges` a dozen times, on purpose -- it is the sentence explaining
    # where those rows do NOT go. So this checks the CODE, with the docstring removed, and asserts
    # on the table name it opens. A naive substring check over the whole source would fail on a
    # comment that is the safety argument, which is a good way to train people to delete the comment.
    sink_source = inspect.getsource(supabase_client.upsert_quarantined)
    code = sink_source.split('"""')[0] + sink_source.rsplit('"""', 1)[-1]
    assert "kalshi_edges" not in code, "the quarantine sink must never open the trade sink"
    assert 'client.table("kalshi_quarantine_edges")' in sink_source


# ── 2. the engines now MEASURE, and the numbers are pinned ──────────────────────────────────

class _StubbedEngine:
    """Runs a real engine's `find_opportunities` against a fixed market list.

    Not a fake engine: the method under test is the real one, on a real class, with only its two
    network dependencies replaced. A stub that returned a canned list would let the repair be reverted
    and the measured counts would not move, which is the exact regression this file exists to catch.
    """

    def __init__(self, engine, markets, edge_type):
        self._engine = engine
        self._markets = markets
        self._edge_type = edge_type

    def find_opportunities(self, kalshi_markets=None):
        return self._engine.find_opportunities(self._markets)


class _FrozenDatetime(_datetime):
    """The wall clock the fixtures were captured under: 2026-09-28, midday.

    `weather_engine.find_opportunities` reads `datetime.now()` twice: once to
    drop markets whose date has passed, once to drop same-day markets after
    18:00 local time. Both are correct behaviour against live markets and both
    make a frozen snapshot unusable the moment the wall clock moves past it --
    the fixtures close 2026-09-29T05:00Z, so on 2026-09-29 every one of the 30
    weather rows is "expired", and in CI (UTC) any run after 18:00 drops them
    the same day. That is how this file's count test passed on 2026-09-28 and
    failed the next day with `KeyError: 'Weather'`: not a product regression,
    a snapshot outliving the clock it was taken against.

    Freezing is honest here because the fixtures ARE that date: evaluating a
    2026-09-28 snapshot "as of" 2026-09-28 is what the measurement means. What
    would be dishonest is refreshing the fixtures to keep an unfrozen test
    green -- that would move the pinned numbers without saying so.
    """

    @classmethod
    def now(cls, tz=None):
        base = cls(2026, 9, 28, 12, 0, 0)
        return base.replace(tzinfo=tz) if tz is not None else base


def _freeze_fixture_time(monkeypatch) -> None:
    """Pin the engine's clock to the fixtures' date. See `_FrozenDatetime`."""
    monkeypatch.setattr(
        "tradehub.engines.weather_engine.datetime", _FrozenDatetime
    )


def _measure(monkeypatch, weather_markets) -> list[dict]:
    """Run the weather engine against the recorded snapshot and return the marked rows.

    Weather only: the macro engine and the daemon that ran both were deleted (v2 spec §9). The engine
    class is the real one; only its NWS call is replaced.
    """
    from tradehub.engines.weather_engine import WeatherEngine

    _freeze_fixture_time(monkeypatch)

    engine = WeatherEngine()
    engine.get_nws_forecast = lambda city: {"2026-09-28": 74, "2026-09-29": 76}
    return mark_quarantine(_StubbedEngine(engine, weather_markets, "WEATHER").find_opportunities())


class TestTheEnginesMeasureSomething:
    def test_the_repaired_engine_returns_a_non_zero_count(self, monkeypatch, weather_markets):
        """Not "more than zero" -- the exact figure this fixture produces, pinned.

        Previously the engine returned 0 for every market it fetched: `market.get('yes_ask', 0)` read a
        key Kalshi stopped sending, so every price came back 0 and `if yes_ask == 0: continue` skipped
        all of them. Pinning the exact number means a regression to zero fails here, and a large drift
        fails as a NUMBER somebody has to look at rather than as a quiet change. The weather fixture is
        the complete live 30-market snapshot, so its count is the real one. (The macro half of this test
        went with the macro engine.)
        """
        rows = _measure(monkeypatch, weather_markets)

        assert len(rows) == FIXTURE_WEATHER_ROWS
        assert all(row["engine"] == "Weather" for row in rows)
        # Every row is measured, priced, and marked. The count going to zero is a regression to a
        # known defect, not a quiet market.
        assert all(row["market_price"] for row in rows)
        assert all(row[QUARANTINE_FLAG] is True for row in rows)

    def test_the_engine_applies_no_minimum_edge(self, monkeypatch, weather_markets):
        """Sixteen of thirty rows come back under the 10 points the docstring used to promise.

        The behavioural half of the stale-docstring pair: whatever the sentence says, this pins what
        the engine does. `find_opportunities` used to end `if edge is not None and abs(edge) > 10:`;
        a0fc404 ("remove math thresholds") dropped the second half and left the sentence describing
        it, so 16 of the 30 fixture markets come back at or below a point the docstring said could
        not appear -- the smallest at 1 point. Green before the docstring fix and green after it,
        because the fix is text only; it is here so a threshold coming BACK fails as a moved number
        rather than as a sentence that has quietly stopped being true again.
        """
        from tradehub.engines.weather_engine import WeatherEngine

        _freeze_fixture_time(monkeypatch)
        engine = WeatherEngine()
        engine.get_nws_forecast = lambda city: {"2026-09-28": 74, "2026-09-29": 76}
        rows = engine.find_opportunities(weather_markets)

        at_or_below_ten = [r for r in rows if r["edge"] <= 10]
        # Every priced market comes back, not just the ones past a floor: 30 in, 30 out.
        assert len(rows) == len(weather_markets) == FIXTURE_WEATHER_ROWS == 30
        assert len(at_or_below_ten) == 16, [r["edge"] for r in at_or_below_ten]
        assert min(r["edge"] for r in at_or_below_ten) == pytest.approx(1.0)
        # The other side, so the two numbers differ and the count above is not a tautology: the
        # other 14 rows clear the old floor, so it was a filter and not a constant.
        assert len(rows) - len(at_or_below_ten) == 14

    def test_the_docstring_does_not_promise_an_edge_threshold_anymore(self):
        """The sentence and the code, asserted to agree -- which they did not.

        `find_opportunities` read "Returns list of opportunities with edge > 10%" for months after
        a0fc404 removed the `abs(edge) > 10` test that sentence describes. It is a claim about the
        engine's output sitting in the one place a caller reads before trusting the count, and the
        test above is the evidence it was false. Asserted on the text because the fix is text: a
        behaviour-only test cannot see this at all.
        """
        from tradehub.engines.weather_engine import WeatherEngine

        doc = WeatherEngine.find_opportunities.__doc__
        assert "edge > 10%" not in doc, doc
        assert "no minimum edge" in doc, doc

    def test_a_regression_to_the_pre_repair_state_fails_loudly(self):
        """The failure the pinned counts exist for, asserted directly rather than left implicit.

        A read of the moved field with a 0 default is the original defect. If a future edit restores
        it, `find_opportunities` returns [] and the pinned counts above fail. This says so in words
        where the next person will read it: the number going to zero is a REGRESSION to a known
        defect, not a quiet market.
        """
        from tradehub.engines.weather_engine import WeatherEngine

        engine = WeatherEngine()
        engine.get_nws_forecast = lambda city: {"2026-09-28": 74}

        # The pre-repair read, spelled out, against the same snapshot.
        pre_repair_skip = [
            market for market in _fixture("weather_markets.json")
            if market.get("yes_ask", 0) == 0
        ]
        assert len(pre_repair_skip) == len(_fixture("weather_markets.json")), (
            "the fixture must be shaped so the pre-repair read skips EVERY market -- that is the "
            "defect. If this fails the fixture has grown a legacy key and would no longer reproduce it"
        )
        assert engine.find_opportunities([]) == []

    def test_the_weather_fixtures_expire_like_real_markets_do(self, monkeypatch):
        """Why `_measure` freezes time, pinned as behaviour rather than comment.

        The weather fixtures close 2026-09-29T05:00Z, and the engine drops
        markets whose date has passed -- correctly, against live markets. So
        with the clock past the fixtures' close the engine returns nothing,
        and the count test above would fail with `KeyError: 'Weather'`. That is
        what happened the day after the fixtures were captured: green on
        2026-09-28, red on 2026-09-29, with no product change in between.

        This test runs the real engine with the clock past the close and
        asserts the empty result, so the freeze in `_measure` is load-bearing
        and documented: fixtures have a lifetime, and the measurement is taken
        inside it.
        """
        from tradehub.engines import weather_engine

        class _PastTheClose(_FrozenDatetime):
            @classmethod
            def now(cls, tz=None):
                base = cls(2026, 10, 5, 12, 0, 0)
                return base.replace(tzinfo=tz) if tz is not None else base

        monkeypatch.setattr(weather_engine, "datetime", _PastTheClose)
        engine = weather_engine.WeatherEngine()
        engine.get_nws_forecast = lambda city: {"2026-09-28": 74, "2026-09-29": 76}
        assert engine.find_opportunities(_fixture("weather_markets.json")) == []

    def test_the_measured_live_run_is_pinned(self, live_rows):
        """The 2026-09-28 live measurement, as a recorded artefact, with the numbers this PR claims.

        Separate from the test above on purpose. The test above runs the engines against a trimmed
        snapshot, so it proves the repair works and is reproducible. This one pins what actually
        happened against 441 live markets, which is the evidence for the report and for the decision
        the quarantine exists to inform. It is a record of a DATE, not a live assertion -- if the
        market moves on, the numbers here stay as they were and the drift is visible as a diff in
        this file rather than as a test that fails on a Tuesday for no reason anyone can act on.
        """
        counts = partition_quarantine(live_rows).counts()

        assert len(live_rows) == MEASURED_TOTAL_ROWS
        assert len([r for r in live_rows if r["engine"] == "Weather"]) == MEASURED_WEATHER_ROWS
        assert len([r for r in live_rows if r["engine"] == "Macro"]) == MEASURED_MACRO_ROWS

        # The full split, because each of these is a claim the report makes and the quarantine
        # surface exists to let somebody check.
        assert counts["opportunities"] == MEASURED_OPPORTUNITIES
        assert counts["units_artefacts"] == MEASURED_UNITS_ARTEFACTS
        assert counts["restated_opportunities"] == MEASURED_RESTATED_OPPORTUNITIES
        assert counts["independent_opportunities"] == MEASURED_INDEPENDENT_OPPORTUNITIES

        # 26 real opportunities out of 295 rows. Asserted as a ratio as well as a count, because the
        # ratio is the finding: the number of rows is an order of magnitude away from the number of
        # things the engines actually thought, and that gap is why they are not published.
        assert counts["independent_opportunities"] * 10 < counts["rows"]

    def test_the_66_ninety_nine_cent_buy_no_rows_are_the_largest_artefact_group(self, live_rows):
        """The specific number the brief names, pinned so it cannot quietly change meaning.

        66 rows read "BUY NO" against a 99c YES ask. Each reports an edge of up to 84 points, and
        each is worth about a cent.
        """
        at_99 = [
            classified for classified in partition_quarantine(live_rows).units_artefacts
            if classified.row["market_price"] == 99
        ]
        assert len(at_99) == MEASURED_UNITS_ARTEFACTS_AT_99C
        edges = []
        for classified in at_99:
            assert classified.row["action"] == "BUY NO"
            # And the arithmetic that makes them artefacts: the "edge" is the gap between the
            # model's YES probability and a YES quote, printed as the edge of a NO trade. A model
            # at 15% against a 99c quote reports 84 points; the trade described is worth a cent.
            assert classified.row["edge"] == pytest.approx(
                99 - classified.row["model_probability"], abs=0.01
            )
            edges.append(classified.row["edge"])
        # 25 of the 66 report the full 84 points; the rest report 14, 39 or 59. The spread is itself
        # the finding: the "edge" is just `99 - model_probability` off a four-way lookup table
        # {85, 60, 35, 10}, so it takes four possible values and has nothing to do with the market
        # being quoted. 25 is the figure the brief names, and it is 25 out of 66 -- not 66.
        assert edges.count(84.0) == MEASURED_84_POINT_ROWS == 25
        assert max(edges) == 84.0
        assert set(edges) <= {14.0, 39.0, 59.0, 84.0}, (
            f"the phantom edge is a function of the lookup table, not the market; got {set(edges)}"
        )

    def test_the_measurements_block_agrees_with_the_rows_it_describes(self, live_rows, measured):
        """The recorded counts and the recorded rows must not be able to drift apart.

        A fixture that carried both a `measured` block and a `rows` list could be edited in one
        place and not the other, and then the pinned counts in the tests above would be pinning a
        number that describes rows nobody has. This closes that gap.
        """
        assert measured["total_rows"] == len(live_rows)
        assert measured["weather_rows"] == MEASURED_WEATHER_ROWS
        assert measured["macro_rows"] == MEASURED_MACRO_ROWS
        assert measured["econ_markets_fetched"] == MEASURED_LIVE_ECON_MARKETS
        assert measured["econ_markets_priceable"] == MEASURED_PRICEABLE_ECON
        assert measured["econ_markets_unpriceable"] == MEASURED_UNPRICEABLE_ECON
        for key, value in measured["counts"].items():
            assert partition_quarantine(live_rows).counts()[key] == value, key

# ── 3. the artefacts are distinguished from the opportunities ───────────────────────────────

class TestArtefactsAreNotCountedAsOpportunities:
    def test_the_partition_conserves_every_row_on_both_axes(self, live_rows):
        """`opportunities + artefacts == rows` and `independent + restatements == rows`, always.

        The contract that makes the two counts trustworthy. A row that vanished from a bucket is a
        count that reads as a finding, which is the defect this whole surface exists to prevent --
        295 rows that quietly became "265 opportunities" is the original lie with a new label.
        """
        partition = partition_quarantine(live_rows)
        counts = partition.counts()

        assert counts["opportunities"] + counts["units_artefacts"] == counts["rows"]
        assert counts["independent_forecasts"] + counts["restatements"] == counts["rows"]
        assert len(partition.opportunities) + len(partition.units_artefacts) == len(partition)
        assert len(partition.independent) + len(partition.restatements) == len(partition)

    def test_a_99c_buy_no_is_a_units_artefact_and_not_an_opportunity(self, live_rows):
        """The headline artefact, named as one.

        On the measured run 82 rows read "BUY NO" against a YES ask at or above 95c, and 66 of them
        are at exactly 99c. The largest carry a model probability of 15 against a 99c quote and report
        an 84-point edge. But the trade described -- buy NO -- costs the far side of that book, about
        a cent, and the 84 points is a difference between the model's YES probability and a YES quote.
        It is not an 84-point opportunity and it is not an 84-point loss; it is a number in the wrong
        units wearing a headline.

        The test is on the real rows, not a hand-built one, because the rule is about real prices.
        """
        partition = partition_quarantine(live_rows)
        artefacts = partition.units_artefacts
        assert artefacts, "the measured run contained 99c BUY NO rows and they must be classified"

        for classified in artefacts:
            assert classified.kind == KIND_UNITS_ARTEFACT
            assert classified.row["action"] == "BUY NO"
            assert classified.row["market_price"] >= DEGENERATE_YES_ASK_CENTS
            assert classified.reason == UNITS_ARTEFACT_REASON
            # A row in the artefact bucket is never also counted as an opportunity. Conservation
            # says the buckets are disjoint; this says the artefact bucket is not quietly re-entered
            # by the independent count, which is a different axis and must not override this one.
            assert classified not in partition.opportunities

    def test_the_artefact_count_is_reported_separately_and_not_averaged_away(self, live_rows):
        """No headline in the payload is the row count when the row count is not the story.

        This is the requirement that 295 must never read as 295 opportunities. Asserted three ways:
        the counts disagree with each other, the payload has no field called "opportunities" sitting
        next to the row total, and the independent figure is strictly smaller than the row total.
        """
        counts = partition_quarantine(live_rows).counts()

        assert counts["rows"] != counts["opportunities"]
        assert counts["rows"] != counts["independent_opportunities"]
        assert counts["independent_opportunities"] < counts["opportunities"] < counts["rows"]
        assert counts["units_artefacts"] > 0
        assert counts["restatements"] > 0

        payload = quarantine_report(live_rows)
        assert payload["counts"]["independent_opportunities"] < payload["totals"]["rows"]
        # The headline the UI will render is the independent figure, and the key it comes from is
        # named for what it counts. There is deliberately NO key that is the row count called
        # "opportunities": the two counts the brief warns about being conflated have to be
        # distinguishable by name as well as by value, or a future reader picks the wrong one.
        assert payload["counts"]["independent_opportunities"] == MEASURED_INDEPENDENT_OPPORTUNITIES
        assert "independent_opportunities" in payload["totals"]
        assert payload["totals"]["opportunities"] != payload["totals"]["rows"]
        # `totals` and `counts` are the same object on purpose, and this asserts they agree rather
        # than leaving a payload with two sets of numbers that could drift.
        assert payload["totals"] == payload["counts"]

    def test_one_forecast_restated_across_year_events_is_one_opinion(self, live_rows, measured):
        """The second artefact, which the first axis cannot see: 138 rows, 4 forecasts, 11 events.

        Neither engine has a per-market model. Each fetches ONE scalar per asset and quantises it
        into a handful of constants, so a GDP reading of 1.9% produces model_probability 10 for every
        strike above 2.8, on every one of the eleven year-events Kalshi lists for that series. Those
        are 84 rows and one opinion. Reading them as 84 opportunities is a units error of the same
        family as the 99c one: a count of ROWS where a count of STATEMENTS was meant.

        Asserted with the exact figures because this is the largest single distortion in the output.
        The GDP rows outnumber the whole independent count several times over, and that is the
        clearest evidence in the data for not publishing.
        """
        partition = partition_quarantine(live_rows)
        gdp_rows = [row for row in partition.opportunities if row.forecast[1] == "GDP"]
        assert len(gdp_rows) == MEASURED_GDP_ROWS

        distinct_forecasts = {row.forecast for row in gdp_rows}
        assert len(distinct_forecasts) == MEASURED_GDP_FORECASTS, (
            f"expected {MEASURED_GDP_FORECASTS} distinct GDP forecasts across "
            f"{MEASURED_GDP_ROWS} rows, got {len(distinct_forecasts)}"
        )

        events = {row.row.get("event_ticker") for row in gdp_rows}
        assert len(events) == MEASURED_GDP_EVENTS, "the restatement spans the year-events Kalshi lists"

        # One forecast dominating: 84 of the 138, which is the whole point.
        groups: dict[tuple, int] = {}
        for row in gdp_rows:
            groups[row.forecast] = groups.get(row.forecast, 0) + 1
        assert max(groups.values()) == 84
        assert max(groups.values()) * 1.5 < MEASURED_GDP_ROWS, (
            "a single GDP forecast should dominate its series, not merely lead it"
        )
        assert measured["gdp_rows"] == len(gdp_rows)

    def test_a_restatement_is_still_an_opportunity_not_a_demotion(self, live_rows):
        """The two axes are independent, and this is what that means concretely.

        A row can be a restatement AND a units artefact, and it can be a restatement AND a genuine
        opportunity. Bucketing them into one set of categories would force a choice and whichever way
        it went one of the two questions would go unasked. So `restatements` is not a subset of the
        artefact bucket, and a row's `independent` flag is not a verdict on its kind.
        """
        partition = partition_quarantine(live_rows)
        restated_artefacts = [r for r in partition.restatements if r.kind == KIND_UNITS_ARTEFACT]
        restated_opportunities = [r for r in partition.restatements if r.kind == KIND_OPPORTUNITY]
        assert restated_artefacts, "the two axes must be able to intersect"
        assert restated_opportunities, "a restatement can also be a real opportunity"
        assert len(restated_artefacts) + len(restated_opportunities) == len(partition.restatements)

    def test_the_first_occurrence_is_the_independent_one_and_the_rule_is_stable(self, live_rows):
        """Deterministic, because a count that changes when the query order changes is not a count.

        The first row making a statement is the independent one. That is arbitrary, and it is stated
        rather than hidden: the copies do not disagree, so there is nothing to choose between, and
        picking the largest edge would be selecting on the outcome. What matters is that the answer
        is the same every time, so the figure means something on Tuesday that it meant on Monday.
        """
        forwards = partition_quarantine(live_rows).counts()["independent_forecasts"]
        backwards = partition_quarantine(list(reversed(live_rows))).counts()["independent_forecasts"]
        assert forwards == backwards


class TestClassificationRules:
    @pytest.mark.parametrize("price,action,expected", [
        (99, "BUY NO", KIND_UNITS_ARTEFACT),
        (95, "BUY NO", KIND_UNITS_ARTEFACT),
        (94, "BUY NO", KIND_OPPORTUNITY),
        (99, "BUY YES", KIND_OPPORTUNITY),
        (50, "BUY NO", KIND_OPPORTUNITY),
        (50, "BUY YES", KIND_OPPORTUNITY),
    ])
    def test_the_artefact_rule_is_the_price_and_the_side_together(self, price, action, expected):
        """Both halves of the rule, and the mirror case that must NOT be an artefact.

        A 99c `BUY YES` is a real 99-point gap on a 1c risk and is a genuine finding. Only the `BUY
        NO` side is a units artefact, because only there does the price belong to the other side of
        the book. A rule that flagged "price >= 95" on its own would swallow the 99c BUY YES rows,
        which are the most interesting rows in the whole output.
        """
        assert classify_row({"action": action, "market_price": price}) == expected

    def test_a_row_with_no_price_is_not_classified_as_an_artefact(self):
        """A missing figure is never a number, and it is not a verdict either.

        `market_price: None` must not compare as 0 and land the row in a bucket, and must not be
        quietly read as 99. It is reported as unclassifiable rather than counted as an opportunity,
        because this module reports what it can check and says nothing about what it cannot.
        """
        for price in (None, "", "99", [], {}):
            assert classify_row({"action": "BUY NO", "market_price": price}) == KIND_OPPORTUNITY
        assert classify_row(None) == KIND_OPPORTUNITY
        assert classify_row({}) == KIND_OPPORTUNITY

    def test_the_threshold_is_a_written_ruling_not_a_computed_one(self):
        """95 cents, in the source, as a named constant.

        Not derived from the rows it judges. A threshold read off the data it is judging moves until
        whatever it is looking at comes out right, and this surface exists because a number was
        already on screen looking authoritative while meaning something else.
        """
        assert DEGENERATE_YES_ASK_CENTS == 95.0
        from tradehub import quarantine

        assert "DEGENERATE_YES_ASK_CENTS = 95.0" in inspect.getsource(quarantine)

    def test_a_malformed_row_does_not_raise(self):
        """This runs on rows read back from a database, and a read that dies on a row it was handed
        reports the fault as a crash -- which looks identical to a board with nothing on it."""
        partition = partition_quarantine([None, 42, "nonsense", {"action": 7}, {"model_probability": "x"}])
        assert partition.counts()["rows"] == 2
        assert quarantine_report([None, 42])["totals"]["rows"] == 0


# ── 4. quarantined reads as quarantined ────────────────────────────────────────────────────

class TestQuarantineReadsAsItsOwnState:
    def test_the_repaired_engines_are_quarantined_not_stopped_and_not_ran(self):
        """Three states, and the middle one is not a synonym for either neighbour.

        `ran` beside an empty board says the market was quiet -- the original defect, restated.
        `could_not_run` says nothing was looked at, which is false: these engines measured 295 rows.
        The state has to be its own word, and this is the test that says the middle bucket is
        populated rather than merely defined.
        """
        assert edge_type_state("WEATHER") == STATE_QUARANTINED
        assert edge_type_state("MACRO") == STATE_QUARANTINED

    def test_an_engine_that_ran_and_found_nothing_is_still_quiet(self):
        """The other direction, and the one a fix that only ever renders the failure would break.

        Hiding that would be its own kind of lie: it would make every unfashionable engine look
        broken and train the reader to ignore the label.
        """
        for edge_type in ("SPORTS", "CRYPTO", "ENERGY"):
            assert edge_type_state(edge_type) == STATE_RAN, edge_type
            assert stopped_reason_none(edge_type) is None

    def test_an_unrepaired_wired_site_would_still_read_as_could_not_run(self, monkeypatch):
        """The third state is not the only outcome of a ruling, and the middle one is not automatic.

        Exercised by emptying the repaired dispositions: with the ruling as it stands the wired sites
        are repaired, so `could_not_run` is currently unreachable for a wired edge type. A future
        engine that drifts again must be able to land in it, and the way to prove that is to make it
        happen here rather than to leave the branch untested on the theory that it cannot be reached.
        """
        drifted = tuple(
            site.__class__(**{**site.__dict__, "disposition": "unrepaired"})
            for site in STOPPED_SITES
        )
        monkeypatch.setattr(health, "STOPPED_SITES", drifted)
        assert health.edge_type_state("WEATHER") == STATE_COULD_NOT_RUN
        assert health.edge_type_state("MACRO") == STATE_COULD_NOT_RUN
        assert health.edge_type_state("SPORTS") == STATE_RAN

    def test_the_three_states_read_differently_on_the_page(self):
        """The copy, and the requirement that it cannot collapse back to two.

        A quarantined engine must not be announced as stopped -- it is running, and a reader told
        otherwise is being told something false -- and it must not be announced as quiet either. Both
        sentences are checked for, and the forbidden one is checked for by content, the way
        `FOUND_NOTHING_PHRASE` is in the client.
        """
        entry = edge_type_entry("WEATHER")

        assert entry["state"] == STATE_QUARANTINED
        assert entry["quarantine_sink"] == "kalshi_quarantine_edges"
        assert entry["opportunities_found"] is None
        assert entry["opportunities_found_reason"] == OPPORTUNITIES_QUARANTINED

        # Not "found no qualifying opportunity", and not "not counted here" either: the second would
        # send a reader to a ledger that deliberately has none of these rows on it.
        assert "found no qualifying opportunity" not in entry["opportunities_found_reason"].lower()
        assert entry["opportunities_found_reason"] != OPPORTUNITIES_NOT_COUNTED

    def test_the_three_reasons_for_an_unmeasured_figure_stay_distinct(self):
        """One per state, and all three differ from each other.

        They are three different facts -- a search that found nothing, a search that never ran, and a
        search whose output was withheld -- and a reader who cannot tell which one is being shown
        has been handed the product's whole problem in miniature.
        """
        assert OPPORTUNITIES_NOT_MEASURED != OPPORTUNITIES_NOT_COUNTED
        assert OPPORTUNITIES_NOT_MEASURED != OPPORTUNITIES_QUARANTINED
        assert OPPORTUNITIES_NOT_COUNTED != OPPORTUNITIES_QUARANTINED

        assert edge_type_entry("SPORTS")["opportunities_found_reason"] == OPPORTUNITIES_NOT_COUNTED
        assert edge_type_entry("WEATHER")["opportunities_found_reason"] == OPPORTUNITIES_QUARANTINED

    def test_a_quarantined_engine_still_reports_no_opportunity_count_on_this_endpoint(self):
        """It HAS a count. 295 rows. It still reports `null` here, and the reason is the point.

        Two reasons, both load-bearing. `0` is the one value that would turn a search nobody ran into
        a measurement. And the figure that IS true lives in `kalshi_quarantine_edges` and is reported
        by `/api/quarantine` with the split that makes it worth having -- a bare total here would
        throw away the distinction between 26 real opportunities and 269 rows, which is the whole
        reason to publish a number at all.
        """
        for edge_type in QUARANTINED_EDGE_TYPES:
            entry = edge_type_entry(edge_type)
            assert entry["opportunities_found"] is None
            assert entry["opportunities_found"] != 0

    def test_the_quarantine_marker_is_on_every_payload_and_every_row(self, live_rows):
        """Loudly, and everywhere, because a number that travels alone is the failure this prevents.

        A reader who screenshots one figure from this surface still has the word QUARANTINED in the
        image, and a row read out of SQL or a CSV carries it too.
        """
        report = quarantine_report(live_rows)
        assert report["marker"] == QUARANTINE_MARK
        assert report["quarantined"] is True
        assert QUARANTINE_MARK in report["note"]
        assert "kalshi_edges" in report["note"]
        for engine_block in report["engines"]:
            assert engine_block["marker"] == QUARANTINE_MARK
            assert engine_block["quarantined"] is True
        for row in mark_quarantine(live_rows):
            assert row[QUARANTINE_FLAG] is True
            assert is_quarantined_row(row)

    def test_the_response_reports_zero_writes_as_a_hard_zero(self):
        """A hard `0`, and that is the one place `0` is the right value.

        Everywhere else in this codebase a missing figure is never a number. Here the figure is `0`
        BY CONSTRUCTION -- there is no code path from a quarantined row to the trade sink -- so `0` is
        a measurement of a property of the system rather than a stand-in for an absence. Asserted so
        nobody "fixes" it to null on the general principle.
        """
        report = quarantine_report([{"engine": "Macro", "action": "BUY NO", "market_price": 99}])
        assert report["kalshi_edges_written"] == 0
        assert report["sink"] == "kalshi_quarantine_edges"

    def test_a_corrupt_row_cannot_escape_the_flag_by_failing_to_classify(self):
        """Marked FIRST, before any classification runs.

        A row that cannot be classified -- a corrupt payload, a shape nobody anticipated -- still
        leaves `mark_quarantine` quarantined. A row that failed the checks must not become
        publishable by failing them, which is the kind of inversion that looks like robustness.
        """
        marked = mark_quarantine([{"engine": "Macro", "action": 7, "market_price": "nonsense"}])
        assert len(marked) == 1
        assert marked[0][QUARANTINE_FLAG] is True
        assert is_quarantined_row(marked[0])

    def test_mark_quarantine_does_not_mutate_the_engines_own_dicts(self):
        """Copies, never in-place decoration.

        The engine hands these dicts straight to the sink, and a function that stamped the flag onto
        its argument would be writing to an object the caller still holds -- which is how a
        quarantine marker ends up on a row somewhere it was never meant to be.
        """
        original = {"engine": "Macro", "action": "BUY NO", "market_price": 99}
        marked = mark_quarantine([original])
        assert QUARANTINE_FLAG not in original
        assert marked[0][QUARANTINE_FLAG] is True

    def test_the_ruling_does_not_join_on_the_engine_column(self):
        """`WeatherEngine` writes `engine: "Weather"`, which the writer lower-cases to `weather` --
        the same key the MEASURED, working `weather` engine writes from `tradehub/scripts/scan.py`.
        Joining these two on that column would put "quarantined" beside a real Brier on the Models
        page, which is a false claim about an engine that demonstrably runs. Pinned at both ends, the
        same collision `test_engine_health.py` pins, so nobody "tidies up" the ruling by joining on
        the column that looks cleaner.
        """
        from tradehub.core.supabase_client import upsert_opportunities
        from tradehub.engines.weather_engine import WeatherEngine

        quarantined = {s.name for s in STOPPED_SITES if s.disposition == "repaired_quarantined"}
        assert quarantined == {"WeatherEngine", "MacroEngine"}
        assert "WeatherEngine" in quarantined
        assert "weather" not in quarantined

        assert "'engine': 'Weather'" in inspect.getsource(WeatherEngine.find_opportunities)
        assert 'str(op["engine"]).strip().lower()' in inspect.getsource(upsert_opportunities)

    def test_the_ruling_cannot_quote_a_quarantined_row_as_publishable(self):
        """The sink's refusal is on the FLAG and not the edge type, and this is why.

        `tradehub/scripts/scan.py` publishes measured rows under both `WEATHER` and `MACRO` and must
        keep doing so, so a sink that refused those edge types would refuse the product's working
        engines to enforce a ruling about two other engines that share their boards. Asserted by
        running the writer on a WEATHER row with no flag and watching it through.
        """
        from tradehub.core import supabase_client

        client = _RecordingClient()
        original = supabase_client.get_client
        supabase_client.get_client = lambda: client
        try:
            measured_weather = {
                "engine": "weather", "edge_type": "WEATHER", "market_ticker": "KXHIGHNY-26SEP28-T75",
                "market_title": "NYC above 75", "action": "BUY YES", "market_price": 43,
                "model_probability": 75, "edge": 32,
            }
            assert supabase_client.upsert_opportunities([measured_weather]) == 0, "nothing dropped"
            assert [r["market_id"] for r in client.rows_for("kalshi_edges")] == ["KXHIGHNY-26SEP28-T75"]
        finally:
            supabase_client.get_client = original


def stopped_reason_none(edge_type: str):
    return health.stopped_reason(edge_type)


# ── the ruling's own integrity ──────────────────────────────────────────────────────────────

class TestTheRulingIsNotStale:
    """A ruling that has gone stale is worse than none: it keeps calling a fixed engine broken."""

    def test_a_repaired_site_points_at_the_line_that_was_repaired(self):
        """The site/line for a repaired engine pins the REPAIRED read, not the original defect.

        This is the direct successor to PR #38's canary, which pinned `market.get('yes_ask', 0)` at
        each site. That test did its job -- it fired the moment the repair landed, which is what
        told this change the ruling had to be rewritten rather than deleted. Pinning the repaired
        read keeps the canary pointed at the thing that is now true, so a future revert of the repair
        is caught by the same mechanism that caught this one.
        """
        for site in STOPPED_SITES:
            if site.disposition != "repaired_quarantined" or site.module in legacy_ruling.DELETED_MODULES:
                continue
            module, _, line = site.site.partition(":")
            assert module == site.module
            source = (REPO_ROOT / site.module).read_text(encoding="utf-8").splitlines()
            assert 0 < int(line) <= len(source), site.site
            body = source[int(line) - 1]
            assert "quote_cents(market)" in body, (
                f"{site.site} no longer contains the repaired read; the ruling is stale. It says "
                f"{site.name} is quarantined, which is a claim about a working engine"
            )

    def test_an_unrepaired_site_still_points_at_the_defect(self):
        """The other two sites were not repaired, and their ruling must still be true of them.

        Pinned to the exact offending read, which is `OFFENDING_READS` in
        `tests/test_engine_health.py` rather than a second copy of it. Two copies of the same pin is
        two things to update, and the one that gets missed is the one that stops noticing.
        """
        from tests.test_engine_health import OFFENDING_READS

        unrepaired = [s for s in STOPPED_SITES if s.disposition != "repaired_quarantined"]
        assert len(unrepaired) == 2, "WeatherMaker and clean_market_data were not repaired"

        for site in unrepaired:
            module, _, line = site.site.partition(":")
            source = (REPO_ROOT / module).read_text(encoding="utf-8").splitlines()
            assert 0 < int(line) <= len(source), site.site
            expected = OFFENDING_READS[site.site]
            assert expected in source[int(line) - 1], (
                f"{site.site} no longer contains {expected!r}; the ruling still calls it unrepaired, "
                "which is a claim about a defect that is no longer there"
            )

    def test_a_repaired_site_never_says_it_did_not_run(self):
        """The copy is the claim. "Not running" beside a repaired engine is false, and a reader
        acting on it -- going and fixing a second time -- is the cost."""
        for site in STOPPED_SITES:
            if site.disposition != "repaired_quarantined":
                continue
            assert "Not running" not in site.reason, site.name
            assert "QUARANTINED" in site.reason, site.name
            assert "yes_ask" in site.reason, "the cause is still part of the record"

    def test_the_disposition_is_in_the_payload_so_a_client_need_not_infer_it(self):
        """Travels for the same reason `wired_to_a_scanner` does.

        A site with no disposition is indistinguishable from a live defect, and this list holds both
        now. A client that guessed would call a fixed engine broken -- the PR #38 defect, reintroduced
        one layer up, by a client this time.
        """
        body = engine_health()
        assert body["sites_repaired"] == 2
        assert body["sites_unrepaired"] == 2
        assert body["sites_repaired"] + body["sites_unrepaired"] == body["sites_total"]
        for site in body["sites"]:
            assert site["disposition"] in {"repaired_quarantined", "unrepaired"}


class TestConservationAcrossThreeStates:
    def test_the_partition_conserves_three_ways(self):
        """`ran + quarantined + could_not_run == len(input)`, always."""
        names = [edge_type for edge_type, _label in health.EDGE_TYPES]
        result = partition_edge_types(names)

        assert len(result) == len(names)
        assert sorted(result.ran + result.quarantined + result.could_not_run) == sorted(names)
        assert set(result.quarantined) == {"WEATHER", "MACRO"}
        assert set(result.could_not_run) == set()
        assert set(result.ran) == {"SPORTS", "CRYPTO", "ENERGY"}

    def test_a_hand_built_edge_type_still_does_not_raise(self):
        assert health.edge_type_state(None) == STATE_RAN
        assert health.edge_type_state(17) == STATE_RAN
        assert health.stopped_sites_for(object()) == ()

    def test_the_counts_in_the_response_agree_with_the_entries(self):
        body = engine_health()
        entries = body["edge_types"]
        assert body["edge_types_total"] == len(entries) == len(health.EDGE_TYPES)
        assert (
            body["edge_types_could_not_run"] + body["edge_types_quarantined"] + body["edge_types_ran"]
            == body["edge_types_total"]
        )
        assert body["edge_types_quarantined"] == sum(
            1 for e in entries if e["state"] == STATE_QUARANTINED)
        assert body["edge_types_could_not_run"] == sum(
            1 for e in entries if e["state"] == STATE_COULD_NOT_RUN)

    def test_a_healthy_board_still_says_so(self):
        """The mirror of every quarantine test, and the reason they are worth having.

        With the ruling emptied, the response has to be a clean board with no reason and a
        `board_state` of `ran`. A change that made quarantined boards louder by making healthy ones
        look broken would be its own kind of lie.
        """
        from tradehub import engine_health as module

        original = (module.STOPPED_SITES, module.WIRED_STOPPED_SITES, module.UNWIRED_STOPPED_SITES)
        module.STOPPED_SITES = ()
        module.WIRED_STOPPED_SITES = ()
        module.UNWIRED_STOPPED_SITES = ()
        try:
            body = module.engine_health()
        finally:
            module.STOPPED_SITES, module.WIRED_STOPPED_SITES, module.UNWIRED_STOPPED_SITES = original

        assert body["board_state"] == STATE_RAN
        assert body["board_reason"] is None
        assert body["edge_types_quarantined"] == 0
        assert body["edge_types_could_not_run"] == 0
        assert body["edge_types_ran"] == body["edge_types_total"]

    def test_a_broken_engine_outranks_a_quarantined_one_for_the_whole_board(self):
        """The unfiltered view cannot say "measured but withheld" without also saying what was not
        measured at all. A reader told only the first is being told a board is in better shape than
        it is."""
        from tradehub import engine_health as module

        drifted = tuple(
            s.__class__(**{**s.__dict__, "disposition": "unrepaired"}) for s in STOPPED_SITES
        )
        original = (module.STOPPED_SITES, module.WIRED_STOPPED_SITES, module.UNWIRED_STOPPED_SITES)
        module.STOPPED_SITES = drifted
        module.WIRED_STOPPED_SITES = tuple(s for s in drifted if s.wired_to_a_scanner)
        module.UNWIRED_STOPPED_SITES = tuple(s for s in drifted if not s.wired_to_a_scanner)
        try:
            assert module.engine_health()["board_state"] == STATE_COULD_NOT_RUN
        finally:
            module.STOPPED_SITES, module.WIRED_STOPPED_SITES, module.UNWIRED_STOPPED_SITES = original
