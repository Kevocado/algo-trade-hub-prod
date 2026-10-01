# Readable Journal and Sports Pages (Plan o) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild /journal and /sports so a visitor gets the state in five seconds: three big numbers, plain words, one row per game, and a hard cap on explanatory copy that tests enforce.

**Architecture:** Pure view logic first (`forecasterLabels`, `journalView`, `sportsPicks`, each unit-tested), then two shared components (`Stat`, `Chip`), then the two pages built on them. The pages render server numbers and compute nothing. A test helper `copyWords` counts the words in headings and paragraphs only (tables, chips and buttons are data), and each page test asserts a word budget, so the copy cannot grow back into essays. The retired quarantine surface leaves /journal.

**Tech Stack:** React + TypeScript, Tailwind (existing dark slate theme), vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§11 Journal UI; owner feedback 2026-10-01: too text-heavy, says nothing in particular). **Depends on:** plans (f), (i) and (l) merged (they are). Independent of plans (n), (p), (q), (r).

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (frontend vitest 422 passed, tsc clean, eslint clean on every new file, build succeeds; both pages inspected in a browser against the live API (desktop width)). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- **The design rules, which every later page plan inherits:**
  1. **Numbers first.** The top of a page is two to four big numbers (`Stat`), each with a two-to-four-word label. No paragraph before them.
  2. **One sentence of intro, at most**, under the title, 15 words or fewer.
  3. **Verdicts are words, not paragraphs:** a `Chip` with one or two words (`Too early`, `Ahead`, `Behind`, `Waiting`, `Promoted`).
  4. **Plain names.** Raw ids (`spy_quant@spy-wf-v1`, `kalshi_implied_cpi`) appear only in a detail view or a tooltip, never as the headline of a row. Names come from `forecasterLabels.ts`.
  5. **Detail on request.** Calibration tables, locked-in forecasts, gate reasons and backtests sit behind a click and are not mounted (or fetched) until opened.
  6. **A missing figure is a word** (`—`, `Waiting`), never `0`.
  7. **Word budget enforced by test:** `copyWords(container) <= 45` per page (headings, paragraphs and summaries only). If a page needs more, show a number or move text behind a click.
- Keep the existing dark slate theme, the sidebar and the site-wide no-orders banner. This is a content and layout rewrite, not a rebrand.
- Use the `impeccable` skill's `distill` and `clarify` commands (operate mode) if you refine further; do not add a new visual world or fonts.
- **Sports behaviour decisions, for Kevin to confirm in the PR:** (a) one row per game and bet type (a winner market exists for both teams, so both sides of a game are the same bet); (b) a pick is featured as a top pick only if the reviewer passed it **and** its model/market gap is at most 25 points (`LARGE_GAP_POINTS`, chosen before looking at outcomes: a 78% model against a 32% market is more likely a model error than an opportunity); a larger gap is listed under "flagged" with the gap shown; (c) when nothing passes review the page says so instead of filling the screen. Today that is the honest state: the reviewer flagged all 28 candidate rows.
- The retired quarantine surface is removed from /journal (`QuarantineNotice`, `useQuarantine`, `lib/quarantine`): its only producer, the legacy daemon, was deleted, so it could only ever say "nothing". The backend endpoint and tables stay.
- Do not change any API or backend code in this plan.
- `vite.config.ts` gains an optional dev proxy so a page can be inspected against the deployed API without CORS: `DEV_API_PROXY=https://algo.40-160-91-131.sslip.io npx vite --port 8081`. The app also needs dummy `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` values locally (it builds a Supabase client at import); use placeholders such as `http://127.0.0.1:1` and `local-dummy`. Never use real keys for this.

---
### Task 1: Shared pieces and view logic

**Files:**
- Create: `market_sentiment_tool/src/test/copyWords.ts`, `market_sentiment_tool/src/components/Stat.tsx`, `market_sentiment_tool/src/components/Chip.tsx`, `market_sentiment_tool/src/lib/forecasterLabels.ts`, `market_sentiment_tool/src/lib/journalView.ts`, `market_sentiment_tool/src/lib/journalView.test.ts`
- Modify: `market_sentiment_tool/src/lib/journal.ts` (`MARKET_PAIR` gains the two sports baselines), `market_sentiment_tool/src/components/PreJournalContext.tsx` (drops its own heading and paragraph; the page labels it)

**Interfaces:**
- Produces: `copyWords(root)`; `Stat({value,label,hint?})`; `Chip({tone,children,title?})`; `forecasterLabel(forecaster, version?)`, `baselineName(baseline)`; `viewRows(scores) -> ViewRow[]`, `split(rows) -> {results, waiting}`, `totals(rows)`, `statusOf(score)`, `STATUS_WORDS`, `skillText(skill)`, `EARLY_N = 30`, `NEEDED`.

- [ ] **Step 1: Write the failing test** (`market_sentiment_tool/src/lib/journalView.test.ts`)

```ts
import { describe, expect, it } from "vitest";

import { forecasterLabel } from "@/lib/forecasterLabels";
import { baselineName } from "@/lib/forecasterLabels";
import type { JournalScore } from "@/lib/journal";
import { EARLY_N, skillText, split, statusOf, totals, viewRows } from "@/lib/journalView";

function score(over: Partial<JournalScore> = {}): JournalScore {
  return {
    forecaster: "spy_quant", forecaster_version: "spy-wf-v1", cadence: "daily", baseline: "climatology",
    n_targets: 3, n_settled: 0, brier: null, brier_baseline: null, bss: null, reliability: [], murphy: {},
    calibration_ready: false, gate_status: "SHADOW", gate_reasons: [], computed_at: "2026-10-01T00:00:00Z", ...over,
  };
}

describe("labels", () => {
  it("speaks plainly and falls back to the raw name made readable", () => {
    expect(forecasterLabel("spy_quant")).toBe("S&P 500 tomorrow: model");
    expect(forecasterLabel("cpi_nowcast", "cpi-core-v1")).toBe("Core inflation (CPI)");
    expect(forecasterLabel("cpi_nowcast", "cpi-v1")).toBe("Inflation (CPI)");
    expect(forecasterLabel("new_thing")).toBe("New thing");
    expect(baselineName("market")).toBe("the Kalshi price");
  });
});

describe("status", () => {
  it("is waiting with nothing scored, too early before enough evidence, then ahead or behind", () => {
    expect(statusOf(score())).toBe("waiting");
    expect(statusOf(score({ n_settled: 1, bss: 0.2 }))).toBe("early");
    expect(statusOf(score({ n_settled: EARLY_N, bss: null }))).toBe("early");
    expect(statusOf(score({ n_settled: EARLY_N, bss: 0.05 }))).toBe("ahead");
    expect(statusOf(score({ n_settled: EARLY_N, bss: -0.05 }))).toBe("behind");
    expect(statusOf(score({ n_settled: 250, bss: 0.1, gate_status: "PROMOTED" }))).toBe("promoted");
  });
});

describe("view", () => {
  const scores = [
    score(),
    score({ forecaster: "sports_nfl", forecaster_version: "feed-v1", baseline: "market", n_settled: 4, n_targets: 6 }),
    score({ forecaster: "kalshi_implied_sports_nfl", forecaster_version: "v1", n_settled: 4, n_targets: 6 }),
    score({ forecaster: "housing_direction", forecaster_version: "housing-wf-v1", cadence: "monthly" }),
  ];

  it("folds the Kalshi baseline into its model's row and orders scored rows first", () => {
    const { results, waiting } = split(viewRows(scores));
    expect(results.map((r) => r.label)).toEqual(["NFL winners"]);
    expect(results[0].market?.forecaster).toBe("kalshi_implied_sports_nfl");
    expect(results[0].against).toBe("the Kalshi price");
    expect(waiting.map((r) => r.label)).toEqual(["S&P 500 tomorrow: model", "US home prices"]);
  });

  it("counts what the page headlines, and a monthly forecaster needs 50 not 200", () => {
    const rows = viewRows(scores);
    expect(totals(rows)).toEqual({ forecasters: 3, frozen: 12, scored: 4, promoted: 0 });
    expect(rows.find((r) => r.label === "US home prices")?.needed).toBe(50);
  });

  it("writes skill signed and never as a bare zero for 'not measured'", () => {
    expect(skillText(0.234)).toBe("+0.23");
    expect(skillText(-0.097)).toBe("-0.10");
    expect(skillText(null)).toBe("—");
  });
});
```

- [ ] **Step 2: Run it** — `cd market_sentiment_tool && npx vitest run src/lib/journalView.test.ts` — Expected: FAIL (modules missing).

- [ ] **Step 3: Implement**

`market_sentiment_tool/src/test/copyWords.ts`:

```ts
/**
 * How much explaining a page does, in words: everything inside headings and paragraphs, nothing inside
 * tables, chips, buttons or links (those are the data). Page tests assert a budget on this so the copy
 * cannot quietly grow back into essays. A page that needs more words should show a number instead.
 */
export function copyWords(root: ParentNode): number {
  const nodes = Array.from(root.querySelectorAll("h1, h2, h3, p, summary"));
  return nodes
    .map((node) => (node.textContent ?? "").trim())
    .filter(Boolean)
    .reduce((total, text) => total + text.split(/\s+/).length, 0);
}
```

`market_sentiment_tool/src/components/Stat.tsx`:

```tsx
/** One big number and what it counts. The page's first read: a visitor should get the state from these alone. */
export function Stat({ value, label, hint }: { value: string | number; label: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-5 py-4">
      <div className="text-4xl font-semibold tabular-nums tracking-tight text-white">{value}</div>
      <div className="mt-1 text-sm text-slate-300">{label}</div>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}
```

`market_sentiment_tool/src/components/Chip.tsx`:

```tsx
const TONES = {
  good: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  bad: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  warn: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  quiet: "border-slate-700 bg-slate-800/60 text-slate-300",
} as const;

export type Tone = keyof typeof TONES;

/** A one-or-two-word verdict. The word does the work; the colour only agrees with it. */
export function Chip({ tone = "quiet", children, title }: { tone?: Tone; children: React.ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-block rounded-full border px-2.5 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {children}
    </span>
  );
}
```

`market_sentiment_tool/src/lib/forecasterLabels.ts`:

```ts
import type { Baseline } from "@/lib/journal";

/** Plain-language names for the journal's forecasters. The raw `name@version` stays in the detail view. */
const BASE: Record<string, string> = {
  cpi_nowcast: "Inflation (CPI)",
  fomc_mapped: "Fed rate decision",
  labor_nowcast: "Jobs report (payrolls)",
  unrate_direction: "Unemployment rate",
  quits_direction: "Job quits",
  sentiment_meter: "S&P 500 tomorrow: sentiment",
  spy_quant: "S&P 500 tomorrow: model",
  vix_direction: "Volatility (VIX) tomorrow",
  gold_direction: "Gold tomorrow",
  eurusd_direction: "Euro vs dollar tomorrow",
  housing_direction: "US home prices",
  sports_nfl: "NFL winners",
  sports_cfb: "College football winners",
};

const VERSIONED: Record<string, string> = {
  "cpi_nowcast@cpi-core-v1": "Core inflation (CPI)",
};

export function forecasterLabel(forecaster: string, version?: string): string {
  if (version && VERSIONED[`${forecaster}@${version}`]) return VERSIONED[`${forecaster}@${version}`];
  if (BASE[forecaster]) return BASE[forecaster];
  const text = forecaster.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** What a forecaster is being compared with, in words a visitor already knows. */
export function baselineName(baseline: Baseline): string {
  if (baseline === "market") return "the Kalshi price";
  if (baseline === "climatology") return "the usual rate";
  return "no baseline yet";
}
```

`market_sentiment_tool/src/lib/journalView.ts`:

```ts
import { baselineName, forecasterLabel } from "@/lib/forecasterLabels";
import { tiles, type Baseline, type JournalScore } from "@/lib/journal";

/**
 * The /journal page's view of the scorecards: one row per forecaster, ordered by how much evidence it has.
 * Presentation only. Every number comes from the server; the only constants here are display rules.
 */

/** Below this many scored forecasts a skill number is too noisy to praise or blame. Display rule, not a gate. */
export const EARLY_N = 30;

/** Mirrors `MIN_SETTLED` in tradehub/journal/scoring.py, for the "x of y" progress hint only. */
export const NEEDED: Record<JournalScore["cadence"], number> = { daily: 200, monthly: 50, meeting: 50 };

export type Status = "waiting" | "early" | "ahead" | "behind" | "promoted";

export interface ViewRow {
  key: string;
  label: string;
  frozen: number;
  scored: number;
  needed: number;
  skill: number | null;
  against: string;
  baseline: Baseline;
  status: Status;
  score: JournalScore;
  market: JournalScore | null;
}

export function statusOf(score: JournalScore): Status {
  if (score.n_settled === 0) return "waiting";
  if (score.gate_status === "PROMOTED") return "promoted";
  if (score.n_settled < EARLY_N || score.bss === null) return "early";
  return score.bss > 0 ? "ahead" : "behind";
}

export const STATUS_WORDS: Record<Status, string> = {
  waiting: "Waiting",
  early: "Too early",
  ahead: "Ahead",
  behind: "Behind",
  promoted: "Promoted",
};

export function viewRows(scores: JournalScore[]): ViewRow[] {
  return tiles(scores).map(({ model, market }) => ({
    key: `${model.forecaster}@${model.forecaster_version}`,
    label: forecasterLabel(model.forecaster, model.forecaster_version),
    frozen: model.n_targets,
    scored: model.n_settled,
    needed: NEEDED[model.cadence] ?? NEEDED.daily,
    skill: model.bss,
    against: baselineName(model.baseline),
    baseline: model.baseline,
    status: statusOf(model),
    score: model,
    market,
  }));
}

/** Rows with at least one scored forecast first (most evidence first); the rest wait. */
export function split(rows: ViewRow[]): { results: ViewRow[]; waiting: ViewRow[] } {
  const results = rows.filter((r) => r.scored > 0).sort((a, b) => b.scored - a.scored);
  const waiting = rows.filter((r) => r.scored === 0).sort((a, b) => a.label.localeCompare(b.label));
  return { results, waiting };
}

export interface Totals {
  forecasters: number;
  frozen: number;
  scored: number;
  promoted: number;
}

export function totals(rows: ViewRow[]): Totals {
  return {
    forecasters: rows.length,
    frozen: rows.reduce((n, r) => n + r.frozen, 0),
    scored: rows.reduce((n, r) => n + r.scored, 0),
    promoted: rows.filter((r) => r.status === "promoted").length,
  };
}

/** Signed to three places, never a bare 0 for "not measured". */
export function skillText(skill: number | null): string {
  if (skill === null) return "—";
  return `${skill > 0 ? "+" : ""}${skill.toFixed(2)}`;
}
```

```diff
diff --git a/market_sentiment_tool/src/components/PreJournalContext.tsx b/market_sentiment_tool/src/components/PreJournalContext.tsx
index 2744094..2bb614c 100644
--- a/market_sentiment_tool/src/components/PreJournalContext.tsx
+++ b/market_sentiment_tool/src/components/PreJournalContext.tsx
@@ -5,9 +5,9 @@ import { brierPair } from "@/lib/models";
 import type { ScoreboardResponse } from "@/lib/scoreboard";
 
 /**
- * Backtests run before the journal existed (v2 spec §2): shown as labelled context, never counted.
- * The journal's N is frozen-then-settled forecasts only; a backtest is a different kind of evidence
- * and must never add to it, so this block says so in the heading and computes nothing.
+ * Backtests run before the journal existed (v2 spec §2): context only, never counted. The caller labels
+ * it ("Past backtests (not counted)") and mounts it only when opened, so it adds no words or requests
+ * until a visitor asks for it. Computes nothing.
  */
 export function PreJournalContext() {
   const [data, setData] = useState<ScoreboardResponse | null>(null);
@@ -25,10 +25,6 @@ export function PreJournalContext() {
 
   return (
     <section aria-label="Pre-journal backtests">
-      <h2 className="mb-1 text-lg font-semibold text-slate-200">Pre-journal backtests</h2>
-      <p className="mb-2 text-sm text-slate-500">
-        Shown for context only. These ran before the journal existed and are never counted in its settled total.
-      </p>
       {error ? (
         <p className="text-sm text-rose-300">Backtest history unavailable: {error}</p>
       ) : !data ? (
diff --git a/market_sentiment_tool/src/lib/journal.ts b/market_sentiment_tool/src/lib/journal.ts
index 64d6138..c040a7b 100644
--- a/market_sentiment_tool/src/lib/journal.ts
+++ b/market_sentiment_tool/src/lib/journal.ts
@@ -83,6 +83,8 @@ export const MARKET_PAIR: Record<string, string> = {
   cpi_nowcast: "kalshi_implied_cpi",
   fomc_mapped: "kalshi_implied_fomc",
   labor_nowcast: "kalshi_implied_labor",
+  sports_nfl: "kalshi_implied_sports_nfl",
+  sports_cfb: "kalshi_implied_sports_cfb",
 };
 
 /** Forecasters the spec labels experimental (ruling Q5). */
```

- [ ] **Step 4: Run** — `npx vitest run src/lib/journalView.test.ts src/lib/journal.test.ts` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/src
git commit -m "ui: plain-language view logic and shared Stat and Chip"
```

---

### Task 2: The new /journal

**Files:**
- Modify: `market_sentiment_tool/src/pages/Journal.tsx` (full rewrite), `market_sentiment_tool/src/pages/Journal.test.tsx` (full rewrite)
- Delete: `market_sentiment_tool/src/components/QuarantineNotice.tsx`, `market_sentiment_tool/src/components/QuarantineNotice.test.tsx`, `market_sentiment_tool/src/hooks/useQuarantine.ts`, `market_sentiment_tool/src/lib/quarantine.ts`, `market_sentiment_tool/src/lib/quarantine.test.ts`

**Interfaces:**
- Consumes: Task 1; `/api/journal`, `/api/journal/feed`, `/api/scoreboard`.
- Produces: `/journal` with sections labelled `Totals`, `Results`, `Waiting`, a click-to-open detail row, and a lazy `Past backtests (not counted)` block.

- [ ] **Step 1: Write the failing test** (`market_sentiment_tool/src/pages/Journal.test.tsx`, replaces the old file)

```tsx
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import Journal from "@/pages/Journal";
import type { JournalFeed, JournalResponse, JournalScore } from "@/lib/journal";
import { copyWords } from "@/test/copyWords";

function score(over: Partial<JournalScore> = {}): JournalScore {
  return {
    forecaster: "spy_quant", forecaster_version: "spy-wf-v1", cadence: "daily", baseline: "climatology", n_targets: 2,
    n_settled: 1, brier: 0.311, brier_baseline: 0.2836, bss: -0.0966,
    reliability: [{ bucket: "50-60", n: 1, predicted: 0.558, observed: 0 }], murphy: {}, calibration_ready: false,
    gate_status: "SHADOW", gate_reasons: ["only 1 settled targets, need 200 (daily)"], computed_at: "2026-10-01T13:00:00+00:00", ...over,
  };
}

const waiting = (forecaster: string, version: string, over: Partial<JournalScore> = {}) =>
  score({ forecaster, forecaster_version: version, n_settled: 0, n_targets: 0, brier: null, bss: null, baseline: "none",
          reliability: [], gate_reasons: [], ...over });

const journal: JournalResponse = {
  as_of: "2026-10-01T13:00:00+00:00",
  forecasters: [
    score(),
    score({ forecaster: "sentiment_meter", forecaster_version: "meter-v1", brier: 0.277, bss: 0.0234 }),
    waiting("cpi_nowcast", "cpi-v1", { cadence: "monthly" }),
    waiting("cpi_nowcast", "cpi-core-v1", { cadence: "monthly" }),
    waiting("kalshi_implied_cpi", "v1", { cadence: "monthly" }),
    waiting("housing_direction", "housing-wf-v1", { cadence: "monthly" }),
  ],
  headline: { forecasters: 6, calibrated: 0, settled_calibrated: 0, promoted: 0 },
};

const feed: JournalFeed = {
  forecaster: "spy_quant", forecaster_version: "spy-wf-v1", generated_at: "2026-10-01T13:00:00+00:00",
  forecasts: [{ target: "spx:2026-09-30:up", probability: 0.558, market_prob: null, frozen_at: "2026-09-30T10:17:00+00:00", rebuilt: false, source_hash: "h" }],
  calibration: [], gate_status: "SHADOW", provisional: true,
};

const scoreboard = { as_of: "x", runs_read: 1, engines: 1, rows: [{ engine: "cpi_nowcast", engine_version: "cpi-v1", mode: "taker",
  date_from: "2025-01-01T00:00:00+00:00", date_to: "2026-06-30T00:00:00+00:00", n_decisions: 412, brier_ours: 0.0712, brier_market: 0.0683 }] };

function stubFetch() {
  const fn = vi.fn((url: string) => {
    const body = url.includes("/api/journal/feed") ? feed : url.includes("/api/scoreboard") ? scoreboard : journal;
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("Journal", () => {
  it("leads with three numbers and only the forecasters that have results", async () => {
    stubFetch();
    render(<Journal />);
    const totals = await screen.findByLabelText("Totals");
    expect(within(totals).getByText("forecasts locked in").previousSibling).toHaveTextContent("4");
    expect(within(totals).getByText("scored so far").previousSibling).toHaveTextContent("2");
    expect(within(totals).getByText("promoted").previousSibling).toHaveTextContent("0");
    const results = screen.getByLabelText("Results");
    expect(within(results).getByText("S&P 500 tomorrow: model")).toBeInTheDocument();
    expect(within(results).getByText("-0.10")).toBeInTheDocument();
    expect(within(results).getAllByText("Too early").length).toBe(2);
  });

  it("lists forecasters with nothing scored as short chips, in plain words, with the baseline folded away", async () => {
    stubFetch();
    render(<Journal />);
    const list = await screen.findByLabelText("Waiting");
    expect(within(list).getByText("Inflation (CPI)")).toBeInTheDocument();
    expect(within(list).getByText("Core inflation (CPI)")).toBeInTheDocument();
    expect(within(list).getByText("US home prices")).toBeInTheDocument();
    expect(within(list).queryByText(/kalshi_implied/i)).toBeNull();
  });

  it("opens a forecaster's calibration and locked-in forecasts only on request", async () => {
    stubFetch();
    render(<Journal />);
    fireEvent.click(await screen.findByRole("button", { name: "S&P 500 tomorrow: model" }));
    expect(await screen.findByLabelText("Calibration spy_quant@spy-wf-v1")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("spx:2026-09-30:up")).toBeInTheDocument());
  });

  it("loads past backtests only when asked, and says they are not counted", async () => {
    const fetchFn = stubFetch();
    render(<Journal />);
    await screen.findByLabelText("Totals");
    expect(fetchFn.mock.calls.some(([u]) => String(u).includes("/api/scoreboard"))).toBe(false);
    const summary = screen.getByText("Past backtests (not counted)");
    const details = summary.closest("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect(await screen.findByText("cpi_nowcast · cpi-v1 · taker")).toBeInTheDocument();
  });

  it("stays inside its word budget", async () => {
    stubFetch();
    const { container } = render(<Journal />);
    await screen.findByLabelText("Totals");
    expect(copyWords(container)).toBeLessThanOrEqual(45);
  });

  it("shows the API's error instead of an empty ledger", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({ detail: "journal_scores is missing: apply 20260428000014" }) })));
    render(<Journal />);
    expect(await screen.findByText(/apply 20260428000014/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it** — `npx vitest run src/pages/Journal.test.tsx` — Expected: FAIL (the old page has no `Totals` section).

- [ ] **Step 3: Implement**

`market_sentiment_tool/src/pages/Journal.tsx`:

```tsx
import { Fragment, useEffect, useState } from "react";

import { Chip, type Tone } from "@/components/Chip";
import { PreJournalContext } from "@/components/PreJournalContext";
import { Stat } from "@/components/Stat";
import { buildApiUrl } from "@/lib/api";
import {
  biasReadout,
  costsText,
  pct,
  type JournalFeed,
  type JournalResponse,
} from "@/lib/journal";
import { STATUS_WORDS, skillText, split, totals, viewRows, type Status, type ViewRow } from "@/lib/journalView";

/**
 * /journal: every forecaster's locked-in, scored record, numbers first.
 *
 * Three numbers, then the forecasters that have results, then a one-line list of those still waiting.
 * Everything else (calibration, the frozen forecasts, why a gate is closed) is one click away, because
 * the first read should be the state of the whole journal, not 19 tiles saying "not scored yet".
 * Nothing here computes a score: the server does, and this renders it.
 */

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(buildApiUrl(path));
  const payload = await response.json();
  if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
  return payload as T;
}

const STATUS_TONE: Record<Status, Tone> = { waiting: "quiet", early: "quiet", ahead: "good", behind: "bad", promoted: "good" };

function Detail({ row }: { row: ViewRow }) {
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

export default function Journal() {
  const [data, setData] = useState<JournalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [backtests, setBacktests] = useState(false);

  useEffect(() => {
    getJson<JournalResponse>("/api/journal").then(setData).catch((e: Error) => setError(e.message));
  }, []);

  if (error) {
    return (
      <div className="p-8">
        <div className="rounded-lg border border-rose-900 bg-rose-950/30 p-4 text-sm text-rose-200">
          <p className="font-semibold">Journal unavailable</p>
          <p className="mt-1 text-rose-300/80">{error}</p>
        </div>
      </div>
    );
  }
  if (!data) return <div className="p-8 text-slate-400">Loading journal…</div>;

  const rows = viewRows(data.forecasters);
  const { results, waiting } = split(rows);
  const t = totals(rows);

  return (
    <div className="mx-auto max-w-5xl space-y-10 p-6 md:p-8">
      <header>
        <h1 className="text-3xl font-bold text-white">Prediction Journal</h1>
        <p className="mt-2 text-slate-400">Forecasts locked in before the event, scored after.</p>
      </header>

      <section aria-label="Totals" className="grid gap-3 sm:grid-cols-3">
        <Stat value={t.frozen} label="forecasts locked in" />
        <Stat value={t.scored} label="scored so far" />
        <Stat value={t.promoted} label="promoted" hint="Needs 200 scored (daily) or 50 (monthly)." />
      </section>

      {results.length > 0 && (
        <section aria-label="Results">
          <h2 className="mb-3 text-lg font-semibold text-slate-200">Scored so far</h2>
          <table className="w-full text-sm">
            <thead className="text-xs uppercase tracking-wider text-slate-500">
              <tr>
                <th className="py-2 text-left font-normal">Forecast</th>
                <th className="py-2 text-right font-normal">Scored</th>
                <th className="py-2 text-right font-normal" title="Positive means better than the baseline">Skill</th>
                <th className="py-2 pl-4 text-left font-normal">Status</th>
              </tr>
            </thead>
            <tbody>
              {results.map((row) => (
                <Fragment key={row.key}>
                  <tr className="border-t border-slate-800">
                    <td className="py-3">
                      <button
                        type="button"
                        aria-expanded={open === row.key}
                        onClick={() => setOpen(open === row.key ? null : row.key)}
                        className="text-left text-slate-100 hover:text-white"
                      >
                        {row.label}
                      </button>
                      <div className="text-xs text-slate-500">vs {row.against}</div>
                    </td>
                    <td className="py-3 text-right tabular-nums text-slate-300">
                      {row.scored} <span className="text-slate-600">of {row.needed}</span>
                    </td>
                    <td className="py-3 text-right text-lg tabular-nums text-slate-100">{skillText(row.skill)}</td>
                    <td className="py-3 pl-4"><Chip tone={STATUS_TONE[row.status]}>{STATUS_WORDS[row.status]}</Chip></td>
                  </tr>
                  {open === row.key && (
                    <tr><td colSpan={4} className="border-t border-slate-800/60"><Detail row={row} /></td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {waiting.length > 0 && (
        <section aria-label="Waiting">
          <h2 className="mb-3 text-lg font-semibold text-slate-200">Waiting for results</h2>
          <ul className="flex flex-wrap gap-2">
            {waiting.map((row) => (
              <li key={row.key}><Chip title={row.key}>{row.label}</Chip></li>
            ))}
          </ul>
        </section>
      )}

      <details onToggle={(e) => setBacktests((e.currentTarget as HTMLDetailsElement).open)}>
        <summary className="cursor-pointer text-sm text-slate-400">Past backtests (not counted)</summary>
        <div className="mt-3">{backtests && <PreJournalContext />}</div>
      </details>
    </div>
  );
}
```

```bash
git rm market_sentiment_tool/src/components/QuarantineNotice.tsx market_sentiment_tool/src/components/QuarantineNotice.test.tsx market_sentiment_tool/src/hooks/useQuarantine.ts market_sentiment_tool/src/lib/quarantine.ts market_sentiment_tool/src/lib/quarantine.test.ts
```

- [ ] **Step 4: Run** — `npx vitest run && npx tsc --noEmit -p tsconfig.app.json` — Expected: all pass, tsc silent.

- [ ] **Step 5: Commit**

```bash
git add -A market_sentiment_tool/src
git commit -m "ui: a readable /journal: three numbers, results, a one-line waiting list"
```

---

### Task 3: The new /sports

**Files:**
- Create: `market_sentiment_tool/src/lib/sportsPicks.ts`, `market_sentiment_tool/src/lib/sportsPicks.test.ts`, `market_sentiment_tool/src/pages/SportsEdges.test.tsx`
- Modify: `market_sentiment_tool/src/pages/SportsEdges.tsx` (full rewrite), `market_sentiment_tool/src/lib/sportsEdges.test.ts` (retire the one test that pinned the old page header)

**Interfaces:**
- Consumes: `SportsEdge` and `SportsEdgesResponse` from `@/lib/sportsEdges` (unchanged); `/api/sports-edges` (limit up to 200, paged by the page).
- Produces: `toPicks(edges)`, `board(edges) -> {topPicks, flagged, unreviewed, noEdge}`, `gapPoints`, `gapText`, `LARGE_GAP_POINTS = 25`, `SportsPick`.

- [ ] **Step 1: Write the failing tests**

```ts
import { describe, expect, it } from "vitest";

import { board, gapPoints, gapText, LARGE_GAP_POINTS, toPicks } from "@/lib/sportsPicks";
import type { SportsEdge } from "@/lib/sportsEdges";

function edge(over: Partial<SportsEdge> = {}): SportsEdge {
  return {
    market_id: "M1", title: "UConn wins", our_prob: 0.7, market_prob: 0.55, edge_pct: 0.1, market_url: "k", source_url: "p",
    sport: "cfb", kind: "winner", side: "yes", entry_price: 0.55, maker: true, home: "UConn", away: "Syracuse",
    start_utc: "2026-10-03T16:00:00+00:00", game_id: "g1", tier: "flagged", candidate: true, reject_reasons: [],
    review: null, engine: "sports_cfb", engine_version: null, gate_status: "SHADOW", ...over,
  };
}

describe("gap", () => {
  it("is the model minus the market for the side you would take", () => {
    expect(gapPoints(edge({ side: "yes", our_prob: 0.78, market_prob: 0.32 }))).toBeCloseTo(46);
    expect(gapPoints(edge({ side: "no", our_prob: 0.18, market_prob: 0.43 }))).toBeCloseTo(25);
    expect(gapText(46.3)).toBe("+46");
    expect(gapText(-4.2)).toBe("-4");
  });
});

describe("one pick per game", () => {
  it("folds the two sides of a winner market into one pick, naming the team to win", () => {
    const yes = edge({ market_id: "A", title: "UConn wins", side: "yes", our_prob: 0.78, market_prob: 0.32 });
    const no = edge({ market_id: "B", title: "Syracuse wins", side: "no", our_prob: 0.22, market_prob: 0.68 });
    const picks = toPicks([no, yes]);
    expect(picks).toHaveLength(1);
    expect(picks[0].call).toBe("UConn to win");
    expect(picks[0].model).toBe(78);
    expect(picks[0].market).toBe(32);
  });

  it("names the OTHER team when the kept row is the NO side, matching 'Iowa St.' to 'Iowa State'", () => {
    const pick = toPicks([edge({ title: "West Virginia wins", side: "no", home: "Iowa State", away: "West Virginia",
                                  our_prob: 0.18, market_prob: 0.41 })])[0];
    expect(pick.call).toBe("Iowa State to win");
    expect(pick.model).toBe(82);
    expect(pick.market).toBe(59);
    const abbrev = toPicks([edge({ title: "Iowa St. wins", side: "yes", home: "Iowa State", away: "West Virginia" })])[0];
    expect(abbrev.call).toBe("Iowa St. to win");
  });

  it("keeps a spread and a winner on the same game as two different bets", () => {
    const picks = toPicks([edge({ market_id: "W" }), edge({ market_id: "S", kind: "spread", title: "UConn by 6.5" })]);
    expect(picks.map((p) => p.kind).sort()).toEqual(["spread", "winner"]);
  });
});

describe("the board", () => {
  it("features only reviewed, plausible picks; a huge gap is shown as flagged, not featured", () => {
    const edges = [
      edge({ game_id: "a", market_id: "a", tier: "top_pick", our_prob: 0.62, market_prob: 0.5 }),
      edge({ game_id: "b", market_id: "b", tier: "top_pick", our_prob: 0.9, market_prob: 0.4 }),
      edge({ game_id: "c", market_id: "c", tier: "flagged" }),
      edge({ game_id: "d", market_id: "d", tier: "unreviewed" }),
      edge({ game_id: "e", market_id: "e", tier: "filtered", edge_pct: null, candidate: false }),
    ];
    const b = board(edges);
    expect(b.topPicks.map((p) => p.gameId)).toEqual(["a"]);
    expect(b.flagged.map((p) => p.gameId).sort()).toEqual(["b", "c"]);
    expect(b.unreviewed.map((p) => p.gameId)).toEqual(["d"]);
    expect(b.noEdge).toBe(1);
    expect(LARGE_GAP_POINTS).toBe(25);
  });

  it("says there is nothing to feature when nothing passed review, rather than inventing a list", () => {
    const b = board([edge({ tier: "flagged" })]);
    expect(b.topPicks).toEqual([]);
  });
});
```

```tsx
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import SportsEdges from "@/pages/SportsEdges";
import type { SportsEdge } from "@/lib/sportsEdges";
import { copyWords } from "@/test/copyWords";

function edge(over: Partial<SportsEdge>): SportsEdge {
  return {
    market_id: "M", title: "UConn wins", our_prob: 0.78, market_prob: 0.32, edge_pct: 0.46, market_url: "https://k", source_url: "https://p",
    sport: "cfb", kind: "winner", side: "yes", entry_price: 0.31, maker: true, home: "UConn", away: "Syracuse",
    start_utc: "2026-10-03T16:00:00+00:00", game_id: "g1", tier: "flagged", candidate: true, reject_reasons: [], review: null,
    engine: "sports_cfb", engine_version: null, gate_status: "SHADOW", ...over,
  };
}

// Both sides of two games, as the API sends them, plus one game that failed the filter.
const EDGES: SportsEdge[] = [
  edge({ market_id: "a1", title: "UConn wins", side: "yes" }),
  edge({ market_id: "a2", title: "Syracuse wins", side: "no", our_prob: 0.22, market_prob: 0.68 }),
  edge({ market_id: "b1", game_id: "g2", home: "Iowa State", away: "West Virginia", title: "Iowa St. wins", our_prob: 0.82, market_prob: 0.6, tier: "flagged" }),
  edge({ market_id: "c1", game_id: "g3", home: "Army", away: "Temple", title: "Army wins", our_prob: 0.6, market_prob: 0.5, tier: "top_pick" }),
  edge({ market_id: "d1", game_id: "g4", tier: "filtered", edge_pct: null, candidate: false }),
];

function stub(edges: SportsEdge[]) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({
    ok: true, status: 200, json: () => Promise.resolve({ edges, total: edges.length, limit: 200, offset: 0 }),
  })));
}

afterEach(() => vi.unstubAllGlobals());

describe("SportsEdges", () => {
  it("shows one row per game with the call, both probabilities and the gap", async () => {
    stub(EDGES);
    render(<SportsEdges />);
    expect(await screen.findByText("Army to win")).toBeInTheDocument();
    expect(screen.getAllByText("UConn to win")).toHaveLength(1); // the two sides of one game are one pick
    expect(screen.getAllByText("+46 pts").length).toBeGreaterThan(0);
  });

  it("features only reviewed, plausible picks and says so when there are none", async () => {
    stub(EDGES.filter((e) => e.tier !== "top_pick"));
    render(<SportsEdges />);
    expect(await screen.findByText("No pick passed review today.")).toBeInTheDocument();
    expect(screen.queryByText("Top picks (1)")).not.toBeInTheDocument();
  });

  it("counts the games that had no usable edge instead of listing them", async () => {
    stub(EDGES);
    render(<SportsEdges />);
    expect(await screen.findByText("1 more games had no usable edge.")).toBeInTheDocument();
  });

  it("stays inside its word budget: a page that needs more words should show a number instead", async () => {
    stub(EDGES);
    const { container } = render(<SportsEdges />);
    await screen.findByText("Army to win");
    expect(copyWords(container)).toBeLessThanOrEqual(45);
  });

  it("asks for another sport when a filter is pressed", async () => {
    stub(EDGES);
    render(<SportsEdges />);
    await screen.findByText("Army to win");
    fireEvent.click(screen.getByRole("button", { name: "NFL" }));
    await waitFor(() => expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(([u]) => String(u).includes("sport=nfl"))).toBe(true));
  });
});
```

- [ ] **Step 2: Run** — `npx vitest run src/lib/sportsPicks.test.ts src/pages/SportsEdges.test.tsx` — Expected: FAIL (modules missing).

- [ ] **Step 3: Implement**

`market_sentiment_tool/src/lib/sportsPicks.ts`:

```ts
import type { SportsEdge, SportsTier } from "@/lib/sportsEdges";

/**
 * The sports page's view of the edge rows: one pick per game, in plain terms.
 * Presentation only. The server decided which rows pass the candidate filter and which tier each is in;
 * this only folds duplicate rows together and states the comparison in words a fan would use.
 */

/**
 * A model/market gap bigger than this is shown, but never as a top pick or a headline.
 * Chosen before looking at outcomes: when a model says 78% and the market says 32%, someone is wrong, and
 * with no settled record yet the likelier culprit is the model. Revisit with data, not by feel.
 */
export const LARGE_GAP_POINTS = 25;

export interface SportsPick {
  key: string;
  gameId: string;
  sport: string;
  kind: string;
  matchup: string;
  startUtc: string;
  /** "UConn to win", or the market title for spreads and totals. */
  call: string;
  /** Model and market probability that THIS pick wins, 0-100. */
  model: number;
  market: number;
  /** Model minus market for this pick, in points. */
  gap: number;
  largeGap: boolean;
  tier: SportsTier;
  entryCents: number;
  marketUrl: string;
  sourceUrl: string;
}

const letters = (s: string) =>
  s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z]/g, "");

/** "Iowa St." names the same team as "Iowa State": compare by letters, either one a prefix of the other. */
function sameTeam(a: string, b: string): boolean {
  const x = letters(a);
  const y = letters(b);
  return x.length > 0 && y.length > 0 && (x.startsWith(y) || y.startsWith(x));
}

function callOf(edge: SportsEdge): string {
  if (edge.kind === "winner") {
    const named = (edge.title ?? "").replace(/\s+wins\s*$/i, "").trim();
    const other = sameTeam(named, edge.home) ? edge.away : sameTeam(named, edge.away) ? edge.home : null;
    if (edge.side === "yes") return `${named || edge.title} to win`;
    return other ? `${other} to win` : `${named} to lose`;
  }
  return `${edge.title ?? edge.market_id} (${edge.side.toUpperCase()})`;
}

/** The pick's gap in points: for a NO side the model's edge is the market's overpricing of YES. */
export function gapPoints(edge: Pick<SportsEdge, "our_prob" | "market_prob" | "side">): number {
  const diff = edge.our_prob - edge.market_prob;
  return (edge.side === "yes" ? diff : -diff) * 100;
}

function toPick(edge: SportsEdge): SportsPick {
  const yes = edge.side === "yes";
  const gap = gapPoints(edge);
  return {
    key: edge.market_id,
    gameId: edge.game_id,
    sport: edge.sport,
    kind: edge.kind,
    matchup: `${edge.away} @ ${edge.home}`,
    startUtc: edge.start_utc,
    call: callOf(edge),
    model: Math.round((yes ? edge.our_prob : 1 - edge.our_prob) * 100),
    market: Math.round((yes ? edge.market_prob : 1 - edge.market_prob) * 100),
    gap,
    largeGap: gap > LARGE_GAP_POINTS,
    tier: edge.tier,
    entryCents: Math.round(edge.entry_price * 100),
    marketUrl: edge.market_url,
    sourceUrl: edge.source_url,
  };
}

/**
 * One row per game and bet type. A winner market exists for BOTH teams, so "UConn wins YES" and
 * "Syracuse wins NO" are the same bet; keeping both is what made the board look twice as long and
 * twice as sure. The row with the larger gap is kept (ties: the first seen).
 */
export function toPicks(edges: SportsEdge[]): SportsPick[] {
  const best = new Map<string, SportsPick>();
  for (const edge of edges) {
    const pick = toPick(edge);
    const key = `${edge.game_id}|${edge.kind}`;
    const held = best.get(key);
    if (!held || pick.gap > held.gap) best.set(key, pick);
  }
  return [...best.values()].sort((a, b) => b.gap - a.gap);
}

export interface Board {
  topPicks: SportsPick[];
  flagged: SportsPick[];
  unreviewed: SportsPick[];
  /** Games whose only rows failed the server's candidate filter: counted, not listed. */
  noEdge: number;
}

export function board(edges: SportsEdge[]): Board {
  const all = toPicks(edges);
  const shown = all.filter((p) => p.tier !== "filtered");
  return {
    // A top pick must also be a plausible one: a large gap is a reason to doubt, not to feature.
    topPicks: shown.filter((p) => p.tier === "top_pick" && !p.largeGap),
    flagged: shown.filter((p) => p.tier === "flagged" || (p.tier === "top_pick" && p.largeGap)),
    unreviewed: shown.filter((p) => p.tier === "unreviewed"),
    noEdge: all.length - shown.length,
  };
}

export function gapText(gap: number): string {
  return `${gap > 0 ? "+" : ""}${Math.round(gap)}`;
}
```

`market_sentiment_tool/src/pages/SportsEdges.tsx`:

```tsx
import { useEffect, useState } from "react";

import { Chip } from "@/components/Chip";
import { Stat } from "@/components/Stat";
import { buildApiUrl } from "@/lib/api";
import type { SportsEdge, SportsEdgesResponse } from "@/lib/sportsEdges";
import { board, gapText, type SportsPick } from "@/lib/sportsPicks";

/**
 * /sports: where the NFL and college-football predictors and the Kalshi market disagree, one pick per game.
 *
 * The reviewer decides what is featured, not the size of the gap: a pick is a "top pick" only if the
 * reviewer passed it, and a huge gap (model far from market) is listed under "flagged" with the gap
 * shown, never promoted. When nothing passes, the page says so instead of filling the screen.
 */

const PAGE = 200;

async function fetchAll(sport: string): Promise<SportsEdge[]> {
  const edges: SportsEdge[] = [];
  for (let offset = 0; ; offset += PAGE) {
    const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (sport) params.set("sport", sport);
    const response = await fetch(buildApiUrl(`/api/sports-edges?${params}`));
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
    const page = payload as SportsEdgesResponse;
    edges.push(...page.edges);
    if (edges.length >= page.total || page.edges.length === 0) return edges;
  }
}

const WHEN = new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });

function PickRow({ pick }: { pick: SportsPick }) {
  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 border-t border-slate-800 py-3 lg:grid-cols-[1.4fr_1fr_auto]">
      <div>
        <div className="font-medium text-slate-100">{pick.call}</div>
        <div className="text-xs text-slate-500">
          {pick.matchup} · {WHEN.format(new Date(pick.startUtc))}
          {pick.kind !== "winner" && <span> · {pick.kind}</span>}
        </div>
      </div>
      <div className="hidden text-sm tabular-nums text-slate-300 lg:block">
        Model <b className="text-slate-100">{pick.model}%</b> <span className="text-slate-600">·</span> Market{" "}
        <b className="text-slate-100">{pick.market}%</b>
      </div>
      <div className="flex items-center gap-3 justify-self-end">
        <Chip tone={pick.largeGap ? "warn" : "good"} title={pick.largeGap ? "Model and market are unusually far apart" : "Model minus market, in points"}>
          {gapText(pick.gap)} pts
        </Chip>
        <a className="text-xs text-sky-400 hover:underline" href={pick.marketUrl} target="_blank" rel="noreferrer">Kalshi</a>
      </div>
      <div className="text-xs tabular-nums text-slate-400 lg:hidden">
        Model {pick.model}% · Market {pick.market}%
      </div>
    </li>
  );
}

function Section({ title, picks, initial = 6 }: { title: string; picks: SportsPick[]; initial?: number }) {
  const [all, setAll] = useState(false);
  if (picks.length === 0) return null;
  const shown = all ? picks : picks.slice(0, initial);
  return (
    <section>
      <h2 className="mb-1 text-lg font-semibold text-slate-200">
        {title} <span className="text-slate-500">({picks.length})</span>
      </h2>
      <ul>{shown.map((p) => <PickRow key={p.key} pick={p} />)}</ul>
      {picks.length > initial && (
        <button type="button" className="mt-2 text-sm text-sky-400 hover:underline" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${picks.length}`}
        </button>
      )}
    </section>
  );
}

export default function SportsEdges() {
  const [edges, setEdges] = useState<SportsEdge[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sport, setSport] = useState<"" | "nfl" | "cfb">("");

  useEffect(() => {
    setEdges(null);
    fetchAll(sport).then(setEdges).catch((e: Error) => setError(e.message));
  }, [sport]);

  if (error) return <div className="p-8 text-red-400">Sports picks unavailable: {error}</div>;
  if (!edges) return <div className="p-8 text-slate-400">Loading sports picks…</div>;

  const b = board(edges);
  return (
    <div className="mx-auto max-w-5xl space-y-10 p-6 md:p-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white">Sports picks</h1>
          <p className="mt-2 text-slate-400">Where our predictors and the market disagree.</p>
        </div>
        <div role="group" aria-label="Sport" className="flex gap-2">
          {([["", "All"], ["nfl", "NFL"], ["cfb", "College"]] as const).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={sport === value}
              onClick={() => setSport(value)}
              className={`rounded-full border px-3 py-1 text-sm ${
                sport === value ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300" : "border-slate-700 text-slate-400 hover:text-slate-200"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      <section aria-label="Totals" className="grid gap-3 sm:grid-cols-3">
        <Stat value={b.topPicks.length} label="top picks" />
        <Stat value={b.flagged.length} label="flagged by the reviewer" />
        <Stat value={b.unreviewed.length} label="not reviewed yet" />
      </section>

      {b.topPicks.length === 0 && (
        <p className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3 text-slate-300">No pick passed review today.</p>
      )}

      <Section title="Top picks" picks={b.topPicks} />
      <Section title="Flagged by the reviewer" picks={b.flagged} />
      <Section title="Not reviewed yet" picks={b.unreviewed} />

      {b.noEdge > 0 && <p className="text-sm text-slate-500">{b.noEdge} more games had no usable edge.</p>}
    </div>
  );
}
```

Retire the obsolete test (it read the old page's source for `rankingSentence(data.ranking)`; the new page makes no ranking claim and shows the gap on every row):

```diff
diff --git a/market_sentiment_tool/src/lib/sportsEdges.test.ts b/market_sentiment_tool/src/lib/sportsEdges.test.ts
index 600c720..6d6d982 100644
--- a/market_sentiment_tool/src/lib/sportsEdges.test.ts
+++ b/market_sentiment_tool/src/lib/sportsEdges.test.ts
@@ -1,4 +1,3 @@
-import { readFileSync } from "node:fs";
 
 import { describe, expect, it } from "vitest";
 
@@ -140,30 +139,4 @@ describe("which ranking the page claims", () => {
   // this file -- see the `payload` docstring -- and the property is now stated where it is
   // testable: the `edge_sigma` sentence must NAME the fallback ("keeps the edge_sigma sentence true
   // when only some rows are scored" above), which fails the moment it claims a total order.
-
-  it("SHAPE, not render: the page is a caller of the helper and owns no literal of its own", () => {
-    // NOT a render test. This reads the page's SOURCE with `readFileSync` and a regex, so it proves
-    // the shape of the page's use of the helper, not what a user sees. It is the only way to catch a
-    // second literal in the header -- a mutation that renders perfectly and leaves the Python suite
-    // green -- so it earns its place, but it must not be read as covering the rendered output.
-    //
-    // Two consequences a future editor should know before changing either line:
-    //
-    // 1. `not.toMatch(/Ranked (by|raw)/)` is a SHAPE assertion about a prefix, and it will fail on
-    //    unrelated future copy that happens to start a line with "Ranked by ..." -- including a
-    //    correct one. If it fires, read the page: the fix is to narrow the pattern, not to delete it
-    //    and not to reword the page to satisfy a regex.
-    // 2. The two `not.toContain` checks catch a copy-pasted literal verbatim. A REWORDED hardcode
-    //    slips past them, which is exactly why the regex above is here as well; neither check alone
-    //    covers the mutation.
-    //
-    // Read relative to the package root, which is vitest's cwd -- `import.meta.url` is a dev-server
-    // URL here, not a file: one.
-    const page = readFileSync("src/pages/SportsEdges.tsx", "utf8");
-
-    expect(page).toContain("rankingSentence(data.ranking)");
-    expect(page).not.toContain(RANKING_SENTENCE.edge_sigma);
-    expect(page).not.toContain(RANKING_SENTENCE.raw_edge);
-    expect(page).not.toMatch(/Ranked (by|raw)/);
-  });
 });
```

- [ ] **Step 4: Run** — `npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx eslint src/pages/Journal.tsx src/pages/SportsEdges.tsx src/lib/sportsPicks.ts src/lib/journalView.ts src/lib/forecasterLabels.ts src/components/Stat.tsx src/components/Chip.tsx && npx vite build` — Expected: vitest all pass (reviewer baseline 422), tsc and eslint silent, build succeeds.

- [ ] **Step 5: Commit**

```bash
git add -A market_sentiment_tool/src
git commit -m "ui: a readable /sports: one pick per game, reviewed picks only"
```

---

### Task 4: Look at it, then open the PR

**Files:**
- Modify: `market_sentiment_tool/vite.config.ts` (optional dev proxy)

- [ ] **Step 1: Apply the dev proxy**

```diff
diff --git a/market_sentiment_tool/vite.config.ts b/market_sentiment_tool/vite.config.ts
index a9b992f..9850308 100644
--- a/market_sentiment_tool/vite.config.ts
+++ b/market_sentiment_tool/vite.config.ts
@@ -11,6 +11,10 @@ export default defineConfig(({ mode }) => ({
     hmr: {
       overlay: false,
     },
+    // Local development against a deployed API without CORS: DEV_API_PROXY=https://host npm run dev
+    proxy: process.env.DEV_API_PROXY
+      ? { "/api": { target: process.env.DEV_API_PROXY, changeOrigin: true, secure: true } }
+      : undefined,
   },
   plugins: [react(), mode === "development" && componentTagger()].filter(Boolean),
   resolve: {
```

- [ ] **Step 2: Run the app against the live API and look at both pages**

```bash
cd market_sentiment_tool
VITE_SUPABASE_URL=http://127.0.0.1:1 VITE_SUPABASE_ANON_KEY=local-dummy DEV_API_PROXY=https://algo.40-160-91-131.sslip.io npx vite --port 8081 --host 127.0.0.1
```

Open `http://127.0.0.1:8081/journal` and `/sports` at desktop width (about 1280px) and phone width (375px). Confirm: three big numbers at the top; no horizontal scroll; the "Kalshi" link on a sports row is not cut off; the first screen of each page reads without scrolling; text is legible at 200% zoom. Attach a screenshot of each to the PR. Fix anything off in this PR; do not iterate more than two rounds.

- [ ] **Step 3: Verify and open the PR** (no backend change, so the Python suite is not needed)

```bash
cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx vite build
```

PR body: the two screenshots, the word budget numbers (`copyWords`) before and after (journal was about 970 visible words on the live page, sports about 1,540), and the three sports decisions above for Kevin.

---

## Self-Review

- **Owner feedback (too text-heavy, says nothing in particular):** each page now opens on numbers a visitor can act on; copy per page is capped at 45 words by a test; raw ids moved behind a click.
- **Truthfulness kept:** a missing figure is `—` or `Waiting`, never `0`; a huge model/market gap is flagged, never featured; "No pick passed review today" appears when that is true; the backtests block says "not counted".
- **Sports duplicates fixed:** both sides of a winner market are one pick; the live board's 90 rows become about 15 games.
- **Type consistency:** `ViewRow`, `SportsPick`, `Board` and the `copyWords` helper are defined once (Task 1 and Task 3) and used by the page tests.
