import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import { brierPair } from "@/lib/models";
import { forecasterLabel } from "@/lib/forecasterLabels";
import type { ScoreboardResponse } from "@/lib/scoreboard";

export interface ReplayRow {
  forecaster: string;
  forecaster_version: string;
  date_from: string;
  date_to: string;
  n: number;
  bss: number | null;
  by_year?: Record<string, { n: number; bss: number | null }>;
}

/**
 * A signed skill that never prints a bare zero.
 *
 * Every live figure is smaller than three places (gold pools to +0.000482, EUR/USD to +0.000557), so
 * `toFixed(3)` printed "+0.000" -- a signed zero, which reads as "no skill measured" when the number is
 * positive and was measured from 753 sessions. `skillText` on /journal already refuses to print a bare
 * 0 for null; this is the same rule for a value too small for its own display precision. Digits are
 * added until the number survives.
 */
function signedSkill(value: number): string {
  const sign = value > 0 ? "+" : "";
  for (const places of [3, 4, 5, 6]) {
    const text = value.toFixed(places);
    if (Number(text) !== 0) return `${sign}${text}`;
  }
  return `${sign}${value.toPrecision(3)}`;
}

/** "2023 +0.004 · 2024 +0.004 · 2025 +0.011 · 2026 -0.019" -- the split the replay was built for. */
function yearSplit(row: ReplayRow): string | null {
  const years = Object.entries(row.by_year ?? {}).sort(([a], [b]) => a.localeCompare(b));
  if (!years.length) return null;
  return years
    .map(([year, v]) => `${year} ${v.bss === null ? "—" : signedSkill(v.bss)}`)
    .join(" · ");
}

/**
 * Backtests run before the journal existed (v2 spec §2): context only, never counted. The caller labels
 * it ("Past backtests (not counted)") and mounts it only when opened, so it adds no words or requests
 * until a visitor asks for it. Computes nothing.
 */
export function PreJournalContext() {
  const [data, setData] = useState<ScoreboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [replays, setReplays] = useState<ReplayRow[]>([]);

  useEffect(() => {
    // Optional context: a failure here must not hide the backtest table below.
    fetch(buildApiUrl("/api/journal/backtests"))
      .then((response) => response.json())
      .then((payload) => setReplays(Array.isArray(payload?.backtests) ? payload.backtests : []))
      .catch(() => setReplays([]));
  }, []);

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
      {replays.length > 0 && (
        <table className="mb-6 w-full text-xs text-slate-300" aria-label="Daily models replayed over history">
          <thead className="text-slate-500">
            <tr>
              <th className="text-left font-normal">Replayed over history</th>
              <th className="text-left font-normal">Window</th>
              <th className="text-right font-normal">Sessions</th>
              <th className="text-right font-normal" title="Positive means better than the usual up-rate, pooled across every year below">Skill</th>
            </tr>
          </thead>
          <tbody>
            {replays.map((r) => (
              <tr key={`${r.forecaster}@${r.forecaster_version}`}>
                <td>{forecasterLabel(r.forecaster, r.forecaster_version)}</td>
                <td>{r.date_from} → {r.date_to}</td>
                <td className="text-right">{r.n}</td>
                <td className="text-right font-mono">{r.bss === null ? "—" : signedSkill(r.bss)}</td>
              </tr>
            ))}
            {replays.map((r) => {
              const split = yearSplit(r);
              if (!split) return null;
              return (
                <tr key={`${r.forecaster}@${r.forecaster_version}-years`} className="text-slate-500">
                  <td colSpan={2} className="pl-4">By year</td>
                  <td className="text-right pl-4 font-mono">{split}</td>
                  <td />
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
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
