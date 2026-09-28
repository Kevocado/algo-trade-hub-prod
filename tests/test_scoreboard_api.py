"""`GET /api/scoreboard` — the endpoint's contract, and the two ways it can be green and wrong.

The route decides nothing: it reads `backtest_runs` through the paged reader and hands the rows to
`current_runs` / `market_comparison` in `tradehub/scoreboard.py`. So these tests are not about the
arithmetic — Task 1's file owns that. They are about the two ways an endpoint like this is green,
all the assertions pass, and the page is nonetheless lying:

1. **It returns a superset of what it read.** A `gas-v1-lead12h` experiment is present because
   nobody thought to filter, and the page presents the 12h run as the gas record. The whole
   premise of the page is that experiments are ABSENT, so a leak is the exact lie this work
   exists to prevent. `TestTheExperimentIsAbsent` asserts absence — the version string and the
   experiment's own numbers appear nowhere in the response body — not merely that the production
   run is present, because "the production row is there" and "the experiment is not" are different
   claims and only the second one is the invariant.

2. **A read failure renders as "this engine has nothing."** A swallowed exception, a `[]` on
   error, or a partial read that stops paging quietly all produce a board that looks complete and
   is not, and the page's job is to say whether to trust an engine. `TestReadFailureIsNotEmpty`
   covers all three shapes of that failure.

Presence tests are the floor here, not the ceiling; the plan's version of this file was presence
tests only, and a superset leak passes every one of them.

The fake below enforces PostgREST's 1000-row cap exactly, and raises on any `.range()` that was
not preceded by an `.order()`, so a regression to a single capped `.execute()` fails here rather
than in production. It is modelled on `tests/test_sports_api_range_paging.py`, which is the
established shape for this in this repo.
"""
import ast
import inspect
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tradehub.api.dependencies import get_supabase
from tradehub.api.main import POSTGREST_CAP, app
from tradehub.scoreboard import (
    HEADLINE_AHEAD,
    HEADLINE_BEHIND,
    HEADLINE_NOT_COMPARABLE,
    HEADLINE_NO_RUNS,
    SOURCE_ENGINE,
    SOURCE_GATE,
)
from tradehub.sports.scorecard import MIN_SETTLED

MAIN_PY = Path(__file__).resolve().parents[1] / "tradehub" / "api" / "main.py"
# The real strings `check_promotion_gate` emits, and the gas figures from the 12h experiment that
# must never reach a reader. Asserted absent by string, not by row count, so a leak cannot hide
# behind an engine that also has a production run.
NEEDS_200_DAILY = "only 42 settled contracts, need 200 (daily)"
NEEDS_50_MONTHLY = "only 70 settled contracts, need 50 (monthly)"
EXPERIMENT_VERSION = "gas-v1-lead12h"
EXPERIMENT_BRIER_OURS = 0.11216
EXPERIMENT_BRIER_MARKET = 0.0519


# ── the fake ──────────────────────────────────────────────────────────────────
class _Q:
    def __init__(self, table, store):
        self.table, self.store = table, store
        self.rows = list(store.tables[table])
        self.ops: list[str] = []
        self.ordered: list = []
        self.window: tuple[int, int] | None = None

    def select(self, *_a):
        self.ops.append("select")
        return self

    def eq(self, col, val):
        # The VALUE is recorded, not just the column: the gate lookup's whole job is which
        # (engine, engine_version) pair it asked about, and a fake that recorded only `eq` names
        # would make "the version is in the key" untestable.
        self.ops.append(f"eq:{col}={val!r}")
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def order(self, col, *rest, **kwargs):
        self.ops.append("order")
        desc = kwargs.get("desc", bool(rest) and rest[0] == "desc")
        self.ordered.append((col, "desc" if desc else "asc") if desc else col)
        # Sorted, not merely recorded. `latest_gate_statuses` asks for the LATEST backtest for a
        # pair with `.order("created_at", desc=True).limit(1)`, and a fake that recorded the clause
        # without applying it would make every "the latest run says SHADOW" assertion vacuous -- it
        # would be reading whichever row the fixture happened to put first.
        self.rows = sorted(self.rows, key=lambda r: r.get(col), reverse=bool(desc))
        return self

    def limit(self, n):
        self.ops.append(f"limit:{n}")
        self.rows = self.rows[:n]
        return self

    def range(self, lo, hi):
        self.ops.append(f"range:{lo},{hi}")
        self.window = (lo, hi)
        return self

    def execute(self):
        self.store.calls += 1
        self.store.queries.append(
            {"table": self.table, "ops": list(self.ops), "ordered": list(self.ordered)}
        )
        if self.store.fail_on_call == self.store.calls:
            raise self.store.error
        # PostgREST without ORDER BY returns rows in plan order, which is not stable between two
        # requests, so paging over an unordered read can repeat a row and lose another. A
        # `.range()` with no `.order()` is therefore a bug here, not a style preference.
        if self.window is not None and not self.ordered:
            raise AssertionError(
                f"{self.table} was paged with .range() and no .order(): {self.ops}"
            )
        if self.window is not None:
            lo, hi = self.window
            data = self.rows[lo:hi + 1]      # PostgREST `Range: lo-hi` is INCLUSIVE of hi
        else:
            data = self.rows
        if len(data) > POSTGREST_CAP:        # and capped at 1000 rows per response
            data = data[:POSTGREST_CAP]
        return type("R", (), {"data": data})()


class _Supa:
    """A Supabase stand-in that records how it was read and can be made to fail.

    `fail_on_call` is 1-based over `execute()` calls, which is what makes "the SECOND page fails"
    expressible — the case where a partial read could otherwise be returned as a whole board.
    """

    def __init__(self, tables, *, fail_on_call=None, error=None):
        self.tables = tables
        self.fail_on_call = fail_on_call
        self.error = error or RuntimeError("connection reset by peer")
        self.queries: list[dict] = []
        self.calls = 0

    def table(self, name):
        if name not in self.tables:
            # What PostgREST actually says, so `_missing_table_message` is exercised for real.
            raise RuntimeError(
                f"Could not find the table 'public.{name}' in the schema cache"
            )
        return _Q(name, self)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _run(engine, version, **over):
    """One `backtest_runs` row in the shape the WRITER produces.

    Keys and types come from `tradehub/backtest/store.py::build_backtest_run_row` and the columns
    in `20260416000004_backtest_runs.sql`, not from the plan's fixture: `brier_ours`/`brier_market`
    are `numeric` and arrive as floats, `created_at` is a `timestamptz` and arrives as an ISO
    string in the response's own offset, and `gate_reasons` is `jsonb` and arrives as a list.
    """
    row = {
        "id": over.pop("id", f"id-{engine}-{version}-{over.get('mode', 'taker')}-{over.get('created_at', '')}"),
        "engine": engine,
        "engine_version": version,
        "mode": "taker",
        "date_from": "2026-06-01T00:00:00+00:00",
        "date_to": "2026-09-20T00:00:00+00:00",
        "n_decisions": 1982,
        "n_fills": 274,
        "n_settled": 42,
        "pnl_after_fees": -3.84,
        "max_drawdown": 7.06,
        "turnover": 19.5,
        "brier_ours": 0.1148,
        "brier_market": 0.02676,
        "cal_buckets": [],
        "max_cal_dev": 0.04,
        "gate_status": "SHADOW",
        "gate_reasons": [NEEDS_200_DAILY],
        "created_at": "2026-09-20T00:00:00+00:00",
    }
    row.update(over)
    return row


def _get(supa):
    app.dependency_overrides[get_supabase] = lambda: supa
    return TestClient(app).get("/api/scoreboard")


def _get_body(rows, **kw):
    response = _get(_Supa({"backtest_runs": rows}, **kw))
    assert response.status_code == 200, response.text
    return response.json()


def _get_board(backtest_runs, track_record=()):
    """A board plus the `track_record` rows the promotion gate's second half reads.

    `track_record` is the table the full promotion decision consults and `backtest_runs.gate_status`
    never does -- which is the whole subject of `TestThePromotionVerdict` below.
    """
    return _get(_Supa({"backtest_runs": list(backtest_runs),
                       "track_record": [dict(t) for t in track_record]})).json()


def _promoted(engine, version):
    """A `track_record` row that agrees the promotion holds, for exactly this version."""
    return {"engine": engine, "engine_version": version, "gate_status": "PROMOTED",
            "cadence": "daily", "as_of": "2026-09-27T00:00:00+00:00"}


def _row_for(body, engine, mode="taker"):
    return next(r for r in body["rows"] if r["engine"] == engine and r["mode"] == mode)


# ── what it reads, and how ────────────────────────────────────────────────────
class TestTheRead:
    def test_it_reads_backtest_runs_and_nothing_else_unless_the_gate_lookup_needs_more(self):
        """REPLACES `test_it_reads_backtest_runs_and_nothing_else`, deliberately.

        That test pinned `{tables read} == {"backtest_runs"}`, and its own comment said the pin
        existed "so the second lookup cannot arrive quietly". The controller's ruling on 2026-09-27
        is that the lookup MUST arrive: `backtest_runs.gate_status` is the BACKTEST gate, and
        reporting it under the word PROMOTED reads as a promotion to a human. So the pin is
        repurposed rather than deleted -- it still pins the same property, which is that the
        endpoint has no lookup of its own. The extra reads are `track_record`, and they arrive
        only through the shared function in `tradehub/gate_status.py`.

        The falsifiable form of that is: the tables the endpoint reads are the run table plus the
        tables `latest_gate_statuses` reads, and the route's own code contains no promotion
        verdict to read off a run row.
        """
        supa = _Supa({"backtest_runs": [_run("gas", "gas-v1")]})

        _get(supa)

        assert {q["table"] for q in supa.queries} == {"backtest_runs"}

    def test_a_promotion_verdict_is_never_decided_in_the_route(self):
        """The route has no copy of the gate to keep in step with the scan's.

        Parsed rather than grepped, so the docstring is allowed to NAME the rule while the code is
        held to it: a `PROMOTED` literal anywhere in the route's executable text is a second gate
        lookup, and a second gate lookup is how the War Room and the scan would start disagreeing
        about whether an edge is tradable.
        """
        from tradehub.api import main

        tree = ast.parse(inspect.getsource(main.get_scoreboard))
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and body
                    and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)):
                body[0].value.value = ""  # the docstring: prose about the rule, not the rule
        executable = ast.unparse(tree)

        assert "PROMOTED" not in executable, (
            "the route decides a promotion verdict itself; it must carry "
            "latest_gate_statuses' answer instead"
        )
        assert "latest_gate_statuses" in executable, (
            "the route no longer asks the shared lookup at all"
        )

    def test_every_page_is_ordered_by_the_primary_key(self):
        """`id` is the only column that is unique and immutable, so it is the only safe ordering.

        The plan's endpoint added `.order("created_at", desc=True)` inside the query builder. That
        does not replace `_fetch_all`'s own `.order("id")` — postgrest-py joins order clauses with
        commas, so the request becomes `order=created_at.desc,id.asc`: the paged read is led by a
        NON-UNIQUE column, which is the exact instability `_fetch_all`'s docstring exists to
        prevent, and it makes the endpoint's paging correct only by accident of a clause it should
        not be adding. Recency is the reducer's job (`current_runs` parses `created_at` as an
        instant); the read's job is to line the pages up.
        """
        supa = _Supa({"backtest_runs": [_run("gas", "gas-v1")]})

        _get(supa)

        # Scoped to the PAGED read. The shared gate lookup issues its own `.order("created_at",
        # desc=True)`, and that is a single-row `limit(1)` query with no page boundary to be
        # unstable across -- it wants the newest, which is a different question from lining pages up.
        paged = [q for q in supa.queries if any(op.startswith("range:") for op in q["ops"])]
        assert paged, "the board read no longer pages at all"
        ordered = {tuple(q["ordered"]) for q in paged}
        assert ordered == {("id",)}, ordered

    def test_the_read_pages_past_the_postgrest_cap_instead_of_truncating(self):
        """2,500 rows against a 1,000-row cap: two full pages, then a short third.

        A single `.execute()` returns 1,000 of 2,500 and the page reports a board smaller than the
        ledger with no way to tell. `created_at` deliberately repeats across rows, so this also
        says recency ties do not need the read to break them for us.
        """
        rows = [
            _run("gas", "gas-v1", id=f"g{i}", created_at=f"2026-01-01T00:00:0{i % 10}+00:00")
            for i in range(2_500)
        ]
        supa = _Supa({"backtest_runs": rows})

        body = _get(supa).json()

        assert body["runs_read"] == 2_500
        windows = [op for q in supa.queries for op in q["ops"] if op.startswith("range:")]
        assert windows == ["range:0,999", "range:1000,1999", "range:2000,2999"], windows

    def test_a_row_the_cap_would_have_dropped_still_reaches_the_page(self):
        """Why there is no `cap` on the read.

        The plan capped the read at 200 rows. `backtest_runs` grows by one row per recorded CLI
        run, so the newest 200 are overwhelmingly gas. A monthly-cadence engine whose only recent
        run falls outside that window is not rendered slightly stale — it is ABSENT, and an absent
        engine reads as "this engine has no settled contracts", which is a claim about the engine.
        So the engine below exists only in the last row of a 2,500-row table, and it must appear.
        """
        rows = [_run("gas", "gas-v1", id=f"g{i}") for i in range(2_499)]
        rows.append(_run("labor_nowcast", "labor-v1", id="z-last", n_settled=70,
                         gate_reasons=[NEEDS_50_MONTHLY]))

        body = _get_body(rows)

        assert {row["engine"] for row in body["rows"]} == {"gas", "labor_nowcast"}
        tail = next(row for row in body["rows"] if row["engine"] == "labor_nowcast")
        assert tail["n_settled"] == 70


# ── the response contract ─────────────────────────────────────────────────────
class TestTheRow:
    def test_each_engine_carries_its_brier_beside_the_market_and_the_distance(self):
        body = _get_body([_run("gas", "gas-v1")])

        row = body["rows"][0]
        assert row["engine"] == "gas"
        assert row["brier_ours"] == pytest.approx(0.1148)
        assert row["brier_market"] == pytest.approx(0.02676)
        assert row["brier_ratio"] == pytest.approx(4.29, abs=0.01)
        # The two bars travel separately and say which one the verdict was made against. The
        # plan's Task 2 test asserted the pre-ruling five-field shape, which no longer exists.
        distance = row["settled_distance"]
        assert distance["required"] == 200 and distance["required_source"] == SOURCE_GATE
        assert distance["remaining"] == 158 and distance["met"] is False
        assert distance["pct"] == pytest.approx(21.0)
        assert distance["floor"] == MIN_SETTLED and distance["floor_met"] is False
        assert distance["floor_remaining"] == 58

    def test_a_losing_engine_is_present_with_its_numbers_intact(self):
        """The page exists to show losses. Omitting one, or softening it, defeats it."""
        rows = [
            _run("gas", "gas-v1", brier_ours=0.1148, brier_market=0.02676, pnl_after_fees=-3.84),
            _run("weather", "weather-v1", brier_ours=0.13, brier_market=0.1017, pnl_after_fees=-11.2),
            _run("labor_nowcast", "labor-v1", brier_ours=0.1792, brier_market=0.1659,
                 pnl_after_fees=-2.05),
        ]

        body = _get_body(rows)

        assert {row["engine"] for row in body["rows"]} == {"gas", "weather", "labor_nowcast"}
        for row in body["rows"]:
            assert row["brier_ratio"] > 1.0, row
            assert row["pnl_after_fees"] < 0, row
        assert body["headline"] == HEADLINE_BEHIND
        assert body["rows_behind_market"] == 3

    def test_an_engine_with_no_settled_contracts_says_so_honestly(self):
        """Not omitted, and not rendered as "0 of 0" — which reads as having met the gate.

        `n_settled = 0` with the gate naming 200 is a real state (nothing has resolved yet), and
        the row has to carry it as a distance rather than as silence or a pass.
        """
        body = _get_body([
            _run("labor_nowcast", "labor-v1", n_settled=0,
                 gate_reasons=["only 0 settled contracts, need 50 (monthly)"])
        ])

        row = body["rows"][0]
        distance = row["settled_distance"]
        assert distance["n_settled"] == 0
        assert distance["required"] == 50, "0 of 0 reads as having met the gate"
        assert distance["remaining"] == 50 and distance["met"] is False
        assert distance["pct"] == 0.0

    def test_an_engine_that_cleared_its_own_gate_is_not_reported_as_failing_a_number(self):
        """A monthly engine at 70 settled has met its own 50 bar.

        The gate names a bar only when the engine is short of it, so the engine's own bar is
        unstateable from a `backtest_runs` row and `required` is `None` with
        `required_source: "engine"`. The reviewer's `MIN_SETTLED` is reported beside it as a
        floor, and it is not the bar `met` is judged against.
        """
        body = _get_body([
            _run("cpi_nowcast", "cpi-v1", n_settled=70, brier_ours=0.2, brier_market=0.1,
                 gate_reasons=["model Brier 0.2 is not below market Brier 0.1",
                               "simulated P&L after fees/spread is not positive"])
        ])

        distance = body["rows"][0]["settled_distance"]
        assert distance["required"] is None
        assert distance["required_source"] == SOURCE_ENGINE
        assert distance["met"] is True, "70 settled has cleared the monthly engine's own 50 bar"
        assert distance["floor"] == MIN_SETTLED
        assert distance["floor_remaining"] == 30 and distance["floor_met"] is False


# ── the experiment must be ABSENT, not merely outnumbered ─────────────────────
class TestTheExperimentIsAbsent:
    def _both_gas_runs(self):
        return [
            _run("gas", "gas-v1", brier_ours=0.1148, brier_market=0.02676,
                 created_at="2026-09-20T00:00:00+00:00"),
            # Later, and better-looking (2.16x rather than 4.29x). Must still lose.
            _run("gas", EXPERIMENT_VERSION, brier_ours=EXPERIMENT_BRIER_OURS,
                 brier_market=EXPERIMENT_BRIER_MARKET,
                 created_at="2026-09-27T00:00:00+00:00"),
        ]

    def test_the_experiments_version_string_appears_nowhere_in_the_response(self):
        response = _get(_Supa({"backtest_runs": self._both_gas_runs()}))

        assert response.status_code == 200, response.text
        assert EXPERIMENT_VERSION not in response.text, (
            "the experiment's version string reached the client: it is not the engine's record "
            "and must be absent, not footnoted"
        )

    def test_the_experiments_own_numbers_appear_nowhere_in_the_response(self):
        """A leak is a SUPERSET problem, so the assertion has to be about the superset.

        Asserting only "the production row is present" passes just as happily when the experiment
        is present too. So: the experiment's distinctive Briers are searched for in the whole
        serialised body, and the 12h ratio (2.16) must not appear anywhere either.
        """
        body = _get_body(self._both_gas_runs())

        assert len(body["rows"]) == 1
        row = body["rows"][0]
        assert row["engine_version"] == "gas-v1"
        assert row["brier_ours"] == pytest.approx(0.1148)
        assert row["brier_ratio"] == pytest.approx(4.29, abs=0.01)

        serialised = json.dumps(body)
        assert str(EXPERIMENT_BRIER_OURS) not in serialised
        assert str(EXPERIMENT_BRIER_MARKET) not in serialised
        assert 2.16 not in [r["brier_ratio"] for r in body["rows"]]

    def test_the_excluded_run_is_still_in_the_table_and_still_counted_as_read(self):
        """Excluded from the page, not deleted. `runs_read` proves the read saw it.

        The run has to stay reproducible from the CLI and queryable in SQL; the page's job is to
        refuse to present it, not to make it disappear.
        """
        body = _get_body(self._both_gas_runs())

        assert body["runs_read"] == 2
        assert body["rows_total"] == 1


# ── the read failure must not look like an empty ledger ──────────────────────
class TestReadFailureIsNotEmpty:
    def test_a_failed_read_is_a_503_carrying_no_rows_at_all(self):
        supa = _Supa({"backtest_runs": [_run("gas", "gas-v1")]}, fail_on_call=1)

        response = _get(supa)

        assert response.status_code == 503
        body = response.json()
        assert "rows" not in body, "a failed read returned a scoreboard: it has no rows to return"
        assert "headline" not in body, "a failed read stated a verdict about the engines"
        assert body["detail"]

    def test_a_failure_on_a_later_page_never_renders_a_truncated_scoreboard(self):
        """The sharp edge of a paged read: page 1 succeeds, page 2 fails.

        An implementation that returns whatever it managed to read would answer 200 with a
        partial board — a page that looks complete, is not, and is missing engines. There is no
        way to tell that from a real result, so the whole read fails instead.
        """
        rows = [_run("gas", "gas-v1", id=f"g{i}") for i in range(1_500)]

        response = _get(_Supa({"backtest_runs": rows}, fail_on_call=2))

        assert response.status_code == 503
        assert "rows" not in response.json()

    def test_a_missing_table_names_the_migration_that_creates_it(self):
        """`backtest_runs` is created by 20260416000004; without the entry in `TABLE_MIGRATIONS`
        `_missing_table_message` says "no migration in this repo creates it", which is false."""
        supa = _Supa({})  # the table is not there

        response = _get(supa)

        assert response.status_code == 503
        assert "20260416000004_backtest_runs.sql" in response.json()["detail"]

    def test_an_empty_table_is_a_valid_empty_scoreboard_and_says_a_different_thing(self):
        body = _get_body([])

        assert body["rows"] == []
        assert body["rows_total"] == 0 and body["runs_read"] == 0
        assert body["engines"] == 0
        assert body["headline"] == HEADLINE_NO_RUNS

    def test_the_two_are_not_the_same_response(self):
        """One sentinel, one meaning. Measured, not asserted in prose."""
        failed = _get(_Supa({"backtest_runs": []}, fail_on_call=1))
        empty = _get(_Supa({"backtest_runs": []}))

        assert failed.status_code != empty.status_code
        assert failed.status_code == 503 and empty.status_code == 200
        assert set(failed.json()) != set(empty.json())
        assert empty.json()["headline"] != failed.json()["detail"]

    def test_503_without_supabase(self):
        app.dependency_overrides[get_supabase] = lambda: None

        assert TestClient(app).get("/api/scoreboard").status_code == 503


# ── the promotion verdict: the SHARED lookup, keyed on (engine, version) ──────
class TestThePromotionVerdict:
    """`promotion_status` is the full promotion decision, and it is not the row's `gate_status`.

    `backtest_runs.gate_status` is what `check_promotion_gate` (`tradehub/track_record.py:126`) --
    settled count, Brier, P&L, calibration -- returned at record time. The full decision is
    `tradehub/gate_status.py::latest_gate_statuses`: the latest backtest for that exact version
    AND a `track_record` row, both PROMOTED, and SHADOW otherwise. Nothing has ever passed the
    backtest gate, so before the controller's ruling this defect was invisible -- and it would
    have surfaced on the first promotion, which is the moment the page matters most.

    The two therefore travel as two fields, and the page labels them. A field still carrying the
    word PROMOTED from a partial gate reads as a promotion to a human, and this page is read by
    humans deciding whether to trust an engine.
    """

    def test_a_backtest_gate_that_passed_is_not_reported_as_promoted_on_its_own(self):
        """The defect, exactly. The row says the backtest gate passed; the page must not."""
        body = _get_board(
            [_run("gas", "gas-v1", gate_status="PROMOTED", gate_reasons=[])],
            track_record=[],
        )

        row = _row_for(body, "gas")
        assert row["gate_status"] == "PROMOTED", "the run's own gate verdict is still carried"
        assert row["promotion_status"] == "SHADOW", (
            "a backtest gate with no track record is not a promotion; the two tables must both say "
            "PROMOTED, or the edge is not tradable"
        )

    def test_a_promotion_needs_both_a_promoted_backtest_and_a_promoted_track_record(self):
        body = _get_board(
            [_run("gas", "gas-v1", gate_status="PROMOTED", gate_reasons=[])],
            track_record=[_promoted("gas", "gas-v1")],
        )

        assert _row_for(body, "gas")["promotion_status"] == "PROMOTED"

    def test_a_shadow_track_record_demotes_an_otherwise_promoted_pair(self):
        """Promotion is dynamic (spec section 6): a slip below any threshold demotes back."""
        body = _get_board(
            [_run("gas", "gas-v1", gate_status="PROMOTED", gate_reasons=[])],
            track_record=[dict(_promoted("gas", "gas-v1"), gate_status="SHADOW")],
        )

        assert _row_for(body, "gas")["promotion_status"] == "SHADOW"

    def test_a_promotion_is_not_inherited_by_another_version(self):
        """The specific leak `gate_status.py`'s docstring warns about, pinned at the endpoint.

        gas at `gas-v1` is promoted. gas at `gas-v2` has a track record that says PROMOTED but its
        OWN latest backtest is SHADOW, so it is SHADOW. A lookup keyed on the engine alone returns
        PROMOTED for both and the page then tells a reader that an unpromoted version is promoted.

        Two modes, so both rows survive `current_runs` -- which keys on `(engine, mode)`, and would
        otherwise keep only the newest run per engine and hide the second version entirely.
        """
        body = _get_board(
            [
                _run("gas", "gas-v1", mode="taker", gate_status="PROMOTED", gate_reasons=[]),
                _run("gas", "gas-v2", mode="maker", gate_status="SHADOW",
                     gate_reasons=[NEEDS_200_DAILY]),
            ],
            track_record=[_promoted("gas", "gas-v1"), _promoted("gas", "gas-v2")],
        )

        assert {r["engine_version"]: r["promotion_status"] for r in body["rows"]} == {
            "gas-v1": "PROMOTED",
            "gas-v2": "SHADOW",
        }

    def test_the_lookup_is_asked_with_the_version_in_the_key(self):
        """Not just the right answer -- the right question.

        The version is what stops one version's promotion leaking to another, so it has to reach
        the query. Asserted on the recorded VALUES, because a lookup that dropped the version and
        then happened to return the right answer in a test would be a passing accident.
        """
        supa = _Supa({
            "backtest_runs": [
                _run("gas", "gas-v1", mode="taker", gate_status="PROMOTED", gate_reasons=[]),
                _run("gas", "gas-v2", mode="maker", gate_status="SHADOW"),
                _run("weather", "weather-v1", mode="taker", gate_status="PROMOTED", gate_reasons=[]),
            ],
            "track_record": [_promoted("gas", "gas-v1"), _promoted("gas", "gas-v2")],
        })

        _get(supa)

        asked = set()
        for q in supa.queries:
            filters = dict(op[3:].split("=", 1) for op in q["ops"] if op.startswith("eq:"))
            if "engine" in filters and "engine_version" in filters:
                asked.add((ast.literal_eval(filters["engine"]),
                           ast.literal_eval(filters["engine_version"])))
        assert asked == {
            ("gas", "gas-v1"), ("gas", "gas-v2"), ("weather", "weather-v1"),
        }, f"the gate was asked about the wrong pairs: {sorted(asked)}"

    def test_two_modes_of_one_engine_share_one_promotion_verdict(self):
        """The row key is `(engine, mode)`; the gate key is `(engine, engine_version)`.

        Promotion is a property of an engine version, not of a fill mode, so both rows carry the
        same verdict. A per-mode verdict would be a second gate to keep in step, and would let the
        two rows of one engine disagree about whether the engine is tradable.
        """
        body = _get_board(
            [
                _run("gas", "gas-v1", mode="taker", gate_status="PROMOTED", gate_reasons=[]),
                _run("gas", "gas-v1", mode="maker", gate_status="PROMOTED", gate_reasons=[]),
            ],
            track_record=[_promoted("gas", "gas-v1")],
        )

        assert body["rows_total"] == 2
        assert {r["promotion_status"] for r in body["rows"]} == {"PROMOTED"}

    def test_an_unreadable_gate_lookup_fails_closed_and_says_it_was_unread(self):
        """A missing `track_record` table must not take the page down, and must not look measured.

        `SHADOW` is the fail-closed default and is the safe direction: it cannot make a
        non-tradable edge look tradable. But a column of SHADOW badges that were never verified
        is still a claim, so the response says the lookup failed and the page has to say so too.
        """
        # No `track_record` in the fake's tables: `table()` raises the way PostgREST does.
        body = _get_body([_run("gas", "gas-v1", gate_status="PROMOTED", gate_reasons=[])])

        assert body["promotion_lookup_failed"] is True
        assert [r["promotion_status"] for r in body["rows"]] == ["SHADOW"]
        assert body["rows_total"] == 1, "the board itself was readable, so it is still rendered"

    def test_a_healthy_lookup_does_not_raise_the_alarm(self):
        body = _get_board([_run("gas", "gas-v1")], track_record=[_promoted("gas", "gas-v1")])

        assert body["promotion_lookup_failed"] is False

    def test_the_lookup_is_not_run_at_all_when_there_is_nothing_to_look_up(self):
        """An empty board must not pay for a lookup, and must not read a table it has no row for."""
        supa = _Supa({"backtest_runs": []})

        body = _get(supa).json()

        assert {q["table"] for q in supa.queries} == {"backtest_runs"}
        assert body["promotion_lookup_failed"] is False
        assert body["rows"] == []

    def test_the_lookup_reads_only_the_two_gate_tables(self):
        """The cost of not having two answers is two extra tables, and only those two."""
        supa = _Supa({
            "backtest_runs": [_run("gas", "gas-v1", gate_status="PROMOTED", gate_reasons=[])],
            "track_record": [_promoted("gas", "gas-v1")],
        })

        _get(supa)

        assert {q["table"] for q in supa.queries} == {"backtest_runs", "track_record"}


class TestTheGateLookupIsShared:
    def test_the_scoreboard_and_the_scan_share_one_gate_lookup(self):
        """Two copies of this logic is how the War Room and the scan would start disagreeing about
        whether an edge is tradable -- `tradehub/gate_status.py`'s own docstring.

        Modelled on the identical assertion for `/api/jobs-scorecard`
        (`tests/test_api_jobs_scorecard.py::test_the_scan_and_the_api_share_one_gate_lookup`), which
        is why the endpoint had to import it rather than reimplement it: that endpoint already
        does, and two endpoints doing it differently would be the failure the function exists to
        prevent.
        """
        from tradehub import gate_status
        from tradehub.api import main
        from tradehub.scripts import scan

        assert main.latest_gate_statuses is gate_status.latest_gate_statuses
        assert scan.latest_gate_statuses is gate_status.latest_gate_statuses
        assert "track_record" in inspect.getsource(gate_status.latest_gate_statuses)

    def test_the_fail_closed_default_is_one_named_constant(self):
        """`"SHADOW"` was written out at four call sites across three modules.

        All four failed closed, so drift was harmless -- and that is exactly how a default starts
        disagreeing with itself: a reader comparing `scoreboard.py`'s default against
        `latest_gate_statuses`'s return could not tell a deliberate agreement from a coincidence, and
        there was no name to grep for. `tradehub/gate_status.py` is the module that decides the
        value, so `DEFAULT_GATE_STATUS` lives there and the callers import it.

        Structural, like the assertion above, because the behavioural version cannot work: a caller
        that restated the literal produces byte-identical output.
        """
        from tradehub import gate_status, scoreboard
        from tradehub.api import main

        assert gate_status.DEFAULT_GATE_STATUS == "SHADOW"
        # Walk the AST rather than grepping `getsource`: the invariant is about CODE,
        # and a comment is allowed to name the value it is explaining. Grepping the
        # raw source made a prose mention of "SHADOW" look like a second literal, which
        # is the same class of error as the restatement itself -- a test that cannot
        # tell a claim from the code making it.
        for module in (main, scoreboard):
            restated = [
                node.value
                for node in ast.walk(ast.parse(inspect.getsource(module)))
                if isinstance(node, ast.Constant) and node.value == "SHADOW"
            ]
            assert not restated, (
                f"{module.__name__} restates the fail-closed default as a literal; import "
                f"DEFAULT_GATE_STATUS from tradehub.gate_status instead"
            )


# ── the summary: derived here, never by the page ──────────────────────────────
class TestTheSummary:
    def test_the_headline_is_derived_from_the_rows_not_asserted_by_hand(self):
        behind = _get_body([_run("gas", "gas-v1"), _run("weather", "weather-v1",
                                                        brier_ours=0.13, brier_market=0.1017)])
        ahead = _get_body([_run("weather", "weather-v1", brier_ours=0.05, brier_market=0.10)])

        assert behind["headline"] == HEADLINE_BEHIND
        assert behind["rows_behind_market"] == 2 and behind["any_beats_market"] is False
        assert ahead["headline"] == HEADLINE_AHEAD
        assert ahead["rows_ahead_of_market"] == 1 and ahead["rows_behind_market"] == 0
        assert ahead["any_beats_market"] is True

    def test_a_row_with_no_market_brier_is_unmeasured_not_a_loss(self):
        """`brier_market` is nullable, so this is a real state.

        Counting it as behind would be inventing a comparison that was never made, and the
        headline would then claim something about an engine nobody measured. The row still
        appears, with its numbers, and the board says how much of it is unmeasured.
        """
        rows = [
            _run("gas", "gas-v1", brier_market=None,
                 gate_reasons=["no market Brier recorded; gate cannot be evaluated"]),
            _run("weather", "weather-v1", brier_ours=0.13, brier_market=0.1017),
        ]

        body = _get_body(rows)

        assert body["rows_not_comparable"] == 1
        assert body["rows_behind_market"] == 1
        assert body["rows"][0]["brier_ratio"] is None
        assert body["headline"] == HEADLINE_BEHIND

    def test_a_board_with_nothing_comparable_says_it_measured_nothing(self):
        """The state where "no engine beats the market" would be a lie rather than a finding."""
        body = _get_body([
            _run("gas", "gas-v1", brier_market=None),
            _run("weather", "weather-v1", brier_market=None),
        ])

        assert body["headline"] == HEADLINE_NOT_COMPARABLE
        assert body["rows_not_comparable"] == 2
        assert body["any_beats_market"] is False
        assert len(body["rows"]) == 2, "the engines are still shown; they were just not comparable"

    def test_every_row_lands_in_exactly_one_bucket(self):
        """A row silently uncounted is how "3 of 5 behind" becomes true of a board of five."""
        rows = [
            _run("gas", "gas-v1", brier_ours=0.1148, brier_market=0.02676),        # behind
            _run("weather", "weather-v1", brier_ours=0.05, brier_market=0.10),     # ahead
            _run("cpi_nowcast", "cpi-v1", brier_ours=0.10, brier_market=0.10),     # level
            _run("labor_nowcast", "labor-v1", brier_market=None),                  # unmeasured
        ]

        body = _get_body(rows)

        assert body["rows_total"] == 4 == len(body["rows"])
        assert (body["rows_behind_market"] + body["rows_ahead_of_market"]
                + body["rows_level_with_market"] + body["rows_not_comparable"]) == body["rows_total"]

    def test_a_tie_is_level_not_a_loss(self):
        body = _get_body([_run("weather", "weather-v1", brier_ours=0.10, brier_market=0.10)])

        assert body["rows_level_with_market"] == 1
        assert body["rows_behind_market"] == 0 and body["rows_ahead_of_market"] == 0
        assert body["any_beats_market"] is False
        assert body["headline"] == HEADLINE_BEHIND

    def test_taker_and_maker_are_two_rows_and_one_engine(self):
        """Why the counts are named `rows_*` and not `engines_*`.

        The plan's field was `engines_behind_market` and it counted rows. With weather in both
        fill modes the board has two rows and one engine, so "1 of 2 engines behind" is a
        sentence about a board that had one engine in it — a right number under a label that
        makes it mean something else.
        """
        rows = [
            _run("weather", "weather-v1", mode="taker", brier_ours=0.1242, brier_market=0.09713),
            _run("weather", "weather-v1", mode="maker", brier_ours=0.118, brier_market=0.09713),
            _run("gas", "gas-v1", brier_ours=0.1148, brier_market=0.02676),
        ]

        body = _get_body(rows)

        assert body["engines"] == 2, "two (engine, mode) pairs across two distinct engines"
        assert body["rows_total"] == 3
        assert body["rows_behind_market"] == 3
        assert {row["mode"] for row in body["rows"] if row["engine"] == "weather"} == {"taker", "maker"}

    def test_the_floor_travels_as_min_settled_and_is_not_hardcoded(self):
        """`MIN_SETTLED` is imported from `tradehub/sports/scorecard.py` and asserted, never
        written out here — a hardcoded 100 in the endpoint would be a second place to be wrong.
        """
        body = _get_body([_run("gas", "gas-v1")])

        assert MIN_SETTLED == 100
        for row in body["rows"]:
            assert row["settled_distance"]["floor"] == MIN_SETTLED
        # And the endpoint's own module does not contain the literal.
        assert "100" not in [
            line.split("#")[0] for line in MAIN_PY.read_text().splitlines()
            if "MIN_SETTLED" in line
        ]


# ── the catalogue: which engines EXIST, not only which were measured ─────────
class TestTheCatalogue:
    """`catalogue` is the answer to "what are the models and what are they doing".

    It rides on this response rather than on a second endpoint, for two reasons that are both about
    drift rather than about cost. The page needs the rows and the claims JOINED -- an engine with
    a run beside its claim, and an engine with no run beside its claim anyway -- and a join done at
    render time is a join a component can do wrong in a direction nobody sees. And the claim is a
    sentence about what an engine predicts, which is a fact about the same code that reduces the
    runs; a second endpoint would be a second place for it to be out of date.
    """

    def test_an_engine_with_no_backtest_is_still_in_the_response(self):
        """The rule the page exists to keep. `backtest_runs` only holds engines somebody ran a
        backtest for, so a response built from the board alone has already dropped most of the
        product before a reader sees it."""
        body = _get_body([_run("gas", "gas-v1")])

        engines = {entry["engine"] for entry in body["catalogue"]["entries"]}
        assert "gas" in engines
        for unmeasured in ("crypto", "sports_nfl", "sports_cfb"):
            assert unmeasured in engines

    def test_an_unmeasured_engine_says_not_measured_and_carries_no_number(self):
        entry = next(
            e for e in _get_body([])["catalogue"]["entries"] if e["engine"] == "crypto"
        )

        assert entry["measured"] is False
        assert entry["status"] == "not_measured"
        # None, never 0. A ratio of zero is a model that never misses.
        assert entry["worst_brier_ratio"] is None
        # And the claim is still there: a claim is not a measurement, and the engine is real
        # whether or not anybody has scored it.
        assert entry["claim"]

    def test_the_counts_say_how_much_of_the_product_has_never_been_measured(self):
        body = _get_body([_run("gas", "gas-v1")])
        catalogue = body["catalogue"]

        assert catalogue["engines_measured"] == 1
        assert catalogue["engines_not_measured"] == catalogue["engines_total"] - 1
        # And the number the page leads with is one the server computed, because it is a
        # subtraction on a set and a page that does it at render time does it in a component.
        assert catalogue["engines_total"] == len(catalogue["entries"])

    def test_every_catalogue_entry_carries_its_own_rows_whole(self):
        """Self-contained, so the page reads a row's ratio, verdict and both bars off the entry
        instead of joining on a name. And it is the same object, not an edited copy."""
        body = _get_body([
            _run("gas", "gas-v1", brier_ours=0.1148, brier_market=0.02676),
        ])

        gas = next(e for e in body["catalogue"]["entries"] if e["engine"] == "gas")
        assert gas["measured"] is True
        assert gas["measured_rows"] == 1
        assert gas["status"] == "behind"
        assert gas["worst_brier_ratio"] == pytest.approx(4.29, abs=0.01)
        # The row is the scoreboard's, whole -- including the promotion verdict the route attached
        # AFTER the reduction. An entry built before that loop would ship a gate the board does not
        # show, which is a right number under the wrong label. Compared by value, because the
        # response has been through JSON by now and identity is gone; every field is compared.
        assert gas["rows"][0] == body["rows"][0]
        assert gas["rows"][0]["promotion_status"] == "SHADOW"

    def test_every_row_lands_in_exactly_one_entry(self):
        body = _get_body([
            _run("gas", "gas-v1"),
            _run("weather", "weather-v1", mode="taker", brier_ours=0.13, brier_market=0.1017),
            _run("weather", "weather-v1", mode="maker", brier_ours=0.1242, brier_market=0.09713),
        ])

        carried = [row for entry in body["catalogue"]["entries"] for row in entry["rows"]]

        assert len(carried) == body["rows_total"] == 3
        # A weather row's count is 2, and the engine count is 2 across 3 rows -- the same
        # rows-vs-engines distinction the headline counts already make.
        weather = next(e for e in body["catalogue"]["entries"] if e["engine"] == "weather")
        assert weather["measured_rows"] == 2
        assert body["engines"] == 2

    def test_a_losing_engine_is_reported_at_its_worst_row(self):
        body = _get_body([
            _run("weather", "weather-v1", mode="taker", brier_ours=0.1242, brier_market=0.09713),
            _run("weather", "weather-v1", mode="maker", brier_ours=0.1347, brier_market=0.1124),
        ])

        weather = next(e for e in body["catalogue"]["entries"] if e["engine"] == "weather")

        assert weather["status"] == "behind"
        assert weather["worst_brier_ratio"] == pytest.approx(1.2787, abs=0.0001)
        # ...and the better row is still on the entry, so the worst is a summary and not a filter.
        assert len(weather["rows"]) == 2

    def test_the_catalogue_costs_no_extra_reads(self):
        """It is a pure join over rows already in hand. A catalogue that had to read something --
        an `engines` table, a config file, a query -- would be a second source of truth about
        which engines exist, and the two could disagree."""
        supa = _Supa({"backtest_runs": [_run("gas", "gas-v1")]})

        _get(supa)

        assert {q["table"] for q in supa.queries} == {"backtest_runs"}

    def test_a_failed_read_is_still_a_503_and_still_carries_no_catalogue(self):
        """The catalogue joins rows that were read. A failed read has none, and an empty catalogue
        would be indistinguishable from a product with no engines in it."""
        response = _get(_Supa({"backtest_runs": [_run("gas", "gas-v1")]}, fail_on_call=1))

        assert response.status_code == 503
        assert "catalogue" not in response.json()

    def test_the_page_does_not_have_to_derive_the_claim_or_the_status(self):
        """Structural. The two things the page must not compute are the ratio comparison and the
        engine list, and both are words and arithmetic the server resolved. `1.0` in the route's
        executable text is a second copy of `BEHIND_THE_MARKET`."""
        from tradehub.api import main

        tree = ast.parse(inspect.getsource(main.get_scoreboard))
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and body
                    and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)):
                body[0].value.value = ""
        executable = ast.unparse(tree)

        assert "1.0" not in executable
        assert "engine_catalogue(" in executable
        assert "market_verdict" not in executable, "the route decided a market verdict itself"


# ── structural: the route has to be reachable, and above the SPA mount ────────
class TestRegistration:
    def test_the_route_is_registered(self):
        assert "/api/scoreboard" in {getattr(route, "path", None) for route in app.routes}

    def test_every_api_route_is_registered_above_the_spa_mount(self):
        """The SPA is mounted at "/", so a route added after `mount_frontend` is shadowed and
        answers with the app shell instead of JSON.

        Checked against the real source with `ast`, because the mount only happens when
        `market_sentiment_tool/dist/index.html` exists — it does not in the test environment, so
        a runtime assertion here would be vacuous. This one is not: it fails the moment an
        `@app.get("/api/...")` decorator moves below the mount call in `main.py`.
        """
        tree = ast.parse(MAIN_PY.read_text())

        mount_at = None
        api_routes_at = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "mount_frontend":
                mount_at = node.lineno
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if (isinstance(decorator, ast.Call)
                            and getattr(decorator.func, "attr", "") == "get"
                            and decorator.args
                            and isinstance(decorator.args[0], ast.Constant)
                            and str(decorator.args[0].value).startswith("/api/")):
                        api_routes_at.append((decorator.lineno, decorator.args[0].value))

        assert mount_at is not None, "main.py no longer calls mount_frontend"
        assert api_routes_at, "no /api route decorators found in main.py"
        below = [path for lineno, path in api_routes_at if lineno > mount_at]
        assert below == [], (
            f"these /api routes are registered after mount_frontend (line {mount_at}) and would "
            f"be shadowed by the SPA: {below}"
        )
