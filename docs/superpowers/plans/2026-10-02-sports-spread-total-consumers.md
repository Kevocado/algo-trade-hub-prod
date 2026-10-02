# Sports Spread and Total Consumers (Roadmap v2 item 11) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Journal the NFL and CFB predictors' spread and total forecasts beside the Kalshi price on the same contract, one target per game and kind, settled on Kalshi's own result.

**Architecture:** A game has a ladder of strikes per team (about 25 spread rungs and 5 to 20 total rungs), and every rung of one game is the same bet restated. The journal takes the one rung per game and kind whose Kalshi mid is nearest a coin flip, chosen from the price alone and never from the forecast. Each kind is its own forecaster name (`sports_nfl_spread`, `sports_nfl_total`, and the same for CFB), so winners, spreads and totals are scored apart and the winner keys do not change. The scan records which way YES points (the strike, the team the ticker names, both teams) so no consumer can flip a sign.

**Tech Stack:** Python 3.12, existing sports and journal stacks, pytest; one small frontend label change.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§8 Wave 3 Sports, §10 gates). **Depends on:** plans (g), (l) and the readable-UI plans merged.

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (backend suite all-pass at both clocks on the final stack; new files ruff-clean). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- **One target per game and kind.** The rule `one_rung` reads only `market_prob`; a test proves flipping the forecast cannot change the pick. A row with no market price is never chosen (no baseline, no target).
- **Winner keys unchanged:** `sports_<sport>` / `feed-v1` and `kalshi_implied_sports_<sport>` / `v1` keep their names, targets and behaviour.
- **Orientation is data, not inference.** The scan's prediction payload gains `strike`, `team`, `home`, `away` (additive; nothing reads them today). A spread forecast's payload carries `yes_means` ("CLE wins by more than 9.5"), a total's carries "total points above 42.5".
- **Live volume is thin and the plan does not pretend otherwise.** On 2026-10-01 only NFL has spread and total rows (44, all open) and every settled sports row is a winner market. One target per game means about 16 NFL spread targets a week, so a 200-target gate is months away for NFL and about a month for CFB. That is the honest cost of not counting one bet 25 times.
- The `predictions` table keeps its sports rows (every rung): the reviewer scorecard settles against them. See the roadmap.
- **Facts from the live feed, found by the agent's earlier draft (PR 68) and kept:** a spread market is about the team its title names, and in all six live rows that is the AWAY team (`KXNFLSPREAD-26OCT01PITCLE-PIT8` is "PIT Steelers wins by over 7.5 points?" on a CLE home game); the ticker's integer is not the line (`PIT8` is 7.5, a total ticker `-39` is over 38.5). So the strike is read from the market's `floor_strike` (the line), the team from the ticker's letters, and both go in the frozen payload; no consumer may assume home.
- **A deliberate difference from that draft:** it journals every line as its own target. This plan journals one rung per game and kind, because the lines of one game are one bet restated and counting them separately inflates the settled count the 200-target gate is judged on. If Kevin wants every rung journaled, that is a one-line change to `one_rung` and a different reading of the gate; ask him before changing it.

---
## Files

- Modify: `tradehub/sports/scan.py`, `tradehub/journal/forecasters/sports.py`, `tests/test_journal_sports.py`, `market_sentiment_tool/src/lib/{forecasterLabels,journal,journalView.test}.ts`
- Create: `tests/test_journal_sports_kinds.py`

---

### Task 1: Spread and total forecasters

**Files:**
- Modify: `tradehub/sports/scan.py` (four additive payload keys), `tradehub/journal/forecasters/sports.py`, `tests/test_journal_sports.py` (the build count goes from 4 to 12)
- Create: `tests/test_journal_sports_kinds.py`

**Interfaces:**
- Consumes: `tradehub.sports.pricing.price_market` (already prices every rung), `tradehub.sports.kalshi.team_code`, `settle_on_kalshi`.
- Produces: `one_rung(predictions, kind) -> {ticker: row}`; `SportsSnapshot.rows(now, kind='winner')`; `SportsFeedForecaster(snapshot, fetch, kind)` and `SportsMarketImplied(snapshot, fetch, kind)` with names `sports_<sport>[_<kind>]` and `kalshi_implied_sports_<sport>[_<kind>]`; `build_sports()` returns 12 forecasters.

- [ ] **Step 1: Write the failing test** (`tests/test_journal_sports_kinds.py`)

`tests/test_journal_sports_kinds.py`:

```python
import json
import math

import pytest
from test_journal_sports import FIXTURES, PRE_GAME, _final, _scan

from tradehub.journal.forecasters.sports import (
    SportsFeedForecaster,
    SportsMarketImplied,
    SportsSnapshot,
    build_sports,
    one_rung,
)
from tradehub.markets import prob_in_interval


def _row(ticker, game, kind, our, mid):
    return {"market_ticker": ticker, "our_prob": our, "market_prob": mid,
            "raw_payload": {"kind": kind, "game_id": game}}


def test_one_rung_picks_the_strike_the_market_prices_nearest_a_coin_flip():
    rows = [_row("S-HOU7", "g1", "spread", 0.9, 0.20), _row("S-IND3", "g1", "spread", 0.1, 0.46),
            _row("S-HOU3", "g1", "spread", 0.2, 0.55), _row("T-43", "g1", "total", 0.5, 0.80),
            _row("T-46", "g1", "total", 0.5, 0.52), _row("S-X", "g2", "spread", 0.5, 0.50)]
    assert set(one_rung(rows, "spread")) == {"S-IND3", "S-X"}   # |.46-.5| beats |.55-.5|
    assert set(one_rung(rows, "total")) == {"T-46"}


def test_one_rung_never_looks_at_the_forecast_and_breaks_ties_by_ticker():
    a = [_row("S-B", "g", "spread", 0.01, 0.40), _row("S-A", "g", "spread", 0.99, 0.60)]
    b = [_row("S-B", "g", "spread", 0.99, 0.40), _row("S-A", "g", "spread", 0.01, 0.60)]
    assert set(one_rung(a, "spread")) == set(one_rung(b, "spread")) == {"S-A"}
    assert one_rung([_row("S-A", "g", "spread", 0.5, None)], "spread") == {}   # no mid, no baseline, no target


def _spread(sport="nfl", kind="spread"):
    snap = SportsSnapshot(sport, _scan(sport))
    return SportsFeedForecaster(snap, _final("yes"), kind=kind), SportsMarketImplied(snap, _final("yes"), kind=kind)


def test_names_and_families_keep_each_kind_on_its_own_scorecard():
    feed, implied = _spread()
    assert (feed.name, feed.family) == ("sports_nfl_spread", "sports_nfl_spread")
    assert implied.name == "kalshi_implied_sports_nfl_spread"
    winner = SportsFeedForecaster(SportsSnapshot("nfl", _scan("nfl")), _final("yes"))
    assert (winner.name, winner.family) == ("sports_nfl", "sports_nfl")   # existing keys unchanged


def test_a_spread_forecast_is_the_probability_of_the_side_the_market_names_never_sign_flipped():
    feed, _ = _spread()
    entries = feed.targets(PRE_GAME)
    assert entries and all(e.target.startswith("kalshi:KXNFLSPREAD-") for e in entries)
    game = next(g for g in json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text())["games"]
                if g["game_id"].endswith("HOU_IND") or g["game_id"].endswith("IND_HOU"))
    seen = set()
    for entry in entries:
        f = feed.forecast(entry, PRE_GAME)
        p = f.payload
        assert p["kind"] == "spread" and p["team"] in (p["home"], p["away"]) and p["strike"] is not None
        mu, sigma = game["margin_mu"], game["sigma"]   # margin = home minus away
        want = (prob_in_interval(mu, sigma, (p["strike"], math.inf)) if p["team"] == p["home"]
                else prob_in_interval(mu, sigma, (-math.inf, -p["strike"])))
        assert f.probability == pytest.approx(want, abs=1e-4)
        assert p["yes_means"] == f"{p['team']} wins by more than {p['strike']:g}"
        seen.add(p["team"] == p["home"])
    assert seen   # at least one side exercised


def test_a_total_forecast_is_the_probability_of_the_over():
    feed, implied = _spread(kind="total")
    entry = feed.targets(PRE_GAME)[0]
    f, m = feed.forecast(entry, PRE_GAME), implied.forecast(entry, PRE_GAME)
    game = next(g for g in json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text())["games"]
                if g["game_id"] == f.payload["game_id"])
    assert f.probability == pytest.approx(prob_in_interval(game["total_mu"], game["total_sigma"],
                                                           (f.payload["strike"], math.inf)), abs=1e-4)
    assert f.payload["yes_means"] == f"total points above {f.payload['strike']:g}"
    assert m.probability == pytest.approx(f.market_prob) and m.market_prob == f.market_prob   # same contract, the mid


def test_the_registry_adds_spread_and_total_for_both_sports_without_touching_the_winner_keys():
    from tradehub.journal.registry import FORECASTERS

    keys = [(f.name, f.version) for f in FORECASTERS]
    for sport in ("nfl", "cfb"):
        for kind in ("spread", "total"):
            assert (f"sports_{sport}_{kind}", "feed-v1") in keys
            assert (f"kalshi_implied_sports_{sport}_{kind}", "v1") in keys
    assert ("sports_nfl", "feed-v1") in keys and len(set(keys)) == len(keys) and len(build_sports()) == 12


def test_every_spread_rung_the_scan_records_carries_an_orientation_that_reproduces_its_probability():
    run = _scan("nfl")(PRE_GAME)
    game = {g["game_id"]: g for g in json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text())["games"]}
    rows = [r for r in run.predictions if r["raw_payload"]["kind"] == "spread"]
    assert {r["raw_payload"]["team"] == r["raw_payload"]["home"] for r in rows} == {True, False}  # both sides present
    for r in rows:
        p, g = r["raw_payload"], game[r["raw_payload"]["game_id"]]
        want = (prob_in_interval(g["margin_mu"], g["sigma"], (p["strike"], math.inf)) if p["team"] == p["home"]
                else prob_in_interval(g["margin_mu"], g["sigma"], (-math.inf, -p["strike"])))
        assert r["our_prob"] == pytest.approx(want, abs=1e-4), r["market_ticker"]
```

- [ ] **Step 2: Run it** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_sports_kinds.py` — Expected: FAIL (the code below does not exist yet).

- [ ] **Step 3: Implement**

`tradehub/sports/scan.py` and `tradehub/journal/forecasters/sports.py` (apply the diff; the second file is shown as a diff because most of it is unchanged):

```diff
diff --git a/tests/test_journal_sports.py b/tests/test_journal_sports.py
index 0e81a1d..e0d2ced 100644
--- a/tests/test_journal_sports.py
+++ b/tests/test_journal_sports.py
@@ -116,4 +116,4 @@ def test_the_registry_runs_both_sports_with_unique_keys():
     for expected in (("sports_nfl", "feed-v1"), ("kalshi_implied_sports_nfl", "v1"),
                      ("sports_cfb", "feed-v1"), ("kalshi_implied_sports_cfb", "v1")):
         assert expected in keys
-    assert len(set(keys)) == len(keys) and len(build_sports()) == 4
+    assert len(set(keys)) == len(keys) and len(build_sports()) == 12
diff --git a/tradehub/journal/forecasters/sports.py b/tradehub/journal/forecasters/sports.py
index 436af0b..decafc3 100644
--- a/tradehub/journal/forecasters/sports.py
+++ b/tradehub/journal/forecasters/sports.py
@@ -9,7 +9,13 @@ the model's skill is measured against the price on exactly the same contracts.
 One target per game: only `winner` markets, and of a game's two winner markets only the first in ASCII
 ticker order. The two are exact complements, and spread/total lines on one game are correlated; counting
 them as separate targets would inflate the settled count the gate is judged on. The rule never looks at
-the forecast. Spread and total consumers are a named follow-up, not an assumption.
+the forecast.
+
+Spread and total consumers (plan 11) follow the same shape with a different pick rule, because a game has a
+ladder of strikes per team and every rung of one game is the same bet restated: only the rung the market
+prices nearest a coin flip is journaled (`one_rung`), chosen from the Kalshi mid alone, never from the
+forecast. Each kind is its own forecaster name, so winners, spreads and totals are scored apart; the winner
+keys are unchanged.
 
 The forecaster version is `feed-v1` and stays put when the predictor retrains: the predictor's own
 `model_version` is recorded in each row's payload, so the journal's key is the consumer, not the model.
@@ -29,6 +35,7 @@ from tradehub.sports.kalshi import SportsKalshi
 from tradehub.sports.scan import SportsRun, run_sports_scan
 
 SPORTS = ("nfl", "cfb")
+KINDS = ("winner", "spread", "total")
 FEED_VERSION = "feed-v1"
 SCAN_BUDGET_SECONDS = 600.0
 
@@ -53,21 +60,42 @@ def one_per_game(predictions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]
     return {row["market_ticker"]: row for row in chosen.values()}
 
 
+def one_rung(predictions: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
+    """{ticker: prediction row}: per game, the one `kind` market whose Kalshi mid is nearest 0.5.
+
+    Ties go to the first ticker (ASCII). A row with no mid has no baseline and is never chosen. The rule
+    reads only the market's price, so the forecast cannot influence which rung is journaled.
+    """
+    chosen: dict[str, dict[str, Any]] = {}
+    for row in predictions:
+        payload = row.get("raw_payload") or {}
+        if payload.get("kind") != kind or row.get("market_prob") is None:
+            continue
+        game = payload["game_id"]
+        rank = (abs(float(row["market_prob"]) - 0.5), row["market_ticker"])
+        best = chosen.get(game)
+        if best is None or rank < (abs(float(best["market_prob"]) - 0.5), best["market_ticker"]):
+            chosen[game] = row
+    return {row["market_ticker"]: row for row in chosen.values()}
+
+
 class SportsSnapshot:
-    """One sport's priced markets, scanned at most once per hourly run and shared by both forecasters."""
+    """One sport's priced markets, scanned at most once per hourly run and shared by every forecaster."""
 
     def __init__(self, sport: str, scan: Callable[[datetime], SportsRun] | None = None):
         self.sport = sport
         self._scan = scan or _default_scan(sport)
         self._hour: datetime | None = None
-        self._rows: dict[str, dict[str, Any]] = {}
+        self._rows: dict[str, dict[str, dict[str, Any]]] = {}
 
-    def rows(self, now: datetime) -> dict[str, dict[str, Any]]:
+    def rows(self, now: datetime, kind: str = "winner") -> dict[str, dict[str, Any]]:
         hour = now.replace(minute=0, second=0, microsecond=0)
         if self._hour != hour:
-            self._rows = one_per_game(self._scan(now).predictions)
+            predictions = self._scan(now).predictions
+            self._rows = {"winner": one_per_game(predictions),
+                          "spread": one_rung(predictions, "spread"), "total": one_rung(predictions, "total")}
             self._hour = hour
-        return self._rows
+        return self._rows[kind]
 
 
 def _start(row: dict[str, Any]) -> datetime:
@@ -76,9 +104,15 @@ def _start(row: dict[str, Any]) -> datetime:
 
 def _payload(row: dict[str, Any]) -> dict[str, Any]:
     p = row["raw_payload"]
-    return {"sport": p["sport"], "game_id": p["game_id"], "kind": p["kind"], "start_utc": p["start_utc"],
-            "snapshotted_at": p["snapshotted_at"], "model_version": p.get("model_version"),
-            "yes_bid": p.get("yes_bid"), "yes_ask": p.get("yes_ask")}
+    out = {"sport": p["sport"], "game_id": p["game_id"], "kind": p["kind"], "start_utc": p["start_utc"],
+           "snapshotted_at": p["snapshotted_at"], "model_version": p.get("model_version"),
+           "yes_bid": p.get("yes_bid"), "yes_ask": p.get("yes_ask")}
+    if p["kind"] != "winner":   # which way YES points, frozen with the forecast
+        team, strike = p.get("team"), p.get("strike")
+        out |= {"strike": strike, "team": team, "home": p.get("home"), "away": p.get("away"),
+                "yes_means": (f"{team} wins by more than {strike:g}" if p["kind"] == "spread"
+                              else f"total points above {strike:g}")}
+    return out
 
 
 class _SportsBase:
@@ -86,20 +120,24 @@ class _SportsBase:
     version: str
     name: str
 
-    def __init__(self, snapshot: SportsSnapshot, fetch: Callable[[str], Any] = fetch_market):
-        self._snapshot, self._fetch_market = snapshot, fetch
-        self.family = f"sports_{snapshot.sport}"
+    def __init__(self, snapshot: SportsSnapshot, fetch: Callable[[str], Any] = fetch_market,
+                 kind: str = "winner"):
+        if kind not in KINDS:
+            raise ValueError(f"unknown sports kind {kind!r}")
+        self._snapshot, self._fetch_market, self.kind = snapshot, fetch, kind
+        self.suffix = "" if kind == "winner" else f"_{kind}"
+        self.family = f"sports_{snapshot.sport}{self.suffix}"
 
     def targets(self, now: datetime) -> list[CalendarEntry]:
         out = []
-        for ticker, row in self._snapshot.rows(now).items():
+        for ticker, row in self._snapshot.rows(now, self.kind).items():
             start = _start(row)
             if now < start <= now + FREEZE_LEAD:
                 out.append(CalendarEntry(kalshi_target(ticker), self.family, self.cadence, start, market_linked=True))
         return out
 
     def _row(self, entry: CalendarEntry, now: datetime) -> dict[str, Any] | None:
-        return self._snapshot.rows(now).get(entry.target.removeprefix("kalshi:"))
+        return self._snapshot.rows(now, self.kind).get(entry.target.removeprefix("kalshi:"))
 
     def settle(self, target: str, now: datetime) -> Settlement | None:
         return settle_on_kalshi(target, self._fetch_market)
@@ -110,9 +148,10 @@ class SportsFeedForecaster(_SportsBase):
 
     version = FEED_VERSION
 
-    def __init__(self, snapshot: SportsSnapshot, fetch: Callable[[str], Any] = fetch_market):
-        super().__init__(snapshot, fetch)
-        self.name = f"sports_{snapshot.sport}"
+    def __init__(self, snapshot: SportsSnapshot, fetch: Callable[[str], Any] = fetch_market,
+                 kind: str = "winner"):
+        super().__init__(snapshot, fetch, kind)
+        self.name = f"sports_{snapshot.sport}{self.suffix}"
 
     def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
         row = self._row(entry, now)
@@ -127,9 +166,10 @@ class SportsMarketImplied(_SportsBase):
 
     version = "v1"
 
-    def __init__(self, snapshot: SportsSnapshot, fetch: Callable[[str], Any] = fetch_market):
-        super().__init__(snapshot, fetch)
-        self.name = f"kalshi_implied_sports_{snapshot.sport}"
+    def __init__(self, snapshot: SportsSnapshot, fetch: Callable[[str], Any] = fetch_market,
+                 kind: str = "winner"):
+        super().__init__(snapshot, fetch, kind)
+        self.name = f"kalshi_implied_sports_{snapshot.sport}{self.suffix}"
 
     def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
         row = self._row(entry, now)
@@ -143,8 +183,9 @@ def build_sports(scans: dict[str, Callable[[datetime], SportsRun]] | None = None
     out: list[_SportsBase] = []
     for sport in SPORTS:
         snapshot = SportsSnapshot(sport, (scans or {}).get(sport))
-        out += [SportsFeedForecaster(snapshot), SportsMarketImplied(snapshot)]
+        for kind in KINDS:
+            out += [SportsFeedForecaster(snapshot, kind=kind), SportsMarketImplied(snapshot, kind=kind)]
     return out
 
 
-__all__ = ["SportsFeedForecaster", "SportsMarketImplied", "SportsSnapshot", "build_sports", "one_per_game"]
+__all__ = ["SportsFeedForecaster", "SportsMarketImplied", "SportsSnapshot", "build_sports", "one_per_game", "one_rung"]
diff --git a/tradehub/sports/scan.py b/tradehub/sports/scan.py
index ff510aa..b3cd6d3 100644
--- a/tradehub/sports/scan.py
+++ b/tradehub/sports/scan.py
@@ -26,7 +26,7 @@ from tradehub.sports.deadline import (
 )
 from tradehub.sports.feed import Feed, FeedUnavailable, fetch_feed
 from tradehub.sports.hub_calibration import settled_buckets
-from tradehub.sports.kalshi import SportsKalshi, SportsMarket
+from tradehub.sports.kalshi import SportsKalshi, SportsMarket, team_code
 from tradehub.sports.kinds import KINDS
 from tradehub.sports.mapping import MatchedGame, load_aliases, match_games
 from tradehub.sports.pricing import price_market
@@ -124,6 +124,14 @@ class SportScan:
     too_soon: int = 0
 
 
+def _orientation(sm: SportsMarket, mg: MatchedGame) -> dict[str, Any]:
+    """Which way YES points: the strike, the team the ticker names, and both teams. Read defensively so a
+    market object without a suffix or strike (a hand-built one) records nulls instead of failing the scan."""
+    return {"strike": getattr(sm.market, "floor_strike", None),
+            "team": team_code(sm) if hasattr(sm, "suffix") else None,
+            "home": getattr(mg, "home_code", None), "away": getattr(mg, "away_code", None)}
+
+
 def _fact_pack(cfg: SportConfig, kind: str, sm: SportsMarket, mg: MatchedGame, s: EdgeSuggestion,
                check: CandidateCheck, now: datetime) -> dict[str, Any]:
     """Public facts only (spec §3.2 'Data sent'): no keys, no account data."""
@@ -386,7 +394,10 @@ def scan_sport(cfg: SportConfig, markets_by_series: dict[str, list[SportsMarket]
                                      # journal can net an edge of fees and spread (spec §10) and keep the
                                      # version out of its own key. Additive: nothing reads them today.
                                      "yes_bid": q.yes_bid, "yes_ask": q.yes_ask,
-                                     "model_version": mg.game.model_version},
+                                     "model_version": mg.game.model_version,
+                                     # Which way YES points, so a spread or total consumer can never
+                                     # flip a sign: the strike, the team the ticker names, and both teams.
+                                     **_orientation(sm, mg)},
                     ))
                 s = evaluate_edge(sm.market.ticker, prob, q, min_edge_pct=cfg.edge.min_edge_pct,
                                   prefer_maker=cfg.edge.prefer_maker)
```

- [ ] **Step 4: Run** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_sports_kinds.py tests/test_journal_sports.py tests/test_sports_scan.py tests/test_sports_inversion.py` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tradehub/sports/scan.py tradehub/journal/forecasters/sports.py tests/test_journal_sports.py tests/test_journal_sports_kinds.py
git commit -m "feat(journal): spread and total consumers, one rung per game"
```

---

### Task 2: Names the page can read

**Files:**
- Modify: `market_sentiment_tool/src/lib/forecasterLabels.ts`, `market_sentiment_tool/src/lib/journal.ts`, `market_sentiment_tool/src/lib/journalView.test.ts`

**Interfaces:**
- Produces: plain labels (`NFL point spreads`, `NFL game totals`, `College football point spreads`, `College football game totals`) and the `MARKET_PAIR` entries that fold each kind's Kalshi baseline into its row.

- [ ] **Step 1: Write the failing test** (`market_sentiment_tool/src/lib/journalView.test.ts`)

Add this test to the `view` describe in `journalView.test.ts` (in the diff below).

- [ ] **Step 2: Run it** — `cd market_sentiment_tool && npx vitest run src/lib/journalView.test.ts` — Expected: FAIL (the code below does not exist yet).

- [ ] **Step 3: Implement**

```diff
diff --git a/market_sentiment_tool/src/lib/forecasterLabels.ts b/market_sentiment_tool/src/lib/forecasterLabels.ts
index 1a6dace..19dc057 100644
--- a/market_sentiment_tool/src/lib/forecasterLabels.ts
+++ b/market_sentiment_tool/src/lib/forecasterLabels.ts
@@ -15,6 +15,10 @@ const BASE: Record<string, string> = {
   housing_direction: "US home prices",
   sports_nfl: "NFL winners",
   sports_cfb: "College football winners",
+  sports_nfl_spread: "NFL point spreads",
+  sports_nfl_total: "NFL game totals",
+  sports_cfb_spread: "College football point spreads",
+  sports_cfb_total: "College football game totals",
 };
 
 const VERSIONED: Record<string, string> = {
diff --git a/market_sentiment_tool/src/lib/journal.ts b/market_sentiment_tool/src/lib/journal.ts
index c040a7b..aad832d 100644
--- a/market_sentiment_tool/src/lib/journal.ts
+++ b/market_sentiment_tool/src/lib/journal.ts
@@ -85,6 +85,10 @@ export const MARKET_PAIR: Record<string, string> = {
   labor_nowcast: "kalshi_implied_labor",
   sports_nfl: "kalshi_implied_sports_nfl",
   sports_cfb: "kalshi_implied_sports_cfb",
+  sports_nfl_spread: "kalshi_implied_sports_nfl_spread",
+  sports_nfl_total: "kalshi_implied_sports_nfl_total",
+  sports_cfb_spread: "kalshi_implied_sports_cfb_spread",
+  sports_cfb_total: "kalshi_implied_sports_cfb_total",
 };
 
 /** Forecasters the spec labels experimental (ruling Q5). */
diff --git a/market_sentiment_tool/src/lib/journalView.test.ts b/market_sentiment_tool/src/lib/journalView.test.ts
index 4737e19..c7054dd 100644
--- a/market_sentiment_tool/src/lib/journalView.test.ts
+++ b/market_sentiment_tool/src/lib/journalView.test.ts
@@ -50,6 +50,17 @@ describe("view", () => {
     expect(waiting.map((r) => r.label)).toEqual(["S&P 500 tomorrow: model", "US home prices"]);
   });
 
+  it("pairs a spread or total forecaster with its own Kalshi baseline and names it in plain words", () => {
+    const rows = viewRows([
+      score({ forecaster: "sports_nfl_spread", forecaster_version: "feed-v1", baseline: "market", n_settled: 3, n_targets: 5 }),
+      score({ forecaster: "kalshi_implied_sports_nfl_spread", forecaster_version: "v1", n_settled: 3, n_targets: 5 }),
+      score({ forecaster: "sports_nfl_total", forecaster_version: "feed-v1", n_targets: 2 }),
+    ]);
+    const spread = rows.find((r) => r.label === "NFL point spreads");
+    expect(spread?.market?.forecaster).toBe("kalshi_implied_sports_nfl_spread");
+    expect(rows.find((r) => r.label === "NFL game totals")?.market).toBeNull();
+  });
+
   it("counts what the page headlines, and a monthly forecaster needs 50 not 200", () => {
     const rows = viewRows(scores);
     expect(totals(rows)).toEqual({ forecasters: 3, frozen: 12, scored: 4, promoted: 0 });
```

- [ ] **Step 4: Run** — `cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/src/lib
git commit -m "feat(ui): plain names and baselines for spread and total rows"
```

---

### Task 3: Verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass (reviewer baseline on the final stack: see the roadmap).

- [ ] Ruff on the files this plan created or changed: `.venv/bin/python -m ruff check --select F tradehub/journal/forecasters/sports.py tests/test_journal_sports_kinds.py` → `All checks passed!` (import-order findings on files you did not create are older debt, not yours).
- [ ] Frontend: `cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx vite build` — all green.
- [ ] Open the PR from a fresh branch off `main` (title in the roadmap). Body: what changed, the verification output, and whether a migration needs applying. Then stop and report in 4 lines.

---

## Self-Review

- **Never sign-flipped:** `test_every_spread_rung_the_scan_records_carries_an_orientation_that_reproduces_its_probability` recomputes every recorded spread rung's probability from the feed's margin distribution and the recorded `team`, `home` and `strike`, for both sides of the ladder; the two forecast tests do the same for the journaled rung and for totals.
- **No hindsight in the pick:** `test_one_rung_never_looks_at_the_forecast_and_breaks_ties_by_ticker`.
- **Existing keys:** `test_names_and_families_keep_each_kind_on_its_own_scorecard` pins the winner name and family.
- **Type consistency:** `kind` is one of `KINDS = ("winner", "spread", "total")` everywhere; a stray value raises at construction.
