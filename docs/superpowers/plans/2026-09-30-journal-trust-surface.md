# Journal Trust Surface: Banner, Pre-Journal Context, Retired Verdict (Plan i) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the no-orders line above every page, show pre-journal backtests on /journal as labelled context that is never counted, and give deleted engines a `retired` tombstone on /models.

**Architecture:** A `NoOrdersBanner` inside the app shell; a `PreJournalContext` section on `/journal` that reads the existing `/api/scoreboard` and computes nothing; and a sixth catalogue status, `retired`, produced by `ENGINE_TOMBSTONES` in `tradehub/engine_catalogue.py` (empty until a PR deletes an engine) and rendered on `/models` with when, why and what replaced it.

**Tech Stack:** Python 3.12, React + TypeScript, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§1 positioning, §2 pre-journal context, §9 retired verdict). **Depends on:** plan (j) merged (this plan edits the `App.tsx` that plan (j) leaves behind).

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (backend suite passes at monotonic 5.0 and 1e7; vitest 433 passed, tsc and eslint clean). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- The banner text is exactly `Places no orders — the ledger is the product.` and sits above every page (inside `AppShell`), so a screenshot of a number cannot lose it.
- Pre-journal rows are **context only**: the heading and the sentence under it say they are never counted in the journal's settled total, and the headline numbers on `/journal` are asserted unchanged by a test. The block computes nothing; it prints `/api/scoreboard` rows (`brierPair` from `@/lib/models`).
- `retired` is a status, not a verdict on accuracy (muted tone, like `not_measured`). Retired engines are **not** counted in `engines_total` / `engines_measured` / `engines_not_measured` / `engines_unlisted`; they have their own `engines_retired`. A retired engine keeps any backtest history attached.
- `ENGINE_TOMBSTONES` ships **empty**: nothing with a scoreboard row has been deleted. The next PR that deletes an engine adds its tombstone (`engine`, `label`, `removed` ISO date, `reason`, `replaced_by`) in the same PR.

---
### Task 1: Tombstones in the engine catalogue

**Files:**
- Modify: `tradehub/engine_catalogue.py`, `tests/test_engine_catalogue.py`

**Interfaces:**
- Produces: `STATUS_RETIRED = "retired"`, `ENGINE_TOMBSTONES: tuple[dict, ...] = ()`, `engine_catalogue(rows, tombstones=None)` (default reads `ENGINE_TOMBSTONES`), entries of the form `{..., "status": "retired", "retired": {removed, reason, replaced_by}}`, and a new `engines_retired` count. The API needs no change: `/api/scoreboard` already calls `engine_catalogue(rows)`.

- [ ] **Step 1: Write the failing tests and Step 3 implementation as one reviewed diff.** Apply only the `tests/test_engine_catalogue.py` hunks first and run them to watch them fail:

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_engine_catalogue.py -v`
Expected: FAIL — `cannot import name 'ENGINE_TOMBSTONES'`.

- [ ] **Step 2: Apply the rest**

```diff
diff --git a/tests/test_engine_catalogue.py b/tests/test_engine_catalogue.py
index e3a831b..9b7d50f 100644
--- a/tests/test_engine_catalogue.py
+++ b/tests/test_engine_catalogue.py
@@ -25,7 +25,9 @@ from tradehub.engine_catalogue import (
     CATALOGUE_ENGINES,
     CLAIM_UNLISTED,
     ENGINE_CATALOGUE,
+    ENGINE_TOMBSTONES,
     STATUS_NOT_MEASURED,
+    STATUS_RETIRED,
     catalogue_entry,
     engine_catalogue,
     engine_status,
@@ -453,3 +455,39 @@ def test_the_threshold_it_summarises_is_the_threshold_the_board_already_uses():
 
     assert str(BEHIND_THE_MARKET) not in executable
     assert "row_verdict(" in executable, "the roll-up stopped reading the reduced row's own verdict"
+
+
+_GONE = {"engine": "macro_engine", "label": "Macro engine (retired)", "removed": "2026-10-15",
+    "reason": "deleted with the legacy daemon; its quarantine ruling was superseded",
+    "replaced_by": "cpi_nowcast"}
+
+
+class TestRetiredEnginesLeaveATombstone:
+    """Deleted engines do not vanish (v2 spec §9): they stay on the page as `retired`."""
+
+    def test_no_engine_is_retired_until_a_pr_deletes_one(self):
+        assert ENGINE_TOMBSTONES == ()
+        assert engine_catalogue([_row("gas")])["engines_retired"] == 0
+
+    def test_a_tombstone_is_a_retired_entry_with_what_happened_and_what_replaced_it(self):
+        catalogue = engine_catalogue([_row("gas")], tombstones=[_GONE])
+        entry = catalogue["entries"][-1]
+        assert entry["engine"] == "macro_engine" and entry["status"] == STATUS_RETIRED
+        assert entry["retired"] == {"removed": "2026-10-15", "reason": _GONE["reason"],
+                                    "replaced_by": "cpi_nowcast"}
+        assert entry["claim"] is None and entry["claim_note"].startswith("Retired: ")
+        assert entry["measured"] is False and entry["rows"] == []
+
+    def test_retired_engines_are_not_live_engines_in_the_counts(self):
+        live = engine_catalogue([_row("gas")])
+        with_ts = engine_catalogue([_row("gas")], tombstones=[_GONE])
+        for key in ("engines_total", "engines_measured", "engines_not_measured", "engines_unlisted"):
+            assert with_ts[key] == live[key], key
+        assert with_ts["engines_retired"] == 1 and len(with_ts["entries"]) == len(live["entries"]) + 1
+
+    def test_a_retired_engine_keeps_its_backtest_history_and_is_never_also_unlisted(self):
+        catalogue = engine_catalogue([_row("gas"), _row("macro_engine", version="m-v1")], tombstones=[_GONE])
+        retired = [e for e in catalogue["entries"] if e["engine"] == "macro_engine"]
+        assert len(retired) == 1 and retired[0]["status"] == STATUS_RETIRED
+        assert retired[0]["measured"] is True and retired[0]["worst_brier_ratio"] == 4.29
+        assert catalogue["engines_unlisted"] == 0
diff --git a/tradehub/engine_catalogue.py b/tradehub/engine_catalogue.py
index 82eb6b2..ba1eadd 100644
--- a/tradehub/engine_catalogue.py
+++ b/tradehub/engine_catalogue.py
@@ -63,6 +63,17 @@ from tradehub.scoreboard import (
 # statement about the CATALOGUE meeting the scoreboard, which is this module's whole job.
 STATUS_NOT_MEASURED = "not_measured"
 
+# A deleted engine does not vanish from the page: it leaves a tombstone (v2 spec §9), so the
+# truthfulness story survives the deletion. `retired` is a sixth status and, like `not_measured`, it is
+# not a verdict on the engine's accuracy. Its backtest history, if any, stays attached and visible.
+STATUS_RETIRED = "retired"
+
+# One dict per deleted engine: {"engine", "label", "removed" (ISO date), "reason", "replaced_by"}.
+# `replaced_by` names what took over, or is None when nothing did. Add an entry in the SAME PR that
+# deletes the engine; `tests/test_engine_catalogue.py` checks the shape. Empty today: nothing with a
+# scoreboard row has been deleted yet (the wave-1 cuts removed a page and a helper, not an engine).
+ENGINE_TOMBSTONES: tuple[dict[str, Any], ...] = ()
+
 # The four words a row can carry, as a set, so a hand-built or older row whose `market_verdict` is
 # missing does not silently fall through to a verdict nobody resolved. `market_verdict()` is the
 # fallback and is the SAME function the reducer used, so this stays one threshold.
@@ -253,7 +264,10 @@ def worst_brier_ratio(rows: Sequence[Mapping[str, Any]] | None) -> float | None:
     return max(ratios) if ratios else None
 
 
-def engine_catalogue(rows: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
+def engine_catalogue(
+    rows: Iterable[Mapping[str, Any]] | None,
+    tombstones: Sequence[Mapping[str, Any]] | None = None,
+) -> dict[str, Any]:
     """Every engine this product has, each joined to the scoreboard rows that measured it.
 
     Takes the rows `current_runs` produced and adds no measurement of its own. Three things come
@@ -285,6 +299,7 @@ def engine_catalogue(rows: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]
             continue
         by_engine.setdefault(engine, []).append(row)
 
+    retired = {str(ts["engine"]): ts for ts in (ENGINE_TOMBSTONES if tombstones is None else tombstones)}
     entries: list[dict[str, Any]] = []
     seen: set[str] = set()
     for declared in ENGINE_CATALOGUE:
@@ -293,19 +308,45 @@ def engine_catalogue(rows: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]
         entries.append(_entry(declared, by_engine.get(engine, []), in_catalogue=True))
     # Anything with a run that the catalogue does not name, in the order the board produced it.
     for engine, engine_rows in by_engine.items():
-        if engine not in seen:
+        if engine not in seen and engine not in retired:
             entries.append(_entry(None, engine_rows, in_catalogue=False))
 
     measured = sum(1 for entry in entries if entry["measured"])
+    live_total = len(entries)
+    # Tombstones come last and are NOT live engines: they leave `engines_total` and the measured
+    # counts alone, and are counted in their own number. A retired engine with history keeps its rows.
+    for tombstone in retired.values():
+        entries.append(_tombstone_entry(tombstone, by_engine.get(str(tombstone["engine"]), [])))
     return {
-        "engines_total": len(entries),
+        "engines_total": live_total,
         "engines_measured": measured,
-        "engines_not_measured": len(entries) - measured,
-        "engines_unlisted": sum(1 for entry in entries if not entry["in_catalogue"]),
+        "engines_not_measured": live_total - measured,
+        "engines_unlisted": sum(1 for entry in entries if entry["status"] != STATUS_RETIRED and not entry["in_catalogue"]),
+        "engines_retired": len(retired),
         "entries": entries,
     }
 
 
+def _tombstone_entry(tombstone: Mapping[str, Any], engine_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
+    """A deleted engine: what it was, when and why it went, what replaced it, and any history it left."""
+    engine = str(tombstone["engine"])
+    return {
+        "engine": engine,
+        "label": str(tombstone["label"]),
+        "claim": None,
+        "claim_note": "Retired: " + str(tombstone["reason"]),
+        "in_catalogue": False,
+        "cadence": None,
+        "measured": bool(engine_rows),
+        "measured_rows": len(engine_rows),
+        "status": STATUS_RETIRED,
+        "worst_brier_ratio": worst_brier_ratio(engine_rows),
+        "rows": list(engine_rows),
+        "retired": {"removed": str(tombstone["removed"]), "reason": str(tombstone["reason"]),
+                    "replaced_by": tombstone.get("replaced_by")},
+    }
+
+
 def _entry(
     declared: Mapping[str, Any] | None,
     engine_rows: list[Mapping[str, Any]],
```

- [ ] **Step 3: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_engine_catalogue.py tests/test_scoreboard_api.py -v`
Expected: all pass; the existing conservation assertions hold because with no tombstones every count is unchanged.

- [ ] **Step 4: Commit**

```bash
git add tradehub/engine_catalogue.py tests/test_engine_catalogue.py
git commit -m "feat(catalogue): retired status with tombstones for deleted engines"
```

---

### Task 2: Show retired engines on /models

**Files:**
- Modify: `market_sentiment_tool/src/lib/models.ts`, `market_sentiment_tool/src/lib/models.test.ts`, `market_sentiment_tool/src/pages/Models.tsx`

**Interfaces:**
- Consumes: Task 1's `retired` object and `engines_retired`.
- Produces: `EngineStatus` gains `"retired"`; `Retirement` type; `retirementText(entry) -> string | null`; `statusWord("retired") === "Retired"`; `catalogueCounts` appends `· N retired` only when N > 0.

- [ ] **Step 1: Apply the `models.test.ts` hunk** and run `cd market_sentiment_tool && npx vitest run src/lib/models.test.ts` → FAIL (`retirementText` is not exported).

- [ ] **Step 2: Implement**

```diff
diff --git a/market_sentiment_tool/src/lib/models.test.ts b/market_sentiment_tool/src/lib/models.test.ts
index 73b0915..72d78ca 100644
--- a/market_sentiment_tool/src/lib/models.test.ts
+++ b/market_sentiment_tool/src/lib/models.test.ts
@@ -8,6 +8,7 @@ import {
   catalogueCounts,
   claimText,
   displayOnlyNote,
+  retirementText,
   statusTone,
   statusWord,
   worstRatioText,
@@ -251,3 +252,26 @@ describe("catalogueCounts", () => {
     expect(catalogueCounts(catalogue())).not.toMatch(/catalogue/);
   });
 });
+
+describe("retired engines leave a tombstone", () => {
+  const retired = { removed: "2026-10-15", reason: "deleted with the legacy daemon", replaced_by: "cpi_nowcast" };
+
+  it("has its own status word, and the muted tone rather than a loss", () => {
+    expect(statusWord("retired")).toBe("Retired");
+    expect(statusTone("retired")).toBe("unknown");
+  });
+
+  it("says when, why and what replaced it; nothing for a live engine", () => {
+    expect(retirementText({ retired })).toBe(
+      "Retired 2026-10-15: deleted with the legacy daemon. Replaced by cpi_nowcast.",
+    );
+    expect(retirementText({ retired: { ...retired, replaced_by: null } })).toContain("Nothing replaced it.");
+    expect(retirementText({})).toBeNull();
+  });
+
+  it("counts retired engines beside the live ones, and is silent when there are none", () => {
+    const base = { engines_total: 7, engines_measured: 3, engines_not_measured: 4, engines_unlisted: 0, entries: [] };
+    expect(catalogueCounts({ ...base, engines_retired: 2 })).toBe("7 engines · 3 measured · 4 not measured · 2 retired");
+    expect(catalogueCounts({ ...base, engines_retired: 0 })).not.toMatch(/retired/);
+  });
+});
diff --git a/market_sentiment_tool/src/lib/models.ts b/market_sentiment_tool/src/lib/models.ts
index abd0626..a985324 100644
--- a/market_sentiment_tool/src/lib/models.ts
+++ b/market_sentiment_tool/src/lib/models.ts
@@ -44,7 +44,7 @@ import {
  * than a flavour of `not_comparable`. "A run exists and recorded no market Brier" and "there is no
  * run" are different facts, and collapsing them turns a gap in the evidence into a verdict.
  */
-export type EngineStatus = MarketVerdict | "not_measured";
+export type EngineStatus = MarketVerdict | "not_measured" | "retired";
 
 /** One engine, joined to the scoreboard rows that measured it. Self-contained by construction. */
 export interface CatalogueEntry {
@@ -64,6 +64,15 @@ export interface CatalogueEntry {
   worst_brier_ratio: number | null;
   /** The scoreboard's own rows, whole and unmodified. The page re-derives nothing from them. */
   rows: ScoreboardRow[];
+  /** Present only on a deleted engine's tombstone (status "retired"). */
+  retired?: Retirement | null;
+}
+
+/** What happened to a deleted engine. `replaced_by` is null when nothing took over. */
+export interface Retirement {
+  removed: string;
+  reason: string;
+  replaced_by: string | null;
 }
 
 export interface Catalogue {
@@ -72,6 +81,8 @@ export interface Catalogue {
   engines_not_measured: number;
   /** Engines with a backtest run that the catalogue has never heard of. */
   engines_unlisted: number;
+  /** Deleted engines, shown as tombstones. Not counted in `engines_total`. Absent on an older API. */
+  engines_retired?: number;
   entries: CatalogueEntry[];
 }
 
@@ -138,6 +149,8 @@ export function statusWord(status: EngineStatus): string {
       return "Level with the market";
     case "not_comparable":
       return "Not comparable";
+    case "retired":
+      return "Retired";
     default:
       return "Not measured";
   }
@@ -213,6 +226,15 @@ export function catalogueCounts(catalogue: Catalogue | null | undefined): string
     `${formatCount(catalogue.engines_not_measured)} not measured` +
     (catalogue.engines_unlisted > 0
       ? ` · ${formatCount(catalogue.engines_unlisted)} not in the catalogue`
-      : "")
+      : "") +
+    (catalogue.engines_retired ? ` · ${formatCount(catalogue.engines_retired)} retired` : "")
   );
 }
+
+/** One sentence for a tombstone: when it went, why, and what replaced it. Null for a live engine. */
+export function retirementText(entry: Pick<CatalogueEntry, "retired">): string | null {
+  const r = entry.retired;
+  if (!r) return null;
+  const successor = r.replaced_by ? `Replaced by ${r.replaced_by}.` : "Nothing replaced it.";
+  return `Retired ${r.removed}: ${r.reason}. ${successor}`;
+}
diff --git a/market_sentiment_tool/src/pages/Models.tsx b/market_sentiment_tool/src/pages/Models.tsx
index b518b4b..e78072b 100644
--- a/market_sentiment_tool/src/pages/Models.tsx
+++ b/market_sentiment_tool/src/pages/Models.tsx
@@ -12,6 +12,7 @@ import {
   brierPair,
   catalogueCounts,
   claimText,
+  retirementText,
   statusTone,
   statusWord,
   worstRatioText,
@@ -110,6 +111,9 @@ function Row({ entry }: { entry: CatalogueEntry }) {
           data rather than a string in this file -- see `@/lib/models`. */}
       <td className="py-3 pr-3 text-slate-300">
         <p className="max-w-md text-[13px] leading-snug">{claimText(entry)}</p>
+        {retirementText(entry) && (
+          <p className="mt-2 max-w-md text-[11px] leading-snug text-slate-400">{retirementText(entry)}</p>
+        )}
         {/* The display-only ruling, in the row rather than only in the page title: a model
             probability beside a market price reads as an opportunity everywhere else in finance. */}
         {displayOnly && <p className="mt-2 max-w-md text-[11px] leading-snug text-amber-300">{displayOnly}</p>}
```

- [ ] **Step 3: Run**

Run: `cd market_sentiment_tool && npx vitest run src/lib/models.test.ts src/pages/Models.test.tsx && npx tsc --noEmit -p tsconfig.app.json`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add market_sentiment_tool/src/lib/models.ts market_sentiment_tool/src/lib/models.test.ts market_sentiment_tool/src/pages/Models.tsx
git commit -m "feat(ui): show retired engines on /models"
```

---

### Task 3: The no-orders banner and the pre-journal context block

**Files:**
- Create: `market_sentiment_tool/src/components/NoOrdersBanner.tsx`, `market_sentiment_tool/src/components/PreJournalContext.tsx`
- Modify: `market_sentiment_tool/src/App.tsx`, `market_sentiment_tool/src/App.routes.test.tsx`, `market_sentiment_tool/src/pages/Journal.tsx`, `market_sentiment_tool/src/pages/Journal.test.tsx`

**Interfaces:**
- Consumes: plan (f) `Journal`; `buildApiUrl`; `brierPair`; `ScoreboardResponse`.
- Produces: `NoOrdersBanner` (role `note`, text exported as `NO_ORDERS_TEXT`); `PreJournalContext` (section labelled `Pre-journal backtests`).

- [ ] **Step 1: Apply the test hunks** (`App.routes.test.tsx`, `Journal.test.tsx`) and run `cd market_sentiment_tool && npx vitest run src/App.routes.test.tsx src/pages/Journal.test.tsx` → FAIL.

- [ ] **Step 2: Implement**

`market_sentiment_tool/src/components/NoOrdersBanner.tsx`:

```tsx
/**
 * The site-wide line (v2 spec §1): this product places no orders, the ledger is the product.
 * A banner, not a footnote: it sits above every page so no screenshot of a number can lose it.
 */
export const NO_ORDERS_TEXT = "Places no orders — the ledger is the product.";

export function NoOrdersBanner() {
  return (
    <div
      role="note"
      className="border-b border-slate-800 bg-slate-900/70 px-4 py-1.5 text-center text-[11px] uppercase tracking-wider text-slate-400"
    >
      {NO_ORDERS_TEXT}
    </div>
  );
}
```

`market_sentiment_tool/src/components/PreJournalContext.tsx`:

```tsx
import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import { brierPair } from "@/lib/models";
import type { ScoreboardResponse } from "@/lib/scoreboard";

/**
 * Backtests run before the journal existed (v2 spec §2): shown as labelled context, never counted.
 * The journal's N is frozen-then-settled forecasts only; a backtest is a different kind of evidence
 * and must never add to it, so this block says so in the heading and computes nothing.
 */
export function PreJournalContext() {
  const [data, setData] = useState<ScoreboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(buildApiUrl("/api/scoreboard"))
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        setData(payload as ScoreboardResponse);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <section aria-label="Pre-journal backtests">
      <h2 className="mb-1 text-lg font-semibold text-slate-200">Pre-journal backtests</h2>
      <p className="mb-2 text-sm text-slate-500">
        Shown for context only. These ran before the journal existed and are never counted in its settled total.
      </p>
      {error ? (
        <p className="text-sm text-rose-300">Backtest history unavailable: {error}</p>
      ) : !data ? (
        <p className="text-sm text-slate-500">Loading backtest history…</p>
      ) : data.rows.length === 0 ? (
        <p className="text-sm text-slate-400">No backtest runs are recorded.</p>
      ) : (
        <table className="w-full text-xs text-slate-300">
          <thead className="text-slate-500">
            <tr>
              <th className="text-left font-normal">Engine</th>
              <th className="text-left font-normal">Window</th>
              <th className="text-right font-normal">Decisions</th>
              <th className="text-right font-normal">Brier</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={`${row.engine}-${row.engine_version}-${row.mode}`}>
                <td className="font-mono">
                  {row.engine} · {row.engine_version ?? "—"} · {row.mode}
                </td>
                <td>
                  {row.date_from && row.date_to ? `${row.date_from.slice(0, 10)} → ${row.date_to.slice(0, 10)}` : "no window recorded"}
                </td>
                <td className="text-right">{row.n_decisions ?? "not recorded"}</td>
                <td className="text-right font-mono">{brierPair(row)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
```

```diff
diff --git a/market_sentiment_tool/src/App.routes.test.tsx b/market_sentiment_tool/src/App.routes.test.tsx
index 9878d86..1928fd0 100644
--- a/market_sentiment_tool/src/App.routes.test.tsx
+++ b/market_sentiment_tool/src/App.routes.test.tsx
@@ -1,5 +1,5 @@
 import { afterEach, describe, expect, it, vi } from "vitest";
-import { act, render, screen } from "@testing-library/react";
+import { act, cleanup, render, screen } from "@testing-library/react";
 
 import App from "@/App";
 import type { ModelsResponse } from "@/lib/models";
@@ -196,6 +196,14 @@ describe("the sidebar link and the route agree", () => {
     expect(screen.getByRole("link", { name: /journal/i })).toHaveAttribute("href", "/journal");
   });
 
+  it("carries the no-orders line above every page", async () => {
+    for (const path of ["/journal", "/models", "/no-such-route"]) {
+      await renderAppAt(path);
+      expect(screen.getByRole("note")).toHaveTextContent("Places no orders — the ledger is the product.");
+      cleanup();
+    }
+  });
+
   it("redirects the retired /lab to the journal without a 404", async () => {
     // The Prediction Lab was cut (v2 spec §9). Old links must land somewhere real, not on an empty shell.
     await renderAppAt("/lab");
diff --git a/market_sentiment_tool/src/App.tsx b/market_sentiment_tool/src/App.tsx
index 684cd4e..48ea232 100644
--- a/market_sentiment_tool/src/App.tsx
+++ b/market_sentiment_tool/src/App.tsx
@@ -8,6 +8,7 @@ import SportsEdges from "@/pages/SportsEdges";
 import JobsScorecard from "@/pages/JobsScorecard";
 import CpiDisplay from "@/pages/CpiDisplay";
 import Journal from "@/pages/Journal";
+import { NoOrdersBanner } from "@/components/NoOrdersBanner";
 import { usePortfolio } from "@/hooks/usePortfolio";
 import { portfolioHeadline } from "@/lib/portfolioTruth";
 import { LayoutDashboard, Activity, Wallet, Cpu, LineChart, Scale, Trophy, Briefcase, BarChart3, BookOpen } from "lucide-react";
@@ -128,6 +129,7 @@ const AppShell = ({ children }: { children: React.ReactNode }) => {
     <div className="flex min-h-screen bg-slate-950">
       <Sidebar />
       <main className="flex-1 min-h-screen overflow-auto bg-slate-950 text-slate-100">
+        <NoOrdersBanner />
         {children}
       </main>
     </div>
diff --git a/market_sentiment_tool/src/pages/Journal.test.tsx b/market_sentiment_tool/src/pages/Journal.test.tsx
index ba36934..2782938 100644
--- a/market_sentiment_tool/src/pages/Journal.test.tsx
+++ b/market_sentiment_tool/src/pages/Journal.test.tsx
@@ -49,9 +49,17 @@ const feed: JournalFeed = {
   provisional: true,
 };
 
+const scoreboard = {
+  as_of: "2026-10-01T13:00:00+00:00",
+  runs_read: 1,
+  engines: 1,
+  rows: [{ engine: "cpi_nowcast", engine_version: "cpi-v1", mode: "taker", date_from: "2025-01-01T00:00:00+00:00",
+           date_to: "2026-06-30T00:00:00+00:00", n_decisions: 412, brier_ours: 0.0712, brier_market: 0.0683 }],
+};
+
 function stubFetch() {
   const fn = vi.fn((url: string) => {
-    const body = url.includes("/api/journal/feed") ? feed : journal;
+    const body = url.includes("/api/journal/feed") ? feed : url.includes("/api/scoreboard") ? scoreboard : journal;
     return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
   });
   vi.stubGlobal("fetch", fn);
@@ -73,6 +81,16 @@ describe("Journal", () => {
     expect(within(tile).getByText(/overconfident by 15.0pp/)).toBeInTheDocument();
   });
 
+  it("shows backtests as labelled context that is never counted in the journal's N", async () => {
+    stubFetch();
+    render(<Journal />);
+    const section = await screen.findByLabelText("Pre-journal backtests");
+    expect(await within(section).findByText(/never counted in its settled total/)).toBeInTheDocument();
+    expect(within(section).getByText("cpi_nowcast · cpi-v1 · taker")).toBeInTheDocument();
+    expect(within(section).getByText("2025-01-01 → 2026-06-30")).toBeInTheDocument();
+    expect(screen.getByLabelText("Headline")).toHaveTextContent("0 of 3 forecasters calibrated");  // untouched
+  });
+
   it("says unscored in words and labels the FOMC model experimental", async () => {
     stubFetch();
     render(<Journal />);
diff --git a/market_sentiment_tool/src/pages/Journal.tsx b/market_sentiment_tool/src/pages/Journal.tsx
index 480502f..3a3f920 100644
--- a/market_sentiment_tool/src/pages/Journal.tsx
+++ b/market_sentiment_tool/src/pages/Journal.tsx
@@ -2,6 +2,7 @@ import { useEffect, useState } from "react";
 
 import { buildApiUrl } from "@/lib/api";
 import { GateBadge } from "@/components/GateBadge";
+import { PreJournalContext } from "@/components/PreJournalContext";
 import { QuarantineNotice } from "@/components/QuarantineNotice";
 import { useQuarantine } from "@/hooks/useQuarantine";
 import {
@@ -192,6 +193,8 @@ export default function Journal() {
         </section>
       )}
 
+      <PreJournalContext />
+
       <section aria-label="Quarantine">
         <h2 className="mb-2 text-lg font-semibold text-slate-200">Quarantine</h2>
         <p className="mb-2 text-sm text-slate-500">Scored in public, excluded from every headline number above.</p>
```

- [ ] **Step 3: Run the whole frontend**

Run: `cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx eslint src/App.tsx src/components/NoOrdersBanner.tsx src/components/PreJournalContext.tsx src/pages/Journal.tsx src/lib/models.ts src/pages/Models.tsx && npx vite build`
Expected: vitest all pass (reviewer baseline 433), tsc/eslint silent, build succeeds.

- [ ] **Step 4: Commit**

```bash
git add market_sentiment_tool/src
git commit -m "feat(ui): no-orders banner and labelled pre-journal backtests on /journal"
```

---

### Task 4: Verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass.

- [ ] Ruff on every file this plan created or changed: `.venv/bin/python -m ruff check <files>` → `All checks passed!` (pre-existing ruff debt elsewhere is not yours to fix here).
- [ ] Open the PR from a fresh branch off `main`. Body: what changed, the verification output, and whether a migration needs applying.

## Self-Review

- **Spec §1:** the no-orders line is a site-wide banner above every page, asserted on three routes including an unknown one.
- **Spec §2:** prior backtests appear on the journal as labelled pre-journal context and never count toward N (the headline is asserted unchanged with the block present).
- **Spec §9:** `retired` is a sixth catalogue status with a tombstone (removed date, reason, replaced-by) and its own count; it cannot disturb the live-engine totals, which the existing conservation tests still pin.
- **Type consistency:** the backend keys `retired`, `engines_retired` match `Retirement` and `Catalogue.engines_retired` in `models.ts`.
