# Cuts: FinBERT and the Prediction Lab (Plan j) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the FinBERT sentiment filter and the /lab Prediction Lab page, leaving guard tests that keep them deleted, and record the three larger cuts that are deliberately not made here.

**Architecture:** Two independent deletions, each with a guard. Backend: `tradehub/core/sentiment_filter.py` goes, and its only two callers lose the path (`ai_validator`'s Macro-only pre-filter; `feature_engineering`'s news column becomes a neutral constant so stored feature lists still line up). Frontend: `PredictionLab.tsx` and its two test files go, the nav link goes, and `/lab` redirects to `/journal` so no link 404s. Nothing else becomes an orphan: every module the lab imported is used elsewhere (checked with an import-graph script).

**Tech Stack:** Python 3.12, React + TypeScript, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§9 Cuts (sentiment_filter, /lab)). **Depends on:** plans (a)–(f) merged (the sentiment meter, plan d, is what replaces the FinBERT path).

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (backend 1395 passed at monotonic 5.0 and at 1e7; vitest 428 passed, tsc/eslint clean, build succeeds). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- **Deliberately NOT cut here (Kevin's decision, see the last section):** `tradehub/engines/macro_engine.py`, `tradehub/engines/quant_engine.py`, `tradehub/scripts/background_scanner.py`. Do not delete or edit them in this PR.
- The `hourly_news_sentiment` column stays in `feature_engineering.py` (constant `0.0`): stored model feature lists name it, and removing it would change a contract this plan is not authorised to change.
- `/lab` must redirect to `/journal` (`Navigate replace`), never 404.
- Do not touch `tests/test_weather_macro_quarantine.py` or the quarantine modules: spec §12 says the quarantine-safety tests stay untouched.

---
### Task 1: Delete the FinBERT path

**Files:**
- Delete: `tradehub/core/sentiment_filter.py`
- Modify: `tradehub/core/ai_validator.py`, `tradehub/core/feature_engineering.py`
- Test: `tests/test_cuts.py` (create)

**Interfaces:**
- Produces: a guard test that fails if `tradehub/core/sentiment_filter.py` exists, or if any `tradehub` module imports `sentiment_filter`, `transformers` or `torch`, or if the neutral `hourly_news_sentiment` column contract changes.

- [ ] **Step 1: Write the failing test** (`tests/test_cuts.py`)

```python
"""Guards for the v2 spec §9 cuts: what was deleted stays deleted, and nothing imports it."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = [p for p in (ROOT / "tradehub").rglob("*.py") if "__pycache__" not in p.parts]


def test_the_finbert_sentiment_filter_is_gone_and_nothing_imports_it():
    assert not (ROOT / "tradehub/core/sentiment_filter.py").exists()
    offenders = []
    for path in CODE:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any("sentiment_filter" in n or n.split(".")[0] in {"transformers", "torch"} for n in names):
                offenders.append(f"{path.relative_to(ROOT)}: {names}")
    assert not offenders, offenders



def test_the_feature_contract_still_lists_the_neutral_news_column():
    # The column stays so stored model feature lists still line up; it is constant 0.0 (no news source).
    source = (ROOT / "tradehub/core/feature_engineering.py").read_text(encoding="utf-8")
    assert "'hourly_news_sentiment'," in source and "df['hourly_news_sentiment'] = 0.0" in source
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_cuts.py -v`
Expected: FAIL — the file still exists and `ai_validator.py` / `feature_engineering.py` import it.

- [ ] **Step 3: Implement**

```bash
git rm tradehub/core/sentiment_filter.py
```

Apply these changes (the Macro-only HuggingFace tier in `ai_validator` was dead the moment the meter replaced FinBERT, and `get_stats` loses its HuggingFace counters):

```diff
diff --git a/tradehub/core/ai_validator.py b/tradehub/core/ai_validator.py
index 3cb977d..d355116 100644
--- a/tradehub/core/ai_validator.py
+++ b/tradehub/core/ai_validator.py
@@ -29,25 +29,12 @@ class AIValidator:
         self.client = genai.Client(api_key=api_key)
         self.model_name = 'gemini-2.5-flash'
 
-        # Add Hugging Face pre-filter
-        try:
-            from tradehub.core.sentiment_filter import SentimentFilter
-            self.sentiment_filter = SentimentFilter()
-        except Exception as e:
-            print(f"⚠️ HuggingFace SentimentFilter not available: {e}")
-            self.sentiment_filter = None
-
         # Track API usage
         self.gemini_calls = 0
-        self.hf_auto_approved = 0
 
     def validate_trade(self, opportunity, recent_news=None):
         """
-        Validate a trade using two-tier system:
-        1. First: Hugging Face sentiment filter (free, local)
-        2. Only if needed: Gemini API (paid)
-
-        This saves ~70% of Gemini API costs.
+        Validate a trade with the Gemini API.
 
         Returns:
             dict: {
@@ -55,48 +42,14 @@ class AIValidator:
                 'ai_reasoning': str,
                 'risk_factors': list,
                 'confidence': int (1-10),
-                'tier': str ('huggingface'|'gemini'|'fallback'),
+                'tier': str ('gemini'|'fallback'),
                 'ai_used': bool,
                 'error': str or None
             }
         """
 
-        # TIER 1: Hugging Face Pre-Filter (only for Macro trades)
-        if self.sentiment_filter and opportunity.get('engine') == 'Macro':
-            try:
-                pre_filter = self.sentiment_filter.pre_filter_macro_trade(
-                    opportunity,
-                    recent_news=recent_news
-                )
-
-                if pre_filter['auto_approve']:
-                    self.hf_auto_approved += 1
-                    return {
-                        'approved': True,
-                        'ai_reasoning': f"[HuggingFace] {pre_filter['reasoning']}",
-                        'risk_factors': [],
-                        'confidence': 8,
-                        'tier': 'huggingface',
-                        'ai_used': True,
-                        'error': None
-                    }
-
-                elif pre_filter['auto_reject']:
-                    return {
-                        'approved': False,
-                        'ai_reasoning': f"[HuggingFace] {pre_filter['reasoning']}",
-                        'risk_factors': ['Sentiment conflict detected'],
-                        'confidence': 2,
-                        'tier': 'huggingface',
-                        'ai_used': True,
-                        'error': None
-                    }
-
-                # If not auto-approved/rejected, fall through to Gemini
-            except Exception as e:
-                print(f"HuggingFace pre-filter error: {e}")
-
-        # TIER 2: Gemini API (for uncertain cases or non-Macro trades)
+        # Gemini API. The local HuggingFace pre-filter (Macro trades only) was deleted with the macro engine
+        # and the FinBERT path (v2 spec §9).
         self.gemini_calls += 1
 
         prompt = f"""
@@ -249,15 +202,7 @@ Rules: Block only for: exchange hack, {symbol.replace('USDT','')} regulatory act
 
     def get_stats(self):
         """Return usage statistics"""
-        total_validations = self.gemini_calls + self.hf_auto_approved
-        savings = (self.hf_auto_approved / total_validations * 100) if total_validations > 0 else 0
-
-        return {
-            'total_validations': total_validations,
-            'gemini_api_calls': self.gemini_calls,
-            'huggingface_auto_approved': self.hf_auto_approved,
-            'api_cost_savings': f"{savings:.1f}%"
-        }
+        return {'total_validations': self.gemini_calls, 'gemini_api_calls': self.gemini_calls}
 
 
     def validate_top_edges(self, top_edges):
diff --git a/tradehub/core/feature_engineering.py b/tradehub/core/feature_engineering.py
index e7300d3..c6fb317 100644
--- a/tradehub/core/feature_engineering.py
+++ b/tradehub/core/feature_engineering.py
@@ -1,7 +1,7 @@
 """
 Feature Engineering — 3-Cluster Microstructure + Derivatives Pipeline
 
-Cluster 1: Momentum & Sentiment (RSI, MACD, Price Acceleration, FinBERT)
+Cluster 1: Momentum & Sentiment (RSI, MACD, Price Acceleration; news sentiment is neutral, see below)
 Cluster 2: Market Microstructure (Amihud, Corwin-Schultz, RVOL)
 Cluster 3: Derivatives Positioning (Black-Scholes GEX + fallback proxy)
 
@@ -58,59 +58,6 @@ def add_momentum_features(df):
     return df
 
 
-def add_finbert_sentiment(df, ticker="SPY"):
-    """
-    Pipes Alpaca news stream through local FinBERT model.
-    Returns hourly_news_sentiment score (-1 to +1).
-    Falls back to 0.0 if models unavailable.
-    """
-    try:
-        from tradehub.core.sentiment_filter import SentimentFilter
-        sf = SentimentFilter()
-
-        # Try fetching recent Alpaca news
-        try:
-            from alpaca.data.historical import StockHistoricalDataClient
-            from alpaca.data.requests import NewsRequest
-            import os
-
-            api_key = os.getenv("ALPACA_API_KEY", "")
-            secret_key = os.getenv("ALPACA_SECRET_KEY", "")
-
-            if api_key and secret_key:
-                client = StockHistoricalDataClient(api_key, secret_key)
-                # Fetch recent news for the ticker
-                news_req = NewsRequest(symbols=[ticker], limit=10)
-                news = client.get_news(news_req)
-
-                if news:
-                    sentiments = []
-                    for article in news:
-                        headline = article.headline if hasattr(article, 'headline') else str(article)
-                        result = sf.analyze_fed_statement(headline)
-                        # Map: positive=+1, negative=-1, neutral=0
-                        score = result.get('confidence', 0.5)
-                        if result.get('sentiment') == 'negative':
-                            score = -score
-                        elif result.get('sentiment') == 'neutral':
-                            score = 0
-                        sentiments.append(score)
-
-                    avg_sentiment = np.mean(sentiments) if sentiments else 0.0
-                    df['hourly_news_sentiment'] = avg_sentiment
-                    return df
-        except Exception:
-            pass
-
-        # Fallback: set to neutral
-        df['hourly_news_sentiment'] = 0.0
-        return df
-
-    except Exception:
-        df['hourly_news_sentiment'] = 0.0
-        return df
-
-
 # ═══════════════════════════════════════════════════════════════
 # CLUSTER 2: MARKET MICROSTRUCTURE (LIQUIDITY)
 # ═══════════════════════════════════════════════════════════════
@@ -473,8 +420,9 @@ def create_features(df, ticker="SPY"):
     # Cluster 1: Momentum
     df = add_momentum_features(df)
 
-    # Cluster 1: Sentiment
-    df = add_finbert_sentiment(df, ticker)
+    # Cluster 1: Sentiment. The FinBERT news path was deleted (v2 spec §9; the sentiment meter replaced it),
+    # and the column stays so the feature contract is unchanged: there is no news source, so it is neutral.
+    df['hourly_news_sentiment'] = 0.0
 
     # Cluster 2: Microstructure
     df = add_microstructure_features(df)
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_cuts.py -v && SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider`
Expected: 2 new tests pass and the whole suite passes.

- [ ] **Step 5: Commit**

```bash
git add tests/test_cuts.py tradehub/core/ai_validator.py tradehub/core/feature_engineering.py
git commit -m "cut: delete the FinBERT sentiment filter (the meter replaced it)"
```

---

### Task 2: Remove the Prediction Lab and redirect /lab

**Files:**
- Delete: `market_sentiment_tool/src/pages/PredictionLab.tsx`, `market_sentiment_tool/src/pages/PredictionLab.cpiDisplay.test.tsx`, `market_sentiment_tool/src/pages/PredictionLab.stoppedEngines.test.tsx`
- Modify: `market_sentiment_tool/src/App.tsx`, `market_sentiment_tool/src/App.routes.test.tsx`

**Interfaces:**
- Produces: `/lab` → `/journal` redirect; no "Prediction Lab" nav entry. The deleted tests pinned the lab page only; the properties they pinned live on where they always lived (`cpiDisplay.ts`, `displayOnlyEngines.ts`, `StoppedEnginesNotice`, each with its own tests, all kept).

- [ ] **Step 1: Write the failing test.** Apply only the `App.routes.test.tsx` hunks of the diff below (the new `redirects the retired /lab to the journal` test and the import/comment tweaks), then run it:

Run: `cd market_sentiment_tool && npx vitest run src/App.routes.test.tsx`
Expected: FAIL — `/lab` still renders the lab, not the journal heading.

- [ ] **Step 2: Implement**

```bash
git rm market_sentiment_tool/src/pages/PredictionLab.tsx market_sentiment_tool/src/pages/PredictionLab.cpiDisplay.test.tsx market_sentiment_tool/src/pages/PredictionLab.stoppedEngines.test.tsx
```

```diff
diff --git a/market_sentiment_tool/src/App.routes.test.tsx b/market_sentiment_tool/src/App.routes.test.tsx
index a343a20..9878d86 100644
--- a/market_sentiment_tool/src/App.routes.test.tsx
+++ b/market_sentiment_tool/src/App.routes.test.tsx
@@ -6,7 +6,7 @@ import type { ModelsResponse } from "@/lib/models";
 import type { ShadowPerformanceResponse } from "@/lib/shadowPerformance";
 
 // `src/lib/supabase.ts` builds a real client at import time and THROWS when the publishable key is
-// absent, so importing `App` -- which pulls in `Home` and `PredictionLab` -> `useMarketEdges` --
+// absent, so importing `App` -- which pulls in `Home` -> `useMarketEdges` --
 // fails before a single assertion runs. The stub is a stand-in for a credential this test does not
 // need: neither route rendered here reads a Supabase table directly (the API does), so nothing
 // calls it. Setting a fake URL instead would be worse: it would let a test that means to prove
@@ -196,6 +196,15 @@ describe("the sidebar link and the route agree", () => {
     expect(screen.getByRole("link", { name: /journal/i })).toHaveAttribute("href", "/journal");
   });
 
+  it("redirects the retired /lab to the journal without a 404", async () => {
+    // The Prediction Lab was cut (v2 spec §9). Old links must land somewhere real, not on an empty shell.
+    await renderAppAt("/lab");
+
+    expect(screen.getByRole("heading", { name: "Prediction Journal", level: 1 })).toBeInTheDocument();
+    expect(window.location.pathname).toBe("/journal");
+    expect(screen.queryByRole("link", { name: /prediction lab/i })).not.toBeInTheDocument();
+  });
+
   it("renders no models page on a path with no route", async () => {
     // The control. Without it the test above would also pass if the page rendered unconditionally
     // -- a bug the deletion it guards against and a missing guard both look like.
diff --git a/market_sentiment_tool/src/App.tsx b/market_sentiment_tool/src/App.tsx
index 0303c17..684cd4e 100644
--- a/market_sentiment_tool/src/App.tsx
+++ b/market_sentiment_tool/src/App.tsx
@@ -1,7 +1,6 @@
 import { BrowserRouter, Routes, Route, NavLink, Navigate } from "react-router-dom";
 // Pages
 import Home from "@/pages/Home";
-import PredictionLab from "@/pages/PredictionLab";
 import ShadowBacktester from "@/pages/ShadowBacktester";
 import Models from "@/pages/Models";
 import Scoreboard from "@/pages/Scoreboard";
@@ -11,7 +10,7 @@ import CpiDisplay from "@/pages/CpiDisplay";
 import Journal from "@/pages/Journal";
 import { usePortfolio } from "@/hooks/usePortfolio";
 import { portfolioHeadline } from "@/lib/portfolioTruth";
-import { LayoutDashboard, Activity, Wallet, Brain, Cpu, LineChart, Scale, Trophy, Briefcase, BarChart3, BookOpen } from "lucide-react";
+import { LayoutDashboard, Activity, Wallet, Cpu, LineChart, Scale, Trophy, Briefcase, BarChart3, BookOpen } from "lucide-react";
 
 const Sidebar = () => {
   const { portfolio } = usePortfolio();
@@ -38,12 +37,6 @@ const Sidebar = () => {
         >
           <LayoutDashboard className="w-5 h-5" /> Portfolio
         </NavLink>
-        <NavLink 
-          to="/lab" 
-          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
-        >
-          <Brain className="w-5 h-5 text-emerald-500" /> Prediction Lab
-        </NavLink>
         {/* "Crypto Shadow", not "Shadow". This is the nav entry that cost the owner a page on
             2026-09-28: a list item reading "Shadow" beside one reading "Scoreboard" reads as two
             halves of the same thing, and they are not. This page is the crypto shadow-timeline
@@ -147,7 +140,9 @@ function App() {
       <AppShell>
         <Routes>
           <Route path="/" element={<Home />} />
-          <Route path="/lab" element={<PredictionLab />} />
+          {/* /lab was the Prediction Lab; the journal replaced it (v2 spec §9). A redirect, not a 404, so
+              bookmarks and links keep working. */}
+          <Route path="/lab" element={<Navigate to="/journal" replace />} />
           {/* The crypto shadow-timeline backtester, which keeps the /shadow route it has always
               had. It is NOT the scoreboard and never becomes it: a redirect from here to the
               scoreboard would swap a crypto backtester for an engine scoreboard without saying so,
```

- [ ] **Step 3: Run to verify it passes**

Run: `cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx eslint src/App.tsx && npx vite build`
Expected: vitest all pass (reviewer baseline 428), tsc and eslint silent, build succeeds.

- [ ] **Step 4: Commit**

```bash
git add -A market_sentiment_tool/src
git commit -m "cut: remove the Prediction Lab; /lab redirects to /journal"
```

---

### Task 3: Verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass.

- [ ] Ruff on every file this plan created or changed: `.venv/bin/python -m ruff check <files>` → `All checks passed!` (pre-existing ruff debt elsewhere is not yours to fix here).
- [ ] Open the PR from a fresh branch off `main`. Body: what changed, the verification output, and whether a migration needs applying.

## Not cut here, and the decision Kevin owes

Spec §9 also lists `macro_engine.py` and the `quant_engine.py` remote-pickle loader. They are **not** in this plan because the two spec sections conflict and the code is entangled:

- `tradehub/scripts/background_scanner.py` (the legacy daemon, not deployed on the VPS and not run by any timer) imports both `MacroEngine` and `quant_engine`, and its `run_scan` publishing path is built around the quant signals. Removing either engine means removing or gutting the daemon.
- §12 says "the existing quarantine-safety test untouched", but `tests/test_weather_macro_quarantine.py` (about 1,150 lines) drives `background_scanner.run_scan` and `MacroEngine` directly, and `tests/test_engine_health.py` pins `MacroEngine` as a stopped site at `tradehub/engines/macro_engine.py:459`. Deleting the engines forces a rewrite of those pinned tests.
- `tradehub/engine_health.py` lists `MacroEngine` as a ruled-against site, and `MACRO` is still an edge type that `scan.py`'s labor/CPI engines publish under quarantine.

**Options for Kevin:** (1) keep the legacy daemon and both engines (they are dead weight but quarantined and tested); (2) delete the daemon, `macro_engine`, `quant_engine` and `ai_validator`'s callers together, and re-home the quarantine-safety tests onto `scan.py`, the code path that actually publishes now. The reviewer recommends (2) as its own plan with its own PR, and will write it on request. Until then, leave them.

## Self-Review

- **Spec §9:** `sentiment_filter` FinBERT path deleted on meter launch (Task 1); `/lab` removed and redirects to `/journal` with no 404, `PredictionLab.tsx` deleted (Task 2). `macro_engine` and `quant_engine` are explicitly deferred with the reason above rather than silently skipped.
- **No orphans:** an import-graph check found no module kept alive only by the lab page, so no other deletion is owed.
- **Guards:** the FinBERT deletion cannot be undone without `tests/test_cuts.py` failing; the redirect is pinned by the route test.
