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
