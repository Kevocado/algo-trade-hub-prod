# Sports Feed Consumers (Wave 3, Plan l) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Journal the NFL and CFB predictors' frozen pre-game win probabilities, each beside the Kalshi-implied baseline on the same contracts, settled on Kalshi's own results.

**Architecture:** The journal consumes what `tradehub.sports.scan.run_sports_scan` already prices from each predictor's `/api/kalshi-feed` (the same path as the hub's sports board), so the two cannot disagree. `SportsSnapshot` runs that scan at most once per sport per hour and keeps one winner market per game; `SportsFeedForecaster` freezes the predictor's probability inside 24h of kickoff (cutoff = kickoff) and `SportsMarketImplied` freezes the Kalshi mid for the same contract. Both settle with `settle_on_kalshi`.

**Tech Stack:** Python 3.12, existing sports stack, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§8 Wave 3 Sports, §10 gates). **Depends on:** plans (a), (b) and (h) merged; (h) is needed for the promotion gate to see the recorded quotes, but this plan's code runs without it.

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (backend 1399 passed at monotonic 5.0 and at 1e7; new files ruff-clean). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- **The journal never re-models or re-settles a game.** It consumes the predictors' frozen feed and Kalshi's market result. NFL and CFB only: NBA, PL and F1 join only after each ships the same frozen pre-game feed (spec §8).
- **One target per game.** Only `winner` markets, and of a game's two winner markets only the first in ASCII ticker order. The two are exact complements and spread/total lines on one game are correlated, so counting them would inflate the settled count the 200-target gate is judged on. The rule never looks at the forecast. Spread and total consumers are a named follow-up.
- **The key is the consumer, not the model:** forecaster `sports_<sport>` version `feed-v1` stays fixed when the predictor retrains; the predictor's `model_version` is recorded in each row's payload.
- Freeze lead is the wave-1 Kalshi lead (24h before kickoff, which is also the calendar cutoff). The scan itself never prices a game less than an hour out, so a game has roughly 23 hourly chances to freeze.
- `scan_sport`'s prediction payload gains `yes_bid`, `yes_ask` and `model_version`. This is additive (nothing reads them today) and is what lets plan (h)'s cost gate net the edge of fees and spread.
- Sports stay in the `predictions` ledger too until plan (k) cuts the legacy ledger over; do not remove that here.
- Weather stays quarantined; earnings and crypto stay deferred to v1.x.

---
### Task 1: The sports consumers and their registration

**Files:**
- Modify: `tradehub/sports/scan.py` (three additive payload keys), `tradehub/journal/registry.py`
- Create: `tradehub/journal/forecasters/sports.py`
- Test: `tests/test_journal_sports.py`

**Interfaces:**
- Consumes: `tradehub.sports.scan.{run_sports_scan, SportsRun}`, `tradehub.sports.kalshi.SportsKalshi`, plan (b) `kalshi_linked.{FREEZE_LEAD, kalshi_target, settle_on_kalshi}`, `tradehub.core.kalshi_feed.fetch_market`, the fixtures under `tests/fixtures/sports/`.
- Produces: `one_per_game(predictions) -> {ticker: row}`; `SportsSnapshot(sport, scan=None).rows(now)`; `SportsFeedForecaster(snapshot, fetch=...)` (name `sports_<sport>`, version `feed-v1`); `SportsMarketImplied(snapshot, fetch=...)` (name `kalshi_implied_sports_<sport>`, version `v1`); `build_sports(scans=None)` returning the four forecasters for `nfl` and `cfb`. Targets are `kalshi:<winner market ticker>`, cadence `daily`, family `sports_<sport>`, cutoff = kickoff.

- [ ] **Step 1: Write the failing test** (`tests/test_journal_sports.py`)

```python
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from journal_fakes import FakeJournalDB

from tradehub.journal.forecasters.sports import (
    SportsFeedForecaster,
    SportsMarketImplied,
    SportsSnapshot,
    build_sports,
    one_per_game,
)
from tradehub.journal.runner import run_journal
from tradehub.sports.feed import parse_feed
from tradehub.sports.kalshi import parse_sports_market
from tradehub.sports.scan import run_sports_scan

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
PRE_GAME = datetime(2026, 9, 27, 2, 0, tzinfo=UTC)  # the recorded NFL games kick off at 17:00Z: 15h out


class FakeKalshi:
    def __init__(self, sport):
        raw = json.loads((FIXTURES / f"{sport}_open_markets.json").read_text())
        self.markets = {s: [parse_sports_market(m) for m in ms] for s, ms in raw.items()}

    def open_markets(self, series):
        return self.markets.get(series, [])


def _scan(sport, counter=None):
    feed = parse_feed(json.loads((FIXTURES / f"{sport}_kalshi_feed.json").read_text()))

    def scan(now):
        if counter is not None:
            counter.append(now)
        return run_sports_scan(now, FakeKalshi(sport), fetch=lambda base_url, deadline=None: feed, sports=(sport,))
    return scan


def _final(ticker_result):
    return lambda ticker: {"market": {"ticker": ticker, "status": "finalized", "result": ticker_result}}


def test_one_target_per_game_winner_markets_only_first_ticker():
    rows = [
        {"market_ticker": "B-HOU", "raw_payload": {"kind": "winner", "game_id": "g1"}},
        {"market_ticker": "A-IND", "raw_payload": {"kind": "winner", "game_id": "g1"}},
        {"market_ticker": "S-IND8", "raw_payload": {"kind": "spread", "game_id": "g1"}},
        {"market_ticker": "T-O45", "raw_payload": {"kind": "total", "game_id": "g1"}},
        {"market_ticker": "C-KC", "raw_payload": {"kind": "winner", "game_id": "g2"}},
    ]
    assert set(one_per_game(rows)) == {"A-IND", "C-KC"}  # never looks at the forecast


def test_the_feed_forecaster_freezes_the_predictors_probability_and_the_quote():
    snapshot = SportsSnapshot("nfl", _scan("nfl"))
    fc = SportsFeedForecaster(snapshot, _final("yes"))
    entries = fc.targets(PRE_GAME)
    assert entries and all(e.market_linked and e.cadence == "daily" and e.target.startswith("kalshi:KXNFLGAME-")
                           for e in entries)
    assert all(e.cutoff_at == datetime(2026, 9, 27, 17, 0, tzinfo=UTC) or e.cutoff_at > PRE_GAME for e in entries)
    forecast = fc.forecast(entries[0], PRE_GAME)
    assert (fc.name, fc.version) == ("sports_nfl", "feed-v1")
    assert 0.0 < forecast.probability < 1.0 and forecast.market_prob is not None
    assert forecast.payload["game_id"] and forecast.payload["kind"] == "winner"
    assert forecast.payload["yes_bid"] is not None and forecast.payload["yes_ask"] is not None  # for cost netting
    assert forecast.payload["model_version"]  # the predictor's version rides in the row, not in the key


def test_a_game_outside_the_24h_lead_is_not_a_target_yet():
    fc = SportsFeedForecaster(SportsSnapshot("nfl", _scan("nfl")), _final("yes"))
    assert fc.targets(PRE_GAME - timedelta(hours=12)) == []  # the nearest game is 27h out
    after_sunday = datetime(2026, 9, 27, 17, 30, tzinfo=UTC)  # the 17:00Z games have kicked off
    assert all(e.cutoff_at > after_sunday for e in fc.targets(after_sunday))  # only the late game remains


def test_both_forecasters_share_one_scan_per_hour():
    calls = []
    snapshot = SportsSnapshot("nfl", _scan("nfl", calls))
    feed, implied = SportsFeedForecaster(snapshot, _final("yes")), SportsMarketImplied(snapshot, _final("yes"))
    feed.targets(PRE_GAME)
    implied.targets(PRE_GAME)
    feed.forecast(feed.targets(PRE_GAME)[0], PRE_GAME)
    assert len(calls) == 1
    feed.targets(PRE_GAME + timedelta(hours=1))
    assert len(calls) == 2


def test_end_to_end_freeze_before_kickoff_then_settle_on_kalshi_and_score_against_the_mid():
    clock = [PRE_GAME]
    db = FakeJournalDB(lambda: clock[0])
    snapshot = SportsSnapshot("nfl", _scan("nfl"))
    fcs = [SportsFeedForecaster(snapshot, _final("yes")), SportsMarketImplied(snapshot, _final("yes"))]
    out = run_journal(db, fcs, clock[0])
    frozen = out["forecasters"]["sports_nfl@feed-v1"]["frozen"]
    assert frozen >= 1 and out["forecasters"]["kalshi_implied_sports_nfl@v1"]["frozen"] == frozen
    clock[0] = datetime(2026, 9, 27, 23, 0, tzinfo=UTC)  # after the games
    snapshot._hour = None
    out = run_journal(db, fcs, clock[0])
    started = [c for c in db.tables["journal_calendars"] if datetime.fromisoformat(c["cutoff_at"]) <= clock[0]]
    assert 0 < len(started) < frozen  # the late-Sunday game has not kicked off: it must not settle yet
    assert out["forecasters"]["sports_nfl@feed-v1"]["settled"] == len(started)
    assert not out["failures"]
    cards = {r["forecaster"]: r for r in db.tables["journal_scores"]}
    assert cards["sports_nfl"]["baseline"] == "market"
    assert cards["kalshi_implied_sports_nfl"]["bss"] == pytest.approx(0.0)


def test_the_registry_runs_both_sports_with_unique_keys():
    from tradehub.journal.registry import FORECASTERS

    keys = [(f.name, f.version) for f in FORECASTERS]
    for expected in (("sports_nfl", "feed-v1"), ("kalshi_implied_sports_nfl", "v1"),
                     ("sports_cfb", "feed-v1"), ("kalshi_implied_sports_cfb", "v1")):
        assert expected in keys
    assert len(set(keys)) == len(keys) and len(build_sports()) == 4
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_sports.py -v`
Expected: FAIL — `No module named 'tradehub.journal.forecasters.sports'`.

- [ ] **Step 3: Implement**

`tradehub/sports/scan.py` and `tradehub/journal/registry.py` (apply these changes):

```diff
diff --git a/tradehub/journal/registry.py b/tradehub/journal/registry.py
index 3240aac..263ecad 100644
--- a/tradehub/journal/registry.py
+++ b/tradehub/journal/registry.py
@@ -14,6 +14,7 @@ from tradehub.journal.forecasters.daily_direction import build_wave2
 from tradehub.journal.forecasters.fomc import FOMC_SERIES, FomcMapped, is_hold_market
 from tradehub.journal.forecasters.labor import LaborData, PayrollsForecaster, QuitsDirection, UnrateDirection
 from tradehub.journal.forecasters.sentiment import SentimentMeter
+from tradehub.journal.forecasters.sports import build_sports
 from tradehub.journal.forecasters.spy_quant import SpyQuant
 from tradehub.journal.kalshi_linked import KalshiImplied
 from tradehub.journal.spx import SpxCloses
@@ -40,4 +41,6 @@ FORECASTERS: list[Forecaster] = [
     SpyQuant(_SPX),
     # wave 2 (spec §8): VIX, gold (GLD) and EUR/USD daily direction, same walk-forward model
     *build_wave2(),
+    # wave 3 (spec §8): NFL and CFB feed consumers, each beside its Kalshi-implied baseline
+    *build_sports(),
 ]
diff --git a/tradehub/sports/scan.py b/tradehub/sports/scan.py
index a1cb5ee..ff510aa 100644
--- a/tradehub/sports/scan.py
+++ b/tradehub/sports/scan.py
@@ -381,7 +381,12 @@ def scan_sport(cfg: SportConfig, markets_by_series: dict[str, list[SportsMarket]
                         raw_payload={"sport": cfg.sport, "game_id": mg.game.game_id, "kind": kind,
                                      "start_utc": mg.game.start_utc.isoformat(),
                                      "snapshotted_at": mg.game.snapshotted_at.isoformat(),
-                                     "alias_version": aliases.version, "date_shift_days": mg.date_shift_days},
+                                     "alias_version": aliases.version, "date_shift_days": mg.date_shift_days,
+                                     # The frozen top of book and the predictor's model version, so the
+                                     # journal can net an edge of fees and spread (spec §10) and keep the
+                                     # version out of its own key. Additive: nothing reads them today.
+                                     "yes_bid": q.yes_bid, "yes_ask": q.yes_ask,
+                                     "model_version": mg.game.model_version},
                     ))
                 s = evaluate_edge(sm.market.ticker, prob, q, min_edge_pct=cfg.edge.min_edge_pct,
                                   prefer_maker=cfg.edge.prefer_maker)
```

`tradehub/journal/forecasters/sports.py`:

```python
"""Sports consumers (v2 spec §8 wave 3): the NFL and CFB predictors' frozen pre-game feeds, journaled.

The journal never re-models or re-settles a game. It consumes what `tradehub.sports.scan.run_sports_scan`
already prices from each predictor's `/api/kalshi-feed` (the same code path as the hub's sports board,
so the two cannot disagree), freezes that probability before kickoff, and settles on Kalshi's own market
result. Each sport also gets a market pseudo-forecaster (the Kalshi mid frozen at the same moment), so
the model's skill is measured against the price on exactly the same contracts.

One target per game: only `winner` markets, and of a game's two winner markets only the first in ASCII
ticker order. The two are exact complements, and spread/total lines on one game are correlated; counting
them as separate targets would inflate the settled count the gate is judged on. The rule never looks at
the forecast. Spread and total consumers are a named follow-up, not an assumption.

The forecaster version is `feed-v1` and stays put when the predictor retrains: the predictor's own
`model_version` is recorded in each row's payload, so the journal's key is the consumer, not the model.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from tradehub.core.kalshi_feed import fetch_market
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.kalshi_linked import FREEZE_LEAD, kalshi_target, settle_on_kalshi
from tradehub.sports.kalshi import SportsKalshi
from tradehub.sports.scan import SportsRun, run_sports_scan

SPORTS = ("nfl", "cfb")
FEED_VERSION = "feed-v1"
SCAN_BUDGET_SECONDS = 600.0


def _default_scan(sport: str) -> Callable[[datetime], SportsRun]:
    def scan(now: datetime) -> SportsRun:
        deadline = time.monotonic() + SCAN_BUDGET_SECONDS
        return run_sports_scan(now, SportsKalshi(deadline=deadline), sports=(sport,), deadline=deadline)
    return scan


def one_per_game(predictions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{ticker: prediction row}: winner markets only, the first ticker (ASCII) of each game."""
    chosen: dict[str, dict[str, Any]] = {}
    for row in predictions:
        payload = row.get("raw_payload") or {}
        if payload.get("kind") != "winner":
            continue
        game = payload["game_id"]
        if game not in chosen or row["market_ticker"] < chosen[game]["market_ticker"]:
            chosen[game] = row
    return {row["market_ticker"]: row for row in chosen.values()}


class SportsSnapshot:
    """One sport's priced markets, scanned at most once per hourly run and shared by both forecasters."""

    def __init__(self, sport: str, scan: Callable[[datetime], SportsRun] | None = None):
        self.sport = sport
        self._scan = scan or _default_scan(sport)
        self._hour: datetime | None = None
        self._rows: dict[str, dict[str, Any]] = {}

    def rows(self, now: datetime) -> dict[str, dict[str, Any]]:
        hour = now.replace(minute=0, second=0, microsecond=0)
        if self._hour != hour:
            self._rows = one_per_game(self._scan(now).predictions)
            self._hour = hour
        return self._rows


def _start(row: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(row["raw_payload"]["start_utc"])


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    p = row["raw_payload"]
    return {"sport": p["sport"], "game_id": p["game_id"], "kind": p["kind"], "start_utc": p["start_utc"],
            "snapshotted_at": p["snapshotted_at"], "model_version": p.get("model_version"),
            "yes_bid": p.get("yes_bid"), "yes_ask": p.get("yes_ask")}


class _SportsBase:
    cadence = "daily"
    version: str
    name: str

    def __init__(self, snapshot: SportsSnapshot, fetch: Callable[[str], Any] = fetch_market):
        self._snapshot, self._fetch_market = snapshot, fetch
        self.family = f"sports_{snapshot.sport}"

    def targets(self, now: datetime) -> list[CalendarEntry]:
        out = []
        for ticker, row in self._snapshot.rows(now).items():
            start = _start(row)
            if now < start <= now + FREEZE_LEAD:
                out.append(CalendarEntry(kalshi_target(ticker), self.family, self.cadence, start, market_linked=True))
        return out

    def _row(self, entry: CalendarEntry, now: datetime) -> dict[str, Any] | None:
        return self._snapshot.rows(now).get(entry.target.removeprefix("kalshi:"))

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


class SportsFeedForecaster(_SportsBase):
    """The predictor's frozen pre-game probability for the game's winner market."""

    version = FEED_VERSION

    def __init__(self, snapshot: SportsSnapshot, fetch: Callable[[str], Any] = fetch_market):
        super().__init__(snapshot, fetch)
        self.name = f"sports_{snapshot.sport}"

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        row = self._row(entry, now)
        if row is None:
            return None
        return Forecast(self.name, self.version, entry.target, float(row["our_prob"]),
                        market_prob=row.get("market_prob"), payload=_payload(row))


class SportsMarketImplied(_SportsBase):
    """The Kalshi mid for the same contract, frozen at the same moment: the baseline the feed is graded against."""

    version = "v1"

    def __init__(self, snapshot: SportsSnapshot, fetch: Callable[[str], Any] = fetch_market):
        super().__init__(snapshot, fetch)
        self.name = f"kalshi_implied_sports_{snapshot.sport}"

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        row = self._row(entry, now)
        if row is None or row.get("market_prob") is None:
            return None
        return Forecast(self.name, self.version, entry.target, float(row["market_prob"]),
                        market_prob=float(row["market_prob"]), payload=_payload(row))


def build_sports(scans: dict[str, Callable[[datetime], SportsRun]] | None = None) -> list[_SportsBase]:
    out: list[_SportsBase] = []
    for sport in SPORTS:
        snapshot = SportsSnapshot(sport, (scans or {}).get(sport))
        out += [SportsFeedForecaster(snapshot), SportsMarketImplied(snapshot)]
    return out


__all__ = ["SportsFeedForecaster", "SportsMarketImplied", "SportsSnapshot", "build_sports", "one_per_game"]
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_sports.py tests/test_sports_scan.py tests/test_sports_feed.py -v`
Expected: all pass (6 new tests; the existing sports tests are unchanged because the payload change is additive).

- [ ] **Step 5: Commit**

```bash
git add tradehub/sports/scan.py tradehub/journal/registry.py tradehub/journal/forecasters/sports.py tests/test_journal_sports.py
git commit -m "feat(journal): NFL and CFB feed consumers beside their Kalshi-implied baselines"
```

---

### Task 2: Verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass.

- [ ] Ruff on every file this plan created or changed: `.venv/bin/python -m ruff check <files>` → `All checks passed!` (pre-existing ruff debt elsewhere is not yours to fix here).
- [ ] Operational note for the PR body: each hourly run now makes one sports scan per sport through the journal as well as the existing scan job (public Kalshi market pages plus the predictors' feeds). `SCAN_BUDGET_SECONDS` (600) bounds it; say in the PR if a run exceeds a few minutes.
- [ ] Open the PR from a fresh branch off `main`. Body: what changed, the verification output, and whether a migration needs applying.

## Self-Review

- **Spec §8 Sports:** predictors plug in as consumed graded outputs via the `/api/kalshi-feed` contract (through the existing scan), the journal never re-settles games (Kalshi's market result is the settlement), NFL and CFB only, and PR #27's ranking/window/inversion logic is kept because the scan is reused unchanged.
- **Gate honesty:** one target per game keeps the settled count comparable to the 200-target bar; both the model and its market baseline are frozen at the same moment on the same contract, so Brier skill vs the market is apples to apples.
- **Type consistency:** `SportsSnapshot.rows` keys are bare tickers; targets add the `kalshi:` prefix via `kalshi_target` and `_row` strips it with `removeprefix("kalshi:")`.
