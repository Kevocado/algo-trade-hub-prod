# Readable Models, Scoreboard and Jobs Pages (Plan p) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply plan (o)'s design rules to the pages that remain wordy: rebuild /models around a verdict and an error multiple per engine, and cut the scoreboard and jobs headers to a sentence.

**Architecture:** `/models` (about 1,270 visible words, 21 long paragraphs, a five-column table with jargon) becomes three counts and one row per engine: name, a one-or-two-word verdict chip, the engine's error as a multiple of the market's (`4.0x`), and how many decisions it was tested on. Detail (what it predicts, backtest rows, both settled bars, the gate, the display-only and retired notes) opens on a click and reuses the existing `SettledBars` and `GateBadge`. `/scoreboard` and `/jobs` keep their tables and lose their header essays.

**Tech Stack:** React + TypeScript, vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§11 Journal UI, §9 retired verdict; owner feedback 2026-10-01). **Depends on:** plan (o) merged (shared `Stat`, `Chip`, `copyWords`).

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (frontend vitest 407 passed, tsc clean, eslint clean on the rewritten files, build succeeds; /models inspected in a browser against the live API). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- Follow plan (o)'s design rules exactly (numbers first, one short sentence, verdicts as chips, detail on click, a missing figure is a word, word budget by test).
- **Obligations that must survive the rewrite** (each has a test): every engine is listed, including unmeasured and retired ones, with no filter, sort or collapsed tail; a losing engine is stated as losing and shows its multiple; an engine nobody measured shows `—` and `Not tested`, never `0.0x`; the two settled bars stay two bars with their own labels (`Own gate`, `Reviewer's settled floor`).
- The old `Models.test.tsx` (521 lines, pinned to the old layout) is replaced by the compact test below, which keeps those obligations.
- `/scoreboard` and `/jobs`: change only the header paragraph. Money on the scoreboard stays labelled "a simulated backtest, not a balance".
- The CPI page (`/cpi`, about 910 words) is **not** touched here: it is rebuilt from the journal in the later CPI plan, and rewriting it twice is waste.
- Leave the now-unused exports in `lib/models.ts` (`UNMEASURED_BARS`, `UNMEASURED_GATE`, `statusWord`, `statusTone`, `worstRatioText`) for the next cleanup; `catalogueCounts` is still imported by `lib/engineHealth.ts`.

---
### Task 1: The new /models

**Files:**
- Modify: `market_sentiment_tool/src/pages/Models.tsx` (full rewrite), `market_sentiment_tool/src/pages/Models.test.tsx` (full rewrite)

**Interfaces:**
- Consumes: plan (o) `Stat`, `Chip`, `copyWords`; existing `claimText`, `brierPair`, `displayOnlyNote`, `retirementText`, `SettledBars`, `GateBadge`, `backtestGateLabel`, `brierVerdict`; `GET /api/scoreboard` (unchanged).
- Produces: `/models` with a `Totals` section (beating / behind / not tested), a table of every engine, and a click-to-open detail row.

- [ ] **Step 1: Write the failing test** (`market_sentiment_tool/src/pages/Models.test.tsx`, replaces the old file)

```tsx
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import Models from "@/pages/Models";
import type { CatalogueEntry, ModelsResponse } from "@/lib/models";
import type { ScoreboardRow } from "@/lib/scoreboard";
import { copyWords } from "@/test/copyWords";

/**
 * The obligations that outlive the redesign: every engine appears (measured, unmeasured and retired),
 * a losing engine is stated as losing WITH its multiple, an unmeasured engine is a word and never a 0,
 * and no affordance can remove a row. Plus the copy budget.
 */

const row: ScoreboardRow = {
  engine: "gas", engine_version: "gas-v1", mode: "taker", date_from: "2026-06-01T00:00:00+00:00", date_to: "2026-09-20T00:00:00+00:00",
  created_at: "2026-09-20T00:00:00+00:00", n_decisions: 1982, n_fills: 400, n_settled: 3328, brier_ours: 0.119, brier_market: 0.0296,
  brier_ratio: 4.02, market_verdict: "behind", pnl_after_fees: -10, max_drawdown: 5, gate_status: "shadow", promotion_status: "SHADOW",
  gate_reasons: [], settled_distance: null,
};

const entry = (over: Partial<CatalogueEntry>): CatalogueEntry => ({
  engine: "x", label: "X engine", claim: "Predicts X.", claim_note: "", in_catalogue: true, cadence: "daily", measured: false,
  measured_rows: 0, status: "not_measured", worst_brier_ratio: null, rows: [], ...over,
});

const BODY: ModelsResponse = {
  as_of: "2026-10-01T00:00:00+00:00", runs_read: 1, rows: [row], engines: 1, promotion_lookup_failed: false, rows_total: 1,
  rows_behind_market: 1, rows_ahead_of_market: 0, rows_level_with_market: 0, rows_not_comparable: 0, any_beats_market: false,
  headline: "h", headline_kind: "all_behind", caveat: null,
  catalogue: {
    engines_total: 3, engines_measured: 1, engines_not_measured: 2, engines_unlisted: 0, engines_retired: 1,
    entries: [
      entry({ engine: "gas", label: "Gasoline", measured: true, measured_rows: 1, status: "behind", worst_brier_ratio: 4.02, rows: [row] }),
      entry({ engine: "labor_nowcast", label: "Non-farm payrolls", cadence: "monthly" }),
      entry({ engine: "old", label: "Old engine", status: "retired", claim: null, claim_note: "Retired: deleted",
             retired: { removed: "2026-10-15", reason: "deleted", replaced_by: "gas" } }),
    ],
  },
} as unknown as ModelsResponse;

function stub(body: unknown = BODY, ok = true) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok, status: ok ? 200 : 503, json: () => Promise.resolve(body) })));
}

afterEach(() => vi.unstubAllGlobals());

describe("Models", () => {
  it("lists every engine, measured or not, retired included, and says losing in words with the multiple", async () => {
    stub();
    render(<Models />);
    const gas = (await screen.findByText("Gasoline")).closest("tr")!;
    expect(within(gas).getByText("Behind")).toBeInTheDocument();
    expect(within(gas).getByText("4.0x")).toBeInTheDocument();
    expect(within(gas).getByText("1,982")).toBeInTheDocument();
    const payroll = screen.getByText("Non-farm payrolls").closest("tr")!;
    expect(within(payroll).getByText("Not tested")).toBeInTheDocument();
    expect(within(payroll).queryByText(/0\.0x|^0$/)).toBeNull(); // an untested engine is a dash, never a zero
    expect(screen.getByText("Old engine").closest("tr")).toHaveTextContent("Retired");
  });

  it("headlines three counts without a paragraph", async () => {
    stub();
    render(<Models />);
    const totals = await screen.findByLabelText("Totals");
    expect(within(totals).getByText("beating the market").previousSibling).toHaveTextContent("0");
    expect(within(totals).getByText("behind the market").previousSibling).toHaveTextContent("1");
    expect(within(totals).getByText("not tested yet").previousSibling).toHaveTextContent("2");
  });

  it("opens the claim, the backtest and both settled bars only on request", async () => {
    stub();
    render(<Models />);
    expect(screen.queryByText("Own gate")).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Gasoline" }));
    expect(screen.getByText("Predicts X.")).toBeInTheDocument();
    expect(screen.getByText("Own gate")).toBeInTheDocument();
    expect(screen.getByText("Reviewer's settled floor")).toBeInTheDocument(); // two bars, never merged
  });

  it("stays inside its word budget", async () => {
    stub();
    const { container } = render(<Models />);
    await screen.findByText("Gasoline");
    expect(copyWords(container)).toBeLessThanOrEqual(45);
  });

  it("shows the API's error, and a missing catalogue as a fault rather than an empty table", async () => {
    stub({ detail: "backtest_runs is missing" }, false);
    const { unmount } = render(<Models />);
    expect(await screen.findByText(/backtest_runs is missing/)).toBeInTheDocument();
    unmount();
    stub({ ...BODY, catalogue: { ...BODY.catalogue, entries: [] } });
    render(<Models />);
    expect(await screen.findByText("The model list did not arrive.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it** — `cd market_sentiment_tool && npx vitest run src/pages/Models.test.tsx` — Expected: FAIL (the old page has no `Totals` section).

- [ ] **Step 3: Implement**

`market_sentiment_tool/src/pages/Models.tsx`:

```tsx
import { Fragment, useEffect, useState } from "react";

import { Chip, type Tone } from "@/components/Chip";
import { GateBadge } from "@/components/GateBadge";
import { SettledBars } from "@/components/SettledBars";
import { Stat } from "@/components/Stat";
import { buildApiUrl } from "@/lib/api";
import {
  brierPair,
  claimText,
  displayOnlyNote,
  retirementText,
  type CatalogueEntry,
  type EngineStatus,
  type ModelsResponse,
} from "@/lib/models";
import { backtestGateLabel, brierVerdict } from "@/lib/scoreboard";

/**
 * /models: does each model beat the market?
 *
 * One row per engine, a verdict in one or two words, and how many times the market's error the model
 * makes. Every engine is listed, including the ones nothing has been measured on and the retired ones,
 * because an engine that quietly vanishes from the list reads as "nothing to show". Detail (what it
 * predicts, the backtest rows, both settled bars, the gate) opens on a click. The server decided every
 * verdict and number; this page words them.
 */

const WORDS: Record<EngineStatus, string> = {
  ahead: "Beating it",
  behind: "Behind",
  level: "Level",
  not_comparable: "Unclear",
  not_measured: "Not tested",
  retired: "Retired",
};

const TONES: Record<EngineStatus, Tone> = {
  ahead: "good", behind: "bad", level: "quiet", not_comparable: "quiet", not_measured: "quiet", retired: "quiet",
};

/** The engine's worst error multiple, or an em dash: never 0.0x for an engine nobody measured. */
function ratio(entry: CatalogueEntry): string {
  return entry.worst_brier_ratio === null ? "—" : `${entry.worst_brier_ratio.toFixed(1)}x`;
}

function decisions(entry: CatalogueEntry): string {
  const n = Math.max(0, ...entry.rows.map((r) => r.n_decisions ?? 0));
  return n > 0 ? n.toLocaleString() : "—";
}

function Detail({ entry }: { entry: CatalogueEntry }) {
  const displayOnly = displayOnlyNote(entry);
  const retired = retirementText(entry);
  return (
    <div className="grid gap-6 py-4 md:grid-cols-2">
      <div className="space-y-2 text-sm text-slate-300">
        <div className="font-mono text-xs text-slate-500">{entry.engine}</div>
        <div>{claimText(entry)}</div>
        {displayOnly && <div className="text-amber-300">{displayOnly}</div>}
        {retired && <div className="text-slate-400">{retired}</div>}
      </div>
      <div className="space-y-4">
        {entry.rows.length === 0 && <div className="text-sm text-slate-500">No backtest run yet.</div>}
        {entry.rows.map((row) => (
          <div key={`${row.mode}-${row.engine_version}`} className="text-sm">
            <div className="text-slate-200">{brierVerdict(row)}</div>
            <div className="font-mono text-xs text-slate-400">{brierPair(row)}</div>
            <div className="text-xs text-slate-500">
              {row.engine_version ?? "—"} · {row.mode}
              {row.date_from && row.date_to ? ` · ${row.date_from.slice(0, 10)} → ${row.date_to.slice(0, 10)}` : ""}
            </div>
            <SettledBars row={row} />
            <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
              {backtestGateLabel(row.gate_status)} <GateBadge edge={{ gate_status: row.promotion_status }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Models() {
  const [data, setData] = useState<ModelsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    fetch(buildApiUrl("/api/scoreboard"))
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        setData(payload as ModelsResponse);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Unknown error"));
  }, []);

  if (error) {
    return (
      <div className="p-8">
        <div className="rounded-lg border border-rose-900 bg-rose-950/30 p-4 text-sm text-rose-200">
          <p className="font-semibold">Models unavailable</p>
          <p className="mt-1 text-rose-300/80">{error}</p>
        </div>
      </div>
    );
  }
  if (!data) return <div className="p-8 text-slate-400">Loading models…</div>;

  const entries = data.catalogue?.entries ?? [];
  const count = (status: EngineStatus) => entries.filter((e) => e.status === status).length;

  return (
    <div className="mx-auto max-w-5xl space-y-10 p-6 md:p-8">
      <header>
        <h1 className="text-3xl font-bold text-white">Models</h1>
        <p className="mt-2 text-slate-400">Each model&apos;s error next to the market&apos;s. Lower is better.</p>
      </header>

      <section aria-label="Totals" className="grid gap-3 sm:grid-cols-3">
        <Stat value={count("ahead")} label="beating the market" />
        <Stat value={count("behind")} label="behind the market" />
        <Stat value={data.catalogue?.engines_not_measured ?? "—"} label="not tested yet" />
      </section>

      {data.promotion_lookup_failed && <p className="text-sm text-amber-300">Gates could not be read; all show SHADOW.</p>}

      {entries.length === 0 ? (
        <p className="text-slate-400">The model list did not arrive.</p>
      ) : (
        <table className="w-full text-sm">
          <caption className="sr-only">Every model: its verdict, its error compared with the market, and how many decisions it was tested on.</caption>
          <thead className="text-xs uppercase tracking-wider text-slate-500">
            <tr>
              <th scope="col" className="py-2 text-left font-normal">Model</th>
              <th scope="col" className="py-2 text-left font-normal">Verdict</th>
              <th scope="col" className="py-2 text-right font-normal" title="Our error divided by the market's. Above 1x is worse.">Error vs market</th>
              <th scope="col" className="py-2 text-right font-normal">Tested on</th>
            </tr>
          </thead>
          {/* Every engine, in the catalogue's order: no filter, no sort, no collapsed tail. */}
          <tbody>
            {entries.map((entry) => (
              <Fragment key={entry.engine}>
                <tr className="border-t border-slate-800">
                  <th scope="row" className="py-3 text-left font-normal">
                    <button
                      type="button"
                      aria-expanded={open === entry.engine}
                      onClick={() => setOpen(open === entry.engine ? null : entry.engine)}
                      className="text-left text-slate-100 hover:text-white"
                    >
                      {entry.label}
                    </button>
                    {entry.cadence && <div className="text-xs text-slate-500">{entry.cadence}</div>}
                  </th>
                  <td className="py-3"><Chip tone={TONES[entry.status]}>{WORDS[entry.status]}</Chip></td>
                  <td className="py-3 text-right text-xl tabular-nums text-slate-100">{ratio(entry)}</td>
                  <td className="py-3 text-right tabular-nums text-slate-300">{decisions(entry)}</td>
                </tr>
                {open === entry.engine && (
                  <tr><td colSpan={4} className="border-t border-slate-800/60"><Detail entry={entry} /></td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}

      <p className="text-sm"><a href="/scoreboard" className="text-emerald-400 hover:underline">Full backtest detail</a></p>
    </div>
  );
}
```

- [ ] **Step 4: Run** — `npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx eslint src/pages/Models.tsx src/pages/Models.test.tsx` — Expected: all pass (reviewer baseline 407), tsc and eslint silent.

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/src/pages/Models.tsx market_sentiment_tool/src/pages/Models.test.tsx
git commit -m "ui: a readable /models: a verdict and an error multiple per engine"
```

---

### Task 2: One sentence on /scoreboard and /jobs

**Files:**
- Modify: `market_sentiment_tool/src/pages/Scoreboard.tsx`, `market_sentiment_tool/src/pages/JobsScorecard.tsx`

- [ ] **Step 1: Apply** (header paragraph only; both pages' tests already pass unchanged):

```diff
diff --git a/market_sentiment_tool/src/pages/JobsScorecard.tsx b/market_sentiment_tool/src/pages/JobsScorecard.tsx
index 53e80fe..daad3c3 100644
--- a/market_sentiment_tool/src/pages/JobsScorecard.tsx
+++ b/market_sentiment_tool/src/pages/JobsScorecard.tsx
@@ -32,9 +32,7 @@ export default function JobsScorecard() {
           <div className="space-y-2">
             <h1 className="text-4xl font-black uppercase italic tracking-tight text-white">Jobs Scorecard</h1>
             <p className="max-w-3xl text-sm text-slate-400">
-              Kalshi settles on the BLS first print, not the revised number. Each row compares our nowcast and the
-              Kalshi-implied estimate (one hour before the release) with the first print, then shows how the number
-              was revised afterwards.
+              Our nowcast and Kalshi&apos;s estimate, against the first number the BLS prints.
             </p>
           </div>
           <div className="flex flex-col items-end gap-3">
diff --git a/market_sentiment_tool/src/pages/Scoreboard.tsx b/market_sentiment_tool/src/pages/Scoreboard.tsx
index 93def61..ed76558 100644
--- a/market_sentiment_tool/src/pages/Scoreboard.tsx
+++ b/market_sentiment_tool/src/pages/Scoreboard.tsx
@@ -198,11 +198,9 @@ export default function Scoreboard() {
     <div className="p-8 space-y-6">
       <header className="border-b border-slate-900 pb-4">
         <h1 className="text-2xl font-bold text-white">Engine scoreboard</h1>
-        <p className="max-w-3xl text-sm text-slate-400">
-          Each engine&apos;s Brier against the market&apos;s on the same decisions — a lower Brier is
-          better. The money column is a simulated backtest figure, not a balance: this product
-          suggests, it never places an order. Two bars, because they are two different bars: the
-          engine&apos;s own gate, and the reviewer&apos;s settled floor.
+        <p className="mt-2 text-sm text-slate-400">
+          Each engine&apos;s error next to the market&apos;s, on the same decisions. Lower is better. Money is a
+          simulated backtest, not a balance.
         </p>
       </header>
 
```

- [ ] **Step 2: Run** — `npx vitest run src/pages/Scoreboard.test.tsx && npx tsc --noEmit -p tsconfig.app.json` — Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add market_sentiment_tool/src/pages/Scoreboard.tsx market_sentiment_tool/src/pages/JobsScorecard.tsx
git commit -m "ui: one-sentence headers on /scoreboard and /jobs"
```

---

### Task 3: Look at it, then open the PR

- [ ] **Step 1: Run the app against the live API** (see plan (o) Task 4 for the command and the dummy-env note) and open `/models`, `/scoreboard`, `/jobs` at desktop (about 1280px) and phone (375px) width. Confirm: three counts then the table; no horizontal scroll; the verdict chip and the multiple readable without opening a row; the header is one sentence. Attach screenshots; fix anything off in this PR (two rounds at most).
- [ ] **Step 2:** `cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx vite build` — all green.
- [ ] **Step 3: Open the PR.** Body: screenshots, `copyWords` before and after (models about 1,270 words before), and the note that CPI is deferred to its own plan.

---

## Self-Review

- **Owner feedback:** `/models` goes from an essay-and-jargon table to three numbers and a verdict per engine; the honest finding (no engine beats the market) is visible in the first second.
- **Truthfulness kept:** unmeasured and retired engines stay listed; a loss is shown as a multiple; a missing figure is a dash and a word.
- **Type consistency:** `CatalogueEntry`, `ModelsResponse` and the helper names come unchanged from `@/lib/models` and `@/lib/scoreboard`.
