"""A CPI market that stopped being tradeable before its `expires_at`.

`remove_closed_cpi_edges` deleted every `cpi_nowcast` row whose `expires_at` had passed, on every
hourly scan. That predicate knows about exactly one way a market stops being tradeable: the clock
reaching the close that was recorded when the row was written. A market DELISTED or VOIDED before
that close never satisfies it, so its row stayed -- and it stayed on a page whose reader-facing copy
(`RETENTION_SENTENCE`, market_sentiment_tool/src/components/WithheldEdgesNotice.tsx) says a row is
"kept while its market is still open and is deleted when that market closes".

The fix is on the predicate side, not the copy side, and this file is why that is defensible:

* the copy is true for every row that reaches the reader today, so softening it would trade a true
  sentence for a weaker one, and
* the page's list is supposed to be actionable history. A row for a market nobody can trade is not,
  and it also occupies a permanent slot in a table the board reads a bounded window of -- so it
  pushes real rows out of view.

The last test in this file is the one that matters most: it reads the COPY out of the component and
drives the PREDICATE through the three states the copy has to be true of, so the pair fails together
if either side drifts. A test of the predicate alone would pass while the copy overclaimed, and a
test of the copy alone would pass while the predicate leaked rows.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from tradehub.scripts import scan as scan_mod

NOW = datetime(2026, 9, 28, 13, 0, tzinfo=timezone.utc)
FRONTEND = Path(__file__).resolve().parents[1] / "market_sentiment_tool" / "src"


# ── stubs ───────────────────────────────────────────────────────────────────────

class _Query:
    """Records the chain. `in_` and `gt` are here because the liveness check uses them; `select`
    returns `rec.rows` filtered the way PostgREST would, because a stub that ignored the filters
    would let a test pass for the wrong reason."""

    def __init__(self, rec, table, *, mode="select"):
        self._rec, self._table, self._mode = rec, table, mode
        self.filters: dict = {}
        # `gt` is kept out of `filters` on purpose: a test asserting on a delete's filters would
        # then have to know it was a bound rather than an equality. Here it is a real comparison,
        # because a stub that treated it as `==` would match nothing and the test would pass for
        # the wrong reason.
        self.gt_bounds: dict = {}
        self.ops: list[str] = []
        self.row_limit: int | None = None

    def select(self, *_a):
        self.ops.append("select")
        return self

    def delete(self):
        self.ops.append("delete")
        self._mode = "delete"
        return self

    def eq(self, key, value):
        self.ops.append("eq")
        self.filters[key] = value
        return self

    def lte(self, key, value):
        self.ops.append("lte")
        self.filters[key] = value
        return self

    def gt(self, key, value):
        self.ops.append("gt")
        self.gt_bounds[key] = value
        return self

    def in_(self, key, values):
        self.ops.append("in_")
        self.filters[key] = list(values)
        return self

    def limit(self, n):
        self.ops.append("limit")
        self.row_limit = n
        return self

    def execute(self):
        self._rec.calls.append({"table": self._table, "mode": self._mode, "ops": list(self.ops),
                                "filters": dict(self.filters), "gt": dict(self.gt_bounds),
                                "limit": self.row_limit})
        if self._mode == "delete":
            self._rec.deleted.append(dict(self.filters))
            return type("R", (), {"data": None})()
        rows = list(self._rec.rows)
        for key, value in self.filters.items():
            if key == "market_id" and isinstance(value, list):
                rows = [r for r in rows if r.get(key) in value]
            else:
                rows = [r for r in rows if r.get(key) == value]
        # ISO-8601 with a uniform offset, so a lexicographic comparison agrees with a chronological
        # one -- the same simplification the CPI display's fake used to make.
        for key, value in self.gt_bounds.items():
            rows = [r for r in rows if str(r.get(key) or "") > str(value)]
        if self.row_limit is not None:
            rows = rows[: self.row_limit]
        return type("R", (), {"data": rows})()


class _RecordingClient:
    def __init__(self, rows=()):
        self.calls: list[dict] = []
        self.deleted: list[dict] = []
        self.rows = list(rows)

    def table(self, name):
        return _Query(self, name)


def _cpi_row(market_id: str, *, expires_at: str, engine: str = "cpi_nowcast") -> dict:
    return {"market_id": market_id, "engine": engine, "expires_at": expires_at}


def _http_error(status: int) -> Exception:
    """A `requests.HTTPError` shape: `fetch_market` raises via `raise_for_status`, so the only
    thing the cleanup can know about a failure is what is on the exception."""
    exc = RuntimeError(f"HTTP {status}")
    exc.response = type("R", (), {"status_code": status})()
    return exc


def _open(market: dict) -> dict:
    return {"market": {"ticker": "X", "status": "open", **market}}


# ── the three states a market can be in, and what the predicate does about them ──

def test_a_market_that_closed_before_its_expires_at_is_still_deleted():
    """The original behaviour, unchanged. The regression guard for the half that already worked."""
    client = _RecordingClient(rows=[_cpi_row("CLOSED", expires_at="2026-09-28T12:25:00+00:00")])

    scan_mod.remove_closed_cpi_edges(client, NOW)

    assert client.deleted == [{"engine": "cpi_nowcast", "expires_at": "2026-09-28T13:00:00+00:00"}]


def test_a_market_delisted_before_its_expires_at_is_deleted_by_ticker_not_by_the_clock():
    """The defect. `expires_at` is the close recorded when the row was written and nothing rewrites
    it, so this market's row satisfies `expires_at <= now` for some time yet -- and in the meantime
    it is a row on the board for a trade that can no longer be placed."""
    client = _RecordingClient(rows=[])

    scan_mod.remove_closed_cpi_edges(client, NOW, not_open={"KXCPI-26OCT-T0.3"})

    # A second, engine-scoped, atomic statement -- not a second pass over a SELECT.
    assert len(client.deleted) == 2, client.deleted
    ticker_delete = client.deleted[1]
    assert ticker_delete["engine"] == "cpi_nowcast"
    assert ticker_delete["market_id"] == ["KXCPI-26OCT-T0.3"]
    assert "expires_at" not in ticker_delete, "the clock predicate is the OTHER delete, not this one"


def test_a_market_that_is_still_open_is_not_deleted():
    """The other direction, and the one a delete-by-absence implementation gets wrong. A market
    that is tradeable must survive, or this stops being lifecycle cleanup and starts being hiding."""
    client = _RecordingClient(rows=[])

    scan_mod.remove_closed_cpi_edges(client, NOW, not_open=set())

    assert [d for d in client.deleted if "market_id" in d] == []


def test_the_ticker_delete_is_skipped_entirely_when_nothing_is_not_open():
    """The ordinary hourly scan still issues one statement.

    `test_remove_closed_cpi_edges_is_one_atomic_delete` in tests/test_scan_cpi.py asserts no SELECT
    and exactly one DELETE for a plain call, and this is the same property seen from the other side:
    a second statement on every scan, forever, to delete nothing, is not free.
    """
    client = _RecordingClient(rows=[])

    scan_mod.remove_closed_cpi_edges(client, NOW, not_open=set())
    assert len(client.deleted) == 1

    client = _RecordingClient(rows=[])
    scan_mod.remove_closed_cpi_edges(client, NOW, not_open=["", None])
    assert len(client.deleted) == 1, "empty and absent tickers are not a reason to query"


def test_the_ticker_delete_deduplicates_and_sorts_so_the_statement_is_reproducible():
    client = _RecordingClient(rows=[])

    scan_mod.remove_closed_cpi_edges(client, NOW, not_open={"B", "A", "A"})

    assert client.deleted[1]["market_id"] == ["A", "B"]


# ── where the not-open set comes from, and when it is allowed to be empty ───────

def test_a_404_from_kalshi_counts_as_not_open():
    """What a delisting looks like from here: the ticker is not in the API any more.

    A 404 is positive evidence that the market is gone, which is the only kind of evidence this
    cleanup is allowed to act on.
    """
    def fetch(ticker):
        raise _http_error(404)

    client = _RecordingClient(rows=[_cpi_row("GONE", expires_at="2026-10-01T00:00:00+00:00")])

    assert scan_mod.cpi_markets_not_open(client, NOW, fetch) == frozenset({"GONE"})


def test_a_market_that_resolves_with_a_non_open_status_counts_as_not_open():
    """A voided market may still be listed, with a status that is not `open`."""
    def fetch(ticker):
        return _open({"status": "closed"}) if ticker == "VOIDED" else _open({})

    client = _RecordingClient(rows=[
        _cpi_row("VOIDED", expires_at="2026-10-01T00:00:00+00:00"),
        _cpi_row("TRADEABLE", expires_at="2026-10-01T00:00:00+00:00"),
    ])

    assert scan_mod.cpi_markets_not_open(client, NOW, fetch) == frozenset({"VOIDED"})


def test_a_rate_limit_or_a_timeout_is_not_evidence_and_leaves_the_row_alone():
    """The failure direction, and the reason the function returns a set instead of raising.

    Not knowing is not the same as knowing a market is gone, and the two must not share an
    expression. Anything that is not a 404 and not a status leaves the row for an hour, which is
    the pre-existing behaviour -- and is the right thing for a cleanup to do when it is unsure.
    """
    def fetch(ticker):
        raise _http_error(429)

    client = _RecordingClient(rows=[_cpi_row("A", expires_at="2026-10-01T00:00:00+00:00")])

    assert scan_mod.cpi_markets_not_open(client, NOW, fetch) == frozenset()


def test_an_unparseable_payload_leaves_the_row_alone():
    """A market we cannot read a status out of is a market we know nothing about."""
    for payload in ({}, {"market": None}, {"market": {}}, {"market": {"status": 7}}, None):
        client = _RecordingClient(rows=[_cpi_row("A", expires_at="2026-10-01T00:00:00+00:00")])
        assert scan_mod.cpi_markets_not_open(client, NOW, lambda _t, p=payload: p) == frozenset(), payload


def test_a_failed_read_of_the_rows_itself_is_also_not_evidence():
    client = _RecordingClient()
    client.table = lambda _name: (_ for _ in ()).throw(RuntimeError("supabase down"))

    assert scan_mod.cpi_markets_not_open(client, NOW, lambda _t: _open({})) == frozenset()


def test_it_only_asks_about_rows_whose_close_has_not_passed_and_never_asks_unbounded():
    """The request count cannot grow with the size of the table.

    The rows past `expires_at` are already gone by the time this runs, and they are exactly the ones
    there is no question about. `limit` is on the query for the same reason: a cleanup that asks
    Kalshi about 5,000 tickers an hour is a way to be taken offline, and the only thing the bound
    can cost is one more hour for the rows past it.
    """
    client = _RecordingClient(rows=[_cpi_row("A", expires_at="2026-10-01T00:00:00+00:00")])

    scan_mod.cpi_markets_not_open(client, NOW, lambda _t: _open({}))

    read = client.calls[0]
    assert read["mode"] == "select"
    assert read["filters"]["engine"] == "cpi_nowcast"
    assert read["ops"].count("gt") == 1
    assert read["gt"]["expires_at"] == NOW.isoformat()
    assert read["limit"] == scan_mod.CPI_LIVENESS_CHECK_LIMIT
    # And it really excludes a row whose close has passed, rather than only recording the filter.
    past = _RecordingClient(rows=[_cpi_row("OLD", expires_at="2026-01-01T00:00:00+00:00")])
    asked: list[str] = []
    scan_mod.cpi_markets_not_open(past, NOW, lambda t: (asked.append(t), _open({}))[1])
    assert asked == [], "it asked about a market that has already been deleted by the clock delete"


def test_main_passes_the_liveness_set_through_and_a_liveness_failure_does_not_fail_the_scan(
    monkeypatch, capsys,
):
    """`main()` must call it with the set, and a Kalshi problem must not turn an hourly scan red.

    The cleanup is best-effort for delisted markets: a failure costs the cleanup for an hour and
    deletes nothing, which is the same state as before this change. A scan that reported partial
    failure every hour because of it would be crying wolf, and the real failures would be lost.

    Everything is patched through `monkeypatch` rather than reassigned, because this file's other
    tests drive the REAL `remove_closed_cpi_edges` -- and a stub left installed on the module would
    silently answer for them.
    """
    import tradehub.core.supabase_client as supabase_client
    import tradehub.predictions as predictions

    seen: list[frozenset] = []

    def boom(*_a, **_k):
        raise RuntimeError("kalshi unreachable")

    def closed(client, now, *, not_open=()):
        seen.append(frozenset(not_open))

    def fetch(*_a, **_k):
        # `main()` resolves the fetcher from the module, so the failure has to be injected there.
        raise RuntimeError("kalshi unreachable")

    monkeypatch.setattr(scan_mod, "fetch_market", fetch)
    monkeypatch.setattr(scan_mod, "remove_closed_cpi_edges", closed)
    monkeypatch.setattr(scan_mod, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan_mod, "scan_weather", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan_mod, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan_mod, "scan_cpi", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan_mod, "cpi_scan_due", lambda now: False)
    monkeypatch.setattr(scan_mod, "sports_due", lambda now: False)
    monkeypatch.setattr(scan_mod, "latest_gate_statuses", lambda client, pairs: {})
    monkeypatch.setattr(scan_mod, "remove_stale_edges", lambda client, produced: None)
    monkeypatch.setattr(scan_mod, "remove_closed_labor_edges", lambda *a, **k: None)
    monkeypatch.setattr(supabase_client, "get_client", lambda: object())
    monkeypatch.setattr(predictions, "record_predictions", lambda *a, **k: None)

    class _Unreadable:
        def table(self, _name):
            raise RuntimeError("no such table")

    rc = scan_mod.main(now=NOW, live=object(), client=_Unreadable())

    assert rc == 0, "a Kalshi problem must not be a scan failure"
    assert seen == [frozenset()], "the cleanup still runs, with nothing to add to its predicate"
    summary = json.loads(capsys.readouterr().out)
    assert not [f for f in summary.get("failures", []) if "liveness" in f or "closed_cleanup" in f], (
        summary.get("failures")
    )


# ── the invariant: the copy and the predicate are one claim ────────────────────

def _retention_sentence() -> str:
    """The reader-facing claim, read out of the component that renders it.

    Read from the source rather than retyped, because a retyped copy is a second copy and the
    failure being guarded is precisely that they stop agreeing.
    """
    source = (FRONTEND / "components" / "WithheldEdgesNotice.tsx").read_text()
    block = re.search(r"export const RETENTION_SENTENCE =(.*?);\n", source, re.DOTALL)
    assert block, "RETENTION_SENTENCE is gone: the copy no longer states what happens to a row"
    literal = block.group(1)
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', literal)
    return "".join(parts)


def test_the_retention_copy_and_the_delete_that_bounds_it_are_one_claim():
    """THE invariant. If either side drifts, this fails.

    The copy asserts two things: a row is kept while its market is still open, and it is deleted when
    that market closes. Each clause is driven against the predicate below, so:

    * weaken the copy to "kept while its market is still open" and the second clause's assertion on
      the copy fails -- which is the softening this task explicitly rejected;
    * change the copy back to "the rows are not deleted" and the bounded-clause assertion fails;
    * drop the ticker delete and the third state -- delisted before its close, which the copy does
      not name and the page therefore must not be able to show -- fails;
    * drop the clock delete and the closed-market clause fails.

    Neither fact alone is testable in a way that means anything. A predicate test cannot see the
    sentence, and a sentence test cannot see the rows.
    """
    copy = _retention_sentence()
    lowered = copy.lower()

    # ── the copy: both clauses, and neither of the phrasings it must never be
    assert "still open" in lowered, f"the copy no longer bounds the keeping: {copy!r}"
    assert "when that market closes" in lowered, (
        f"the copy no longer promises the delete, so it has been softened: {copy!r}"
    )
    for phrase in ("not deleted", "never deleted", "permanently kept"):
        assert phrase not in lowered, f"the copy drifted back to an overclaim: {phrase!r}"

    # ── clause 1: "kept while its market is still open"
    # A tradeable market with a future close is not touched by either delete.
    open_client = _RecordingClient(rows=[_cpi_row("TRADEABLE", expires_at="2026-10-05T00:00:00+00:00")])
    assert scan_mod.cpi_markets_not_open(open_client, NOW, lambda _t: _open({})) == frozenset()
    scan_mod.remove_closed_cpi_edges(open_client, NOW, not_open=frozenset())
    assert not [d for d in open_client.deleted if "market_id" in d], (
        "a market that is still open was deleted, so the copy's first clause is false"
    )
    assert open_client.deleted[0]["expires_at"] == "2026-09-28T13:00:00+00:00", (
        "the clock predicate is still there, and is still the only thing that reaches a closed market"
    )

    # ── clause 2: "deleted when that market closes"
    closed_client = _RecordingClient(rows=[_cpi_row("CLOSED", expires_at="2026-09-28T12:00:00+00:00")])
    scan_mod.remove_closed_cpi_edges(closed_client, NOW, not_open=frozenset())
    assert closed_client.deleted == [
        {"engine": "cpi_nowcast", "expires_at": "2026-09-28T13:00:00+00:00"}
    ], "a closed market's row survives, so the copy's second clause is false"

    # ── the state the copy does not name, and therefore must not be able to reach the reader
    delisted_client = _RecordingClient(rows=[_cpi_row("DELISTED", expires_at="2026-10-05T00:00:00+00:00")])

    def gone(_ticker):
        raise _http_error(404)

    not_open = scan_mod.cpi_markets_not_open(delisted_client, NOW, gone)
    assert not_open == frozenset({"DELISTED"})
    scan_mod.remove_closed_cpi_edges(delisted_client, NOW, not_open=not_open)
    assert [d for d in delisted_client.deleted if d.get("market_id") == ["DELISTED"]], (
        "a delisted market's row survives to its scheduled close, so the page is showing a trade "
        "that can no longer be placed -- and the copy's 'kept while its market is still open' is "
        "false for a window it does not name"
    )
    # ...and it is only deleted because Kalshi said so, never because it was missing from a list.
    assert delisted_client.rows[0]["expires_at"] == "2026-10-05T00:00:00+00:00"


def test_the_copy_still_says_the_rows_survive_only_as_long_as_the_market_was_open():
    """The reason the third state has to be deleted rather than ignored.

    The sentence promises the record survives "for as long as the market it measured was open". A
    market that is delisted was open and then stopped being open, and a row that outlives that is a
    record surviving past the window the sentence named -- so the page is showing history nobody
    could have acted on, for ever, on a table it reads a bounded window of.
    """
    copy = _retention_sentence().lower()
    assert "for as long as the market it measured was open" in copy, copy
    # A predicate that deleted nothing for a delisted market would not make this false, but it would
    # make it hollow -- so the sentence is asserted together with the delete, above. Here we only
    # pin that the sentence has not been rewritten into something the delete cannot support.
    assert "close to act on" in copy or "was open" in copy, copy
