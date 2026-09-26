"""Round 4, item 1: started games are not actually removed.

`expires_at` is the Kalshi `close_time`, which for a sports market is about TWO DAYS after
kickoff (the recorded fixture markets close 2026-09-29 for games kicking off 2026-09-27), so
`expires_at <= now` left a started game's row on the board for days. useMarketEdges.ts and
useSupabaseData.ts read `kalshi_edges` directly, so those rows were visible to the UI.

Three parts:
- `scan_sport` skips games whose `start_utc <= now`, so nothing new is written for them;
- the started rows are DELETED on an indexed, filterable `start_utc` column (migration 000008,
  still unapplied, so it is edited in place);
- `scan.main` calls the one tested function instead of an `_errors` twin of it.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "sports"

# 1h after the HOU@IND kickoff (2026-09-27T17:00Z). The DEN@LA game (00:20Z the next day) has
# not started. Every recorded market closes 2026-09-29T17:00Z, i.e. still "open" by expires_at,
# which is exactly the two-day gap that hid these rows.
NOW = datetime(2026, 9, 27, 18, 0, tzinfo=timezone.utc)
STARTED_GAMES = ("2026_03_CIN_PIT", "2026_03_HOU_IND")
STARTED_GAME = "2026_03_HOU_IND"
UPCOMING_GAME = "2026_03_LA_DEN"


def _feed(sport="nfl"):
    from tradehub.sports.feed import parse_feed
    raw = json.loads((FIXTURES / f"{sport}_kalshi_feed.json").read_text())
    for kind in ("winner", "spread", "total"):
        for b in raw["calibration"][kind]:
            mid = round(b["lo"] + 0.05, 2)
            b.update(n=40, mean_prob=mid, hit_rate=mid)
    return parse_feed(raw)


def _markets(sport="nfl"):
    from tradehub.sports.kalshi import parse_sports_market
    raw = json.loads((FIXTURES / f"{sport}_open_markets.json").read_text())
    return {s: [parse_sports_market(m) for m in ms] for s, ms in raw.items()}


# ── no new edges or predictions for a game that has started ────────────────────

def test_a_started_game_produces_no_edges_or_predictions():
    from tradehub.sports import scan as sports_scan
    from tradehub.sports.config import load_sport_config

    result = sports_scan.scan_sport(load_sport_config("nfl"), _markets("nfl"), _feed("nfl"), NOW)
    started = [r for r in result.edges if r.get("game_id") in STARTED_GAMES]
    assert started == [], (
        f"{len(started)} edges were produced for games that kicked off an hour ago: "
        f"{[e['market_ticker'] for e in started][:4]}"
    )
    assert not [p for p in result.predictions if p["raw_payload"].get("game_id") in STARTED_GAMES]
    # The game that has not started is still scanned, so this is a skip and not a failure.
    assert [e for e in result.edges if e.get("game_id") == UPCOMING_GAME], (
        "the upcoming game produced no edges; the started-game skip cost the whole sport"
    )


def test_started_games_are_reported_not_silently_dropped():
    from tradehub.sports import scan as sports_scan
    from tradehub.sports.config import load_sport_config

    result = sports_scan.scan_sport(load_sport_config("nfl"), _markets("nfl"), _feed("nfl"), NOW)
    assert result.report["games_started"] == len(STARTED_GAMES), result.report


def test_a_game_that_has_not_started_yet_is_not_skipped():
    """The boundary: exactly-at-kickoff counts as started, one second earlier does not."""
    from tradehub.sports import scan as sports_scan
    from tradehub.sports.config import load_sport_config

    feed, markets = _feed("nfl"), _markets("nfl")
    cfg = load_sport_config("nfl")
    kickoff = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)
    at_start = sports_scan.scan_sport(cfg, markets, feed, kickoff)
    assert all(e.get("game_id") != STARTED_GAME for e in at_start.edges), (
        "a game exactly at kickoff was still priced"
    )
    assert at_start.report["games_started"] == len(STARTED_GAMES), at_start.report
    one_second_early = sports_scan.scan_sport(cfg, markets, feed, kickoff - timedelta(seconds=1))
    assert one_second_early.report["games_started"] == 0, one_second_early.report
    assert [e for e in one_second_early.edges if e.get("game_id") == STARTED_GAME], (
        "a game one second before kickoff produced no edges"
    )


# ── the delete filters on the game start, not the market close ─────────────────

class _Q:
    """Query fake that keeps every filter, so a two-predicate delete is expressible."""

    def __init__(self, store):
        self.store, self.filters = store, {}

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def lte(self, col, val):
        self.filters[col] = val
        return self

    def delete(self):
        self.store.deletes += 1
        return self

    def execute(self):
        self.store.executed.append(dict(self.filters))
        if self.filters.get("engine") in self.store.fail_engines:
            raise RuntimeError(f"boom {self.filters['engine']}")
        return type("R", (), {"data": None})()


class _Store:
    def __init__(self, fail_engines=()):
        self.fail_engines = set(fail_engines)
        self.executed: list[dict] = []
        self.deletes = 0
        self.tables: list[str] = []

    def table(self, name):
        self.tables.append(name)
        return _Q(self)


def test_started_rows_are_deleted_on_start_utc_not_expires_at():
    from tradehub.sports import scan as sports_scan

    store = _Store()
    sports_scan.remove_started_sports_edges(store, NOW)
    assert len(store.executed) == 2, store.executed
    assert {d["engine"] for d in store.executed} == {"sports_nfl", "sports_cfb"}
    for filters in store.executed:
        assert "expires_at" not in filters, (
            f"the started-game delete still filters on expires_at: {filters}. For a sports "
            "market that is the Kalshi close time, about two days after kickoff."
        )
        assert filters["start_utc"] == NOW.isoformat(), filters
    assert store.deletes == 2, store.deletes
    assert set(store.tables) == {"kalshi_edges"}, store.tables


def test_a_started_game_closing_in_two_days_is_still_deleted():
    """The recorded fixture: kickoff 2026-09-27T17:00Z, market close 2026-09-29T17:00Z. The row
    is two days old and still inside expires_at, so only a start_utc predicate removes it."""
    from tradehub.sports import scan as sports_scan

    markets = _markets("nfl")
    started_market = next(m for m in markets["KXNFLGAME"] if m.market.event_ticker.endswith("HOUIND"))
    assert started_market.market.close_time > NOW + timedelta(days=1), started_market.market.close_time
    started_games = {g.game_id for g in _feed("nfl").games if g.start_utc <= NOW}
    assert STARTED_GAME in started_games
    # The predicate round 3 sent (expires_at <= now) does not match this row; the new one does.
    assert not (started_market.market.close_time <= NOW), "the fixture no longer reproduces the gap"
    an_hour_early = datetime(2026, 9, 27, 16, 0, tzinfo=timezone.utc)
    edges = sports_scan.scan_sport(_cfg(), markets, _feed("nfl"), an_hour_early).edges
    assert any(e["market_ticker"] == started_market.market.ticker and e["game_id"] == STARTED_GAME
               for e in edges), (
        "an hour before kickoff this market produced no edge, so the fixture proves nothing"
    )


def _cfg():
    from tradehub.sports.config import load_sport_config
    return load_sport_config("nfl")


def test_one_failing_sport_delete_is_isolated_and_reported():
    from tradehub.sports import scan as sports_scan

    store = _Store(fail_engines={"sports_nfl"})
    errors = sports_scan.remove_started_sports_edges(store, NOW)
    assert {d["engine"] for d in store.executed} == {"sports_nfl", "sports_cfb"}, store.executed
    assert any("sports_nfl" in e for e in errors), errors
    assert not any("sports_cfb" in e for e in errors), errors


def test_there_is_no_errors_twin_of_the_started_cleanup():
    """main used to call a second copy of the same delete. One function, tested once."""
    from tradehub.sports import scan as sports_scan

    assert not hasattr(sports_scan, "remove_started_sports_edges_errors"), (
        "an _errors twin of remove_started_sports_edges still exists; main must call the tested one"
    )
    assert callable(sports_scan.remove_started_sports_edges)


def test_main_calls_the_tested_started_cleanup_and_reports_its_failures(monkeypatch, capsys):
    import json as _json

    from tradehub.scripts import scan as scan_mod
    from tradehub.sports.scan import SportsRun

    calls: list[str] = []
    monkeypatch.setattr(scan_mod, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(scan_mod, "scan_weather", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan_mod, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan_mod, "cpi_scan_due", lambda now: False)
    monkeypatch.setattr(scan_mod, "sports_due", lambda now: True)
    monkeypatch.setattr(scan_mod, "latest_gate_statuses", lambda client, pairs: {})
    monkeypatch.setattr(scan_mod, "remove_closed_cpi_edges", lambda *a, **k: None)
    monkeypatch.setattr(scan_mod, "remove_stale_edges", lambda *a, **k: None)
    monkeypatch.setattr(scan_mod, "record_predictions", lambda *a, **k: None, raising=False)
    monkeypatch.setattr("tradehub.core.supabase_client.get_client", lambda: "supa")
    monkeypatch.setattr("tradehub.core.supabase_client.upsert_opportunities", lambda rows: None)
    monkeypatch.setattr(scan_mod, "run_sports_for_cron",
                        lambda now, supa, **kw: SportsRun([], [], {}, {}))

    def boom(client, now):
        calls.append("started_cleanup")
        return ["sports_nfl.started_cleanup: RuntimeError: boom"]

    monkeypatch.setattr(scan_mod, "remove_started_sports_edges", boom)
    rc = scan_mod.main(now=NOW, live=object(), client=object())
    assert calls == ["started_cleanup"], (
        f"main did not call the tested started-game cleanup: {calls}"
    )
    summary = _json.loads(capsys.readouterr().out)
    assert any("started_cleanup" in f for f in summary["failures"]), summary["failures"]
    assert rc == 1, "a failed started-game cleanup must be visible in the exit code"


# ── the column the delete filters on ───────────────────────────────────────────

def test_the_migration_adds_an_indexed_filterable_start_utc():
    sql = (Path(__file__).resolve().parents[1] / (
        "market_sentiment_tool/supabase/migrations/20260416000008_sports_reviews.sql"
    )).read_text()
    tight = "".join(sql.split())   # whitespace-insensitive: SQL spacing is not the point here
    assert "ADDCOLUMNIFNOTEXISTSstart_utctimestamptz" in tight, (
        "kalshi_edges has no filterable start_utc; the started-game delete cannot be expressed"
    )
    assert "kalshi_edges_sports_start_idx" in sql, "start_utc must be indexed for the delete"
    assert "kalshi_edges(engine,start_utc)" in tight
    # Rows written before this column existed carry the start inside raw_payload; without the
    # backfill they keep a NULL start_utc, which no `<= now` predicate ever matches.
    assert "raw_payload->>'start_utc'" in tight, "existing SPORTS rows would keep a NULL start_utc"
    assert "WHEREedge_type='SPORTS'" in tight and "ANDstart_utcISNULL" in tight


def test_the_edge_writer_persists_start_utc_as_a_column():
    """`expires_at` is the only time column kalshi_edges had, so the writer must now also put
    the game start somewhere the database can filter on."""
    from tradehub.core.supabase_client import upsert_opportunities

    captured: list[dict] = []

    class _Q:
        def upsert(self, rows, on_conflict=None):
            captured.extend(rows)
            return self

        def execute(self):
            return type("R", (), {"data": None})()

    class _Supa:
        def table(self, name):
            return _Q()

    import tradehub.core.supabase_client as sc
    real = sc.get_client
    sc.get_client = lambda: _Supa()
    try:
        start = NOW.isoformat()
        upsert_opportunities([{
            "market_ticker": "KXNFLGAME-26SEP27HOUIND-IND", "market_title": "t", "edge": 0.12,
            "engine": "sports_nfl", "edge_type": "SPORTS", "model_probability": 0.6,
            "market_price": 0.48, "expires_at": (NOW + timedelta(days=2)).isoformat(),
            "start_utc": start, "gate_status": "SHADOW",
        }])
    finally:
        sc.get_client = real
    assert captured[0]["start_utc"] == start, (
        f"the edge row was written without a top-level start_utc: {sorted(captured[0])}"
    )


def _upsert_rows(rows: list[dict], *, known_columns: set[str] | None = None) -> list[dict]:
    """Write `rows` through the real upsert_opportunities, with a fake that behaves like
    PostgREST: an unknown column is an error, not a silently ignored key."""
    from tradehub.core.supabase_client import upsert_opportunities
    import tradehub.core.supabase_client as sc

    captured: list[dict] = []

    class _Q:
        def upsert(self, payload, on_conflict=None):
            for row in payload:
                if known_columns is not None:
                    unknown = set(row) - known_columns
                    assert not unknown, f"PostgREST would reject these columns: {sorted(unknown)}"
            captured.extend(payload)
            return self

        def execute(self):
            return type("R", (), {"data": None})()

    class _Supa:
        def table(self, name):
            return _Q()

    real = sc.get_client
    sc.get_client = lambda: _Supa()
    try:
        upsert_opportunities(rows)
    finally:
        sc.get_client = real
    return captured


def test_a_row_without_a_game_start_does_not_send_the_column():
    """Follow-up from the step-7b review: `start_utc` is a sports column, and every engine's rows
    go through this one writer. Weather, gas, CPI and labor_nowcast must not depend on a column
    they never set, or a missing column takes the whole edge write down with it."""
    captured = _upsert_rows([{
        "market_ticker": "KXHIGHNY-26SEP25-T", "market_title": "High NY", "edge": 0.05,
        "engine": "weather", "edge_type": "WEATHER", "model_probability": 0.6, "market_price": 0.55,
    }])
    assert captured[0]["engine"] == "weather"
    assert "start_utc" not in captured[0], (
        f"a weather row carries the sports-only column: {sorted(captured[0])}"
    )


def test_non_sports_engines_still_write_when_the_column_does_not_exist_yet():
    """The failure this prevents: kalshi_edges without `start_utc` (migration not applied) made
    the upsert fail for EVERY engine, so weather and gas went red too."""
    captured = _upsert_rows(
        [
            {"market_ticker": "KXHIGHNY-26SEP25-T", "engine": "weather", "edge_type": "WEATHER",
             "edge": 0.05, "model_probability": 0.6, "market_price": 0.55},
            {"market_ticker": "KXPAYROLLS-26AUG-T50", "engine": "labor_nowcast",
             "edge_type": "MACRO", "edge": 0.08, "model_probability": 0.62, "market_price": 0.54},
        ],
        known_columns={"market_id", "title", "engine", "edge_type", "our_prob", "market_prob",
                       "edge_pct", "market_url", "source_url", "gate_status", "updated_at",
                       "expires_at", "raw_payload"},
    )
    assert {row["engine"] for row in captured} == {"weather", "labor_nowcast"}


def test_a_sports_row_still_sends_the_column():
    """The conditional must not cost sports the column it needs for the started-game delete."""
    start = NOW.isoformat()
    captured = _upsert_rows([{
        "market_ticker": "KXNFLGAME-26SEP27HOUIND-IND", "engine": "sports_nfl", "edge_type": "SPORTS",
        "edge": 0.12, "model_probability": 0.6, "market_price": 0.48, "start_utc": start,
    }])
    assert captured[0]["start_utc"] == start
