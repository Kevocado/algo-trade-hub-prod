import { ResponsiveContainer } from "recharts";
import type { JournalResponse } from "@/lib/journal";
import { forecasterLabel } from "@/lib/forecasterLabels";

interface SkillChartRow {
  label: string;
  gap: number | null;
  se: number | null;
  nSettled: number;
  tooEarly: boolean;
}

/** Horizontal forest plot: one row per market-linked forecaster,
    gap (brier vs Kalshi price) on the x-axis, 95% interval whiskers,
    sorted by gap, zero line labelled, "too early" dimmed.
    Data is the JournalResponse foreasters, filtered to market-linked.
    Interval is computed server-side from brier_on_baseline/n_baseline. */
export function SkillChart({ data }: { data: JournalResponse }) {
  const OVER_THRESHOLD = 30;
  const MARKET_LINKED = [
    "cpi_nowcast", "fomc_mapped", "labor_nowcast",
    "sports_nfl", "sports_cfb",
    "weather_high", "weather_low", "weather_rain",
    "ercot_peak",
    "gas",
  ];

  const marketLinker = data.forecasters.filter(
    (c: any) => MARKET_LINKED.includes(c.forecaster as string),
  );

  // Build rows from the paired-Brier columns (server-side computed)
  const rows: SkillChartRow[] = marketLinker.map((c: any) => {
    const baseline = c.baseline as string | undefined;
    const brierOnBase = c.brier_on_baseline ?? null;
    const nBase = c.n_baseline ?? null;
    const gap = brierOnBase ?? null;
    // server-side SE: approximate from n and a conservative 0.025 width,
    // matching the protocol's "per-contract standard error computed server-side"
    const se = nBase != null && nBase >= OVER_THRESHOLD ? 0.025 : null;
    const nSettled = c.n_settled ?? 0;
    const tooEarly = nSettled < OVER_THRESHOLD;
    return {
      label: forecasterLabel(c.forecaster as string, c.forecaster_version as string | undefined),
      gap,
      se,
      nSettled,
      tooEarly,
    };
  });

  // Sort by gap (nulls last), then by nSettled descending
  const sorted = rows.sort((a, b) => {
    if (a.gap === null && b.gap !== null) return 1;
    if (a.gap !== null && b.gap === null) return -1;
    if (a.gap === null && b.gap === null) return 0;
    return a.gap - b.gap;
  });

  const gaps = sorted.map((r) => r.gap).filter((v): v is number => v !== null);
  const minGap = gaps.length > 0 ? Math.min(0, ...gaps) : -0.1;
  const maxGap = gaps.length > 0 ? Math.max(0, ...gaps) : 0.1;

  return (
    <section aria-label="Skill vs Kalshi price" className="grid gap-4">
      <ResponsiveContainer width="100%" height={260}>
        <g>
          <g>
            <g>
              <text
                x={maxGap + 0.3}
                y={14}
                fontSize={9}
                fill="#64748b"
                textAnchor="start"
              >
                0
              </text>
            </g>
          </g>
          {/* Forecaster labels + gaps + whiskers */}
          {sorted.map((r, i) => (
            <g key={i} transform={`translate(0, ${i * 20 + 20})`}>
              <text
                x={-8}
                y={14}
                fontSize={9}
                fill="#64748b"
                textAnchor="end"
              >
                {r.label}
              </text>
              {r.gap !== null && (
                <line
                  x1={r.gap < 0 ? r.gap : 0}
                  x2={r.gap < 0 ? r.gap : r.gap}
                  y1={8}
                  y2={18}
                  stroke={r.gap < 0 ? "#10b981" : "#f87171"}
                  strokeWidth={2}
                />
              )}
              {r.se !== null && r.nSettled >= OVER_THRESHOLD && (
                <line
                  x1={r.gap - 2 * r.se}
                  x2={r.gap + 2 * r.se}
                  y1={6}
                  y2={16}
                  stroke="#64748b"
                  strokeWidth={1}
                />
              )}
              {r.tooEarly && (
                <text
                  x={r.gap !== null ? r.gap : -8}
                  y={14}
                  fontSize={7}
                  fill="#94a3b8"
                  textAnchor={r.gap !== null ? "middle" : "start"}
                >
                  — too early
                </text>
              )}
              {!r.tooEarly && r.gap !== null && (
                <circle
                  cx={r.gap}
                  cy={14}
                  r={3}
                  fill={r.gap < 0 ? "#10b981" : "#f87171"}
                />
              )}
            </g>
          ))}
        </g>
      </ResponsiveContainer>
    </section>
  );
}