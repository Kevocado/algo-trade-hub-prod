# Site Cleanup: Delete What We Decided to Drop (Plan n) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove about 8,100 lines of code, tests and UI components that nothing reaches, so the codebase and the shipped site contain only what the product uses.

**Architecture:** Pure deletion plus the smallest edits needed so everything that remains still builds. Every deleted file was proven unreferenced (import-graph scripts for Python and the frontend, plus grep), and the whole backend and frontend suites were run after deleting. Nothing live changes: the VPS timers run `scan`, `settle` and `journal`, none of which touch these files.

**Tech Stack:** Python 3.12, React + TypeScript, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§9 Cuts (and the 2026-09-30 decision to delete the legacy daemon)). **Depends on:** plans (j) and (m) merged (they are); independent of the other open plans.

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (backend 1428 passed at monotonic 5.0 and at 1e7; frontend vitest 388 passed, tsc clean, build succeeds; lines removed: 8,130 in the commit). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- **Before deleting, tag the old state** so nothing is lost: `git tag legacy/pre-cleanup-2026-10-01 origin/main && git push origin legacy/pre-cleanup-2026-10-01` (the reviewer may already have done this; skip if the tag exists).
- **Kept on purpose, do not delete:** `shared/feature_engine.py` (imported by `shared/__init__.py` and `crypto_features.py`), `shared/crypto_features.py`, `shared/kalshi_fees.py`, `shared/kalshi_ws.py`, `shared/config.py`, `tradehub/engines/weather_engine.py` and `weather_maker.py` (pinned by the engine-health ruling), `tradehub/quarantine.py`, `tradehub/engine_health.py` and their API endpoints and tests, `market_sentiment_tool/backend/` (the crypto operator plane), `archive/` and `research/` (parked, pinned by `tests/test_repo_layout.py`), the Crypto Shadow page, and the four shadcn components still imported (`badge`, `card`, `skeleton`, `table`).
- **Do not touch `package.json` or the lockfile here.** Some `@radix-ui/*` packages are now unused; removing them is a separate follow-up with its own `npm install --package-lock-only` check.
- The `scanner` extra in `pyproject.toml` keeps its name (CI and the README install with `--extra scanner`) but shrinks to the two packages `tradehub/core/data_loader.py` still imports.
- `/api/opportunities` and `/api/nws_weather` are removed: no frontend, test or script used them and their cache had no writer since the daemon was deleted.
- The eslint warnings and the one `no-explicit-any` error already on `main` (in `QuarantineNotice.tsx`, `WithheldEdgesNotice.tsx`, `ui/badge.tsx`, `useMarketEdges.ts`) are not yours to fix here.

---
### Task 1: Delete the dead Python

**Files:**
- Delete: `shared/api_server.py`, `shared/background_scanner.py`, `shared/fast_scanner.py`, `shared/weather_features.py`, `tradehub/core/ai_validator.py`, `tradehub/core/microstructure_engine.py`, `tradehub/core/news_analyzer.py`, `tradehub/core/predictit_engine.py`
- Modify: `tradehub/api/main.py`, `tradehub/api/schemas.py`, `tradehub/api/dependencies.py`, `pyproject.toml`, `tests/test_kalshi_edge_system.py`

**Interfaces:**
- Produces: an API without `/api/opportunities`, `/api/nws_weather`, `Opportunity`, `NWSReading`, `get_scanner_cache` or `update_scanner_cache`; a `scanner` extra of `fredapi` and `python-dateutil`.

- [ ] **Step 1: Tag the old state** (skip if it exists)

```bash
git tag legacy/pre-cleanup-2026-10-01 origin/main && git push origin legacy/pre-cleanup-2026-10-01
```

- [ ] **Step 2: Write the guard first** (`tests/test_cleanup_gone.py`), watch it fail, then delete:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DELETED = [
    "shared/api_server.py",
    "shared/background_scanner.py",
    "shared/fast_scanner.py",
    "shared/weather_features.py",
    "tradehub/core/ai_validator.py",
    "tradehub/core/microstructure_engine.py",
    "tradehub/core/news_analyzer.py",
    "tradehub/core/predictit_engine.py",
]


def test_the_cleaned_up_python_files_stay_deleted():
    assert [p for p in DELETED if (ROOT / p).exists()] == []


def test_the_cache_backed_endpoints_are_gone():
    from tradehub.api.main import app

    paths = {route.path for route in app.routes}
    assert "/api/opportunities" not in paths and "/api/nws_weather" not in paths
```

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_cleanup_gone.py -v` — Expected: both FAIL.

- [ ] **Step 3: Delete and edit**

```bash
git rm shared/api_server.py shared/background_scanner.py shared/fast_scanner.py shared/weather_features.py tradehub/core/ai_validator.py tradehub/core/microstructure_engine.py tradehub/core/news_analyzer.py tradehub/core/predictit_engine.py
```

```diff
diff --git a/pyproject.toml b/pyproject.toml
index 1274ade..77815ba 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -26,16 +26,11 @@ dependencies = [
 ]
 
 [project.optional-dependencies]
-# Heavier deps once used by the deleted background_scanner daemon's AI/news path and HF model downloads.
-# `google-genai` is still imported by tradehub/core/ai_validator.py; the rest are candidates for removal.
+# `scanner` is the name CI and the README install with. fredapi and python-dateutil are what
+# tradehub/core/data_loader.py still imports; the AI/news/HF packages went with the deleted daemon.
 scanner = [
     "fredapi>=0.5.1",
-    "google-genai>=0.1.0",
-    "huggingface_hub",
     "python-dateutil",
-    "sentencepiece>=0.1.99",
-    "torch>=2.1.0",
-    "transformers>=4.36.0",
 ]
 research = [
     "apscheduler>=3.10.4",
diff --git a/tests/test_kalshi_edge_system.py b/tests/test_kalshi_edge_system.py
index d6ee852..f034a2d 100644
--- a/tests/test_kalshi_edge_system.py
+++ b/tests/test_kalshi_edge_system.py
@@ -8,7 +8,6 @@ Tests are designed to work offline (no real API calls) using mocks.
 
 import asyncio
 import pytest
-from unittest.mock import MagicMock, patch
 from datetime import datetime, timezone
 
 # Add project root to path
@@ -38,12 +37,6 @@ class TestFastAPIEndpoints:
         assert data["status"] == "ok"
         assert "timestamp" in data
 
-    def test_opportunities_empty_when_cache_empty(self, client):
-        """With an empty cache, should return empty list, not 500."""
-        response = client.get("/api/opportunities")
-        assert response.status_code == 200
-        assert isinstance(response.json(), list)
-
     def test_docs_available(self, client):
         """Swagger UI should be accessible."""
         response = client.get("/docs")
@@ -322,34 +315,3 @@ class TestTelegramCommands:
         text = asyncio.run(tn._get_scan_text("weather"))
 
         assert "Unsupported domain" in text
-
-# ════════════════════════════════════════════════════════════════════
-# Microstructure Engine Tests
-# ════════════════════════════════════════════════════════════════════
-
-class TestMicrostructureEngine:
-    """Tests MicrostructureEngine Binance features (pure math, no live API)."""
-
-    def test_funding_signal_extreme_long(self):
-        from tradehub.core.microstructure_engine import MicrostructureEngine
-        sig = MicrostructureEngine._funding_signal(2.5)
-        assert "short" in sig.lower()
-
-    def test_funding_signal_extreme_short(self):
-        from tradehub.core.microstructure_engine import MicrostructureEngine
-        sig = MicrostructureEngine._funding_signal(-2.5)
-        assert "long" in sig.lower()
-
-    def test_funding_signal_neutral(self):
-        from tradehub.core.microstructure_engine import MicrostructureEngine
-        sig = MicrostructureEngine._funding_signal(0.0)
-        assert sig == "NEUTRAL"
-
-    @patch("tradehub.core.microstructure_engine.requests.get")
-    def test_compute_funding_zscore_handles_empty(self, mock_get):
-        """If Binance returns empty list, z_score should default to 0."""
-        mock_get.return_value = MagicMock(status_code=200, json=MagicMock(return_value=[]))
-        from tradehub.core.microstructure_engine import MicrostructureEngine
-        engine = MicrostructureEngine()
-        result = engine.compute_funding_zscore("BTCUSDT")
-        assert result["z_score"] == 0.0
diff --git a/tradehub/api/dependencies.py b/tradehub/api/dependencies.py
index 7888e56..fde21f8 100644
--- a/tradehub/api/dependencies.py
+++ b/tradehub/api/dependencies.py
@@ -33,26 +33,3 @@ def get_supabase():
     except Exception as e:
         print(f"⚠️  Supabase init error: {e}")
         return None
-
-
-# ─── In-memory scanner results cache ─────────────────────────────────────────
-# Nothing populates this dict since the legacy background_scanner daemon was deleted; the API reads from it
-# and serves an empty list. Kept so the endpoint's contract is unchanged until it is retired on its own.
-# This avoids hammering Supabase on every API request.
-_scanner_cache: dict = {
-    "opportunities": [],
-    "nws_readings": {},
-    "last_updated": None,
-}
-
-
-def get_scanner_cache() -> dict:
-    """Returns the live in-memory scanner result store."""
-    return _scanner_cache
-
-
-def update_scanner_cache(key: str, value) -> None:
-    """Thread-safe update of the scanner cache. Called by background_scanner."""
-    from datetime import datetime, timezone
-    _scanner_cache[key] = value
-    _scanner_cache["last_updated"] = datetime.now(timezone.utc)
diff --git a/tradehub/api/main.py b/tradehub/api/main.py
index 0f18d32..f2f51c7 100644
--- a/tradehub/api/main.py
+++ b/tradehub/api/main.py
@@ -24,9 +24,9 @@ from fastapi.middleware.cors import CORSMiddleware
 from tradehub.core.env import load_local_env
 from tradehub.api.schemas import (
     HealthResponse, Position, PnLSummary,
-    Opportunity, NWSReading, ShadowPerformanceResponse,
+    ShadowPerformanceResponse,
 )
-from tradehub.api.dependencies import get_supabase, get_scanner_cache
+from tradehub.api.dependencies import get_supabase
 from tradehub.api.frontend import mount_frontend
 from tradehub.engines.cpi import CPI_MIN_TRAIN, DEFAULT_CPI_ERROR
 from tradehub.engine_catalogue import engine_catalogue
@@ -294,27 +294,6 @@ async def health():
     return HealthResponse(status="ok", timestamp=datetime.now(timezone.utc))
 
 
-# ════════════════════════════════════════════════════════════════════════════
-# ENDPOINT 2: /api/opportunities
-# ════════════════════════════════════════════════════════════════════════════
-@app.get("/api/opportunities", response_model=List[Opportunity], tags=["Scanner"])
-async def get_opportunities(
-    engine: Optional[str] = Query(None, description="Filter by engine name"),
-    min_edge: float = Query(0.0, description="Minimum edge % to return"),
-    cache: dict = Depends(get_scanner_cache),
-):
-    """
-    Returns the latest scanner opportunities from the in-memory cache.
-    Empty since the legacy background_scanner daemon was deleted: nothing refreshes this cache now.
-    """
-    opps = cache.get("opportunities", [])
-    if engine:
-        opps = [o for o in opps if o.get("engine", "").lower() == engine.lower()]
-    if min_edge > 0:
-        opps = [o for o in opps if o.get("edge_pct", 0) >= min_edge]
-    return opps
-
-
 # ════════════════════════════════════════════════════════════════════════════
 # ENDPOINT 3: /api/positions
 # ════════════════════════════════════════════════════════════════════════════
@@ -386,34 +365,6 @@ async def get_pnl_summary(supabase=Depends(get_supabase)):
         raise _table_fault("paper_trades", e)
 
 
-# ════════════════════════════════════════════════════════════════════════════
-# ENDPOINT 5: /api/nws_weather
-# ════════════════════════════════════════════════════════════════════════════
-@app.get("/api/nws_weather", response_model=List[NWSReading], tags=["Weather"])
-async def get_nws_weather(
-    city: Optional[str] = Query(None, description="Filter by city name"),
-    cache: dict = Depends(get_scanner_cache),
-):
-    """
-    Latest NWS temperature readings used by the weather maker engine.
-    Keyed by city name. Returns the observed/forecast highs.
-    """
-    readings = cache.get("nws_readings", {})
-    result = []
-    for city_name, data in readings.items():
-        if city and city_name.lower() != city.lower():
-            continue
-        result.append(NWSReading(
-            city=city_name,
-            date=data.get("date", ""),
-            observed_high_f=data.get("observed_high_f"),
-            forecast_high_f=data.get("forecast_high_f"),
-            nws_station=data.get("nws_station"),
-            fetched_at=data.get("fetched_at", datetime.now(timezone.utc)),
-        ))
-    return result
-
-
 # ════════════════════════════════════════════════════════════════════════════
 # ENDPOINT 8: /api/shadow-performance
 # ════════════════════════════════════════════════════════════════════════════
diff --git a/tradehub/api/schemas.py b/tradehub/api/schemas.py
index aed7aa2..99920b5 100644
--- a/tradehub/api/schemas.py
+++ b/tradehub/api/schemas.py
@@ -44,33 +44,6 @@ class PnLSummary(BaseModel):
     suggest_only: bool = True
 
 
-# ─── Scanner Opportunities ───────────────────────────────────────────────────
-
-class Opportunity(BaseModel):
-    engine: str
-    ticker: str
-    title: str
-    action: str          # "BUY YES" | "BUY NO"
-    my_prob: float
-    kalshi_price: float
-    edge_pct: float
-    kelly_bet_cents: float
-    kalshi_url: Optional[str] = None
-    reasoning: Optional[str] = None
-    detected_at: Optional[datetime] = None
-
-
-# ─── Weather ─────────────────────────────────────────────────────────────────
-
-class NWSReading(BaseModel):
-    city: str
-    date: str            # YYYY-MM-DD
-    observed_high_f: Optional[float] = None
-    forecast_high_f: Optional[float] = None
-    nws_station: Optional[str] = None
-    fetched_at: datetime
-
-
 # ─── Shadow Performance ──────────────────────────────────────────────────────
 
 class ShadowThreshold(BaseModel):
```

- [ ] **Step 4: Run** `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider` — Expected: all pass (reviewer baseline 1428 plus the 2 guard tests).

- [ ] **Step 5: Commit**

```bash
git add -A tradehub shared pyproject.toml tests
git commit -m "cut: delete dead Python (unused shared scripts, news/predictit/microstructure/validator, cache-backed endpoints)"
```

---

### Task 2: Delete the dead frontend

**Files:**
- Delete: 23 application files and 45 unused shadcn components under `market_sentiment_tool/src/`.

**Interfaces:**
- Produces: a frontend whose every remaining file is reachable from `main.tsx`. The only UI components left are `badge`, `card`, `skeleton`, `table`.

- [ ] **Step 1: Delete** (these files are unreachable from `main.tsx`; `StoppedEnginesNotice` and `engineHealth` lost their last consumer when the Prediction Lab went):

```bash
git rm market_sentiment_tool/src/components/AgentCommandCenter.tsx market_sentiment_tool/src/components/AgentLogsTerminal.tsx market_sentiment_tool/src/components/ErrorBoundary.tsx market_sentiment_tool/src/components/FilterBar.tsx market_sentiment_tool/src/components/Layout.tsx market_sentiment_tool/src/components/NavLink.tsx market_sentiment_tool/src/components/ProtectedRoute.tsx market_sentiment_tool/src/components/Sidebar.tsx market_sentiment_tool/src/components/StoppedEnginesNotice.test.tsx market_sentiment_tool/src/components/StoppedEnginesNotice.tsx market_sentiment_tool/src/contexts/AuthContext.tsx market_sentiment_tool/src/hooks/use-mobile.tsx market_sentiment_tool/src/hooks/use-toast.ts market_sentiment_tool/src/hooks/useEngineHealth.ts market_sentiment_tool/src/hooks/useSupabaseData.ts market_sentiment_tool/src/integrations/supabase/client.ts market_sentiment_tool/src/integrations/supabase/types.ts market_sentiment_tool/src/lib/engineHealth.test.ts market_sentiment_tool/src/lib/engineHealth.ts market_sentiment_tool/src/pages/Auth.tsx market_sentiment_tool/src/pages/Index.tsx market_sentiment_tool/src/pages/NotFound.tsx market_sentiment_tool/src/types/supabase.ts
git rm market_sentiment_tool/src/components/ui/{accordion.tsx,alert-dialog.tsx,alert.tsx,aspect-ratio.tsx,avatar.tsx,breadcrumb.tsx,button.tsx,calendar.tsx,carousel.tsx,chart.tsx,checkbox.tsx,collapsible.tsx,command.tsx,context-menu.tsx,dialog.tsx,drawer.tsx,dropdown-menu.tsx,form.tsx,hover-card.tsx,input-otp.tsx,input.tsx,label.tsx,menubar.tsx,navigation-menu.tsx,pagination.tsx,popover.tsx,progress.tsx,radio-group.tsx,resizable.tsx,scroll-area.tsx,select.tsx,separator.tsx,sheet.tsx,sidebar.tsx,slider.tsx,sonner.tsx,switch.tsx,tabs.tsx,textarea.tsx,toast.tsx,toaster.tsx,toggle-group.tsx,toggle.tsx,tooltip.tsx,use-toast.ts}
```

- [ ] **Step 2: Prove nothing is left dangling**

Run: `cd market_sentiment_tool && npx tsc --noEmit -p tsconfig.app.json && npx vitest run && npx vite build`
Expected: tsc silent, vitest passes (reviewer baseline 388), build succeeds. Any `Cannot find module` means the file was not actually dead: restore it and tell the reviewer.

- [ ] **Step 3: Commit**

```bash
git add -A market_sentiment_tool/src
git commit -m "cut: delete unreachable frontend files and unused UI components"
```

---

### Task 3: Verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass.

- [ ] Ruff on every file this plan created or changed: `.venv/bin/python -m ruff check <files>` → `All checks passed!` (pre-existing ruff debt elsewhere is not yours to fix here).
- [ ] In the PR body state the line counts removed (`git diff --stat origin/main | tail -1`) and confirm the legacy tag exists.
- [ ] Open the PR from a fresh branch off `main`. Body: what changed, the verification output, and whether a migration needs applying.

## Self-Review

- **Safety:** nothing live depends on any deleted file (VPS runs `scan`, `settle`, `journal`; the SPA's route table is unchanged). The old state is recoverable from the `legacy/pre-cleanup-2026-10-01` tag and git history.
- **Salvage:** the ideas worth keeping from the dead code are noted in the plan roadmap (Taylor-rule inputs for FOMC; PredictIt as a second market baseline; the Binance funding and order-book features for the deferred crypto work); the code itself is in the tag.
- **Spec §9:** the cuts the spec listed are now all done; this removes what became dead as a consequence.
