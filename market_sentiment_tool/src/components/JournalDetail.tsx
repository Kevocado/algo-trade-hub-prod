import { useEffect, useState } from "react";

import { getJson } from "@/lib/getJson";
import { biasReadout, costsText, pct, type JournalFeed } from "@/lib/journal";
import type { ViewRow } from "@/lib/journalView";

/** Calibration, the cost line and the latest locked-in forecasts for one forecaster. */
export function JournalDetail({ row }: { row: ViewRow }) {
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