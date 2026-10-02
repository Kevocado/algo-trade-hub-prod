"""CPI must stop presenting itself as an edge.

Approved 2026-09-27 as DISPLAY ONLY, on the evidence in spec section 5a: the market's Brier at 5 days
out (0.0710) is barely worse than at 25 minutes (0.0677), so Kalshi prices CPI about as accurately a
week ahead as it does in the last half hour. The market is not pricing off the Cleveland Fed
nowcast at all, so a nowcast-based model has nothing to exploit by being early. At every lead we are
1.33-1.43x behind, and P&L is negative at every lead.

So the fix is presentational, not analytical. The `predictions` row is correct and stays -- it is what
carries the nowcast, our probability and the market mid, i.e. exactly the context the display needs,
and it is what keeps the oracle-bound analysis in 5a reproducible. The `edges` row is what tells a
reader "here is an opportunity", and that claim is not supported.

THE POINT OF THIS FILE is that it asserts on what the scan TRIED TO WRITE, not on a return value.
A test that only checked the `edges` list would be a test of the shape of a return, and it would
pass just as happily if some other route built the edge. So the tests below drive `scan_cpi` and
`scan.main()` against a recording Supabase stub and assert on the rows that reached the writer.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradehub.core import supabase_client
from tradehub.data.cleveland_fed import parse_nowcast_month
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.engine_config import EngineConfig
from tradehub.markets import parse_cpi_market
from tradehub.scripts import scan

PAYLOAD = json.loads((Path(__file__).parent / "fixtures" / "cleveland_nowcast_month_trimmed.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 9, 11, 12, 5, tzinfo=timezone.utc)  # 08:05 EDT, the last run before the 08:25 close
CFG = EngineConfig(min_edge_pct=5.0, prefer_maker=True, params={"train_months": 24.0, "use_bias": 0.0})

# A strike the model rates at ~0.52 against a 0.30/0.34 quote -- a wide, clear disagreement. Under
# the old code this produced an edge, and it is what makes these tests fail before the change rather
# than pass vacuously. If this input ever stops being edge-worthy the whole file is toothless, so
# `test_the_fixture_would_have_produced_an_edge` pins that it still is.
LM = ("KXCPI", 0.3, "26AUG", "2026-09-11T12:25:00Z", 0.30, 0.34)


def _lm(series=None, strike=None, month=None, close=None, bid=None, ask=None):
    default_series, default_strike, default_month, default_close, default_bid, default_ask = LM
    series = series or default_series
    return LiveMarket(
        parse_cpi_market({
            "ticker": f"{series}-{month or default_month}-T{strike if strike is not None else default_strike}",
            "event_ticker": f"{series}-{month or default_month}", "strike_type": "greater",
            "floor_strike": strike if strike is not None else default_strike,
            "open_time": "2026-07-23T21:00:00Z", "close_time": close or default_close,
            "title": f"{series} {strike}",
        }),
        Quote(yes_bid=default_bid if bid is None else bid, yes_ask=default_ask if ask is None else ask,
              yes_bid_size=50.0, yes_ask_size=50.0),
    )


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def _nowcast_fn(calls=None):
    def fn(kind):
        if calls is not None:
            calls.append(kind)
        return parse_nowcast_month(PAYLOAD, kind)
    return fn


def _scan():
    return scan.scan_cpi(FakeLive([_lm()]), NOW, CFG, nowcast_fn=_nowcast_fn())


# ── the writer ───────────────────────────────────────────────────────────────────────────────────

def test_cpi_writes_no_edges():
    """The whole point. `edges` is what presents CPI as an opportunity, and the evidence does not
    support that claim."""
    predictions, edges = _scan()

    assert edges == [], f"CPI must not write edges; it is display-only, got {len(edges)}"


def test_cpi_still_writes_its_prediction_with_the_nowcast_and_the_market_mid():
    """Deleting the edge must not delete the measurement. The display view reads this row, and the
    oracle-bound analysis in spec 5a has to stay reproducible from it."""
    predictions, _ = _scan()

    assert predictions, "the nowcast context is the product; it must survive"
    row = predictions[0]
    assert row["engine"] == "cpi_nowcast"
    assert 0.0 <= row["our_prob"] <= 1.0
    assert 0.0 <= row["market_prob"] <= 1.0
    # The three quantities the display view renders. If any of them stopped being recorded, the
    # page would be showing a number it does not have.
    assert row["raw_payload"]["nowcast"] == pytest.approx(0.359180537639179)
    assert row["raw_payload"]["sigma"] > 0
    # The market mid is measured, not derived: it is the quote mid at decision time.
    assert row["market_prob"] == pytest.approx(0.32, abs=1e-4)


def test_the_prediction_carries_no_gate_status_and_could_not_read_as_promoted():
    """Fails closed -- and the real shape is stronger than the plan assumed.

    The plan's version of this test asserted `predictions[0]["gate_status"] == "SHADOW"`. There is
    no such key: `build_prediction_row` (tradehub/predictions.py:40-50) returns market_ticker,
    our_prob, market_prob, engine, engine_version, as_of, status and raw_payload, and the
    `predictions` table has no `gate_status` column at all -- the one in
    20260416000003_predictions_ledger.sql:43 belongs to `track_record`. So that assertion would
    have raised KeyError, not passed.

    The claim itself is sound and is asserted in the form that is actually true: a prediction row
    carries no gate field, so it cannot claim promotion, and the only thing that can carry a
    PROMOTED status is an edge row -- of which CPI now writes none. A reader therefore cannot see
    a promoted CPI anything, which is the property the approval needs.
    """
    row = _scan()[0][0]

    assert "gate_status" not in row, (
        f"a prediction row must not carry a gate status; it could be read as promoted: {sorted(row)}"
    )
    # The gate lives on the edge, and the only engine that marks one is main()'s apply_gate_statuses.
    assert not [e for e in _scan()[1] if e.get("gate_status") == "PROMOTED"]


def test_the_prediction_records_no_edge_figure():
    """A prediction row must not carry an edge. If one ever did, a reader could compute one, and
    the display view would have an edge number to show on an engine that has none."""
    row = _scan()[0][0]

    assert "edge" not in row and "edge_pct" not in row, (
        f"a prediction row must not carry an edge: {sorted(row)}"
    )


def test_the_fixture_would_have_produced_an_edge():
    """Guards the whole file from going toothless.

    Every assertion above is only meaningful if this input is one the old code turned into an edge.
    If the engine is retuned, the strike drifts or the nowcast moves so that no disagreement remains,
    these tests would keep passing while `edges.append` was restored and CPI was once again
    presented as an opportunity. So the disagreement is asserted directly."""
    from tradehub.edges import evaluate_edge

    row = _scan()[0][0]
    suggestion = evaluate_edge(_lm().market.ticker, row["our_prob"], _lm().quote,
                               min_edge_pct=CFG.min_edge_pct, prefer_maker=CFG.prefer_maker)

    assert suggestion is not None, (
        "this fixture no longer produces an edge, so the no-edges assertions are vacuous; "
        "pick a strike/quote pair that the model clearly disagrees with"
    )


def test_it_is_the_edge_that_is_gone_and_not_the_measurement():
    """The prediction is a strictly larger record than the edge was: it carries the nowcast, the
    model probability, the market mid, the fitted sigma and the hours to close. Nothing measured
    was dropped along with the opportunity claim."""
    row = _scan()[0][0]

    assert {"nowcast", "nowcast_obs", "bias", "sigma", "n_train", "hours_to_close"} <= set(row["raw_payload"])
    assert row["raw_payload"]["hours_to_close"] > 0


def test_both_cpi_series_are_stopped_not_just_headline():
    """The edge writer was inside the loop over CPI_TARGETS, so it covered KXCPICORE as well as
    KXCPI. A fix that only handled the headline series would leave core CPI presenting as an edge."""
    live = FakeLive([_lm("KXCPI", 0.3), _lm("KXCPICORE", 0.2)])

    predictions, edges = scan.scan_cpi(live, NOW, CFG, nowcast_fn=_nowcast_fn())

    assert {p["engine_version"] for p in predictions} == {"cpi-v1", "cpi-core-v1"}
    assert edges == [], f"both CPI series must stop writing edges, got {len(edges)}"


def test_the_return_shape_is_unchanged_because_main_still_unpacks_two_lists():
    """main() does `predictions, edges = scan_cpi(...)`. The tuple must stay a 2-tuple: a change
    to one element would raise at the call site, in a try/except that reports the engine as FAILED
    and prunes nothing -- a silent way to lose the predictions too."""
    result = _scan()

    assert isinstance(result, tuple) and len(result) == 2
    assert all(isinstance(part, list) for part in result)


def test_a_market_without_a_nowcast_still_produces_neither_row():
    """Unchanged behaviour on the skip path, checked because it is the path that also skips the
    edge write: a "no nowcast" market must not be counted as evidence that edges are gone."""
    assert scan.scan_cpi(FakeLive([_lm(month="26OCT")]), NOW, CFG, nowcast_fn=_nowcast_fn()) == ([], [])


# ── the reader: the standing rule that holds once the writer is gone ────────────────────────────

def test_the_historical_cpi_edges_are_not_pruned_by_the_absence_of_a_writer():
    """Ruling 1, and the reason this task is not one line.

    `main()` feeds each engine's produced tickers to `remove_stale_edges`, which deletes any row
    whose market is not in the produced set. CPI now produces NOTHING, so an engine still in the
    prune allowlist would have every historical cpi_nowcast row deleted on the next due scan --
    which is a migration by omission, silently, from code that looks like cleanup.

    The ruling is: keep the rows (they are a record of what the scan did), and stop presenting
    them at the read. So the prune must not reach CPI.
    """
    rows = [{"market_id": "KXCPI-26AUG-T0.3", "engine": "cpi_nowcast"}]
    client = _RecordingClient(rows=rows)

    scan.remove_stale_edges(client, {"cpi_nowcast": set()})

    assert not client.deleted, (
        "the absent writer pruned the historical CPI edges; that is a silent migration, and the "
        "ruling is to keep the rows and stop presenting them at the read"
    )
    assert rows, "the rows must survive to be filtered at the read"


def test_the_prune_still_reaches_every_other_scan_owned_engine():
    """The counterweight to the test above. A guard that works by disabling the prune would be a
    far worse bug than the one it prevents, so this pins that CPI was excluded and nothing else."""
    rows = [
        {"market_id": "W", "engine": "weather"},
        {"market_id": "G", "engine": "gas"},
        {"market_id": "L", "engine": "labor_nowcast"},
        {"market_id": "N", "engine": "sports_nfl"},
        {"market_id": "C", "engine": "sports_cfb"},
        {"market_id": "CPI", "engine": "cpi_nowcast"},
        {"market_id": "other", "engine": "crypto"},
    ]
    client = _RecordingClient(rows=rows)

    scan.remove_stale_edges(client, {e: set() for e in ("weather", "gas", "labor_nowcast",
                                                        "sports_nfl", "sports_cfb", "cpi_nowcast")})

    assert sorted(c["engine"] for c in client.deleted) == [
        "gas", "labor_nowcast", "sports_cfb", "sports_nfl", "weather",
    ], f"the prune must reach every engine except CPI, got {client.deleted}"


def test_a_closed_cpi_edge_is_still_deleted_because_its_market_is_gone():
    """`remove_closed_cpi_edges` is lifecycle cleanup, not hiding: a row whose market has closed
    describes nothing anyone can act on. It must survive this change, or closed CPI rows would
    accumulate for ever and crowd the 100-row read."""
    client = _RecordingClient(rows=[{"market_id": "old", "expires_at": "2026-09-01T12:25:00+00:00"}])

    scan.remove_closed_cpi_edges(client, datetime(2026, 9, 11, 12, 5, tzinfo=timezone.utc))

    assert client.deleted == [{"engine": "cpi_nowcast", "expires_at": "2026-09-11T12:05:00+00:00"}]


def test_the_cpi_delete_is_run_on_every_scan_which_is_what_bounds_the_retention_claim():
    """Why the on-screen copy is qualified, pinned from the Python side.

    `remove_closed_cpi_edges` is not a once-a-while tidy-up: `main()` calls it on every hourly scan,
    and the predicate is `expires_at <= now` PLUS the tickers Kalshi reports are no longer open --
    the second because a market delisted before its close never satisfies the first, and a row that
    survives that is a trade nobody can place sitting on a page that promises otherwise. So a
    `cpi_nowcast` row is deleted within the hour its market stops being open -- which is why the UI
    may not say "the rows are not deleted", and says the bounded thing instead. If this ever stops
    being true the UI copy becomes conservative rather than wrong, which is the safe direction to be
    wrong in; the reverse is not.

    The literal is a call site, so it also pins that the delete is handed the liveness set: a
    `remove_closed_cpi_edges(client, now)` that quietly dropped the second predicate would satisfy a
    weaker version of this assertion, and would be the defect tests/test_cpi_delisted_cleanup.py
    exists to catch.
    """
    import inspect

    main_source = inspect.getsource(scan.main)

    assert "remove_closed_cpi_edges(client, now, not_open=not_open)" in main_source, (
        "the closed-market delete must still run on every scan: it is what bounds the retention "
        "claim the UI makes, and dropping it would let the rows accumulate for ever"
    )
    assert "cpi_markets_not_open(client, now, fetch_market)" in main_source, (
        "the delisted-market set has to be computed on the same scan, or the second predicate is "
        "never handed anything and a market delisted before its close keeps its row"
    )


# ── the end-to-end claim: what the scan actually wrote ───────────────────────────────────────────

def test_a_full_scan_writes_no_cpi_prediction_row_and_upserts_no_cpi_edge(monkeypatch, capsys):
    """The end-to-end version, and the one that would catch an edge built by any route.

    Drives `scan.main()` with the REAL `scan_cpi` (not a stub) and a recording Supabase stub, then
    asserts on the rows that reached the writer. CPI is a journal engine (plan 14): the journal owns its
    forecasts, so no `predictions` row is written for it, and it still never reaches `kalshi_edges`.
    """
    client, upserted, pruned = _run_main(monkeypatch)

    assert not [r for r in client.inserted if r.get("engine") == "cpi_nowcast"], (
        f"CPI is a journal engine and must not write predictions; got {client.inserted}"
    )

    assert not [r for r in upserted if r.get("engine") == "cpi_nowcast"], (
        f"CPI must not reach kalshi_edges; got {upserted}"
    )
    assert "cpi_nowcast" in pruned, (
        "main() must still account for CPI in its cleanup, or a CPI failure stops being visible"
    )
    assert pruned["cpi_nowcast"] == set(), "the produced set is empty by design"


def test_a_full_scan_does_not_prune_the_cpi_rows_the_absent_writer_leaves_behind(monkeypatch):
    """The half of Ruling 1 that only shows up end-to-end.

    `main()` calls the prune with CPI's empty produced set, so THIS is where a silent delete would
    actually happen. Testing `remove_stale_edges` in isolation does not prove the behaviour survives
    the real call path -- a future edit to the cleanup loop in `main()` would keep the unit test
    green while the rows went on being deleted every due scan.
    """
    client, upserted, pruned = _run_main(monkeypatch)

    assert pruned["cpi_nowcast"] == set(), "precondition: CPI produced no edges to keep"

    # Two different CPI deletes exist and only one of them is the bug. `remove_closed_cpi_edges`
    # deletes by `expires_at` and is correct -- a row whose market closed describes nothing
    # actionable. The prune deletes by `market_id`, and that is the one that would have eaten the
    # historical rows by omission. They are told apart by the filter, not by a blanket ban.
    prune_deletes = [c for c in client.deleted
                     if c.get("engine") == "cpi_nowcast" and "market_id" in c]
    assert not prune_deletes, (
        f"the absent writer deleted the historical CPI edges through main(): {prune_deletes}"
    )
    assert not [r for r in client.inserted if r.get("engine") == "cpi_nowcast"], "CPI writes no predictions now"


# ── stubs ───────────────────────────────────────────────────────────────────────────────────────

class _RecordingQuery:
    def __init__(self, rec, table, *, mode="select"):
        self._rec, self._table, self._mode = rec, table, mode
        self.filters: dict = {}
        self.ops: list[str] = []

    def select(self, *_a):
        self.ops.append("select")
        return self

    def delete(self):
        self.ops.append("delete")
        self._mode = "delete"
        return self

    def insert(self, rows):
        self.ops.append("insert")
        self._rec.inserted.extend(rows if isinstance(rows, list) else [rows])
        return self

    def eq(self, key, value):
        self.ops.append("eq")
        self.filters[key] = value
        return self

    def lte(self, key, value):
        self.ops.append("lte")
        self.filters[key] = value
        return self

    def execute(self):
        self._rec.calls.append({"table": self._table, "mode": self._mode, "ops": list(self.ops),
                                "filters": dict(self.filters)})
        if self._mode == "delete":
            self._rec.deleted.append(dict(self.filters))
            return type("R", (), {"data": None})()
        # Honour the recorded filters the way PostgREST does. A stub that returned every row for
        # every engine would let one engine's prune delete another's rows, and the test would pass
        # for the wrong reason.
        matched = [row for row in self._rec.rows
                   if all(row.get(k) == v for k, v in self.filters.items())]
        return type("R", (), {"data": matched})()


class _RecordingClient:
    """Records the real chain. `predictions` inserts and `kalshi_edges` deletes are both captured,
    so a test can assert on what the scan tried to write rather than on what it returned."""

    def __init__(self, rows=()):
        self.calls: list[dict] = []
        self.deleted: list[dict] = []
        self.inserted: list[dict] = []
        self.rows = list(rows)

    def table(self, name):
        return _RecordingQuery(self, name)


def _run_main(monkeypatch):
    """Drive scan.main() with the real scan_cpi and a recording Supabase stub.

    Returns the recording, the edge rows upserted, and the produced-by-engine the prune was handed.
    """
    client = _RecordingClient(rows=[{"market_id": "KXCPI-26AUG-T0.3", "engine": "cpi_nowcast"}])
    upserted: list[dict] = []
    pruned: dict[str, set[str]] = {}
    real_prune = scan.remove_stale_edges

    def prune(rec_client, produced_by_engine):
        for name, produced in produced_by_engine.items():
            pruned[name] = set(produced)
        real_prune(rec_client, produced_by_engine)

    monkeypatch.setattr(scan, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan, "scan_weather", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "cpi_scan_due", lambda now: True)
    monkeypatch.setattr(scan, "sports_due", lambda now: False)
    monkeypatch.setattr(scan, "labor_scan_due", lambda now: False)
    monkeypatch.setattr(scan, "remove_started_sports_edges", lambda *a, **k: [])
    monkeypatch.setattr(scan, "latest_gate_statuses", lambda *a, **k: {})
    monkeypatch.setattr(scan, "remove_stale_edges", prune)
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: upserted.extend(rows))
    # `record_predictions` is NOT stubbed either. It is the real writer, so the rows it inserts
    # reach the recording client through `supa.table("predictions").insert(...)` and can be
    # asserted on. Stubbing it out is what made the "it still writes" claim untestable.
    # `scan_cpi` is likewise NOT stubbed: the point is the real engine against a stubbed client.
    monkeypatch.setattr(scan, "fetch_nowcast_history", lambda kind: parse_nowcast_month(PAYLOAD, kind))
    # `scan.main` calls `load_local_env()` at run time, so a garbage `.env` in the repo root puts its
    # keys into this process and the ALFRED fetches then see `FRED_API_KEY=not-a-real-key...`. That is
    # a genuine order-dependency -- the results depend on which test ran first -- and stubbing the
    # loader removes it without touching what this file is asserting.
    import tradehub.core.env as core_env
    monkeypatch.setattr(core_env, "load_local_env", lambda *a, **k: False)

    assert scan.main(now=NOW, live=FakeLive([_lm()]), client=client) == 0
    return client, upserted, pruned


def test_the_scan_reports_zero_cpi_edges_in_its_summary(monkeypatch, capsys):
    """The operator-facing claim. The summary is what a cron reader sees, and it would still say
    `edges: 0` for the wrong reason if the engine had silently failed into that zero."""
    _run_main(monkeypatch)

    summary = json.loads(capsys.readouterr().out)
    assert summary["cpi_nowcast"]["status"] == "ok", "CPI must run, not fail into a quiet zero"
    assert summary["cpi_nowcast"]["edges"] == 0
    assert summary["cpi_nowcast"]["predictions"] > 0, "the measurement must still be reported"
    assert summary["failures"] == []
