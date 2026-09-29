# /journal UI (Wave 1, Plan f) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The flagship /journal page: server headline, one tile per forecaster with its Kalshi pseudo-forecaster beneath, calibration tables with a bias readout, frozen forecasts on demand, and the quarantine section.

**Architecture:** `src/lib/journal.ts` holds the wire types and all wording (pairing, skill text, bias readout); `src/pages/Journal.tsx` renders `GET /api/journal` and, per tile on demand, `GET /api/journal/feed`, reusing `GateBadge`, `QuarantineNotice` and `useQuarantine`. The route and a nav entry are pinned in `App.routes.test.tsx`.

**Tech Stack:** React + TypeScript, Vite, vitest + Testing Library, Tailwind.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§11 Journal UI, §10 display gate). **Depends on:** plan (a) merged (API shapes). Works with any subset of (b)–(e); it renders whatever scorecards exist.

> **Provenance:** every code block below was implemented and run by the reviewer on top of plan (a) in a scratch worktree before this plan was written (full backend suite 1383 passed with `time.monotonic` forced to 5.0 and to 1e7; frontend vitest 462 passed, tsc, eslint and build clean; new Python files ruff-clean). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- A forecaster is a class implementing `tradehub.journal.contract.Forecaster`; its `(name, version)` is its journal key and must be unique in `tradehub/journal/registry.py`.
- Constructing a forecaster must not touch the network; network happens only inside `targets` / `forecast` / `settle`.
- `forecast()` returns `None` when an input is missing (a recorded gap), never a guess or a default.
- **The page computes nothing.** Every number (Brier, BSS, reliability, headline counts, gate reasons) comes from the API; `journal.ts` only chooses words and pairings.
- A missing number is said in words (`not scored yet`, `no market price`), never rendered as 0 or a dash.
- No filter, no sort by skill, no hidden forecaster: every scorecard gets a tile (display gate: from its first frozen row).
- Weather/gas stay in the quarantine section, excluded from the headline (`QuarantineNotice` already renders the quarantine sink).

---
### Task 1: Journal types and wording

**Files:**
- Create: `market_sentiment_tool/src/lib/journal.ts`
- Test: `market_sentiment_tool/src/lib/journal.test.ts`

**Interfaces:**
- Produces: types `JournalScore`, `JournalResponse`, `JournalHeadline`, `JournalFeed`, `FrozenForecast`, `ReliabilityBucket`, `Baseline`; `MARKET_PAIR`, `EXPERIMENTAL`, `NOT_SCORED`; `key()`, `isMarket()`, `tiles(scores) -> Tile[]`, `baselineWord()`, `brierText()`, `skillText()`, `settledText()`, `pct()`, `biasReadout()`.

- [ ] **Step 1: Write the failing test** (`market_sentiment_tool/src/lib/journal.test.ts`)

```tsx
import { describe, expect, it } from "vitest";

import { biasReadout, pct, skillText, tiles, type JournalScore } from "@/lib/journal";

function score(over: Partial<JournalScore> = {}): JournalScore {
  return {
    forecaster: "cpi_nowcast",
    forecaster_version: "cpi-v1",
    cadence: "monthly",
    baseline: "market",
    n_targets: 12,
    n_settled: 10,
    brier: 0.071,
    brier_baseline: 0.068,
    bss: -0.044,
    reliability: [],
    murphy: {},
    calibration_ready: false,
    gate_status: "SHADOW",
    gate_reasons: ["only 10 settled targets, need 50 (monthly)"],
    computed_at: "2026-10-01T13:00:00+00:00",
    ...over,
  };
}

describe("tiles", () => {
  it("puts each market pseudo-forecaster beneath its model and never drops an orphan", () => {
    const out = tiles([
      score(),
      score({ forecaster: "kalshi_implied_cpi", forecaster_version: "v1" }),
      score({ forecaster: "kalshi_implied_fomc", forecaster_version: "v1" }),
      score({ forecaster: "unrate_direction", forecaster_version: "unrate-dir-v1", baseline: "climatology" }),
    ]);
    expect(out.map((t) => [t.model.forecaster, t.market?.forecaster ?? null])).toEqual([
      ["cpi_nowcast", "kalshi_implied_cpi"],
      ["unrate_direction", null],
      ["kalshi_implied_fomc", null],
    ]);
  });
});

describe("wording", () => {
  it("says a missing skill in words, never as zero, and labels the baseline", () => {
    expect(skillText(score({ bss: null }))).toBe("Brier skill not scored yet");
    expect(skillText(score())).toBe("Brier skill -0.044 vs the Kalshi market");
    expect(skillText(score({ bss: 0.12, baseline: "climatology" }))).toBe("Brier skill +0.120 vs climatology");
    expect(pct(null)).toBe("no market price");
  });

  it("reads bias off the best-populated bucket", () => {
    const buckets = [
      { bucket: "60-70", n: 30, predicted: 0.65, observed: 0.55 },
      { bucket: "90-100", n: 4, predicted: 0.95, observed: 1.0 },
    ];
    expect(biasReadout(buckets)).toBe("overconfident by 10.0pp in the 60-70 bucket (n=30)");
    expect(biasReadout([])).toBeNull();
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd market_sentiment_tool && npx vitest run src/lib/journal.test.ts`
Expected: FAIL — cannot resolve `@/lib/journal`.

- [ ] **Step 3: Implement**

`market_sentiment_tool/src/lib/journal.ts`:

```ts
/**
 * The prediction journal's wire types and its wording (v2 spec §11).
 *
 * Every number on /journal is computed by the server (`tradehub/journal/scoring.py`) and rendered
 * here as-is. This module decides words, pairings and formatting only; it never computes a Brier
 * score, a skill score or a gate, because a second implementation is a second place to be wrong.
 */

export type Baseline = "market" | "climatology" | "none";

export interface ReliabilityBucket {
  bucket: string;
  n: number;
  predicted: number;
  observed: number;
}

export interface JournalScore {
  forecaster: string;
  forecaster_version: string;
  cadence: "daily" | "monthly" | "meeting";
  baseline: Baseline;
  n_targets: number;
  n_settled: number;
  brier: number | null;
  brier_baseline: number | null;
  bss: number | null;
  reliability: ReliabilityBucket[];
  murphy: { reliability?: number; resolution?: number; uncertainty?: number };
  calibration_ready: boolean;
  gate_status: "SHADOW" | "PROMOTED";
  gate_reasons: string[];
  computed_at: string;
}

export interface JournalHeadline {
  forecasters: number;
  calibrated: number;
  settled_calibrated: number;
  promoted: number;
}

export interface JournalResponse {
  as_of: string;
  forecasters: JournalScore[];
  headline: JournalHeadline;
}

export interface FrozenForecast {
  target: string;
  probability: number;
  market_prob: number | null;
  frozen_at: string;
  rebuilt: boolean;
  source_hash: string;
}

export interface JournalFeed {
  forecaster: string;
  forecaster_version: string;
  generated_at: string;
  forecasts: FrozenForecast[];
  calibration: ReliabilityBucket[];
  gate_status: "SHADOW" | "PROMOTED";
  provisional: boolean;
}

/** Market pseudo-forecasters are prefixed; their tile sits beneath the model they price. */
export const MARKET_PREFIX = "kalshi_implied_";

/** Model forecaster -> the pseudo-forecaster for the same Kalshi markets (registry, plans b-c). */
export const MARKET_PAIR: Record<string, string> = {
  cpi_nowcast: "kalshi_implied_cpi",
  fomc_mapped: "kalshi_implied_fomc",
  labor_nowcast: "kalshi_implied_labor",
};

/** Forecasters the spec labels experimental (ruling Q5). */
export const EXPERIMENTAL = new Set(["fomc_mapped"]);

export const NOT_SCORED = "not scored yet";

export function key(score: Pick<JournalScore, "forecaster" | "forecaster_version">): string {
  return `${score.forecaster}@${score.forecaster_version}`;
}

export function isMarket(score: Pick<JournalScore, "forecaster">): boolean {
  return score.forecaster.startsWith(MARKET_PREFIX);
}

export interface Tile {
  model: JournalScore;
  market: JournalScore | null;
}

/**
 * One tile per model forecaster, its market pseudo-forecaster beneath it. A pseudo-forecaster
 * whose model is absent still gets a tile of its own: dropping it would hide a row of the ledger.
 */
export function tiles(scores: JournalScore[]): Tile[] {
  const markets = new Map(scores.filter(isMarket).map((s) => [s.forecaster, s]));
  const used = new Set<string>();
  const out: Tile[] = [];
  for (const model of scores.filter((s) => !isMarket(s))) {
    const pair = MARKET_PAIR[model.forecaster];
    const market = pair ? markets.get(pair) ?? null : null;
    if (market) used.add(market.forecaster);
    out.push({ model, market });
  }
  for (const market of scores.filter(isMarket)) {
    if (!used.has(market.forecaster)) out.push({ model: market, market: null });
  }
  return out;
}

export function baselineWord(baseline: Baseline): string {
  if (baseline === "market") return "vs the Kalshi market";
  if (baseline === "climatology") return "vs climatology";
  return "no baseline";
}

export function brierText(value: number | null): string {
  return value === null ? NOT_SCORED : value.toFixed(4);
}

/** Skill in words and a signed number; never a bare 0 for "not measured". */
export function skillText(score: JournalScore): string {
  if (score.bss === null) return `Brier skill ${NOT_SCORED}`;
  const sign = score.bss > 0 ? "+" : "";
  return `Brier skill ${sign}${score.bss.toFixed(3)} ${baselineWord(score.baseline)}`;
}

export function settledText(score: JournalScore): string {
  return `${score.n_settled} settled of ${score.n_targets} frozen (${score.cadence})`;
}

export function pct(value: number | null): string {
  return value === null ? "no market price" : `${(value * 100).toFixed(1)}%`;
}

/** "CPI runs hot by 4.0pp": observed minus predicted in the best-populated bucket, when it exists. */
export function biasReadout(buckets: ReliabilityBucket[]): string | null {
  if (!buckets.length) return null;
  const top = [...buckets].sort((a, b) => b.n - a.n)[0];
  const gap = (top.observed - top.predicted) * 100;
  if (Math.abs(gap) < 0.05) return `calibrated in the ${top.bucket} bucket (n=${top.n})`;
  const word = gap < 0 ? "overconfident" : "underconfident";
  return `${word} by ${Math.abs(gap).toFixed(1)}pp in the ${top.bucket} bucket (n=${top.n})`;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd market_sentiment_tool && npx vitest run src/lib/journal.test.ts`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/src/lib/journal.ts market_sentiment_tool/src/lib/journal.test.ts
git commit -m "feat(ui): journal types and wording"
```

---
### Task 2: The /journal page

**Files:**
- Create: `market_sentiment_tool/src/pages/Journal.tsx`
- Test: `market_sentiment_tool/src/pages/Journal.test.tsx`

**Interfaces:**
- Consumes: Task 1; `buildApiUrl`, `GateBadge`, `QuarantineNotice`, `useQuarantine`.
- Produces: default export `Journal` (h1 "Prediction Journal").

- [ ] **Step 1: Write the failing test** (`market_sentiment_tool/src/pages/Journal.test.tsx`)

```tsx
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import Journal from "@/pages/Journal";
import type { JournalFeed, JournalResponse, JournalScore } from "@/lib/journal";

vi.mock("@/hooks/useQuarantine", () => ({ useQuarantine: () => ({ data: null, loading: false, error: null }) }));

function score(over: Partial<JournalScore> = {}): JournalScore {
  return {
    forecaster: "cpi_nowcast",
    forecaster_version: "cpi-v1",
    cadence: "monthly",
    baseline: "market",
    n_targets: 12,
    n_settled: 10,
    brier: 0.0712,
    brier_baseline: 0.0683,
    bss: -0.0425,
    reliability: [{ bucket: "60-70", n: 10, predicted: 0.65, observed: 0.5 }],
    murphy: {},
    calibration_ready: false,
    gate_status: "SHADOW",
    gate_reasons: ["only 10 settled targets, need 50 (monthly)"],
    computed_at: "2026-10-01T13:00:00+00:00",
    ...over,
  };
}

const journal: JournalResponse = {
  as_of: "2026-10-01T13:00:00+00:00",
  forecasters: [
    score(),
    score({ forecaster: "kalshi_implied_cpi", forecaster_version: "v1", brier: 0.0683, bss: 0 }),
    score({ forecaster: "fomc_mapped", forecaster_version: "fomc-mapped-v1", cadence: "meeting", brier: null,
            bss: null, n_settled: 0, reliability: [], gate_reasons: ["no baseline to compare against"] }),
  ],
  headline: { forecasters: 3, calibrated: 0, settled_calibrated: 0, promoted: 0 },
};

const feed: JournalFeed = {
  forecaster: "cpi_nowcast",
  forecaster_version: "cpi-v1",
  generated_at: "2026-10-01T13:00:00+00:00",
  forecasts: [{ target: "kalshi:KXCPI-26SEP-T0.3", probability: 0.52, market_prob: null,
                frozen_at: "2026-10-14T12:05:00+00:00", rebuilt: false, source_hash: "h" }],
  calibration: [],
  gate_status: "SHADOW",
  provisional: true,
};

function stubFetch() {
  const fn = vi.fn((url: string) => {
    const body = url.includes("/api/journal/feed") ? feed : journal;
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("Journal", () => {
  it("renders the server headline and a losing forecaster as losing, beside its market", async () => {
    stubFetch();
    render(<Journal />);
    expect(await screen.findByLabelText("Headline")).toHaveTextContent("0 of 3 forecasters calibrated");
    const tile = screen.getByText("cpi_nowcast@cpi-v1").closest("article")!;
    expect(within(tile).getByText("Brier skill -0.043 vs the Kalshi market")).toBeInTheDocument();
    expect(within(tile).getByText("Kalshi-implied (kalshi_implied_cpi@v1)")).toBeInTheDocument();
    expect(within(tile).getByText("provisional")).toBeInTheDocument();
    expect(within(tile).getByText("only 10 settled targets, need 50 (monthly)")).toBeInTheDocument();
    expect(within(tile).getByText(/overconfident by 15.0pp/)).toBeInTheDocument();
  });

  it("says unscored in words and labels the FOMC model experimental", async () => {
    stubFetch();
    render(<Journal />);
    const tile = (await screen.findByText("fomc_mapped@fomc-mapped-v1")).closest("article")!;
    expect(within(tile).getByText("experimental")).toBeInTheDocument();
    expect(within(tile).getByLabelText("Brier fomc_mapped@fomc-mapped-v1")).toHaveTextContent("not scored yet");
    expect(within(tile).queryByText("0.0000")).toBeNull();
  });

  it("loads a forecaster's frozen forecasts on demand and never shows a missing price as a number", async () => {
    const fetchFn = stubFetch();
    render(<Journal />);
    const tile = (await screen.findByText("cpi_nowcast@cpi-v1")).closest("article")!;
    fireEvent.click(within(tile).getByText("Show frozen forecasts"));
    await waitFor(() => expect(within(tile).getByText("kalshi:KXCPI-26SEP-T0.3")).toBeInTheDocument());
    expect(within(tile).getByText("no market price")).toBeInTheDocument();
    expect(fetchFn.mock.calls.some(([u]) => String(u).includes("forecaster=cpi_nowcast&version=cpi-v1"))).toBe(true);
  });

  it("shows the API's error instead of an empty ledger", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({
      ok: false, status: 503, json: () => Promise.resolve({ detail: "journal_scores is missing: apply 20260428000014" }),
    })));
    render(<Journal />);
    expect(await screen.findByText(/apply 20260428000014/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd market_sentiment_tool && npx vitest run src/pages/Journal.test.tsx`
Expected: FAIL — cannot resolve `@/pages/Journal`.

- [ ] **Step 3: Implement**

`market_sentiment_tool/src/pages/Journal.tsx`:

```tsx
import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import { GateBadge } from "@/components/GateBadge";
import { QuarantineNotice } from "@/components/QuarantineNotice";
import { useQuarantine } from "@/hooks/useQuarantine";
import {
  EXPERIMENTAL,
  biasReadout,
  brierText,
  key,
  pct,
  settledText,
  skillText,
  tiles,
  type JournalFeed,
  type JournalResponse,
  type JournalScore,
} from "@/lib/journal";

/**
 * /journal, the flagship (v2 spec §11): every forecaster's frozen, settled, scored record.
 *
 * Three blocks: the ledger hero (server headline, calibrated forecasters only), one tile per
 * forecaster with its Kalshi pseudo-forecaster beneath it in the same units, and the quarantine
 * section. A forecaster appears from its first frozen row (display gate); nothing here filters,
 * sorts by skill, or hides a losing forecaster, and nothing here computes a score.
 */

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(buildApiUrl(path));
  const payload = await response.json();
  if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
  return payload as T;
}

function ScoreLines({ score, label }: { score: JournalScore; label?: string }) {
  return (
    <div className="space-y-1 text-sm">
      {label && <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>}
      <p className="font-mono text-2xl text-white" aria-label={`Brier ${key(score)}`}>
        {brierText(score.brier)}
      </p>
      <p className="text-slate-300">{skillText(score)}</p>
      <p className="text-slate-500">{settledText(score)}</p>
    </div>
  );
}

function Calibration({ score }: { score: JournalScore }) {
  if (!score.reliability.length) return <p className="text-xs text-slate-500">No settled targets yet.</p>;
  const bias = biasReadout(score.reliability);
  return (
    <div className="mt-3">
      <table className="w-full text-xs text-slate-300" aria-label={`Calibration ${key(score)}`}>
        <thead className="text-slate-500">
          <tr>
            <th className="text-left font-normal">Confidence</th>
            <th className="text-right font-normal">n</th>
            <th className="text-right font-normal">Predicted</th>
            <th className="text-right font-normal">Observed</th>
          </tr>
        </thead>
        <tbody>
          {score.reliability.map((b) => (
            <tr key={b.bucket}>
              <td>{b.bucket}%</td>
              <td className="text-right">{b.n}</td>
              <td className="text-right">{pct(b.predicted)}</td>
              <td className="text-right">{pct(b.observed)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {bias && <p className="mt-1 text-xs text-slate-400">{bias}</p>}
    </div>
  );
}

function Feed({ score }: { score: JournalScore }) {
  const [feed, setFeed] = useState<JournalFeed | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const q = new URLSearchParams({ forecaster: score.forecaster, version: score.forecaster_version, limit: "20" });
    getJson<JournalFeed>(`/api/journal/feed?${q}`).then(setFeed).catch((e: Error) => setError(e.message));
  }, [score.forecaster, score.forecaster_version]);
  if (error) return <p className="text-xs text-rose-300">Frozen forecasts unavailable: {error}</p>;
  if (!feed) return <p className="text-xs text-slate-500">Loading frozen forecasts…</p>;
  return (
    <table className="mt-3 w-full text-xs text-slate-300" aria-label={`Frozen forecasts ${key(score)}`}>
      <thead className="text-slate-500">
        <tr>
          <th className="text-left font-normal">Target</th>
          <th className="text-right font-normal">Model</th>
          <th className="text-right font-normal">Market</th>
          <th className="text-right font-normal">Frozen</th>
        </tr>
      </thead>
      <tbody>
        {feed.forecasts.map((f) => (
          <tr key={f.target} className={f.rebuilt ? "line-through text-slate-600" : ""}>
            <td className="font-mono">{f.target}</td>
            <td className="text-right">{pct(f.probability)}</td>
            <td className="text-right">{pct(f.market_prob)}</td>
            <td className="text-right">{f.frozen_at.slice(0, 16).replace("T", " ")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Journal() {
  const [data, setData] = useState<JournalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const { data: quarantine, error: quarantineError } = useQuarantine();

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

  const h = data.headline;
  return (
    <div className="space-y-8 p-8">
      <header>
        <h1 className="text-3xl font-bold text-white">Prediction Journal</h1>
        <p className="mt-2 max-w-3xl text-slate-400">
          Every forecast is frozen before its cutoff, settled against a public source, and scored against the
          market where one exists (climatology where not). Nothing is backfilled.
        </p>
        <p className="mt-4 text-slate-200" aria-label="Headline">
          {h.calibrated} of {h.forecasters} forecasters calibrated · {h.settled_calibrated} settled targets across
          calibrated forecasters · {h.promoted} promoted
        </p>
      </header>

      {data.forecasters.length === 0 ? (
        <p className="text-slate-400">No forecaster has frozen a forecast yet.</p>
      ) : (
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Forecasters">
          {tiles(data.forecasters).map(({ model, market }) => (
            <article key={key(model)} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <div className="mb-3 flex items-center justify-between gap-2">
                <h2 className="font-mono text-sm text-slate-100">{key(model)}</h2>
                <div className="flex items-center gap-2">
                  {EXPERIMENTAL.has(model.forecaster) && (
                    <span className="text-[10px] uppercase tracking-wider text-amber-300">experimental</span>
                  )}
                  {!model.calibration_ready && (
                    <span className="text-[10px] uppercase tracking-wider text-slate-400">provisional</span>
                  )}
                  <GateBadge edge={{ gate_status: model.gate_status }} />
                </div>
              </div>
              <ScoreLines score={model} />
              {market && (
                <div className="mt-3 border-t border-slate-800 pt-3">
                  <ScoreLines score={market} label={`Kalshi-implied (${key(market)})`} />
                </div>
              )}
              {model.gate_reasons.length > 0 && (
                <ul className="mt-3 list-disc pl-4 text-xs text-slate-500">
                  {model.gate_reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              )}
              <Calibration score={model} />
              <button
                type="button"
                className="mt-3 text-xs text-sky-300 underline"
                onClick={() => setOpen(open === key(model) ? null : key(model))}
              >
                {open === key(model) ? "Hide frozen forecasts" : "Show frozen forecasts"}
              </button>
              {open === key(model) && <Feed score={model} />}
            </article>
          ))}
        </section>
      )}

      <section aria-label="Quarantine">
        <h2 className="mb-2 text-lg font-semibold text-slate-200">Quarantine</h2>
        <p className="mb-2 text-sm text-slate-500">Scored in public, excluded from every headline number above.</p>
        <QuarantineNotice payload={quarantine} readError={quarantineError} />
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd market_sentiment_tool && npx vitest run src/pages/Journal.test.tsx`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/src/pages/Journal.tsx market_sentiment_tool/src/pages/Journal.test.tsx
git commit -m "feat(ui): /journal page"
```

---
### Task 3: Route, nav entry and the reachability pin

**Files:**
- Modify: `market_sentiment_tool/src/App.tsx` (import, nav link above Models, route)
- Modify: `market_sentiment_tool/src/App.routes.test.tsx` (stub `/api/journal`, pin the route)

**Interfaces:**
- Produces: `/journal` route; nav link labelled "Journal".

- [ ] **Step 1: Write the failing test** (`market_sentiment_tool/src/App.routes.test.tsx`)

```tsx
// Apply the App.routes.test.tsx part of the diff below FIRST (the stub and the new `it`), then run it.
// The full diff is in Step 3.
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd market_sentiment_tool && npx vitest run src/App.routes.test.tsx`
Expected: FAIL — `resolves /journal to the prediction journal` finds no heading.

- [ ] **Step 3: Implement**

`market_sentiment_tool/src/App.routes.test.tsx` (test change):

```diff
diff --git a/market_sentiment_tool/src/App.routes.test.tsx b/market_sentiment_tool/src/App.routes.test.tsx
index 6d6ce18..a343a20 100644
--- a/market_sentiment_tool/src/App.routes.test.tsx
+++ b/market_sentiment_tool/src/App.routes.test.tsx
@@ -128,6 +128,11 @@ const EMPTY_SHADOW: ShadowPerformanceResponse = {
 function stubApi() {
   const answers: Record<string, unknown> = {
     "/api/scoreboard": EMPTY_BOARD,
+    "/api/journal": {
+      as_of: "2026-10-01T00:00:00+00:00",
+      forecasters: [],
+      headline: { forecasters: 0, calibrated: 0, settled_calibrated: 0, promoted: 0 },
+    },
     "/api/shadow-performance": EMPTY_SHADOW,
     "/api/pnl_summary": { total_pnl_cents: 0, suggest_only: true },
     "/api/positions": [],
@@ -183,6 +188,14 @@ describe("the sidebar link and the route agree", () => {
     expect(screen.getByRole("link", { name: /models/i })).toHaveAttribute("href", "/models");
   });
 
+  it("resolves /journal to the prediction journal", async () => {
+    // The flagship page (v2 spec §11). Pinned like /models: a page nobody can reach answers nothing.
+    await renderAppAt("/journal");
+
+    expect(screen.getByRole("heading", { name: "Prediction Journal", level: 1 })).toBeInTheDocument();
+    expect(screen.getByRole("link", { name: /journal/i })).toHaveAttribute("href", "/journal");
+  });
+
   it("renders no models page on a path with no route", async () => {
     // The control. Without it the test above would also pass if the page rendered unconditionally
     // -- a bug the deletion it guards against and a missing guard both look like.
```

`market_sentiment_tool/src/App.tsx` (app change):

```diff
diff --git a/market_sentiment_tool/src/App.tsx b/market_sentiment_tool/src/App.tsx
index 28a3474..0303c17 100644
--- a/market_sentiment_tool/src/App.tsx
+++ b/market_sentiment_tool/src/App.tsx
@@ -8,9 +8,10 @@ import Scoreboard from "@/pages/Scoreboard";
 import SportsEdges from "@/pages/SportsEdges";
 import JobsScorecard from "@/pages/JobsScorecard";
 import CpiDisplay from "@/pages/CpiDisplay";
+import Journal from "@/pages/Journal";
 import { usePortfolio } from "@/hooks/usePortfolio";
 import { portfolioHeadline } from "@/lib/portfolioTruth";
-import { LayoutDashboard, Activity, Wallet, Brain, Cpu, LineChart, Scale, Trophy, Briefcase, BarChart3 } from "lucide-react";
+import { LayoutDashboard, Activity, Wallet, Brain, Cpu, LineChart, Scale, Trophy, Briefcase, BarChart3, BookOpen } from "lucide-react";
 
 const Sidebar = () => {
   const { portfolio } = usePortfolio();
@@ -55,6 +56,13 @@ const Sidebar = () => {
         >
           <LineChart className="w-5 h-5 text-amber-400" /> Crypto Shadow
         </NavLink>
+        <NavLink
+          to="/journal"
+          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
+        >
+          {/* The flagship (v2 spec §11): every forecaster's frozen, settled, scored record. */}
+          <BookOpen className="w-5 h-5 text-emerald-400" /> Journal
+        </NavLink>
         <NavLink
           to="/models"
           className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
@@ -146,6 +154,7 @@ function App() {
               which is the same collision wearing a hat. The page says what it is and links to the
               scoreboard instead. */}
           <Route path="/shadow" element={<ShadowBacktester />} />
+          <Route path="/journal" element={<Journal />} />
           <Route path="/models" element={<Models />} />
           {/* The engine scoreboard, canonically at /scoreboard.
               `/engines` was the other candidate and was rejected: /models already lists every
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx eslint src/pages/Journal.tsx src/lib/journal.ts src/App.tsx && npx vite build`
Expected: vitest all pass (reviewer baseline 462), tsc/eslint silent, build succeeds.

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/src/App.tsx market_sentiment_tool/src/App.routes.test.tsx
git commit -m "feat(ui): route and nav for /journal"
```

---
### Final task: verify and open the PR

- [ ] `cd market_sentiment_tool && npx vitest run && npx tsc --noEmit -p tsconfig.app.json && npx vite build` — all green.
- [ ] Use impeccable (or a browser) on the deployed page once plan (a) has data: check the tiles at phone width and that the quarantine section is visually separate.
- [ ] Open the PR from a fresh branch off `main`.

## Self-Review

- **Spec §11:** ledger hero (server headline, calibrated-only per §10), tiles in the model-vs-market pattern (model Brier large, Kalshi-implied beneath in the same units), reliability tables with a bias readout, quarantine section excluded from headline numbers. `/scoreboard`, `/models` and `/shadow` are untouched.
- **No recomputation:** the only arithmetic in `journal.ts` is formatting and the bias readout's observed−predicted of one server bucket (a wording of two server numbers, tested).
- **Type consistency:** `JournalResponse`/`JournalFeed` match plan (a)'s API exactly (`as_of`, `forecasters`, `headline`; `forecasts`, `calibration`, `gate_status`, `provisional`).
