import { Fragment, useEffect, useState } from "react";

import { Chip, type Tone } from "@/components/Chip";
import { JournalDetail } from "@/components/JournalDetail";
import { LiveSkill, liveRows, verdict as verdictOf } from "@/components/LiveSkill";
import { SkillOverTime } from "@/components/SkillOverTime";
import { Stat } from "@/components/Stat";
import { WeatherPanel } from "@/components/WeatherPanel";
import { getJson } from "@/lib/getJson";
import { PreJournalContext } from "@/components/PreJournalContext";
import type { JournalResponse, SeriesResponse } from "@/lib/journal";
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

type Tab = "scored" | "time" | "weather" | "waiting";

/** Skill is a Brier skill score; +-0.25 fills the half-bar, past that it just clips. */
const SKILL_FULL = 0.25;
const SHOW_FIRST = 8;

function SkillBar({ skill }: { skill: number | null }) {
  if (skill === null) return null;
  const pct = Math.min(Math.abs(skill) / SKILL_FULL, 1) * 50;
  return (
    <div aria-hidden className="relative mt-1 h-1.5 w-16 sm:w-24 rounded-full bg-slate-800 ml-auto">
      <div className="absolute inset-y-0 left-1/2 w-px bg-slate-600" />
      <div
        className={`absolute inset-y-0 rounded-full ${skill >= 0 ? "bg-emerald-500" : "bg-rose-500"}`}
        style={skill >= 0 ? { left: "50%", width: `${pct}%` } : { right: "50%", width: `${pct}%` }}
      />
    </div>
  );
}

function ProgressBar({ scored, needed }: { scored: number; needed: number }) {
  return (
    <div aria-hidden className="mt-1 h-1.5 w-16 sm:w-24 rounded-full bg-slate-800 ml-auto">
      <div className="h-full rounded-full bg-sky-500" style={{ width: `${Math.min(scored / needed, 1) * 100}%` }} />
    </div>
  );
}

export default function Journal() {
  const [data, setData] = useState<JournalResponse | null>(null);
  const [series, setSeries] = useState<SeriesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [backtests, setBacktests] = useState(false);
  const [tab, setTab] = useState<Tab>("scored");
  const [all, setAll] = useState(false);

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
  const calls = liveRows(data.forecasters).map((r) => verdictOf(r.gap, r.se));
  const nCalls = (v: string) => calls.filter((c) => c === v).length;
  const verdict = calls.length === 0
    ? "No forecaster has a measured gap yet."
    : `${nCalls("ahead")} ahead · ${nCalls("behind")} behind · ${nCalls("none")} no signal`;

  const handleTabKeyDown = (e: React.KeyboardEvent, tabs: Tab[]) => {
    const idx = tabs.indexOf(tab);
    if (e.key === "ArrowRight") {
      e.preventDefault();
      setTab(tabs[(idx + 1) % tabs.length]);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      setTab(tabs[(idx - 1 + tabs.length) % tabs.length]);
    }
  };

  const tabs: [Tab, string][] = [
    ["scored", "Scored"],
    ["time", "Over time"],
    ["weather", "Weather"],
    ["waiting", `Waiting (${waiting.length})`],
  ];

  return (
    <div className="mx-auto max-w-5xl space-y-10 p-6 md:p-8">
      <header>
        <h1 className="text-3xl font-bold text-white">Prediction Journal</h1>
        <p className="mt-2 text-slate-400">Forecasts locked in before the event, scored after.</p>
        <p className="mt-3 rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-2.5 text-sm text-slate-200" data-verdict="">{verdict}</p>
      </header>

      <section aria-label="Totals" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat value={h.frozen_calibrated} label="forecasts locked in" />
        <Stat value={h.settled_calibrated} label="scored so far" />
        <Stat value={h.promoted} label="promoted" hint="Needs 200 scored (daily) or 50 (monthly)." />
      </section>

      <section aria-label="Skill against the Kalshi price">
        <h2 className="mb-1 text-lg font-semibold text-slate-200">Skill vs the Kalshi price</h2>
        <div className="mb-3 text-xs text-slate-500">Left of zero beats the market. Bars are 95% intervals.</div>
        <LiveSkill scores={data.forecasters} />
      </section>

      <div role="tablist" aria-label="Journal views" className="-mb-6 flex gap-1 overflow-x-auto border-b border-slate-800">
        {tabs.map(([id, text]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => setTab(id)}
            onKeyDown={(e) => handleTabKeyDown(e, tabs.map(([t]) => t))}
            className={`whitespace-nowrap border-b-2 px-4 py-2 text-sm ${tab === id ? "border-sky-400 text-white" : "border-transparent text-slate-400 hover:text-slate-200"}`}
          >
            {text}
          </button>
        ))}
      </div>

      {results.length > 0 ? (
        <section aria-label="Results" className={tab === "scored" ? "" : "hidden"}>
          <table className="w-full text-sm">
            <thead className="text-xs uppercase tracking-normal text-slate-500 sm:tracking-wider">
              <tr>
                <th className="py-2 text-left font-normal">Forecast</th>
                <th className="py-2 text-right font-normal">Scored</th>
                <th className="py-2 text-right font-normal" title="Positive means better than the baseline">Skill</th>
                <th className="py-2 pl-2 sm:pl-4 text-left font-normal">Status</th>
              </tr>
            </thead>
            <tbody>
              {(all ? results : results.slice(0, SHOW_FIRST)).map((row) => (
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
                      {row.scored} <span className="hidden sm:inline">of {row.needed}</span>
                      <ProgressBar scored={row.scored} needed={row.needed} />
                      <div className="sm:hidden text-xs text-slate-500 mt-1">of {row.needed} needed</div>
                    </td>
                    <td className="py-3 text-right text-base sm:text-lg tabular-nums text-slate-100">
                      {skillText(row.skill)}
                      <SkillBar skill={row.skill} />
                    </td>
                    <td className="py-3 pl-2 sm:pl-4"><Chip tone={STATUS_TONE[row.status]}>{STATUS_WORDS[row.status]}</Chip></td>
                  </tr>
                  {open === row.key && (
                    <tr><td colSpan={4} className="border-t border-slate-800/60"><JournalDetail row={row} /></td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          {results.length > SHOW_FIRST && (
            <button type="button" onClick={() => setAll(!all)} className="mt-3 text-sm text-sky-400 hover:text-sky-300">
              {all ? "Show fewer" : `Show all ${results.length}`}
            </button>
          )}
        </section>
      ) : (
        <section aria-label="Results" className={tab === "scored" ? "" : "hidden"}>
          <p className="text-slate-400 text-center py-8">No scored forecasters yet.</p>
        </section>
      )}

      <div className={tab === "time" ? "" : "hidden"}><SkillOverTime series={series?.series ?? []} /></div>

      <div className={tab === "weather" ? "" : "hidden"}><WeatherPanel /></div>

      {waiting.length > 0 ? (
        <section aria-label="Waiting" className={tab === "waiting" ? "" : "hidden"}>
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
      ) : (
        <section aria-label="Waiting" className={tab === "waiting" ? "" : "hidden"}>
          <p className="text-slate-400 text-center py-8">No forecasters waiting to be scored.</p>
        </section>
      )}

      <details onToggle={(e) => setBacktests((e.currentTarget as HTMLDetailsElement).open)}>
        <summary className="cursor-pointer text-sm text-slate-400">Past backtests (not counted)</summary>
        <div className="mt-3">{backtests && <PreJournalContext />}</div>
      </details>
    </div>
  );
}
