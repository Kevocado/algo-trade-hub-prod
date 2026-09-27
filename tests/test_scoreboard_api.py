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
        self.ops.append(f"eq:{col}")
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def order(self, col, *rest, **_k):
        self.ops.append("order")
        self.ordered.append(col if not rest else (col, *rest))
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


# ── what it reads, and how ────────────────────────────────────────────────────
class TestTheRead:
    def test_it_reads_backtest_runs_and_nothing_else(self):
        # The gate status on the row is the BACKTEST gate, not the full promotion decision, so
        # this endpoint deliberately does not add `latest_gate_statuses` -- that would be a
        # second gate lookup and a second source of truth for "is this engine promoted". See the
        # report's open concern; the test pins the single read so the second one cannot arrive
        # quietly.
        supa = _Supa({"backtest_runs": [_run("gas", "gas-v1")]})

        response = _get(supa)

        assert response.status_code == 200, response.text
        assert {q["table"] for q in supa.queries} == {"backtest_runs"}

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

        ordered = {tuple(q["ordered"]) for q in supa.queries}
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
