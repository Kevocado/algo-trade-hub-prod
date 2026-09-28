"""The CPI display endpoint: the nowcast against the market, labelled as what it is.

A reader shown a model probability beside a market price will assume an opportunity unless something
says otherwise, and this engine is 1.33-1.43x behind the market at every lead (spec 5a, outcome
REFUTED). So `mode`, a null `edge_pct` and the reason travel in the payload rather than being left to
the page -- and the label has to be in the data because `predictions` is owner-only under RLS, so
this endpoint is the only route by which these numbers reach a browser at all.

Two failure modes are worth their own tests because both are green-and-wrong:

* a failed read rendering as "no CPI data", which is indistinguishable from the truth, and
* a row with no market mid rendering as though it were a comparison, which is the display mode
  quietly becoming the edge claim this plan exists to remove.
"""

import re
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from tradehub.api import main as api_main
from tradehub.api.dependencies import get_supabase

FORBIDDEN = ("order", "position", "balance", "fill")


class _Res:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, supa, name):
        self.supa = supa
        self.name = name
        self.orders: list[tuple[str, str]] = []
        self.filters: dict = {}
        self.span: tuple[int, int] | None = None

    def select(self, *cols):
        self.supa.reads.append({"table": self.name, "select": cols, "orders": [], "filters": {}})
        return self

    def eq(self, col, val):
        self.filters[col] = val
        if self.supa.reads:
            self.supa.reads[-1]["filters"][col] = val
        return self

    def order(self, col, *, desc=False, **_kw):
        self.orders.append((col, "desc" if desc else "asc"))
        if self.supa.reads:
            self.supa.reads[-1]["orders"].append((col, "desc" if desc else "asc"))
        return self

    def range(self, lo, hi):
        self.span = (lo, hi)
        return self

    def execute(self):
        if self.name != "predictions":
            raise AssertionError(f"the display read another table: {self.name}")
        if self.supa.boom is not None:
            raise self.supa.boom
        rows = list(self.supa.rows)
        if "engine" in self.filters:
            rows = [r for r in rows if r.get("engine") == self.filters["engine"]]
        # Postgres does the ordering, as a composite: the first ORDER BY is primary and the rest are
        # tiebreaks. Applied least-significant-first so the stable sort composes them.
        # The fixture timestamps are one uniform format, so a lexicographic sort agrees with a
        # chronological one here.
        for col, direction in reversed(self.orders):
            rows.sort(key=lambda r, c=col: (r.get(c) is None, str(r.get(c) or "")),
                      reverse=direction == "desc")
        lo, hi = self.span or (0, len(rows) - 1)
        return _Res(rows[lo:hi + 1])


class _Supa:
    def __init__(self, rows=(), boom=None):
        self.rows = list(rows)
        self.boom = boom
        self.reads: list[dict] = []

    def table(self, name):
        return _Query(self, name)


def _row(ticker, *, our, market, nowcast, as_of="2026-09-27T12:00:00+00:00", **extra):
    row = {
        "id": ticker,
        "market_ticker": ticker,
        "engine": "cpi_nowcast",
        "engine_version": "v0",
        "our_prob": our,
        "market_prob": market,
        "as_of": as_of,
        "status": "OPEN",
        "raw_payload": {
            "nowcast": nowcast,
            "nowcast_obs": "CLEVELAND-2026-09",
            "bias": 0.0,
            "sigma": 0.15,
            "n_train": 24,
            "hours_to_close": 6.5,
        },
    }
    row.update(extra)
    return row


def _stamp(i: int) -> str:
    """`i` distinct, valid, chronological timestamps. Distinct because a tie in the sort key is
    exactly what the `id` tiebreak exists for, and the fake has to exercise that too."""
    return (f"2026-09-{(i // 1440) % 28 + 1:02d}T{i % 24:02d}:{(i // 24) % 60:02d}:{i % 60:02d}"
            "+00:00")


def _get(rows=None, *, boom=None, **params):
    supa = rows if isinstance(rows, _Supa) else _Supa(rows or [], boom=boom)
    app = api_main.app
    app.dependency_overrides[get_supabase] = lambda: supa
    try:
        response = TestClient(app).get("/api/cpi-display", params=params)
    finally:
        app.dependency_overrides.clear()
    return response, supa


# ── the label ────────────────────────────────────────────────────────────────

def test_every_row_declares_itself_display_only_and_carries_no_edge():
    body = _get([_row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3)])[0].json()

    assert body["mode"] == "display"
    assert body["edge_pct"] is None, "a display carries no edge number, at any level"
    row = body["rows"][0]
    assert row["edge_pct"] is None
    assert row["gate_status"] == "SHADOW"
    assert row["nowcast"] == 0.3
    assert row["our_prob"] == 0.55
    assert row["market_prob"] == 0.52


def test_the_response_says_why_in_words_not_just_a_flag():
    """A bare `mode: display` is jargon. The sentence is what a reader actually reads."""
    body = _get([_row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3)])[0].json()

    assert "not an edge engine" in body["reason"].lower()
    assert "market" in body["reason"].lower()


def test_the_response_implies_no_balance_no_position_and_no_order():
    """Suggest-only, and it is a property of the payload: this product never places an order, so
    nothing this endpoint returns may read as if something had been, could be, or is waiting."""
    response, _ = _get([_row("KXCPI-26SEP09-3.0", our=0.55, market=None, nowcast=0.3)])

    assert response.status_code == 200
    for word in FORBIDDEN:
        assert not re.search(rf"\b{word}s?\b", response.text, re.IGNORECASE), (
            f"the response mentions {word!r}: {response.text}"
        )


# ── the gate ─────────────────────────────────────────────────────────────────

def test_the_gate_is_never_read_from_the_row():
    """`predictions` has no `gate_status` column, so reading one would be reading a field that does
    not exist -- and if a future writer ever added one, this endpoint would silently start obeying
    it. The row below carries a PROMOTED value precisely to prove the value is not read."""
    row = _row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3, gate_status="PROMOTED")
    body = _get([row])[0].json()

    assert body["rows"][0]["gate_status"] == "SHADOW", (
        "display-only is never promoted, whatever the row happens to carry"
    )
    assert body["gate_status"] == "SHADOW"


def test_the_writer_cannot_be_carrying_a_gate_column():
    """Why the value above is a fallback and not a lookup: the insert payload has no gate column."""
    from tradehub.predictions import build_prediction_row

    row = build_prediction_row(
        market_ticker="KXCPI-26SEP09-3.0", our_prob=0.55, market_prob=0.52,
        engine="cpi_nowcast", as_of=datetime(2026, 9, 27, 12, tzinfo=timezone.utc),
    )

    assert "gate_status" not in row, sorted(row)


def test_the_gate_says_it_was_not_checked_rather_than_that_it_said_no():
    """"SHADOW" is the gate's own vocabulary and it means "not promoted". Printing it for an engine
    that has no gate at all is a right value under the wrong attribution: it says a gate was consulted
    and returned a verdict. §5 records CPI as REFUTED, not as pending, so the distinction between
    "no gate, and none is expected" and "the gate was checked and said no" has to survive into the
    payload rather than being collapsed into one string."""
    body = _get([_row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3)])[0].json()

    assert body["gate_checked"] is False
    assert body["rows"][0]["gate_checked"] is False
    reason = body["gate_checked_reason"].lower()
    assert "no gate was consulted" in reason
    assert "display" in reason and "fails-closed" in reason


# ── shape, paging, ordering ──────────────────────────────────────────────────

def test_it_paginates_newest_first():
    rows = [
        _row(f"KXCPI-26SEP09-{i}.0", our=0.5, market=0.5, nowcast=0.3,
             as_of=f"2026-09-2{i}T12:00:00+00:00")
        for i in range(1, 6)
    ]
    response, supa = _get(rows, limit=2, offset=0)
    body = response.json()

    assert [r["market_ticker"] for r in body["rows"]] == ["KXCPI-26SEP09-5.0", "KXCPI-26SEP09-4.0"]
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert body["truncated"] is False
    assert ("as_of", "desc") in supa.reads[0]["orders"]


def test_the_read_is_scoped_to_the_cpi_engine_and_ordered_by_a_column_that_exists():
    """`predictions` holds every engine's output, and it has `as_of` and `created_at`; it has no
    `updated_at`. An unscoped read would put weather and gas rows on a CPI page, and ordering by a
    column the table does not have is a 400 from PostgREST, not a sort."""
    body, supa = _get([_row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3)])

    assert body.status_code == 200
    assert supa.reads[0]["filters"] == {"engine": "cpi_nowcast"}
    ordered = [col for col, _ in supa.reads[0]["orders"]]
    assert "updated_at" not in ordered, ordered
    assert ordered[0] == "as_of", ordered
    assert "id" in ordered, "the paging tiebreak has to be there or pages can repeat and skip rows"


def test_the_row_carries_the_timestamp_and_state_it_actually_has():
    """A settled row from a market that closed last month must not render as if it were live."""
    row = _row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3,
               as_of="2026-09-27T12:00:00+00:00", status="SETTLED")
    out = _get([row])[0].json()["rows"][0]

    assert out["as_of"] == "2026-09-27T12:00:00+00:00"
    assert out["status"] == "SETTLED"


def test_it_does_not_publish_the_nowcast_bias_as_a_figure():
    """`fit_cpi_error` returns 0.0 for bias whenever `use_bias` is off (tradehub/engines/cpi.py:78),
    so publishing it would print a disabled knob as though it were a measurement."""
    out = _get([_row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3)])[0].json()["rows"][0]

    assert "bias" not in out, sorted(out)


def test_an_empty_league_returns_a_valid_empty_payload_not_an_error():
    body = _get([])[0].json()

    assert body["rows"] == []
    assert body["total"] == 0
    assert body["withheld_count"] == 0
    assert body["truncated"] is False
    assert body["mode"] == "display"


def test_limit_and_offset_are_bounded():
    assert _get([], limit=0)[0].status_code == 422
    assert _get([], limit=10_000)[0].status_code == 422
    assert _get([], offset=-1)[0].status_code == 422


# ── GREEN AND WRONG #2: an offset past the read's bound serving an empty page ───

def _ledger(n: int) -> list[dict]:
    return [_row(f"KXCPI-26SEP-{i}.0", our=0.5, market=0.5, nowcast=0.3, as_of=_stamp(i))
            for i in range(n)]


def test_an_offset_past_the_read_bound_is_rejected_not_served_as_an_empty_page():
    """The endpoint advertises `offset`, echoes it, and `test_limit_and_offset_are_bounded` asserts
    its bounds -- so paging reads as supported. But the window is applied to `read[:CPI_ROW_SCAN]`
    and `_fetch_all` stops at CPI_ROW_SCAN + 1, so any offset past the bound answered

        200, rows: [], total: 200, truncated: true

    which is indistinguishable from a ledger that holds nothing. The rows past the bound were never
    read, so the empty page is not a fact about the data. At three scans a day the ledger passes
    CPI_ROW_SCAN in about two weeks, so this is the normal case and not an edge case."""
    ledger = _ledger(300)   # past the bound, so the old code had rows to be silent about

    for offset in (200, 201, 250, 10_000):
        response, _ = _get(ledger, offset=offset, limit=50)
        assert response.status_code == 422, f"offset={offset} served {response.status_code}"
        assert "rows" not in response.json(), response.json()


def test_the_rejection_says_why_rather_than_only_being_a_422():
    response, _ = _get(_ledger(300), offset=200, limit=50)

    detail = response.json()["detail"]
    assert str(api_main.CPI_ROW_SCAN) in detail
    assert "empty page" in detail, detail


def test_a_window_inside_the_bound_still_pages():
    """The bound is on the WINDOW, not on paging. Four full 50-row windows exactly cover the read,
    and the last one is the boundary rather than one past it."""
    body = _get(_ledger(200), offset=150, limit=50)[0].json()

    assert body["offset"] == 150 and body["limit"] == 50
    assert len(body["rows"]) == 50
    assert body["total"] == 200 and body["truncated"] is False


def test_the_whole_read_is_still_one_window_when_offset_overshoots_the_ledger():
    """An offset past the end of a COMPLETE read is ordinary paging, not the defect above, and
    `total` is what tells the two apart: here the read was not truncated and `total` is below the
    offset, so a client can see why the page is empty. The defect was an offset past the read's
    BOUND, where `total` said 200 and `truncated` said true and the page still said nothing."""
    response, _ = _get(_ledger(120), offset=150, limit=50)
    body = response.json()

    assert body["rows"] == []
    assert body["total"] == 120
    assert body["truncated"] is False
    assert body["offset"] > body["total"]


# ── GREEN AND WRONG #1: a failed read rendering as "no CPI data" ──────────────

def test_a_read_failure_is_a_503_and_never_an_empty_board():
    """The empty list and the failed read must not look alike. A 200 with `rows: []` is the claim
    "measured, and there is nothing there"; a failed read is the claim "not measured". If the
    failure collapses into an empty list, the page says the nowcast has no markets when in fact
    nobody has asked the database yet."""
    response, _ = _get(_Supa([], boom=RuntimeError(
        "Could not find the table 'public.predictions' in the schema cache")))

    assert response.status_code == 503
    body = response.json()
    assert "rows" not in body, body
    assert "mode" not in body, body


def test_a_read_failure_names_the_migration_that_creates_the_table():
    """A 500 here is what put a red "unavailable" on the War Room with a message no reader could
    act on. The detail has to say what to do."""
    response, _ = _get(_Supa([], boom=RuntimeError(
        "Could not find the table 'public.predictions' in the schema cache")))

    assert "20260416000003" in response.json()["detail"]


def test_a_read_failure_part_way_through_the_pages_is_still_a_503():
    """`_fetch_all` pages. A failure after the first page must not render page one as if it were
    the whole set -- that is a truncated read reading as complete, which is a claim about the data."""
    supa = _Supa([_row(f"KXCPI-26SEP09-{i}.0", our=0.5, market=0.5, nowcast=0.3) for i in range(300)])
    boom = RuntimeError("connection reset")
    original_execute = _Query.execute

    def execute(self):
        if self.span and self.span[0] > 0:
            raise boom
        return original_execute(self)

    _Query.execute = execute
    try:
        response, _ = _get(supa)
    finally:
        _Query.execute = original_execute

    assert response.status_code == 503
    assert "rows" not in response.json()


def test_no_supabase_client_is_a_503():
    from tradehub.api import main as api

    app = api.app
    app.dependency_overrides[get_supabase] = lambda: None
    try:
        response = TestClient(app).get("/api/cpi-display")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503


# ── GREEN AND WRONG #2: a row that is not comparable rendering as if it were ──

def test_a_row_with_no_market_mid_is_not_a_comparison_and_says_why():
    """A CPI release scanned before the first quote has NO market probability. That is a different
    fact from a market probability of zero, so the figure stays null, the row is marked not
    comparable, and the reason travels with it. This is the whole defect: a display row that reads
    as an edge is not a rendering problem, it is the payload claiming something untrue."""
    out = _get([_row("KXCPI-26SEP09-3.0", our=0.55, market=None, nowcast=0.3)])[0].json()["rows"][0]

    assert out["market_prob"] is None
    # `comparable` is a boolean and is False here; it is deliberately not in this tuple, because
    # False == 0 in Python and `0 not in (...)` would be a test that cannot mean what it says.
    assert 0 not in (out["market_prob"], out["edge_pct"], out["our_prob"]), out
    assert out["comparable"] is False
    assert isinstance(out["withheld_reason"], str) and out["withheld_reason"].strip()
    assert "market" in out["withheld_reason"].lower()


def test_a_comparable_row_carries_no_withheld_reason():
    out = _get([_row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3)])[0].json()["rows"][0]

    assert out["comparable"] is True
    assert out["withheld_reason"] is None


def test_a_withheld_row_is_still_shown_and_still_counted():
    """An engine that loses stays visible. The row is withheld from the comparison, not from the
    page, and the count of withheld rows is part of the response -- a page that shows four markets
    without saying a fifth was not comparable is quietly lying about what it read."""
    rows = [
        _row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3),
        _row("KXCPI-26SEP09-4.0", our=0.41, market=None, nowcast=0.3),
    ]
    body = _get(rows)[0].json()

    assert [r["market_ticker"] for r in body["rows"]] == ["KXCPI-26SEP09-3.0", "KXCPI-26SEP09-4.0"]
    assert body["withheld_count"] == 1
    assert sum(1 for r in body["rows"] if not r["comparable"]) == 1


def test_the_withheld_count_is_over_the_whole_read_not_the_page():
    """A page-derived count says "nothing withheld" on page 2 while page 1 had one, which is the
    same shape as the sports board's "everything was rejected" banner: each offset window reporting
    on itself instead of on the set."""
    rows = [
        _row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3,
             as_of="2026-09-27T12:00:00+00:00"),
        _row("KXCPI-26SEP09-4.0", our=0.41, market=None, nowcast=0.3,
             as_of="2026-09-26T12:00:00+00:00"),
    ]
    body = _get(rows, limit=1, offset=0)[0].json()

    assert len(body["rows"]) == 1
    assert body["rows"][0]["comparable"] is True
    assert body["withheld_count"] == 1, "the withheld row is on page 2 and must still be counted"


# ── GREEN AND WRONG #3: a DEFAULTED error model rendering as a fitted one ────

def test_a_row_whose_sigma_is_the_engine_default_says_so():
    """`fit_cpi_error` returns the CONSTANT `DEFAULT_CPI_ERROR` (sigma 0.15) whenever it has fewer
    than CPI_MIN_TRAIN pairs, so `our_prob` can come out of a hardcoded number. On the page that row
    used to be identical to a fitted one: same "±0.15pp", same probability, nothing to tell them
    apart. This is the INVERSE of the missing-figure rule and the same class of defect -- a figure
    the scan did not measure, presented in the shape of one it did."""
    row = _row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3)
    row["raw_payload"].update(sigma=0.15, n_train=3)   # below CPI_MIN_TRAIN

    out = _get([row])[0].json()["rows"][0]

    assert out["n_train"] == 3
    assert out["default_error_model"] is True
    assert isinstance(out["default_error_model_reason"], str)
    assert "default" in out["default_error_model_reason"].lower()
    assert "fit" in out["default_error_model_reason"].lower()


def test_a_fitted_row_is_not_labelled_a_default():
    row = _row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3)
    row["raw_payload"].update(sigma=0.11, n_train=24)

    out = _get([row])[0].json()["rows"][0]

    assert out["n_train"] == 24
    assert out["default_error_model"] is False
    assert out["default_error_model_reason"] is None


def test_the_default_flag_is_derived_from_n_train_and_not_from_the_sigma_value():
    """The default's own sigma (0.15) is a value a FITTED model can also return, so branching on
    `sigma == 0.15` would label some fitted rows "default" and would be a coin flip on the rest.
    The signal has to be the number `fit_cpi_error` actually branched on."""
    row = _row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3)
    row["raw_payload"].update(sigma=0.15, n_train=40)   # fitted, and it happened to fit 0.15

    out = _get([row])[0].json()["rows"][0]

    assert out["sigma"] == 0.15
    assert out["default_error_model"] is False, "a fit that lands on the default's sigma is a fit"


def test_an_unrecorded_n_train_claims_neither_a_fit_nor_a_default():
    """Three-valued on purpose. An absent `n_train` is not evidence that the model was fitted, so
    the flag is null and the page says the count is unknown -- rather than defaulting the reader to a
    conclusion in either direction."""
    row = _row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3)
    del row["raw_payload"]["n_train"]

    out = _get([row])[0].json()["rows"][0]

    assert out["n_train"] is None
    assert out["default_error_model"] is None
    assert out["default_error_model_reason"] is None


def test_the_default_sigma_matches_the_engine_constant_so_the_words_cannot_go_stale():
    from tradehub.engines.cpi import DEFAULT_CPI_ERROR, fit_cpi_error

    # Zero pairs: the branch the endpoint derives `default_error_model` from.
    assert fit_cpi_error([]) is DEFAULT_CPI_ERROR
    assert api_main.CPI_DEFAULT_ERROR_SIGMA == DEFAULT_CPI_ERROR.sigma
    assert str(api_main.CPI_DEFAULT_ERROR_SIGMA) in api_main.CPI_DEFAULT_ERROR_MODEL


# ── the scan bound ───────────────────────────────────────────────────────────

def test_a_read_that_hits_the_scan_bound_says_it_was_truncated():
    """`predictions` is append-only, so an unbounded read grows forever. The bound keeps the newest
    rows, which is the right thing to keep for a live display, but a `total` that silently counts
    only what was read is a claim about the data."""
    scan = api_main.CPI_ROW_SCAN
    rows = [
        _row(f"KXCPI-26SEP-{i}.0", our=0.5, market=0.5, nowcast=0.3, as_of=_stamp(i))
        for i in range(scan + 30)
    ]
    body = _get(rows)[0].json()

    assert body["truncated"] is True
    assert body["total"] == scan


def test_a_read_exactly_at_the_bound_is_not_called_truncated():
    """The boundary, where a "did I fill the cap?" check written the obvious way is wrong."""
    scan = api_main.CPI_ROW_SCAN
    rows = [
        _row(f"KXCPI-26SEP-{i}.0", our=0.5, market=0.5, nowcast=0.3, as_of=_stamp(i))
        for i in range(scan)
    ]
    body = _get(rows)[0].json()

    assert body["truncated"] is False
    assert body["total"] == scan


# ── registration order ───────────────────────────────────────────────────────

def _routes_with_a_spa_mounted(tmp_path):
    """`api_main.app` as it is registered when the SPA is actually present.

    A SEPARATE module instance, deliberately. `importlib.reload` is not safe here: four test
    modules bind `app` with `from tradehub.api.main import app` at import time, so a reload would
    leave them holding the previous object while `api_main.app` became a new one, and this repo has
    order-dependent tests already. Loading the file under a private name gives a fresh FastAPI and
    a fresh `mount_frontend` call, and the real module -- and every other test -- is untouched.

    The alternative was to assert against the live `app.routes` and skip when
    `market_sentiment_tool/dist/index.html` is absent. That is what this test used to do, and
    `dist` is gitignored and never built before pytest, so in CI the assertion never ran: 128
    green Python tests and a route ordering nobody had checked. It passed on a machine where
    someone had run `npm run build` at some point, which is exactly the kind of coverage that only
    exists for whoever built it.
    """
    import importlib.util
    import os
    import sys

    (tmp_path / "index.html").write_text("<!doctype html><title>spa</title>")
    previous = os.environ.get("FRONTEND_DIST")
    os.environ["FRONTEND_DIST"] = str(tmp_path)
    spec = importlib.util.spec_from_file_location("_cpi_display_spa_probe", api_main.__file__)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            os.environ.pop("FRONTEND_DIST", None)
        else:
            os.environ["FRONTEND_DIST"] = previous
    return [getattr(route, "path", None) for route in module.app.routes]


def test_the_route_is_registered_before_the_spa_catch_all(tmp_path):
    """`mount_frontend` mounts the SPA at "/", so a route added after it is shadowed and this
    endpoint would answer with the app shell instead of JSON. Registration order is load-bearing.

    Unconditional, and driven from a temp dist so the SPA is mounted whether or not this machine
    has ever run `npm run build`."""
    paths = _routes_with_a_spa_mounted(tmp_path)

    assert "" in paths, "the probe did not mount a SPA, so it proves nothing about the order"
    assert "/api/cpi-display" in paths, paths
    assert paths.index("/api/cpi-display") < paths.index(""), (
        "the endpoint is registered after the SPA catch-all mount and would be shadowed"
    )


def test_the_endpoint_is_registered_after_every_other_api_route(tmp_path):
    """The same hazard for a route added later, and it is the direction that matters: `mount_frontend`
    is the last statement in the module, so anything registered after it is shadowed in production
    and invisible here. Asserting the CPI route is the LAST `/api/` route makes a future route
    added below the mount fail here instead of shipping."""
    paths = _routes_with_a_spa_mounted(tmp_path)
    api_routes = [p for p in paths if isinstance(p, str) and p.startswith("/api/")]

    assert api_routes[-1] == "/api/cpi-display", api_routes
    assert paths.index(api_routes[-1]) < paths.index("")
