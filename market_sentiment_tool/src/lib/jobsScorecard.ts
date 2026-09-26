export type JobsSeries = "payrolls" | "unemployment";

export type JobsScorecardRow = {
  series: JobsSeries;
  reference_month: string; // YYYY-MM-01
  kalshi_event: string | null;
  release_date: string | null;
  nowcast_mu: number | null;
  nowcast_sigma: number | null;
  engine_version: string | null;
  // Added by GET /api/jobs-scorecard, not stored on the row: the scorecard is built out of band,
  // so the promotion gate has to be looked up per (engine, engine_version) at read time.
  engine?: string | null;
  gate_status?: string | null;
  kalshi_mean_1h: number | null;
  kalshi_median_1h: number | null;
  first_print: number | null;
  rev2: number | null;
  rev3: number | null;
  benchmark: number | null;
  latest: number | null;
  n_strikes: number;
  nowcast_abs_err: number | null;
  kalshi_abs_err: number | null;
  nowcast_brier: number | null;
  kalshi_brier: number | null;
};

export type ScorecardChartPoint = {
  month: string; // YYYY-MM
  nowcast: number | null;
  kalshi: number | null;
  firstPrint: number | null;
  latest: number | null;
};

export type ScorecardSummary = {
  months: number;
  scored: number; // months with a first print, a nowcast and a Kalshi-implied mean
  nowcastMae: number | null;
  kalshiMae: number | null;
  nowcastBrier: number | null;
  kalshiBrier: number | null;
  nowcastCloser: number; // months where our point estimate beat Kalshi's implied mean
};

const toNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

const mean = (values: number[]): number | null =>
  values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;

export function toChartPoints(rows: JobsScorecardRow[]): ScorecardChartPoint[] {
  return [...rows]
    .sort((a, b) => a.reference_month.localeCompare(b.reference_month))
    .map((row) => ({
      month: row.reference_month.slice(0, 7),
      nowcast: toNumber(row.nowcast_mu),
      kalshi: toNumber(row.kalshi_mean_1h),
      firstPrint: toNumber(row.first_print),
      latest: toNumber(row.latest),
    }));
}

export function summarizeScorecard(rows: JobsScorecardRow[]): ScorecardSummary {
  const scored = rows.filter(
    (row) =>
      toNumber(row.nowcast_abs_err) !== null && toNumber(row.kalshi_abs_err) !== null,
  );
  const briers = rows.filter(
    (row) => toNumber(row.nowcast_brier) !== null && toNumber(row.kalshi_brier) !== null,
  );
  return {
    months: rows.length,
    scored: scored.length,
    nowcastMae: mean(scored.map((row) => toNumber(row.nowcast_abs_err) as number)),
    kalshiMae: mean(scored.map((row) => toNumber(row.kalshi_abs_err) as number)),
    nowcastBrier: mean(briers.map((row) => toNumber(row.nowcast_brier) as number)),
    kalshiBrier: mean(briers.map((row) => toNumber(row.kalshi_brier) as number)),
    nowcastCloser: scored.filter(
      (row) => (toNumber(row.nowcast_abs_err) as number) < (toNumber(row.kalshi_abs_err) as number),
    ).length,
  };
}

export function formatValue(series: JobsSeries, value: number | string | null | undefined): string {
  const n = toNumber(value);
  if (n === null) return "—";
  if (series === "unemployment") return `${n.toFixed(1)}%`;
  const rounded = Math.round(n);
  return `${rounded > 0 ? "+" : ""}${rounded}k`;
}
