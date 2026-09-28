import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import { GateBadge } from "@/components/GateBadge";
import { SettledBars } from "@/components/SettledBars";
import { backtestGateLabel, brierVerdict, summarise } from "@/lib/scoreboard";
import { displayOnlyReason } from "@/lib/displayOnlyEngines";
import {
  UNMEASURED_BARS,
  UNMEASURED_GATE,
  UNMEASURED_SCORE,
  brierPair,
  catalogueCounts,
  claimText,
  statusTone,
  statusWord,
  worstRatioText,
  type CatalogueEntry,
  type EngineStatus,
  type ModelsResponse,
} from "@/lib/models";

/**
 * What are the models, and what are they doing?
 *
 * The product had seven pages and none of them answered that. A War Room, a Prediction Lab, a
 * shadow backtester, a sports-edges page, a jobs scorecard, a CPI display and a shadow scoreboard
 * each hold one piece, and the owner of the product reads the site and still cannot say what it is
 * for. This page is the one that says it: one row per engine, what that engine predicts, how it has
 * actually scored against its market, and what its status is. The full backtest detail behind
 * every number stays on `/scoreboard`; this is the page that makes the detail legible rather
 * than replacing it.
 *
 * Four things this page will not do, each because the alternative reads as something it is not.
 *
 *   1. It will not leave an engine off. `/api/scoreboard` reduces `backtest_runs` to one row per
 *      engine and mode, so an engine nobody has backtested is ABSENT from it — and an absent engine
 *      reads as "this engine has nothing to show", which is a claim about the engine. Four of the
 *      seven engines are in exactly that state today. The response therefore carries a catalogue
 *      that is authoritative about which engines EXIST (`tradehub/engine_catalogue.py`), joined to
 *      the rows that measured them, and an engine with no run is rendered as `not_measured`: said
 *      in words, with no number beside it, because a dash standing in for a zero is a measurement
 *      nobody made.
 *   2. It will not drop or soften a losing engine. There is no filter, no sort, no collapse of the
 *      tail, and no summary that names a best engine — the summary block carries the server's
 *      headline and the counts that qualify it, and names no engine at all. Gas sits at 4.29x the
 *      market's Brier, which is not close, and a reader told otherwise cannot judge the engine.
 *   3. It will not collapse the two bars. The engine's own stated bar (200 daily, 50 monthly) and
 *      the reviewer's flat settled floor (100) are different bars and are drawn from the shared
 *      `settledBars()` through the same component `/scoreboard` uses. A monthly engine at 70
 *      settled has MET its own bar and is still short of the floor; reporting it as 70/100 is a
 *      verdict against a number that was never its bar.
 *   4. It will not compute a threshold, a ratio or a gate. "Is this engine ahead" is
 *      `BEHIND_THE_MARKET` in `tradehub/scoreboard.py`, applied once and carried on the row and
 *      then rolled up per engine in `tradehub/engine_catalogue.py`. This file decides layout, and
 *      the one thing it does decide — how a resolved fact is worded — lives in `@/lib/models` with
 *      its tests, because prose is what nobody re-reads when the number is what they look at.
 *
 * A separate page rather than a change to `/scoreboard`: that page's whole frame is "which run is
 * this engine's record", and a reader who lands there without the claim has nothing to judge the
 * record against. This page is upstream of it, not a replacement for it.
 */

/** The status pill. `unknown` covers both "not comparable" and "not measured", on purpose. */
const TONE_CLASS: Record<ReturnType<typeof statusTone>, string> = {
  behind: "bg-amber-500/10 text-amber-300 border-amber-500/30",
  ahead: "bg-emerald-500/10 text-emerald-300 border-emerald-500/30",
  level: "bg-sky-500/10 text-sky-300 border-sky-500/30",
  unknown: "bg-slate-700/40 text-slate-400 border-slate-600",
};

function StatusPill({ status }: { status: EngineStatus }) {
  return (
    <span
      className={`rounded-full border px-2 py-px text-[10px] font-bold uppercase tracking-wider ${
        TONE_CLASS[statusTone(status)]
      }`}
    >
      {statusWord(status)}
    </span>
  );
}

/** The versions the engine's measured rows actually carry. Nothing is invented for an empty one. */
function versionsOf(entry: CatalogueEntry): string {
  return Array.from(new Set(entry.rows.map((row) => row.engine_version).filter(Boolean))).join(" · ");
}

function Row({ entry }: { entry: CatalogueEntry }) {
  const displayOnly = displayOnlyReason({ engine: entry.engine });
  const versions = versionsOf(entry);

  return (
    <tr className="border-t border-slate-800 align-top">
      <th scope="row" className="py-3 pr-3 text-left font-normal">
        <div className="font-medium text-slate-100">{entry.label}</div>
        {/* The key, in the product's own name, so the row can be matched to every other page and
            to the tables behind them. An undeclared engine's label IS its key, and this is the
            only place the two can differ. */}
        <div className="font-mono text-xs text-slate-500">{entry.engine}</div>
        {entry.cadence && (
          <div className="text-[10px] uppercase tracking-wider text-slate-600">
            {entry.cadence} cadence
          </div>
        )}
        {versions && <div className="font-mono text-[10px] text-slate-600">{versions}</div>}
      </th>

      {/* The claim. This is the part that was missing everywhere else on the product, and it is
          data rather than a string in this file -- see `@/lib/models`. */}
      <td className="py-3 pr-3 text-slate-300">
        <p className="max-w-md text-[13px] leading-snug">{claimText(entry)}</p>
        {/* The display-only ruling, in the row rather than only in the page title: a model
            probability beside a market price reads as an opportunity everywhere else in finance. */}
        {displayOnly && <p className="mt-2 max-w-md text-[11px] leading-snug text-amber-300">{displayOnly}</p>}
      </td>

      <td className="py-3 pr-3">
        <StatusPill status={entry.status} />
        {entry.measured ? (
          <>
            {/* The multiple, at the one precision the rest of the product uses. Dashed rather than
                zeroed where nothing was compared. */}
            <div className="mt-1.5 font-mono text-lg text-slate-100">{worstRatioText(entry)}</div>
            <div className="text-[10px] uppercase tracking-wider text-slate-500">
              {entry.measured_rows === 1
                ? "the market's Brier"
                : `the market's Brier · worst of ${entry.measured_rows} runs`}
            </div>
            {/* Ours beside the market's, for every measured row, and each row's own verdict in the
                shared wording. The worst row is a summary of what is here, not a filter over it. */}
            {entry.rows.map((row) => (
              <div key={`${row.mode}-${row.engine_version}`} className="mt-2">
                <div className="text-[11px] text-slate-300">{brierVerdict(row)}</div>
                <div className="font-mono text-[11px] text-slate-400">{brierPair(row)}</div>
                <div className="text-[10px] text-slate-600">
                  {row.mode}
                  {row.date_from && row.date_to
                    ? ` · ${row.date_from.slice(0, 10)} → ${row.date_to.slice(0, 10)}`
                    : ""}
                </div>
              </div>
            ))}
          </>
        ) : (
          // No run. Said in words, with no figure beside it: there is no number to print, and a
          // dash in a figure's place is how "not measured" becomes "measured as zero".
          <p className="mt-1.5 max-w-xs text-[11px] leading-snug text-slate-400">{UNMEASURED_SCORE}</p>
        )}
      </td>

      <td className="py-3 pr-3">
        {entry.measured ? (
          entry.rows.map((row) => <SettledBars key={`${row.mode}-${row.engine_version}`} row={row} />)
        ) : (
          <p className="max-w-xs text-[11px] leading-snug text-slate-400">{UNMEASURED_BARS}</p>
        )}
      </td>

      <td className="py-3 pr-3">
        {entry.measured ? (
          entry.rows.map((row) => (
            <div key={`${row.mode}-${row.engine_version}`} className="mb-2 last:mb-0">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Backtest gate
              </div>
              <div className="text-[11px] text-slate-300">{backtestGateLabel(row.gate_status)}</div>
              <div className="mt-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Promotion
              </div>
              {/* The scope, in the cell and in visible text, naming the pair rather than "this".
                  The verdict is about this engine AND this version, and two versions of one engine
                  carry the same verdict — so a bare "Promotion" reads as the engine's. Not in the
                  badge's `title=`: that is a native tooltip on an element with no tabindex and no
                  role, so a keyboard user cannot reach it and a screen reader never announces it. */}
              <div className="text-[10px] text-slate-500">
                for {row.engine} · {row.engine_version ?? "—"}
              </div>
              <GateBadge edge={{ gate_status: row.promotion_status }} />
            </div>
          ))
        ) : (
          <p className="max-w-xs text-[11px] leading-snug text-slate-400">{UNMEASURED_GATE}</p>
        )}
      </td>
    </tr>
  );
}

const HEAD = ["Engine", "What it predicts", "Against the market", "Two bars", "Gate"];

const TONES = {
  behind: "border-amber-900/60 bg-amber-950/20 text-amber-100",
  ahead: "border-emerald-900/60 bg-emerald-950/20 text-emerald-100",
  unknown: "border-slate-800 bg-slate-900/40 text-slate-300",
} as const;

export default function Models() {
  const [data, setData] = useState<ModelsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(buildApiUrl("/api/scoreboard"))
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        }
        setData(payload as ModelsResponse);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Unknown error"));
  }, []);

  if (error) {
    return (
      <div className="p-8">
        <div className="rounded-lg border border-rose-900 bg-rose-950/30 p-4 text-sm text-rose-200">
          <p className="font-semibold">Models unavailable</p>
          <p className="mt-1 text-rose-300/80">{error}</p>
          {/* The API names the table and the migration that creates it, so the page shows what it
              was told. A second copy of that mapping here would be a second place to be wrong. */}
        </div>
      </div>
    );
  }

  if (!data) return <div className="p-8 text-slate-400">Loading models…</div>;

  // The server's own headline and its caveat, restated by `summarise` and recomputed by nothing.
  const summary = summarise(data);
  const catalogue = data.catalogue;
  const entries = catalogue?.entries ?? [];

  return (
    <div className="p-8 space-y-6">
      <header className="border-b border-slate-900 pb-4">
        <h1 className="text-2xl font-bold text-white">Models</h1>
        <p className="max-w-3xl text-sm text-slate-400">
          One row per engine: what it predicts, and how it has actually scored against the market on
          the same decisions. A lower Brier is better. This product presents a model&apos;s view and
          never places an order, so every figure here is a measurement, not a balance. Every engine
          is listed — including the ones nothing has been measured on, which is a gap in the
          evidence and not a verdict on the engine. The{" "}
          <a href="/scoreboard" className="text-emerald-400 hover:underline">
            Engine Scoreboard
          </a>{" "}
          has the full backtest detail behind each number.
        </p>
      </header>

      {/* Two counts, both from the server, and both about different sets, so each says which set
          it counts. The headline is a claim about ENGINES; `catalogueCounts` counts the seven
          engines themselves; `summarise`'s counts are about ROWS, which is an (engine, mode) pair.
          Unlabelled those last two are "7 engines" and "3 engines" a line apart and a reader
          cannot tell which is which -- the right-number-wrong-label defect this product keeps
          refusing, arrived at through layout instead of through arithmetic. */}
      <div className={`rounded-lg border p-4 text-sm ${TONES[summary.tone]}`}>
        <p className="font-semibold">{summary.headline}</p>
        {summary.caveat && <p className="mt-1 text-xs opacity-90">{summary.caveat}</p>}
        <p className="mt-2 text-[10px] font-bold uppercase tracking-wider opacity-70">
          Engines — every engine this product runs
        </p>
        <p className="text-xs opacity-90">{catalogueCounts(catalogue)}</p>
        <p className="mt-1 text-[10px] font-bold uppercase tracking-wider opacity-70">
          Backtest rows — one per engine and fill mode
        </p>
        <p className="text-xs opacity-90">{summary.counts}</p>
        {data.promotion_lookup_failed && (
          <p className="mt-2 text-xs text-amber-300">
            The promotion gate could not be read, so every gate below reads SHADOW. That is the
            fail-closed default, not a measurement.
          </p>
        )}
      </div>

      {entries.length === 0 ? (
        <p className="text-slate-400">
          The engine catalogue came back empty. The engines this product runs are declared in{" "}
          <code>tradehub/engine_catalogue.py</code> and are not read from a table, so an empty
          catalogue is a fault in the response rather than a product with no engines — and it is
          shown rather than rendered as an empty table, which would read as &quot;nothing to
          report&quot;.
        </p>
      ) : (
        <table className="w-full text-sm">
          <caption className="sr-only">
            Every engine this product runs: what it predicts, its Brier against the market&apos;s,
            both of its settled bars, and its gate.
          </caption>
          <thead>
            <tr className="border-b border-slate-800">
              {HEAD.map((label) => (
                <th
                  key={label}
                  scope="col"
                  className="py-2 pr-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500"
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          {/* Every engine, in the catalogue's order. No filter, no sort, no tail collapsed: this
              page exists to show the losing engines and the unmeasured ones in the same breath. */}
          <tbody>
            {entries.map((entry) => (
              <Row key={entry.engine} entry={entry} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
