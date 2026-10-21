import { ResponsiveContainer, Scatter, ScatterChart, ErrorBar, XAxis, YAxis, ReferenceLine } from "recharts";

import { forecasterLabel } from "@/lib/forecasterLabels";
import type { JournalResponse } from "@/lib/journal";

const AHEAD = "#10b981";   // green: better than baseline (gap < 0)
const BEHIND = "#f87171";  // red: worse than baseline (gap > 0)
const UNKNOWN = "#94a3b8"; // slate: not measured / too early
const TOO_EARLY_N = 30;    // under 30 settled = hollow dot

interface SkillChartRow {
  label: string;
  gap: number | null;
  se: number | null;
  nSettled: number;
}

/** Horizontal forest plot: one row per market-linked forecaster.
    Gap (paired Brier vs baseline) on the x-axis, forecaster names on the y-axis.
    Dots are the point gap; whiskers are ±1.96 × SE (95% interval).
    Rows under 30 settled are hollow ("too early").
    Missing gap renders as no dot. Everything comes from the server; nothing computed here. */
export function SkillChart({ data }: { data: JournalResponse }) {
  const rows: SkillChartRow[] = data.forecasters
    .filter((f) => f.baseline === "market" && f.n_settled > 0)
    .map((f) => ({
      label: forecasterLabel(f.forecaster, f.forecaster_version),
      gap: f.gap ?? null,
      se: f.gap_se ?? null,
      nSettled: f.n_settled,
    }))
    .sort((a, b) => {
      if (a.gap === null && b.gap !== null) return 1;
      if (a.gap !== null && b.gap === null) return -1;
      if (a.gap === null && b.gap === null) return 0;
      return a.gap - b.gap;
    });

  const gaps = rows.map((r) => r.gap).filter((v): v is number => v !== null);
  const minGap = gaps.length > 0 ? Math.min(0, ...gaps) : -0.1;
  const maxGap = gaps.length > 0 ? Math.max(0, ...gaps) : 0.1;
  const pad = Math.max((maxGap - minGap) * 0.15, 0.02);

  return (
    <section aria-label="Skill vs baseline" className="grid gap-4">
      <ResponsiveContainer width="100%" height={260}>
        <ScatterChart data={rows} margin={{ top: 20, right: 60, bottom: 36, left: 120 }} layout="vertical">
          <XAxis
            type="number"
            dataKey="gap"
            domain={[minGap - pad, maxGap + pad]}
            tick={{ fill: "#94a3b8", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            type="category"
            dataKey="label"
            tick={{ fill: "#94a3b8", fontSize: 9 }}
            tickLine={false}
            axisLine={false}
          />
          {/* Labelled zero line */}
          <ReferenceLine x={0} stroke="#64748b" strokeWidth={1.5} strokeDasharray="3 3" label="0" />
          {/* Error bars: horizontal whiskers at gap ± 1.96 × SE */}
          <ErrorBar dataKey="gap" stroke="#64748b" strokeWidth={1} />
          {/* Dots: ahead (green) / behind (red); too early = hollow */}
          <Scatter
            name="Ahead of baseline"
            data={rows.filter((r) => r.gap !== null && r.gap < 0 && r.nSettled >= TOO_EARLY_N)}
            dataKey="gap"
            fill={AHEAD}
          />
          <Scatter
            name="Behind baseline"
            data={rows.filter((r) => r.gap !== null && r.gap > 0 && r.nSettled >= TOO_EARLY_N)}
            dataKey="gap"
            fill={BEHIND}
          />
          <Scatter
            name="Too early (&lt; 30 settled)"
            data={rows.filter((r) => r.gap !== null && r.nSettled < TOO_EARLY_N)}
            dataKey="gap"
            fill="none"
            stroke={UNKNOWN}
            strokeWidth={1.5}
          />
        </ScatterChart>
      </ResponsiveContainer>

      {/* Per-forecaster readout so exact values are readable. */}
      <div className="flex flex-wrap gap-3 text-xs text-slate-400">
        {rows.map((r) => (
          <span key={r.label} className="flex items-center gap-1">
            {r.label}:{" "}
            {r.gap === null ? (
              <span className="text-slate-500">— unknown</span>
            ) : (
              <>
                <span className={r.gap < 0 ? "text-emerald-300" : "text-rose-300"}>{r.gap.toFixed(3)}</span>{" "}
                {r.se === null ? (
                  <span className="text-slate-500">(no interval)</span>
                ) : (
                  <>
                    (±{(2 * r.se).toFixed(3)})
                  </>
                )}
              </>
            )}
          </span>
        ))}
      </div>
    </section>
  );
}