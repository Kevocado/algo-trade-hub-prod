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
