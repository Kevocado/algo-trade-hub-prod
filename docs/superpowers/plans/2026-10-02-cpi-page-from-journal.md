# The CPI Page From the Journal (Roadmap v2 item 13) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the separate CPI display, its endpoint and its display-only machinery with the journal's own CPI rows: the forecast locked in 24 hours before each report, beside the Kalshi price, scored after.

**Architecture:** `/cpi` becomes a small page over the existing `/api/journal` and `/api/journal/feed`: two numbers, then the CPI and Core CPI rows with the shared detail view (calibration, cost line, latest locked-in forecasts). The shared `JournalDetail` is extracted from `/journal` so both pages use one component. The `/api/cpi-display` endpoint, its constants, `lib/cpiDisplay*`, `CpiDisplay*` and the endpoint's tests are deleted. The route-order guard that lived in the deleted endpoint test moves to its own file so no guard is lost.

**Tech Stack:** React + TypeScript + vitest; FastAPI + pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§11 Journal UI; Kevin's decision 2026-10-01 (CPI display = the frozen journal forecast)). **Depends on:** plan (o) (`Stat`, `Chip`, `copyWords`, `journalView`) merged.

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (frontend vitest, tsc, eslint, build green; route-order and CPI tests green). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- **What the page can and cannot say, stated in the PR:** a CPI forecast exists only inside the 24 hours before a report (the journal's freeze window), so on most days the page says "Nothing locked in yet" plus the scored history. There are no CPI rows in the journal today. It no longer shows a live nowcast against the market all month; that was the old page and the decision is to drop it.
- Follow plan (o)'s design rules: numbers first, at most 15 words of intro, verdict chips, word budget by test (`copyWords <= 45`).
- Keep the route `/cpi`. Keep `useMarketEdges`, `WithheldEdgesNotice` and `edgeFigures` (they are for the edges table); only their comments mention the old endpoint.
- No migration.

---
### Task 1: The shared detail view and the new /cpi

**Files:**
- Create: `market_sentiment_tool/src/lib/getJson.ts`, `market_sentiment_tool/src/components/JournalDetail.tsx`, `market_sentiment_tool/src/pages/Cpi.tsx`, `market_sentiment_tool/src/pages/Cpi.test.tsx`
- Modify: `market_sentiment_tool/src/pages/Journal.tsx` (uses the extracted pieces), `market_sentiment_tool/src/App.tsx` (route)
- Delete: `pages/CpiDisplay.tsx`, `pages/CpiDisplay.test.tsx`, `lib/cpiDisplay.ts`, `lib/cpiDisplay.test.ts`

**Interfaces:**
- Consumes: `Stat`, `Chip`, `viewRows`, `totals`, `STATUS_WORDS`, `skillText`, `/api/journal`, `/api/journal/feed`.
- Produces: `getJson<T>(path)`, `<JournalDetail row={ViewRow}/>`, the `/cpi` page.

- [ ] **Step 1: Write the failing test** (`market_sentiment_tool/src/pages/Cpi.test.tsx`)

`market_sentiment_tool/src/pages/Cpi.test.tsx`:

```tsx
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import Cpi from "@/pages/Cpi";
import type { JournalFeed, JournalResponse, JournalScore } from "@/lib/journal";
import { copyWords } from "@/test/copyWords";

function score(over: Partial<JournalScore> = {}): JournalScore {
  return {
    forecaster: "cpi_nowcast", forecaster_version: "cpi-v1", cadence: "monthly", baseline: "market", n_targets: 0,
    n_settled: 0, brier: null, brier_baseline: null, bss: null, reliability: [], murphy: {}, calibration_ready: false,
    gate_status: "SHADOW", gate_reasons: [], computed_at: "2026-10-01T13:00:00+00:00", ...over,
  };
}

function serve(forecasters: JournalScore[], feed: Partial<JournalFeed> = {}) {
  const journal: JournalResponse = {
    as_of: "x", forecasters, headline: { forecasters: forecasters.length, calibrated: 0, settled_calibrated: 0, promoted: 0 },
  };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const body = String(url).includes("/api/journal/feed")
      ? { forecaster: "cpi_nowcast", forecaster_version: "cpi-v1", generated_at: "x", forecasts: [], calibration: [], gate_status: "SHADOW", provisional: true, ...feed }
      : journal;
    return { ok: true, json: async () => body } as Response;
  }));
}

afterEach(() => vi.unstubAllGlobals());

describe("/cpi", () => {
  it("shows only the CPI forecasters, plainly named, and says when nothing is locked in", async () => {
    serve([
      score(), score({ forecaster_version: "cpi-core-v1" }), score({ forecaster: "kalshi_implied_cpi", forecaster_version: "v1" }),
      score({ forecaster: "spy_quant", forecaster_version: "spy-wf-v1", cadence: "daily" }),
    ]);
    const { container } = render(<Cpi />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Inflation (CPI)", level: 1 })).toBeTruthy());
    expect(screen.getByRole("heading", { name: "Core inflation (CPI)" })).toBeTruthy();
    expect(screen.queryByText(/S&P/)).toBeNull();
    expect(screen.getByText(/Nothing locked in yet/)).toBeTruthy();
    expect(copyWords(container)).toBeLessThanOrEqual(45);
  });

  it("shows a scored forecast as a number with a verdict, and a missing score as a dash, never zero", async () => {
    serve([score({ n_targets: 30, n_settled: 30, brier: 0.09, brier_baseline: 0.07, bss: -0.2 }),
           score({ forecaster_version: "cpi-core-v1", n_targets: 2 })]);
    render(<Cpi />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Inflation (CPI)", level: 2 })).toBeTruthy());
    expect(screen.getAllByText("Behind").length).toBeGreaterThan(0);
    expect(screen.getByText("-0.20")).toBeTruthy();
  });

  it("says the page is unavailable when the journal cannot be read", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 503, json: async () => ({ detail: "down" }) }) as Response));
    render(<Cpi />);
    await waitFor(() => expect(screen.getByText(/CPI forecasts unavailable: down/)).toBeTruthy());
  });
});
```

- [ ] **Step 2: Run it** — `cd market_sentiment_tool && npx vitest run src/pages/Cpi.test.tsx` — Expected: FAIL (the code below does not exist yet).

- [ ] **Step 3: Implement**

`market_sentiment_tool/src/lib/getJson.ts`:

```ts
import { buildApiUrl } from "@/lib/api";

/** GET one API path as JSON; a non-2xx answer becomes an Error carrying the server's `detail`. */
export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(buildApiUrl(path));
  const payload = await response.json();
  if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
  return payload as T;
}
```

`market_sentiment_tool/src/components/JournalDetail.tsx`:

```tsx
import { useEffect, useState } from "react";

import { getJson } from "@/lib/getJson";
import { biasReadout, costsText, pct, type JournalFeed } from "@/lib/journal";
import type { ViewRow } from "@/lib/journalView";

/** Calibration, the cost line and the latest locked-in forecasts for one forecaster. */
export function JournalDetail({ row }: { row: ViewRow }) {
  const [feed, setFeed] = useState<JournalFeed | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { score } = row;
  useEffect(() => {
    const q = new URLSearchParams({ forecaster: score.forecaster, version: score.forecaster_version, limit: "10" });
    getJson<JournalFeed>(`/api/journal/feed?${q}`).then(setFeed).catch((e: Error) => setError(e.message));
  }, [score.forecaster, score.forecaster_version]);

  const bias = biasReadout(score.reliability);
  const costs = costsText(score);
  return (
    <div className="grid gap-6 py-4 md:grid-cols-2">
      <div>
        <div className="mb-2 font-mono text-xs text-slate-500">{row.key}</div>
        {row.market && (
          <div className="mb-2 text-sm text-slate-300">
            Kalshi price scores {row.market.brier?.toFixed(3) ?? "—"}; this scores {score.brier?.toFixed(3) ?? "—"} (lower is better).
          </div>
        )}
        {costs && <div className="mb-2 text-sm text-slate-400">{costs}</div>}
        {score.reliability.length > 0 ? (
          <table className="w-full text-xs text-slate-300" aria-label={`Calibration ${row.key}`}>
            <thead className="text-slate-500">
              <tr><th className="text-left font-normal">Said</th><th className="text-right font-normal">Forecasts</th><th className="text-right font-normal">Happened</th></tr>
            </thead>
            <tbody>
              {score.reliability.map((b) => (
                <tr key={b.bucket}><td>{pct(b.predicted)}</td><td className="text-right">{b.n}</td><td className="text-right">{pct(b.observed)}</td></tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="text-sm text-slate-500">Nothing scored yet.</div>
        )}
        {bias && <div className="mt-2 text-xs text-slate-400">{bias}</div>}
        {score.gate_status !== "PROMOTED" && score.gate_reasons.length > 0 && (
          <ul className="mt-3 list-disc pl-4 text-xs text-slate-500">
            {score.gate_reasons.map((r) => <li key={r}>{r}</li>)}
          </ul>
        )}
      </div>
      <div>
        <div className="mb-2 text-xs uppercase tracking-wider text-slate-500">Latest locked-in forecasts</div>
        {error && <div className="text-sm text-rose-300">Unavailable: {error}</div>}
        {!feed && !error && <div className="text-sm text-slate-500">Loading…</div>}
        {feed && (
          <table className="w-full text-xs text-slate-300" aria-label={`Frozen forecasts ${row.key}`}>
            <thead className="text-slate-500">
              <tr><th className="text-left font-normal">Event</th><th className="text-right font-normal">Ours</th><th className="text-right font-normal">Market</th></tr>
            </thead>
            <tbody>
              {feed.forecasts.map((f) => (
                <tr key={f.target}><td className="font-mono">{f.target}</td><td className="text-right">{pct(f.probability)}</td><td className="text-right">{pct(f.market_prob)}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
```

`market_sentiment_tool/src/pages/Cpi.tsx`:

```tsx
import { useEffect, useState } from "react";

import { Chip, type Tone } from "@/components/Chip";
import { JournalDetail } from "@/components/JournalDetail";
import { getJson } from "@/lib/getJson";
import { Stat } from "@/components/Stat";
import type { JournalResponse } from "@/lib/journal";
import { STATUS_WORDS, skillText, totals, viewRows, type Status } from "@/lib/journalView";

/**
 * /cpi: the journal's CPI forecasts, nothing else.
 *
 * The old page read a separate nowcast table and carried its own display-only machinery. The journal
 * already locks in each CPI forecast 24 hours before the report, beside the Kalshi price, and scores
 * it after, so this page is those rows and the shared detail view. Nothing is computed here.
 */
const STATUS_TONE: Record<Status, Tone> = { waiting: "quiet", early: "quiet", ahead: "good", behind: "bad", promoted: "good" };
const CPI = new Set(["cpi_nowcast", "kalshi_implied_cpi"]);

export default function Cpi() {
  const [data, setData] = useState<JournalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJson<JournalResponse>("/api/journal").then(setData).catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <div className="p-8 text-rose-300">CPI forecasts unavailable: {error}</div>;
  if (!data) return <div className="p-8 text-slate-400">Loading…</div>;

  const rows = viewRows(data.forecasters.filter((s) => CPI.has(s.forecaster)));
  const t = totals(rows);

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-6 md:p-8">
      <header>
        <h1 className="text-3xl font-bold text-white">Inflation (CPI)</h1>
        <p className="mt-2 text-slate-400">Our forecast, locked in 24 hours before each report, beside the Kalshi price.</p>
      </header>

      <section aria-label="Totals" className="grid gap-3 sm:grid-cols-2">
        <Stat value={t.frozen} label="forecasts locked in" />
        <Stat value={t.scored} label="scored so far" />
      </section>

      {t.frozen === 0 && <p className="text-slate-400">Nothing locked in yet. The next one locks 24 hours before the report.</p>}

      {rows.map((row) => (
        <section key={row.key} aria-label={row.label} className="border-t border-slate-800 pt-4">
          <div className="flex items-baseline justify-between gap-4">
            <h2 className="text-lg font-semibold text-slate-100">{row.label}</h2>
            <div className="flex items-center gap-3">
              <span className="text-lg tabular-nums text-slate-100">{skillText(row.skill)}</span>
              <Chip tone={STATUS_TONE[row.status]}>{STATUS_WORDS[row.status]}</Chip>
            </div>
          </div>
          <JournalDetail row={row} />
        </section>
      ))}
    </div>
  );
}
```

Then the diffs to `Journal.tsx` and `App.tsx`, and delete the four old files with `git rm`:

```diff
diff --git a/market_sentiment_tool/src/App.tsx b/market_sentiment_tool/src/App.tsx
index 48ea232..e9c4ea6 100644
--- a/market_sentiment_tool/src/App.tsx
+++ b/market_sentiment_tool/src/App.tsx
@@ -6,7 +6,7 @@ import Models from "@/pages/Models";
 import Scoreboard from "@/pages/Scoreboard";
 import SportsEdges from "@/pages/SportsEdges";
 import JobsScorecard from "@/pages/JobsScorecard";
-import CpiDisplay from "@/pages/CpiDisplay";
+import Cpi from "@/pages/Cpi";
 import Journal from "@/pages/Journal";
 import { NoOrdersBanner } from "@/components/NoOrdersBanner";
 import { usePortfolio } from "@/hooks/usePortfolio";
@@ -173,7 +173,7 @@ function App() {
           <Route path="/shadow-scoreboard" element={<Navigate to="/scoreboard" replace />} />
           <Route path="/sports" element={<SportsEdges />} />
           <Route path="/jobs" element={<JobsScorecard />} />
-          <Route path="/cpi" element={<CpiDisplay />} />
+          <Route path="/cpi" element={<Cpi />} />
         </Routes>
       </AppShell>
     </BrowserRouter>
diff --git a/market_sentiment_tool/src/pages/Journal.tsx b/market_sentiment_tool/src/pages/Journal.tsx
index 37acad4..a057df8 100644
--- a/market_sentiment_tool/src/pages/Journal.tsx
+++ b/market_sentiment_tool/src/pages/Journal.tsx
@@ -1,16 +1,11 @@
 import { Fragment, useEffect, useState } from "react";
 
 import { Chip, type Tone } from "@/components/Chip";
+import { JournalDetail } from "@/components/JournalDetail";
+import { getJson } from "@/lib/getJson";
 import { PreJournalContext } from "@/components/PreJournalContext";
 import { Stat } from "@/components/Stat";
-import { buildApiUrl } from "@/lib/api";
-import {
-  biasReadout,
-  costsText,
-  pct,
-  type JournalFeed,
-  type JournalResponse,
-} from "@/lib/journal";
+import type { JournalResponse } from "@/lib/journal";
 import { STATUS_WORDS, skillText, split, totals, viewRows, type Status, type ViewRow } from "@/lib/journalView";
 
 /**
@@ -22,78 +17,8 @@ import { STATUS_WORDS, skillText, split, totals, viewRows, type Status, type Vie
  * Nothing here computes a score: the server does, and this renders it.
  */
 
-async function getJson<T>(path: string): Promise<T> {
-  const response = await fetch(buildApiUrl(path));
-  const payload = await response.json();
-  if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
-  return payload as T;
-}
-
 const STATUS_TONE: Record<Status, Tone> = { waiting: "quiet", early: "quiet", ahead: "good", behind: "bad", promoted: "good" };
 
-function Detail({ row }: { row: ViewRow }) {
-  const [feed, setFeed] = useState<JournalFeed | null>(null);
-  const [error, setError] = useState<string | null>(null);
-  const { score } = row;
-  useEffect(() => {
-    const q = new URLSearchParams({ forecaster: score.forecaster, version: score.forecaster_version, limit: "10" });
-    getJson<JournalFeed>(`/api/journal/feed?${q}`).then(setFeed).catch((e: Error) => setError(e.message));
-  }, [score.forecaster, score.forecaster_version]);
-
-  const bias = biasReadout(score.reliability);
-  const costs = costsText(score);
-  return (
-    <div className="grid gap-6 py-4 md:grid-cols-2">
-      <div>
-        <div className="mb-2 font-mono text-xs text-slate-500">{row.key}</div>
-        {row.market && (
-          <div className="mb-2 text-sm text-slate-300">
-            Kalshi price scores {row.market.brier?.toFixed(3) ?? "—"}; this scores {score.brier?.toFixed(3) ?? "—"} (lower is better).
-          </div>
-        )}
-        {costs && <div className="mb-2 text-sm text-slate-400">{costs}</div>}
-        {score.reliability.length > 0 ? (
-          <table className="w-full text-xs text-slate-300" aria-label={`Calibration ${row.key}`}>
-            <thead className="text-slate-500">
-              <tr><th className="text-left font-normal">Said</th><th className="text-right font-normal">Forecasts</th><th className="text-right font-normal">Happened</th></tr>
-            </thead>
-            <tbody>
-              {score.reliability.map((b) => (
-                <tr key={b.bucket}><td>{pct(b.predicted)}</td><td className="text-right">{b.n}</td><td className="text-right">{pct(b.observed)}</td></tr>
-              ))}
-            </tbody>
-          </table>
-        ) : (
-          <div className="text-sm text-slate-500">Nothing scored yet.</div>
-        )}
-        {bias && <div className="mt-2 text-xs text-slate-400">{bias}</div>}
-        {score.gate_status !== "PROMOTED" && score.gate_reasons.length > 0 && (
-          <ul className="mt-3 list-disc pl-4 text-xs text-slate-500">
-            {score.gate_reasons.map((r) => <li key={r}>{r}</li>)}
-          </ul>
-        )}
-      </div>
-      <div>
-        <div className="mb-2 text-xs uppercase tracking-wider text-slate-500">Latest locked-in forecasts</div>
-        {error && <div className="text-sm text-rose-300">Unavailable: {error}</div>}
-        {!feed && !error && <div className="text-sm text-slate-500">Loading…</div>}
-        {feed && (
-          <table className="w-full text-xs text-slate-300" aria-label={`Frozen forecasts ${row.key}`}>
-            <thead className="text-slate-500">
-              <tr><th className="text-left font-normal">Event</th><th className="text-right font-normal">Ours</th><th className="text-right font-normal">Market</th></tr>
-            </thead>
-            <tbody>
-              {feed.forecasts.map((f) => (
-                <tr key={f.target}><td className="font-mono">{f.target}</td><td className="text-right">{pct(f.probability)}</td><td className="text-right">{pct(f.market_prob)}</td></tr>
-              ))}
-            </tbody>
-          </table>
-        )}
-      </div>
-    </div>
-  );
-}
-
 export default function Journal() {
   const [data, setData] = useState<JournalResponse | null>(null);
   const [error, setError] = useState<string | null>(null);
@@ -167,7 +92,7 @@ export default function Journal() {
                     <td className="py-3 pl-4"><Chip tone={STATUS_TONE[row.status]}>{STATUS_WORDS[row.status]}</Chip></td>
                   </tr>
                   {open === row.key && (
-                    <tr><td colSpan={4} className="border-t border-slate-800/60"><Detail row={row} /></td></tr>
+                    <tr><td colSpan={4} className="border-t border-slate-800/60"><JournalDetail row={row} /></td></tr>
                   )}
                 </Fragment>
               ))}
```

- [ ] **Step 4: Run** — `cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx vite build` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/src
git commit -m "feat(ui): /cpi shows the journal's CPI rows"
```

---

### Task 2: Delete the endpoint and keep the route-order guard

**Files:**
- Modify: `tradehub/api/main.py` (delete the CPI constants and the `/api/cpi-display` endpoint, and the now-unused `tradehub.engines.cpi` import), `tests/test_cpi_no_edges.py` (drop the one test of `_cpi_display_row`), comment-only edits in `tests/test_engine_health.py` and `tests/test_cpi_delisted_cleanup.py`
- Create: `tests/test_api_route_order.py`
- Delete: `tests/test_cpi_display.py`

**Interfaces:**
- Produces: `tests/test_api_route_order.py` keeps the property "every `/api/` route is registered before the SPA catch-all" that the deleted file carried, and asserts `/api/cpi-display` is gone and `/api/journal` is present.

- [ ] **Step 1: Write the failing test** (`tests/test_api_route_order.py`)

`tests/test_api_route_order.py`:

```python
"""Every /api route is registered before the SPA catch-all, so the app shell never shadows an endpoint."""
import importlib.util
import os
import sys

from tradehub.api import main as api_main


def _routes_with_a_spa_mounted(tmp_path):
    """`api_main.app` as registered when the SPA is present, from a private module instance.

    Not `importlib.reload`: other test modules bind `app` at import time and would be left holding the old
    object. Loading the file under a private name gives a fresh app and a fresh `mount_frontend` call and
    leaves the real module alone. Driven from a temp dist, so it runs whether or not `dist` was ever built.
    """
    (tmp_path / "index.html").write_text("<!doctype html><title>spa</title>")
    previous = os.environ.get("FRONTEND_DIST")
    os.environ["FRONTEND_DIST"] = str(tmp_path)
    spec = importlib.util.spec_from_file_location("_spa_order_probe", api_main.__file__)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            os.environ.pop("FRONTEND_DIST", None)
        else:
            os.environ["FRONTEND_DIST"] = previous
        sys.modules.pop(spec.name, None)
    return [getattr(route, "path", None) for route in module.app.routes]


def test_every_api_route_is_registered_before_the_spa_catch_all(tmp_path):
    paths = _routes_with_a_spa_mounted(tmp_path)
    api_routes = [p for p in paths if isinstance(p, str) and p.startswith("/api/")]
    assert api_routes, "the probe found no /api/ routes, so it proves nothing"
    assert "" in paths, "the probe did not mount a SPA, so it proves nothing about the order"
    shadowed = [p for p in api_routes if paths.index(p) > paths.index("")]
    assert not shadowed, f"registered after the SPA catch-all and would be shadowed: {shadowed}"


def test_the_cpi_display_endpoint_is_gone(tmp_path):
    assert "/api/cpi-display" not in _routes_with_a_spa_mounted(tmp_path)
    assert "/api/journal" in _routes_with_a_spa_mounted(tmp_path)
```

- [ ] **Step 2: Run it** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_api_route_order.py -k cpi_display` — Expected: FAIL (the code below does not exist yet).

- [ ] **Step 3: Implement**

Apply the diff, then `git rm tests/test_cpi_display.py`:

```diff
diff --git a/tests/test_cpi_delisted_cleanup.py b/tests/test_cpi_delisted_cleanup.py
index bab6b49..8e57b3c 100644
--- a/tests/test_cpi_delisted_cleanup.py
+++ b/tests/test_cpi_delisted_cleanup.py
@@ -98,7 +98,7 @@ class _Query:
             else:
                 rows = [r for r in rows if r.get(key) == value]
         # ISO-8601 with a uniform offset, so a lexicographic comparison agrees with a chronological
-        # one -- the same simplification tests/test_cpi_display.py's own fake makes.
+        # one -- the same simplification the CPI display's fake used to make.
         for key, value in self.gt_bounds.items():
             rows = [r for r in rows if str(r.get(key) or "") > str(value)]
         if self.row_limit is not None:
diff --git a/tests/test_cpi_no_edges.py b/tests/test_cpi_no_edges.py
index 4a1b9ff..04e3ce3 100644
--- a/tests/test_cpi_no_edges.py
+++ b/tests/test_cpi_no_edges.py
@@ -129,29 +129,6 @@ def test_the_prediction_carries_no_gate_status_and_could_not_read_as_promoted():
     assert not [e for e in _scan()[1] if e.get("gate_status") == "PROMOTED"]
 
 
-def test_the_display_row_fails_closed_for_a_cpi_row():
-    """What the display endpoint actually publishes for this row.
-
-    This replaced an assertion on the SCAN output -- `row.get("gate_status", "SHADOW") == "SHADOW"`
-    -- which could not fail: the default *is* the asserted value, so it said nothing at all. The real
-    property lives on the other side of the endpoint, where the constants are set unconditionally,
-    so that is what is asserted here. The claim it protects is unchanged: a CPI row cannot reach a
-    reader as promoted.
-
-    Note the endpoint does NOT take the `_attach_gate_status` fallback this test used to describe.
-    CPI's rows carry no `gate_status` at all (see the test above), so the display endpoint publishes
-    `CPI_GATE_STATUS` outright and pairs it with `gate_checked: False` -- because "SHADOW" on its own
-    is the gate's own vocabulary and reads as a verdict that was reached."""
-    from tradehub.api.main import CPI_GATE_STATUS, _cpi_display_row
-
-    out = _cpi_display_row(_scan()[0][0])
-
-    assert out["gate_status"] == CPI_GATE_STATUS == "SHADOW"
-    # The stronger half, and the one a reader actually sees: no gate was consulted.
-    assert out["gate_checked"] is False
-    assert out["gate_status"] != "PROMOTED"
-
-
 def test_the_prediction_records_no_edge_figure():
     """A prediction row must not carry an edge. If one ever did, a reader could compute one, and
     the display view would have an edge number to show on an engine that has none."""
diff --git a/tests/test_engine_health.py b/tests/test_engine_health.py
index aa34976..9c8bd67 100644
--- a/tests/test_engine_health.py
+++ b/tests/test_engine_health.py
@@ -561,7 +561,7 @@ class TestEngineHealthEndpoint:
         this endpoint would answer with the app shell.
 
         The property itself is pinned for EVERY route by
-        `tests/test_cpi_display.py::test_every_api_route_is_registered_before_the_spa_catch_all`,
+        `tests/test_api_route_order.py::test_every_api_route_is_registered_before_the_spa_catch_all`,
         which drives a temp dist so the mount happens whether or not this machine has ever run
         `npm run build`. Asserting the order here as well would be a second copy of one rule that
         only runs in some environments -- and the version that ran in the fewest environments is
diff --git a/tradehub/api/main.py b/tradehub/api/main.py
index bdf82ae..34fbf66 100644
--- a/tradehub/api/main.py
+++ b/tradehub/api/main.py
@@ -28,7 +28,6 @@ from tradehub.api.schemas import (
 )
 from tradehub.api.dependencies import get_supabase
 from tradehub.api.frontend import mount_frontend
-from tradehub.engines.cpi import CPI_MIN_TRAIN, DEFAULT_CPI_ERROR
 from tradehub.engine_catalogue import engine_catalogue
 from tradehub.engine_health import engine_health
 from tradehub.gate_status import DEFAULT_GATE_STATUS, latest_gate_statuses
@@ -472,101 +471,6 @@ SPORTS_REVIEW_SCAN = 5000
 # see more has to page with .range() explicitly.
 POSTGREST_CAP = 1000
 
-# ── CPI display (display-only, approved 2026-09-27) ─────────────────────────
-CPI_ENGINE = "cpi_nowcast"
-CPI_PAGE_DEFAULT = 50
-CPI_PAGE_MAX = 200
-# `predictions` is append-only and nothing prunes it: one row per open CPI market per scan run,
-# three runs a day, forever. So the read has to be bounded, and the bound has to be visible -- a
-# `total` that quietly counts only the rows we happened to read is a claim about the data, the same
-# silent-truncation hazard the scoreboard's cap=200 and the edges hook's limit(100) already carry.
-# Ordering by `as_of` descending means the bound drops the OLDEST history, which is the right thing
-# to drop for a live display.
-CPI_ROW_SCAN = 200
-
-# The gate, and the honest reason there is no gate. `predictions` has no `gate_status` column --
-# 20260416000003_predictions_ledger.sql:10 defines the table and `gate_status` is `track_record`'s,
-# at line 43 of the same file -- and `build_prediction_row` (tradehub/predictions.py:41) never sets
-# one. So this endpoint cannot read a gate status and does not try: a display engine is not a
-# candidate for promotion, so there is nothing to check. The gate fails closed, so the value is
-# SHADOW, and `gate_checked` says out loud that no gate was consulted -- because "SHADOW" on its own
-# is the gate's own vocabulary and reads as "not promoted", i.e. as a verdict that was reached.
-# The status is the shared fail-closed default, not a second copy of the string:
-# two literals in this module is how the scan and the API would start disagreeing
-# about whether an edge is tradable, which is what DEFAULT_GATE_STATUS exists to
-# prevent. What makes CPI's verdict its own is CPI_GATE_CHECKED below -- the gate
-# was never checked, which is not the same claim as "checked, and it said no".
-CPI_GATE_STATUS = DEFAULT_GATE_STATUS
-CPI_GATE_CHECKED = False
-CPI_GATE_CHECKED_REASON = (
-    "No gate was consulted and none is expected. cpi_nowcast is a display engine, not a candidate "
-    "for promotion, and the predictions table has no gate_status column to read one from. This "
-    "SHADOW is a fails-closed default, not a verdict from a gate that was checked and said no."
-)
-
-CPI_DISPLAY_REASON = (
-    "Not an edge engine. CPI is shown for context only. Measured over 2026-06-01..2026-09-20 the "
-    "market's Brier score was 0.0677 at 25 minutes before close and 0.0710 five days out, so it "
-    "prices this series about as accurately a week ahead as in the last half hour. The market is "
-    "not pricing off the Cleveland Fed nowcast, so a nowcast-based model has nothing to exploit by "
-    "being early. At every lead this model is 1.33-1.43x behind the market, with negative P&L."
-)
-
-# Why a row is withheld FROM THE COMPARISON (it is never withheld from the page). A release scanned
-# before its first quote has no market mid at all, which is a different fact from a market
-# probability of zero -- `useMarketEdges` still fabricates that zero with `?? 0`, and the same
-# "right number, wrong attribution" shape is not repeated here.
-CPI_NOT_COMPARABLE = (
-    "No market mid was recorded for this release, so there is no market probability to set the "
-    "nowcast against. The nowcast is shown on its own; nothing here is a comparison, and a missing "
-    "mid is not a market mid of zero."
-)
-
-# `fit_cpi_error` (tradehub/engines/cpi.py) returns DEFAULT_CPI_ERROR -- a CONSTANT -- whenever it
-# has fewer than CPI_MIN_TRAIN training pairs, so a row's `our_prob` can come out of a hardcoded
-# sigma rather than a fit. Nothing distinguished the two on the page, which is the inverse of the
-# rule this endpoint is built on: a figure that was not measured is being presented as though it
-# were, and the reader cannot tell. `n_train` is the honest signal, because it is what the branch in
-# `fit_cpi_error` actually tested, so the flag is derived from it rather than from `sigma == 0.15`
-# (which a fitted model can also return).
-CPI_DEFAULT_ERROR_SIGMA = DEFAULT_CPI_ERROR.sigma
-CPI_DEFAULT_ERROR_MODEL = (
-    f"The error model is the default, not a fit: fewer than {CPI_MIN_TRAIN} nowcast/print pairs "
-    f"were available, so the {CPI_DEFAULT_ERROR_SIGMA}pp sigma is the constant the engine falls back "
-    "to rather than something measured. This row's probability comes from that default."
-)
-
-# `offset` is advertised, echoed and bounds-tested, so paging reads as supported. But the read is
-# bounded at CPI_ROW_SCAN, and the window is applied to that bounded list, so any offset past the
-# bound returns an empty page while `total` still says CPI_ROW_SCAN: a 200 with no rows, which is
-# indistinguishable from a ledger that has none. At three scans a day the ledger passes 200 rows in
-# about two weeks, so this is the normal case and not an edge case. Rejected instead of served.
-CPI_PAGE_WINDOW_MAX = CPI_ROW_SCAN
-CPI_PAGE_WINDOW_DETAIL = (
-    f"offset + limit must be at most {CPI_PAGE_WINDOW_MAX}: the read is bounded at that many rows, "
-    f"so a window past it could only ever return an empty page, and an empty page reads as a ledger "
-    f"with nothing in it. Ask for a smaller limit, or start from an earlier offset."
-)
-
-# `comparable=true` keeps only the rows that carry a market mid. The page asks for it (see
-# CPI_CONTEXT_ROWS in market_sentiment_tool/src/lib/cpiDisplay.ts for the count and the reasoning),
-# and the filter lives HERE rather than in the component for two reasons that both come from the
-# review this endpoint was built under: no rule that filters or reorders data may live in TSX, and a
-# client-side filter would describe a window the response does not describe -- `total` would count
-# rows the response never sent, and the page would be reporting on its own reordering rather than on
-# the read. Opt-in, so an unfiltered read of the whole ledger is still available to a caller that
-# wants it; the page is not the only possible reader of this endpoint.
-#
-# The number of rows is a low-teens count decided by the page's own request, not clamped here: this
-# endpoint has no opinion about how much context a reader wants, and a clamp would make a short page
-# a server-side policy the reader could not see.
-CPI_COMPARABLE_HELP = (
-    "comparable=true keeps only the releases that carry a market mid to set the nowcast against. "
-    "Rows without one are still counted in `withheld_count` -- a shorter page is not a licence to "
-    "stop saying what was withheld."
-)
-
-
 def _page(limit: int, offset: int) -> tuple[int, int]:
     if limit < 1 or limit > SPORTS_PAGE_MAX or offset < 0:
         raise HTTPException(status_code=422, detail=f"limit must be 1..{SPORTS_PAGE_MAX} and offset >= 0")
@@ -951,175 +855,6 @@ async def get_jobs_scorecard(
     return rows
 
 
-# ════════════════════════════════════════════════════════════════════════════
-# ENDPOINT: /api/cpi-display (the nowcast against the market, as context)
-# ════════════════════════════════════════════════════════════════════════════
-def _cpi_display_row(row: dict) -> dict:
-    """One `predictions` row as a display row. Nothing measured is changed, and nothing missing is
-    invented: a figure the scan did not record stays null, and the row says why it cannot be
-    compared rather than being passed off as a comparison."""
-    raw = row.get("raw_payload") or {}
-    market_prob = row.get("market_prob")
-    comparable = market_prob is not None
-    n_train = raw.get("n_train")
-    # The same branch `fit_cpi_error` took, decided from the number it branched on. `sigma` is NOT
-    # used: the default's own sigma is a value a fitted model can also produce, so comparing against
-    # it would label some fitted rows "default" and never miss a default one. An absent n_train
-    # means the scan did not record it, which is not evidence the model was fitted -- so the flag is
-    # `None` and the row says the count is unknown rather than asserting either way.
-    default_error_model: bool | None = None if n_train is None else int(n_train) < CPI_MIN_TRAIN
-    return {
-        "market_ticker": row.get("market_ticker"),
-        "our_prob": row.get("our_prob"),
-        # The quote mid, the same quantity the sports endpoint reports. It is NOT what an edge would
-        # be measured against, and `edge_pct` below is null so nothing here implies otherwise.
-        "market_prob": market_prob,
-        # Present and always null. A reader shown a probability and a market price will assume an
-        # opportunity unless something says otherwise, and a null says it in the shape a client
-        # checks rather than in prose it might ignore. There is no edge here to publish: spec 5a
-        # records the outcome as REFUTED, not weak.
-        "edge_pct": None,
-        "nowcast": raw.get("nowcast"),
-        "nowcast_obs": raw.get("nowcast_obs"),
-        "sigma": raw.get("sigma"),
-        # The training-set size, because a sigma printed without it is a number of unknown origin.
-        "n_train": n_train,
-        "default_error_model": default_error_model,
-        "default_error_model_reason": CPI_DEFAULT_ERROR_MODEL if default_error_model else None,
-        "hours_to_close": raw.get("hours_to_close"),
-        # `as_of`, not `updated_at`: the ledger's timestamp is the engine's own and is NOT NULL, and
-        # `predictions` has no `updated_at` column at all. `status` travels so a settled row from a
-        # market that closed last month cannot render as if it were live. The result is deliberately
-        # NOT published: a bare yes/no beside a probability reads as our win, which is a claim the
-        # ledger supports only through the settlement job, not here.
-        "as_of": row.get("as_of"),
-        "status": row.get("status"),
-        "comparable": comparable,
-        "withheld_reason": None if comparable else CPI_NOT_COMPARABLE,
-        "gate_status": CPI_GATE_STATUS,
-        "gate_checked": CPI_GATE_CHECKED,
-    }
-
-
-@app.get("/api/cpi-display", tags=["CPI"])
-def get_cpi_display(
-    limit: int = Query(CPI_PAGE_DEFAULT, ge=1, le=CPI_PAGE_MAX),
-    offset: int = Query(0, ge=0),
-    comparable: bool = Query(False, description=CPI_COMPARABLE_HELP),
-    supabase=Depends(get_supabase),
-):
-    """CPI as context, not as an opportunity.
-
-    Approved display-only on 2026-09-27 (spec section 9, approval 3, quoted verbatim from
-    docs/superpowers/specs/2026-09-27-hub-redesign.md:505: "DISPLAY ONLY. Show the nowcast against
-    the market for context; not an edge engine."), on the evidence in 5a: the market's
-    Brier at 5 days out (0.0710) is barely worse than at 25 minutes (0.0677), so Kalshi prices this
-    series about as accurately a week ahead as in the last half hour. It is not pricing off the
-    nowcast, so a nowcast-based model has nothing to exploit by being early, and at every lead we
-    are 1.33-1.43x behind with negative P&L.
-
-    So this reads the `predictions` rows -- which carry the nowcast, our probability and the market
-    mid -- and labels them. The label is in the payload and not only in the page, because
-    `predictions` is owner-only under RLS, so this endpoint is the only route by which these numbers
-    reach a browser: a label that only existed in a component would not travel with the data.
-
-    Six claims this response makes about itself, and each of them is a claim a reader would
-    otherwise have to assume:
-
-    * `mode`/`edge_pct`/null: this is context, there is no edge, and nothing here implies otherwise.
-    * `withheld_count` and each row's `withheld_reason`: a release with no market mid is shown, and
-      says it is not a comparison. The row is withheld from the comparison, never from the page --
-      an engine that loses stays visible.
-    * `truncated`: a read bounded at CPI_ROW_SCAN says so rather than letting `total` read as the
-      whole set.
-    * `n_train` with `default_error_model`: a probability produced from the engine's FALLBACK sigma
-      says so, because a constant and a fit are otherwise the same figure on the page.
-    * `read_count`: how many rows the bounded read examined, which is NOT `total` once `comparable`
-      has removed any. The page's "N rows read" comes from here.
-    * `comparable_only`: whether this response applied that filter, echoed because a client must be
-      able to tell a short page from a filter it did not know about.
-
-    `comparable=true` is the one that answers the complaint this page was built for: on 2026-09-28
-    the unfiltered read returned 50 rows of which 69 across the read had no market mid at all, so
-    the page was mostly rows with nothing to compare. A row with no market mid has no comparison in
-    it, so for a page whose whole job is the comparison it is padding -- but it is still WITHHELD
-    rather than discarded, and `withheld_count` still says how many. Filtering happens before the
-    window, so `offset`/`limit` index the comparable set, and `total` is the count of what the
-    response describes.
-
-    A failed read is a 503, never a 200 with an empty page: "not measured" and "measured, and there
-    is nothing there" are different facts and must not look alike. For the same reason a `offset` that
-    would read past the bound is a 422 and not an empty window.
-    """
-    if supabase is None:
-        raise HTTPException(status_code=503, detail="Supabase not configured")
-    # The window is checked against the READ'S bound, before the read, because after it an offset
-    # past the bound is a well-formed 200 whose `rows` is empty -- the one shape a client cannot tell
-    # from a ledger with nothing in it.
-    if offset + limit > CPI_PAGE_WINDOW_MAX:
-        raise HTTPException(status_code=422, detail=CPI_PAGE_WINDOW_DETAIL)
-    try:
-        # `as_of` descending, with `_fetch_all` appending `id` as the tiebreak so the pages line up
-        # (PostgREST without a stable order can repeat one row and skip another between pages).
-        # cap is the bound plus one, so "there are more rows" is something the read established
-        # rather than something it guessed from filling the cap.
-        read = _fetch_all(
-            supabase, "predictions",
-            lambda q: q.select("*").eq("engine", CPI_ENGINE).order("as_of", desc=True),
-            page=CPI_ROW_SCAN, cap=CPI_ROW_SCAN + 1,
-        )
-    except Exception as exc:
-        # Deliberately not swallowed into an empty list: an empty page means the nowcast has no
-        # markets, and a reader who is told that when the database was never reached has been told
-        # something false. The detail names the migration, because a 500 with PostgREST's raw dump
-        # is what put a red "unavailable" on the War Room.
-        raise HTTPException(status_code=503, detail=_missing_table_message("predictions", exc))
-    truncated = len(read) > CPI_ROW_SCAN
-    read = read[:CPI_ROW_SCAN]
-    # Built once for the whole read, so the count and the rows come from the same rule rather than
-    # from two copies of "is this row comparable". Counted before any filter and before slicing: a
-    # client cannot derive it from one page, and deriving it is what makes an offset window report
-    # on itself instead of on the set.
-    display = [_cpi_display_row(r) for r in read]
-    read_count = len(display)
-    # Counted BEFORE the `comparable` filter, which is the whole point. Counting after it would
-    # report zero whenever the filter is on -- and that is the one number a reader must never be
-    # able to lose, because a short page that also says "nothing was withheld" is a page that is
-    # padded and silent about it at the same time.
-    withheld_count = sum(1 for r in display if not r["comparable"])
-    # The filter runs BEFORE the window, so `offset`/`limit` index the comparable set rather than
-    # the raw read. Paging past the withheld rows is what makes the short page reach the same
-    # comparable row a reader would have found by scrolling the long one.
-    if comparable:
-        display = [r for r in display if r["comparable"]]
-    # The count of what THIS RESPONSE DESCRIBES, and therefore not a count of what was read once
-    # the filter has run. `read_count` is the latter, and `read_count == total + withheld_count`
-    # whenever `comparable` is on.
-    total = len(display)
-    return {
-        "as_of": datetime.now(timezone.utc).isoformat(),
-        "mode": "display",
-        "engine": CPI_ENGINE,
-        "suggest_only": True,
-        "reason": CPI_DISPLAY_REASON,
-        "edge_pct": None,
-        "gate_status": CPI_GATE_STATUS,
-        "gate_checked": CPI_GATE_CHECKED,
-        "gate_checked_reason": CPI_GATE_CHECKED_REASON,
-        "row_order": "as_of desc",
-        "rows": display[offset:offset + limit],
-        # The number of rows in the set this response describes. When `truncated` is true it is a
-        # floor, not a count.
-        "total": total,
-        "truncated": truncated,
-        "withheld_count": withheld_count,
-        "read_count": read_count,
-        "comparable_only": comparable,
-        "limit": limit,
-        "offset": offset,
-    }
-
-
 # ════════════════════════════════════════════════════════════════════════════
 # ENDPOINT: /api/engine-health (which edge types are fed by a STOPPED engine)
 #
```

- [ ] **Step 4: Run** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_api_route_order.py tests/test_cpi_no_edges.py tests/test_engine_health.py tests/test_cpi_delisted_cleanup.py tests/test_env_hygiene.py` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tradehub tests
git commit -m "cut: remove the CPI display endpoint and its machinery"
```

---

### Task 3: Verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass (reviewer baseline on the final stack: see the roadmap).

- [ ] Ruff on the files this plan created or changed: `.venv/bin/python -m ruff check --select F tradehub/api/main.py tests/test_api_route_order.py` → `All checks passed!` (import-order findings on files you did not create are older debt, not yours).
- [ ] Frontend: `cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx vite build` — all green.
- [ ] Open the PR from a fresh branch off `main` (title in the roadmap). Body: what changed, the verification output, and whether a migration needs applying. Then stop and report in 4 lines.

---

## Self-Review

- **Owner feedback:** the CPI page goes from about 910 words and a bespoke endpoint to two numbers and the shared journal rows; the word budget is a test.
- **No guard lost:** the registration-order test is ported verbatim in behaviour and now also fails if the removed endpoint returns.
- **Truthful:** an unscored forecaster shows a dash and `Waiting`, never `0`; an unreadable journal says so.
