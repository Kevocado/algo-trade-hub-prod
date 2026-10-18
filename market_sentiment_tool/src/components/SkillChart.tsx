import { CartesianGrid, Line, LineChart, ResponsiveContainer, XAxis, YAxis } from "recharts";

import { forecasterLabel } from "@/lib/forecasterLabels";
import type { SeriesEntry } from "@/lib/journal";

const AHEAD = "#10b981";   // green: better than baseline (gap < 0)
const BEHIND = "#f87171";  // red: worse than baseline (gap > 0)
const UNKNOWN = "#94a3b8"; // slate: not measured
const WHISKER = "#64748b";

interface Row {
  label: string;
  gap: number | null;
  se: number | null;
}

/** Last point per forecaster, most recent date wins. */
function latestPoint(points: SeriesEntry["points"]): SeriesEntry["points"][number] | undefined {
  if (!points.length) return undefined;
  return [...points].sort((a, b) => a.date.localeCompare(b.date)).pop();
}

function gapText(gap: number | null): string {
  if (gap === null) return "—";
  const sign = gap > 0 ? "+" : "";
  const digits = gap !== 0 && Math.abs(gap) < 0.005 ? 4 : 2;
  return `${sign}${gap.toFixed(digits)}`;
}

function domain(gaps: number[]): [number, number] {
  if (!gaps.length) return [-1, 1];
  const lo = Math.min(0, ...gaps);
  const hi = Math.max(0, ...gaps);
  const pad = Math.max((hi - lo) * 0.35, 0.02);
  return [lo - pad, hi + pad];
}

/** Dot-and-whisker: one dot per forecaster (gap vs baseline) with ±2 SE whiskers.
 *
 *  Null gap renders as "unknown" — never a dot at 0. Null se renders dot only,
 *  no whisker. Every number comes from /api/journal/series; nothing is computed here. */
export function SkillChart({ series }: { series: SeriesEntry[] }) {
  const rows: Row[] = series.map((s) => {
    const p = latestPoint(s.points);
    return {
      label: forecasterLabel(s.forecaster, s.version),
      gap: p?.gap ?? null,
      se: p?.se ?? null,
    };
  });

  const gaps = rows.map((r) => r.gap).filter((v): v is number => v !== null);
  const [yMin, yMax] = domain(gaps);

  /** One dot per forecaster, null-separated so dots never connect across forecasters. */
  const dots = (rows: Row[]) =>
    rows.flatMap((r) => (r.gap === null ? [] : [{ label: r.label, y: r.gap }, { label: null, y: null }]));

  return (
    <section aria-label="Skill vs baseline" className="grid gap-4">
      <ResponsiveContainer width="100%" height={220}>
        <LineChart margin={{ top: 8, right: 6, bottom: 34, left: 32 }}>
          <CartesianGrid stroke="#1e293b" />
          <XAxis
            type="category"
            dataKey="label"
            tick={{ fill: "#94a3b8", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            interval={0}
          />
          <YAxis
            type="number"
            dataKey="y"
            domain={[yMin, yMax]}
            tick={{ fill: "#94a3b8", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
          />
          {/* ±2 SE whiskers: one vertical line per forecaster with an interval. */}
          {rows.map((r) => (
            r.gap !== null && r.se !== null && (
              <Line
                key={r.label}
                type="linear"
                dataKey="y"
                data={[
                  { label: r.label, y: r.gap - 2 * r.se },
                  { label: r.label, y: r.gap + 2 * r.se },
                ]}
                stroke={WHISKER}
                strokeWidth={1.5}
              />
            )
          ))}
          {/* Dots: ahead (green) / behind (red); null gap -> no dot at all. */}
          {rows.filter((r) => r.gap !== null && r.gap < 0).length > 0 && (
            <Line type="linear" dataKey="y" data={dots(rows.filter((r) => r.gap !== null && r.gap < 0))} dot={{ r: 5, fill: AHEAD }} />
          )}
          {rows.filter((r) => r.gap !== null && r.gap > 0).length > 0 && (
            <Line type="linear" dataKey="y" data={dots(rows.filter((r) => r.gap !== null && r.gap > 0))} dot={{ r: 5, fill: BEHIND }} />
          )}
        </LineChart>
      </ResponsiveContainer>

      {/* Per-forecaster readout so exact values and the unknown / no-interval labels are readable. */}
      <div className="flex flex-wrap gap-3 text-xs text-slate-400">
        {rows.map((r) => (
          <span key={r.label} className="flex items-center gap-1">
            {r.label}:{" "}
            {r.gap === null ? (
              <span className="text-slate-500">— unknown</span>
            ) : (
              <>
                <span className={r.gap < 0 ? "text-emerald-300" : "text-rose-300"}>{gapText(r.gap)}</span>{" "}
                {r.se === null && <span className="text-slate-500">(no interval)</span>}
              </>
            )}
          </span>
        ))}
      </div>
    </section>
  );
}
