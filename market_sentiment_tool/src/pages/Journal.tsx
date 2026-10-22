import { Fragment, useEffect, useState } from "react";

import { Chip, type Tone } from "@/components/Chip";
import { JournalDetail } from "@/components/JournalDetail";
import { SkillChart } from "@/components/SkillChart";
import { SkillOverTime } from "@/components/SkillOverTime";
import { Stat } from "@/components/Stat";
import { getJson } from "@/lib/getJson";
import { PreJournalContext } from "@/components/PreJournalContext";
import type { JournalResponse, SeriesResponse, JournalScore, SeriesEntry, SeriesPoint } from "@/lib/journal";
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
  const [series, setSeries] = useState<SeriesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [backtests, setBacktests] = useState(false);

  useEffect(() => {
    Promise.all([
      getJson<JournalResponse>("/api/journal"),
      getJson<SeriesResponse>("/api/journal/series"),
    ]).then(([journal, serie]) => {
      setData(journal);
      setSeries(serie);
    }).catch((e: Error) => setError(e.message));
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
  if (!data || !series) return <div className="p-8 text-slate-400">Loading journal…</div>;

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
        <Stat value={h.promoted} label="promoted" hint="Needs 200 scored (daily) or 50 (monthly)." />
      </section>

      <SkillChart data={data} />

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

      <SkillOverTime series={series?.series ?? []} />

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

      {/* Weather/ERCOT panel: per-contract probability vs Kalshi, coloured by outcome */}
      {data && series && data.forecasters.some((f: JournalScore) => /weather/i.test(f.forecaster)) && (
        <section aria-label="Weather/ERCOT" className="border-t border-slate-800/40 pt-6">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3">Weather & ERCOT</h2>
          <div className="space-y-4 text-sm text-slate-300">
            {series.series
              .filter((s: SeriesEntry) => /weather/i.test(s.forecaster))
              .slice(0, 3)
              .map((s: SeriesEntry) => (
                <div key={s.forecaster} className="flex items-baseline gap-2">
                  <span className="font-medium text-slate-100">{s.forecaster} v{s.version}</span>
                  <div className="flex gap-1">
                    {s.points.map((p: SeriesPoint, i: number) => (
                      <span
                        key={i}
                        className={p.gap > 0
                          ? "bg-emerald-500/20 text-emerald-300 rounded-full px-2 py-0.5 text-xs font-medium"
                          : p.gap < 0
                          ? "bg-rose-500/20 text-rose-300 rounded-full px-2 py-0.5 text-xs font-medium"
                          : "bg-slate-700/30 text-slate-300 rounded-full px-2 py-0.5 text-xs font-medium"
                        }
                      >
                        {p.gap !== null ? (+p.gap * 100).toFixed(1) + "%" : "—"}
                      </span>
                    ))}
                  </div>
                  <span className="text-xs text-slate-500">n={s.n ?? null}</span>
                </div>
              ))}
            {data.forecasters.some((f: JournalScore) => /weather/i.test(f.forecaster)) ? null : (
              <p className="text-slate-500/60">No weather forecasters active</p>
            )}
          </div>
        </section>
      )}

      <details onToggle={(e) => setBacktests((e.currentTarget as HTMLDetailsElement).open)}>
        <summary className="cursor-pointer text-sm text-slate-400">Past backtests (not counted)</summary>
        <div className="mt-3">{backtests && <PreJournalContext />}</div>
      </details>
    </div>
  );
}
