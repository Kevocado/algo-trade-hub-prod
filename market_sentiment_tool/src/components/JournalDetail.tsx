import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";

import { getJson } from "@/lib/getJson";
import { biasReadout, costsText, pct, type JournalFeed } from "@/lib/journal";
import type { ViewRow } from "@/lib/journalView";

/**
 * Spec §11 asks for "calibration diagrams per forecaster, 50%-baseline markers, bias readouts".
 * The bias readout existed; the diagram and the marker did not.
 *
 * `recharts` is already a dependency (`JobsScorecard`, `ShadowBacktester`), so this uses
 * `ReferenceLine` rather than hand-rolled SVG. The diagonal is perfect calibration: a forecaster
 * whose observed rate equals what it said is perfectly calibrated, so points ON the diagonal are
 * correct and points below it are over-confident. Without that reference a flat-looking line reads
 * as "fine" when it may be badly over-confident.
 *
 * The horizontal 50% line is a different thing and both are needed: it is the no-information
 * baseline for a direction call, so it says where a coin flip sits.
 */
function CalibrationCurve({ points, label }: { points: { predicted: number; observed: number; n: number }[]; label: string }) {
  return (
    <div aria-label={`Calibration curve ${label}`} className="mb-3">
      {/* A legend, because two dashed reference lines are unreadable without one. Named in text so it
          is assertable and so it survives a chart that fails to size itself. */}
      <p className="mb-1 text-xs text-slate-500">
        <span className="text-slate-300">50%</span> is a coin flip; the grey diagonal is perfect
        calibration, so points below it are over-confident.
      </p>
      <div className="h-40 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis type="number" dataKey="predicted" domain={[0, 1]} tick={{ fill: "#94a3b8", fontSize: 10 }} tickLine={false} axisLine={false} />
          <YAxis domain={[0, 1]} tick={{ fill: "#94a3b8", fontSize: 10 }} tickLine={false} axisLine={false} />
          <ReferenceLine y={0.5} stroke="#f59e0b" strokeDasharray="4 2" label={{ value: "50%", position: "insideTopRight", fill: "#f59e0b", fontSize: 10 }} />
          <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#475569" strokeDasharray="2 3" />
          <Line type="monotone" dataKey="observed" stroke="#10b981" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      </div>
    </div>
  );
}

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
          <>
            <CalibrationCurve points={score.reliability} label={row.key} />
          <table className="w-full text-xs text-slate-300" aria-label={`Calibration ${row.key}`}>
            <thead className="text-slate-500">
              <tr><th className="text-left font-normal">Said</th><th className="text-right font-normal">Forecasts</th><th className="text-right font-normal">Happened</th></tr>
            </thead>
            <tbody>
              {score.reliability.map((b) => (
                <tr key={b.bucket}><td>{pct(b.predicted)}</td><td className="text-right">{b.n}</td><td className="text-right">{pct(b.observed)}</td></tr>
              ))}
              {/* The same 50% reference as the diagram, so it survives without the chart -- the table
                  is what a screen reader gets, and a bare table cannot say which side of a coin flip
                  a forecaster sits on. */}
              <tr className="border-t border-amber-500/40 text-amber-300/90">
                <td>50%</td>
                <td className="text-right text-slate-500">no information</td>
                <td className="text-right text-slate-500">a coin flip</td>
              </tr>
            </tbody>
          </table>
          </>
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