import { Fragment, useEffect, useState } from "react";

import { Chip, type Tone } from "@/components/Chip";
import { JournalDetail } from "@/components/JournalDetail";
import { getJson } from "@/lib/getJson";
import { PreJournalContext } from "@/components/PreJournalContext";
import { Stat } from "@/components/Stat";
import type { JournalResponse } from "@/lib/journal";
import { STATUS_WORDS, skillText, split, viewRows, type Status, type ViewRow } from "@/lib/journalView";
import { tileNote } from "@/lib/forecasterLabels";

/**
 * /journal: every forecaster's locked-in, scored record, numbers first.
 *
 * Three numbers, then the forecasters that have results, then a one-line list of those still waiting.
 * Everything else (calibration, the frozen forecasts, why a gate is closed) is one click away, because
 * the first read should be the state of the whole journal, not 19 tiles saying "not scored yet".
 * Nothing here computes a score: the server does, and this renders it.
 */

const STATUS_TONE: Record<Status, Tone> = { waiting: "quiet", early: "quiet", ahead: "good", behind: "bad", promoted: "good" };

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
  // The server's numbers, not a sum over the rows. Spec §3 step 4: "The frontend reads precomputed
  // scores through the REST contract. It never recomputes a number." Spec §10: headline stats
  // aggregate only post-calibration forecasters, which `scoring.headline()` has always enforced --
  // and which this page ignored, because `totals(rows)` summed every card. `/cpi` filters to a
  // subset, so it still uses `totals()`; there the gate is applied in the same place.
  const h = data.headline;

  return (
    <div className="mx-auto max-w-5xl space-y-10 p-6 md:p-8">
      <header>
        <h1 className="text-3xl font-bold text-white">Prediction Journal</h1>
        <p className="mt-2 text-slate-400">Forecasts locked in before the event, scored after.</p>
      </header>

      <section aria-label="Totals" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat value={h.frozen_calibrated} label="forecasts locked in" />
        <Stat value={h.settled_calibrated} label="scored so far" />
        {/* Spec §1: the hero leads with settled-ledger stats including "Brier skill vs market".
            Pooled server-side over market-linked cards only (§10); `skillText` prints an em dash
            for null, so an unmeasured skill never renders as 0.00. */}
        <Stat value={skillText(h.market_skill?.bss ?? null)} label="Brier skill vs market"
              hint="Against the Kalshi price, on market-linked calls only." />
        <Stat value={h.promoted} label="promoted" hint="Needs 200 scored (daily) or 50 (monthly)." />
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
                      {row.experimental && (
                        <span className="ml-2 align-middle text-xs text-amber-300/90">Experimental</span>
                      )}
                      <div className="text-xs text-slate-500">vs {row.against}</div>
                      {tileNote(row.forecaster) && (
                        <div className="text-xs text-slate-500" data-tile-note="">{tileNote(row.forecaster)}</div>
                      )}
                    </td>
                    <td className="py-3 text-right tabular-nums text-slate-300">
                      {row.scored} <span className="text-slate-600">of {row.needed}</span>
                    </td>
                    <td className="py-3 text-right text-lg tabular-nums text-slate-100">{skillText(row.skill)}</td>
                    <td className="py-3 pl-4"><Chip tone={STATUS_TONE[row.status]}>{STATUS_WORDS[row.status]}</Chip></td>
                  </tr>
                  {open === row.key && (
                    <tr><td colSpan={4} className="border-t border-slate-800/60"><JournalDetail row={row} /></td></tr>
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
              <li key={row.key} className="flex items-center gap-2">
                <Chip title={row.key}>{row.label}</Chip>
                {/* "from its first row" -- so the label cannot live only on the scored path. */}
                {row.experimental && (
                  <span className="text-xs text-amber-300/90">Experimental</span>
                )}
              </li>
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
