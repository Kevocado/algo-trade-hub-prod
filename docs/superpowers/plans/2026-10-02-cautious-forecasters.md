# Cautious (Market-Anchored) Forecasters (Roadmap v2 item 15) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add, beside every market-linked model, a copy whose probability starts at the Kalshi price and moves a fixed quarter of the way toward the model, graded on the same targets as its own forecaster.

**Architecture:** `MarketShrunk(inner, weight=0.25)` wraps any forecaster that has a market price: same targets, same settlement, probability `m + 0.25 * (p - m)`, payload records `raw_probability` and `weight`, name `<model>_cautious`, version `<version>+w25`. The weight is fixed here before any result is looked at and is never tuned on journal results; a different weight is a different version. The pure model is untouched. It cannot create skill. It shows whether any exists and caps how badly overconfidence can lose.

**Tech Stack:** Python 3.12 + pytest; small frontend label change.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§10 gates (BSS vs market, costs)). **Depends on:** plan 11 merged (so the sports spread and total models are wrapped too).

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (backend suite all-pass at both clocks on the final stack; vitest, tsc, build green). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- **Why this and not a retrain:** on every settled row we have, the models lose to the market, and shrinking toward the market loses less. Measured on 2026-10-01 over settled `predictions` rows with a market mid (Brier: model / market / shrunk 0.25): weather 0.160 / 0.095 / 0.104 on 1,009 rows; gas 0.162 / 0.067 / 0.075 on 569; NFL winners 0.188 / 0.238 / 0.222 on 30; CFB winners 0.242 / 0.134 / 0.155 on 30. So expect the cautious copies to stay close to zero skill and to lose to the market on weather and gas. A copy that fails to beat the market is the answer, and it goes in the PR body.
- **Wrap only forecasters with a market price:** `cpi_nowcast`, `fomc_mapped`, `labor_nowcast` and the six sports models. Never the `kalshi_implied_*` baselines, and never the daily-direction models (no market price).
- **A missing market price is a gap, never a guess.**
- No migration.

---
### Task 1: MarketShrunk and its registration

**Files:**
- Create: `tradehub/journal/forecasters/shrunk.py`, `tests/test_journal_shrunk.py`
- Modify: `tradehub/journal/registry.py`

**Interfaces:**
- Consumes: the `Forecaster` contract.
- Produces: `MarketShrunk(inner, weight=SHRINK_WEIGHT)`, `SHRINK_WEIGHT = 0.25`, `SUFFIX = '_cautious'`; the registry appends one wrapper per shrinkable forecaster.

- [ ] **Step 1: Write the failing test** (`tests/test_journal_shrunk.py`)

`tests/test_journal_shrunk.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from journal_fakes import FakeJournalDB

from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.forecasters.shrunk import SHRINK_WEIGHT, MarketShrunk
from tradehub.journal.runner import run_journal

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
CUTOFF = NOW + timedelta(hours=10)


class Inner:
    name, version, cadence = "model_x", "v1", "daily"

    def __init__(self, prob=0.80, market=0.50, linked=True):
        self.prob, self.market, self.linked = prob, market, linked
        self.settled = []

    def targets(self, now):
        return [CalendarEntry("kalshi:T1", "fam", "daily", CUTOFF, market_linked=self.linked)]

    def forecast(self, entry, now):
        return Forecast(self.name, self.version, entry.target, self.prob, market_prob=self.market, payload={"k": 1})

    def settle(self, target, now):
        self.settled.append(target)
        return Settlement(target, 1, "test")


def test_the_weight_is_fixed_before_any_result_is_seen():
    assert SHRINK_WEIGHT == 0.25


def test_the_forecast_moves_a_quarter_of_the_way_from_the_market_to_the_model():
    fc = MarketShrunk(Inner(prob=0.80, market=0.50))
    f = fc.forecast(fc.targets(NOW)[0], NOW)
    assert f.probability == pytest.approx(0.575)          # 0.50 + 0.25 * (0.80 - 0.50)
    assert f.market_prob == 0.50                           # graded against the same market price
    assert f.payload == {"k": 1, "raw_probability": 0.80, "weight": 0.25}


def test_it_is_its_own_forecaster_so_the_pure_model_is_never_replaced():
    inner = Inner()
    fc = MarketShrunk(inner)
    assert (fc.name, fc.version, fc.cadence) == ("model_x_cautious", "v1+w25", "daily")
    assert (inner.name, inner.version) == ("model_x", "v1")


def test_it_stays_inside_zero_and_one_at_the_extremes():
    for model, market in ((1.0, 0.0), (0.0, 1.0), (1.0, 1.0)):
        f = MarketShrunk(Inner(model, market)).forecast(CalendarEntry("kalshi:T1", "f", "daily", CUTOFF), NOW)
        assert 0.0 <= f.probability <= 1.0


def test_with_no_market_price_there_is_nothing_to_shrink_toward_so_it_is_a_gap_not_a_guess():
    fc = MarketShrunk(Inner(market=None))
    assert fc.forecast(fc.targets(NOW)[0], NOW) is None


def test_only_market_linked_targets_are_forecast():
    assert MarketShrunk(Inner(linked=False)).targets(NOW) == []


def test_settlement_is_the_inner_forecasters_not_a_second_opinion():
    inner = Inner()
    assert MarketShrunk(inner).settle("kalshi:T1", NOW).outcome == 1 and inner.settled == ["kalshi:T1"]


def test_end_to_end_the_cautious_row_scores_beside_the_pure_one_on_the_same_target():
    db = FakeJournalDB(lambda: NOW)
    inner = Inner(prob=0.95, market=0.50)
    run_journal(db, [inner, MarketShrunk(inner)], NOW)
    later = CUTOFF + timedelta(hours=1)
    db.clock = lambda: later
    out = run_journal(db, [inner, MarketShrunk(inner)], later)
    assert not out["failures"]
    rows = {r["forecaster"]: r for r in db.tables["journal_forecasts"]}
    assert rows["model_x"]["probability"] == pytest.approx(0.95)
    assert rows["model_x_cautious"]["probability"] == pytest.approx(0.6125)
    cards = {r["forecaster"]: r for r in db.tables["journal_scores"]}
    assert cards["model_x_cautious"]["n_settled"] == cards["model_x"]["n_settled"] == 1
    # the event happened (outcome 1): the pure model is closer, so it must have the lower Brier here;
    # the point is that both are scored on identical targets and the market price is the baseline
    assert cards["model_x"]["baseline"] == cards["model_x_cautious"]["baseline"] == "market"


def test_the_registry_wraps_every_market_linked_model_and_no_pseudo_forecaster():
    from tradehub.journal.registry import FORECASTERS

    names = [f.name for f in FORECASTERS]
    for expected in ("cpi_nowcast_cautious", "labor_nowcast_cautious", "fomc_mapped_cautious",
                     "sports_nfl_cautious", "sports_cfb_spread_cautious", "sports_nfl_total_cautious"):
        assert expected in names
    assert not any(n.startswith("kalshi_implied_") and n.endswith("_cautious") for n in names)
    assert not any(n in names for n in ("spy_quant_cautious", "housing_direction_cautious"))  # no market price
    assert len(set((f.name, f.version) for f in FORECASTERS)) == len(FORECASTERS)
```

- [ ] **Step 2: Run it** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_shrunk.py` — Expected: FAIL (the code below does not exist yet).

- [ ] **Step 3: Implement**

`tradehub/journal/forecasters/shrunk.py`:

```python
"""Market-anchored caution (plan 15): a model's probability pulled most of the way back to the Kalshi price.

Today's models are overconfident against the market: where they disagree with the price, the price has
been right more often. A forecast that starts from the market and moves only a fixed fraction toward the
model can lose to the market by at most that fraction of the disagreement, and it still wins whenever the
model really knows something. It cannot create skill. It tells us whether any exists, and it stops the
overconfidence from costing 4x the market's error.

The weight is set here, once, before any result is looked at, and never tuned on journal results. A
different weight is a different forecaster: it is part of the version string (`v1+w25`), so a change
starts a new scorecard instead of rewriting history.

The wrapper is its own forecaster beside the pure model, which keeps scoring exactly as it was. It adds no
settlement of its own: it settles on whatever the wrapped forecaster settles on. With no market price there
is nothing to shrink toward, so that is a gap, never a guess.
"""

from __future__ import annotations

from datetime import datetime

from tradehub.journal.contract import CalendarEntry, Forecast, Forecaster, Settlement

SHRINK_WEIGHT = 0.25
SUFFIX = "_cautious"


class MarketShrunk:
    def __init__(self, inner: Forecaster, weight: float = SHRINK_WEIGHT):
        if not 0.0 < weight < 1.0:
            raise ValueError("weight must be strictly between 0 and 1")
        self.inner, self.weight = inner, weight
        self.name = f"{inner.name}{SUFFIX}"
        self.version = f"{inner.version}+w{round(weight * 100)}"
        self.cadence = inner.cadence

    def targets(self, now: datetime) -> list[CalendarEntry]:
        return [e for e in self.inner.targets(now) if e.market_linked]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        raw = self.inner.forecast(entry, now)
        if raw is None or raw.market_prob is None:
            return None
        probability = raw.market_prob + self.weight * (raw.probability - raw.market_prob)
        return Forecast(self.name, self.version, entry.target, probability, market_prob=raw.market_prob,
                        payload={**raw.payload, "raw_probability": raw.probability, "weight": self.weight})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return self.inner.settle(target, now)
```

`tradehub/journal/registry.py`:

```diff
diff --git a/tradehub/journal/registry.py b/tradehub/journal/registry.py
index 29ad99d..07a6d61 100644
--- a/tradehub/journal/registry.py
+++ b/tradehub/journal/registry.py
@@ -15,6 +15,7 @@ from tradehub.journal.forecasters.fomc import FOMC_SERIES, FomcMapped, is_hold_m
 from tradehub.journal.forecasters.housing import HousingForecaster
 from tradehub.journal.forecasters.labor import LaborData, PayrollsForecaster, QuitsDirection, UnrateDirection
 from tradehub.journal.forecasters.sentiment import SentimentMeter
+from tradehub.journal.forecasters.shrunk import MarketShrunk
 from tradehub.journal.forecasters.sports import build_sports
 from tradehub.journal.forecasters.spy_quant import SpyQuant
 from tradehub.journal.kalshi_linked import KalshiImplied
@@ -47,3 +48,9 @@ FORECASTERS: list[Forecaster] = [
     # wave 3 (spec §8): NFL and CFB feed consumers, each beside its Kalshi-implied baseline
     *build_sports(),
 ]
+
+# plan 15: the market-linked models again, each pulled toward the Kalshi price (see forecasters/shrunk.py).
+# Their own scorecards, beside the pure models', which are untouched.
+_SHRINKABLE = {"cpi_nowcast", "fomc_mapped", "labor_nowcast"}
+FORECASTERS += [MarketShrunk(f) for f in list(FORECASTERS)
+                if f.name in _SHRINKABLE or f.name.startswith("sports_")]
```

- [ ] **Step 4: Run** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_shrunk.py tests/test_journal_sports.py tests/test_journal_runner.py` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tradehub/journal tests/test_journal_shrunk.py
git commit -m "feat(journal): cautious copies of the market-linked models"
```

---

### Task 2: Names the page can read

**Files:**
- Modify: `market_sentiment_tool/src/lib/forecasterLabels.ts`, `market_sentiment_tool/src/lib/journal.ts`, `market_sentiment_tool/src/lib/journalView.test.ts`

**Interfaces:**
- Produces: `CAUTIOUS_SUFFIX`; `forecasterLabel('cpi_nowcast_cautious', 'cpi-core-v1+w25')` is `Core inflation (CPI) (cautious)`; a cautious row folds the same Kalshi baseline as its model.

- [ ] **Step 1: Write the failing test** (`market_sentiment_tool/src/lib/journalView.test.ts`)

The new test is in the diff below.

- [ ] **Step 2: Run it** — `cd market_sentiment_tool && npx vitest run src/lib/journalView.test.ts` — Expected: FAIL (the code below does not exist yet).

- [ ] **Step 3: Implement**

```diff
diff --git a/market_sentiment_tool/src/lib/forecasterLabels.ts b/market_sentiment_tool/src/lib/forecasterLabels.ts
index 19dc057..3950104 100644
--- a/market_sentiment_tool/src/lib/forecasterLabels.ts
+++ b/market_sentiment_tool/src/lib/forecasterLabels.ts
@@ -25,7 +25,14 @@ const VERSIONED: Record<string, string> = {
   "cpi_nowcast@cpi-core-v1": "Core inflation (CPI)",
 };
 
+/** Plan 15: a market-anchored copy of a model, graded beside it. Named after the model it shadows. */
+export const CAUTIOUS_SUFFIX = "_cautious";
+
 export function forecasterLabel(forecaster: string, version?: string): string {
+  if (forecaster.endsWith(CAUTIOUS_SUFFIX)) {
+    const base = version?.replace(/\+w\d+$/, "");
+    return `${forecasterLabel(forecaster.slice(0, -CAUTIOUS_SUFFIX.length), base)} (cautious)`;
+  }
   if (version && VERSIONED[`${forecaster}@${version}`]) return VERSIONED[`${forecaster}@${version}`];
   if (BASE[forecaster]) return BASE[forecaster];
   const text = forecaster.replace(/_/g, " ");
diff --git a/market_sentiment_tool/src/lib/journal.ts b/market_sentiment_tool/src/lib/journal.ts
index aad832d..c5e97ac 100644
--- a/market_sentiment_tool/src/lib/journal.ts
+++ b/market_sentiment_tool/src/lib/journal.ts
@@ -118,7 +118,7 @@ export function tiles(scores: JournalScore[]): Tile[] {
   const used = new Set<string>();
   const out: Tile[] = [];
   for (const model of scores.filter((s) => !isMarket(s))) {
-    const pair = MARKET_PAIR[model.forecaster];
+    const pair = MARKET_PAIR[model.forecaster.replace(/_cautious$/, "")];
     const market = pair ? markets.get(pair) ?? null : null;
     if (market) used.add(market.forecaster);
     out.push({ model, market });
diff --git a/market_sentiment_tool/src/lib/journalView.test.ts b/market_sentiment_tool/src/lib/journalView.test.ts
index c7054dd..ef24c43 100644
--- a/market_sentiment_tool/src/lib/journalView.test.ts
+++ b/market_sentiment_tool/src/lib/journalView.test.ts
@@ -61,6 +61,17 @@ describe("view", () => {
     expect(rows.find((r) => r.label === "NFL game totals")?.market).toBeNull();
   });
 
+  it("names a cautious copy after its model and grades it against the same Kalshi baseline", () => {
+    const rows = viewRows([
+      score({ forecaster: "cpi_nowcast_cautious", forecaster_version: "cpi-core-v1+w25", baseline: "market", n_targets: 3 }),
+      score({ forecaster: "sports_nfl_spread_cautious", forecaster_version: "feed-v1+w25", baseline: "market", n_targets: 2 }),
+      score({ forecaster: "kalshi_implied_cpi", forecaster_version: "v1", n_targets: 3 }),
+      score({ forecaster: "kalshi_implied_sports_nfl_spread", forecaster_version: "v1", n_targets: 2 }),
+    ]);
+    expect(rows.map((r) => r.label).sort()).toEqual(["Core inflation (CPI) (cautious)", "NFL point spreads (cautious)"]);
+    expect(rows.every((r) => r.market !== null)).toBe(true);
+  });
+
   it("counts what the page headlines, and a monthly forecaster needs 50 not 200", () => {
     const rows = viewRows(scores);
     expect(totals(rows)).toEqual({ forecasters: 3, frozen: 12, scored: 4, promoted: 0 });
```

- [ ] **Step 4: Run** — `cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx vite build` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/src/lib
git commit -m "feat(ui): label and pair the cautious rows"
```

---

### Task 3: Verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass (reviewer baseline on the final stack: see the roadmap).

- [ ] Ruff on the files this plan created or changed: `.venv/bin/python -m ruff check --select F tradehub/journal/forecasters/shrunk.py tests/test_journal_shrunk.py` → `All checks passed!` (import-order findings on files you did not create are older debt, not yours).
- [ ] Frontend: `cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx vite build` — all green.
- [ ] In the PR body, copy the Brier table from the Global Constraints above and say that it is the expectation to check, not a result of this PR.
- [ ] Open the PR from a fresh branch off `main` (title in the roadmap). Body: what changed, the verification output, and whether a migration needs applying. Then stop and report in 4 lines.

---

## Self-Review

- **The pure model is never replaced:** the end-to-end test freezes both on one target and scores both; the cautious one is its own scorecard.
- **Arithmetic pinned:** 0.50 + 0.25 x (0.80 - 0.50) = 0.575, and the extremes stay inside [0, 1].
- **Honest framing:** the weight is a constant chosen in advance; changing it is a new version string.
