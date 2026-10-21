import { CartesianGrid, ErrorBar, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, XAxis, YAxis } from "recharts";
import { forecasterLabel } from "@/lib/forecasterLabels";
import type { JournalResponse } from "@/lib/journal";

const AHEAD = "#10b981";   // green: better than baseline (gap < 0)
const BEHIND = "#f87171";  // red: worse than baseline (gap > 0)
const UNKNOWN = "#94a3b8"; // slate: not measured / too early
const TOO_EARLY_N = 30;

/** Horizontal forest plot: one row per market-linked forecaster,
    gap (paired Brier vs Kalshi price) on the x-axis with a labelled zero line,
    95% interval whiskers, sorted by gap, no connecting lines.
    Rows under 30 settled are shown hollow ("too early").
    Gap and SE are computed server-side (per-contract squared-error differences)
    and arrive in `JournalScore.gap` / `gap_se`. Nothing is computed here. */
export function SkillChart({ data }: { data: JournalResponse }) {
  const marketLinked = data.forecasters.filter(
    (f) => f.baseline === "market" && (f.n_settled ?? 0) > 0,
  );

  const rows = marketLinked.map((f) => ({
    label: forecasterLabel(f.forecaster, f.forecaster_version),
    gap: f.gap ?? null,
    se: f.gap_se ?? null,
    nSettled: f.n_settled ?? 0,
    tooEarly: (f.n_settled ?? 0) < TOO_EARLY_N,
  }));

  // Sort by gap ascending (most negative = best first), nulls last.
  const sorted = [...rows].sort((a, b) => {
    if (a.gap === null && b.gap !== null) return 1;
    if (a.gap !== null && b.gap === null) return -1;
    if (a.gap === null && b.gap === null) return 0;
    return a.gap - b.gap;
  });

  const gaps = sorted.map((r) => r.gap).filter((v): v is number => v !== null);
  const minGap = gaps.length > 0 ? Math.min(0, ...gaps) : -0.1;
  const maxGap = gaps.length > 0 ? Math.max(0, ...gaps) : 0.1;
  const pad = Math.max((maxGap - minGap) * 0.15, 0.02);

  return (
    <section aria-label="Skill vs Kalshi price" className="grid gap-4">
      <ResponsiveContainer width="100%" height={260}>
        <ScatterChart
          data={sorted}
          margin={{ top: 24, right: 40, bottom: 36, left: 130 }}
          layout="horizontal"
        >
          <CartesianGrid stroke="#1e293b" />
          {/* Zero line: darker vertical line at x=0 with a "0" label. */}
          <ReferenceLine
            x={0}
            stroke="#64748b"
            strokeWidth={1.5}
            label={{ position: "top", content: "0", fill: "#94a3b8", fontSize: 9, offset: 4 }}
          />
          <XAxis
            type="number"
            dataKey="gap"
            domain={[minGap - pad, maxGap + pad]}
            tick={{ fill: "#94a3b8", fontSize: 10, format: (v: number) => v.toFixed(3) }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            type="category"
            dataKey="label"
            domain={[sorted.length, -1]}
            tick={{ fill: "#94a3b8", fontSize: 9 }}
            tickLine={false}
            axisLine={false}
            allowDuplicatedCategory
          />
          {/* Error bars: horizontal whiskers at ±SE around the gap dot. */}
          <ErrorBar dataKey="gap" errorKey="gap_se" stroke="#64748b" strokeWidth={1} />
          {/* Ahead dots (green): gap < 0, enough settled. */}
          <Scatter
            name="Better than Kalshi"
            data={sorted.filter((r) => r.gap !== null && r.gap < 0 && !r.tooEarly)}
            dataKey="gap"
            fill={AHEAD}
          />
          {/* Behind dots (red): gap > 0, enough settled. */}
          <Scatter
            name="Worse than Kalshi"
            data={sorted.filter((r) => r.gap !== null && r.gap > 0 && !r.tooEarly)}
            dataKey="gap"
            fill={BEHIND}
          />
          {/* Too-early dots (hollow grey): under 30 settled. */}
          <Scatter
            name="Too early"
            data={sorted.filter((r) => r.gap !== null && r.tooEarly)}
            dataKey="gap"
            fill="none"
            stroke={UNKNOWN}
            strokeWidth={1.5}
          />
        </ScatterChart>
      </ResponsiveContainer>
    </section>
  );
}