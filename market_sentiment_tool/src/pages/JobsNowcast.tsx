import { Fragment, useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Scale } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { GateBadge } from "@/components/GateBadge";
import { useJobsScorecard } from "@/hooks/useJobsScorecard";
import { formatValue, summarizeScorecard, toChartPoints, type JobsSeries } from "@/lib/jobsScorecard";

const fmtScore = (value: number | null, digits = 3) => (value === null ? "—" : value.toFixed(digits));

const SERIES: { key: JobsSeries; label: string }[] = [
  { key: "payrolls", label: "Payrolls (KXPAYROLLS)" },
  { key: "unemployment", label: "Unemployment (KXU3)" },
];

const sigmaDisplay = (series: JobsSeries, sigma: number | null) => {
  if (sigma === null) return "";
  const formatted = formatValue(series, sigma).replace("+", "");
  return ` ±${formatted}`;
};

const gateStatusClass = (status: string) => {
  if (status === "PROMOTED") return "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30";
  return "bg-amber-500/10 text-amber-300 border border-amber-500/20";
};

const seriesButtonClass = (isActive: boolean) => {
  if (isActive) return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
  return "border-slate-800 bg-slate-900/50 text-slate-400 hover:text-slate-200 hover:border-slate-700";
};

export default function JobsNowcast() {
  const [series, setSeries] = useState<JobsSeries>("payrolls");
  const { rows, loading, error } = useJobsScorecard(series);
  const points = useMemo(() => toChartPoints(rows), [rows]);
  const summary = useMemo(() => summarizeScorecard(rows), [rows]);
  const errDigits = series === "payrolls" ? 1 : 2;
  const newest = rows[rows.length - 1];

  return (
    <div className="mx-auto max-w-[1200px] space-y-8 p-6 md:p-10">
      <header className="space-y-1">
        <h1 className="text-3xl font-bold tracking-tight text-white">Jobs Scorecard</h1>
        <p className="max-w-[680px] text-sm leading-relaxed text-slate-400">Our nowcast vs Kalshi, one month per row.</p>
      </header>

      {error && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-950/20 p-4 text-sm text-rose-200">
          <span className="font-semibold">Scorecard unavailable</span>
          <span className="ml-2 text-rose-300/80">{error}</span>
        </div>
      )}

      {loading ? (
        <div className="py-12 text-center text-sm text-slate-500" role="status" aria-live="polite">Loading scorecard…</div>
      ) : (
        <Fragment>
          <section aria-label="Headline stats" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard label="Releases scored" value={summary.scored} sub={`${summary.scored} of ${summary.months} months`} />
            <StatCard label="Our vs Kalshi: closer" value={summary.nowcastCloser} sub="Months our point estimate beat Kalshi's" />
            <StatCard label="MAE: ours" value={fmtScore(summary.nowcastMae, errDigits)} sub="Mean abs error vs first print" />
            <StatCard label="MAE: Kalshi" value={fmtScore(summary.kalshiMae, errDigits)} sub="Mean abs error vs first print" />
          </section>

          <section aria-label="Series selection" className="flex gap-2">
            {SERIES.map((s) => (
              <button
                key={s.key}
                type="button"
                onClick={() => setSeries(s.key)}
                className={seriesButtonClass(series === s.key)}
              >
                {s.label}
              </button>
            ))}
          </section>

          <section aria-label="Chart" className="border border-slate-800 rounded-xl bg-slate-900/40 overflow-hidden">
            <div className="px-5 pt-4 pb-1 flex items-center justify-between">
              <h2 className="text-base font-semibold text-slate-200">Nowcast vs Kalshi vs first print vs latest</h2>
              <span className="text-xs text-slate-500">One point per release month</span>
            </div>
            <div className="h-[300px] px-4 pb-4">
              <ResponsiveChart points={points} />
            </div>
          </section>

          <section aria-label="Per-report detail" className="border border-slate-800 rounded-xl bg-slate-900/30 overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
              <h2 className="text-base font-semibold text-slate-200">Per-report detail</h2>
              <span className="text-xs text-slate-500">Latest release first</span>
            </div>
            <table className="w-full text-sm text-slate-300">
              <thead className="text-xs uppercase tracking-wider text-slate-500 bg-slate-950/50">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Month</th>
                  <th className="px-4 py-2 text-right font-medium">Nowcast ±σ</th>
                  <th className="px-4 py-2 text-right font-medium">Kalshi</th>
                  <th className="px-4 py-2 text-right font-medium">First print</th>
                  <th className="px-4 py-2 text-right font-medium">Engine</th>
                  <th className="px-4 py-2 text-right font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {[...rows].reverse().map((r) => (
                  <tr key={r.reference_month} className="border-t border-slate-800 hover:bg-slate-800/30 transition-colors">
                    <td className="px-4 py-2 font-mono text-slate-400">{r.reference_month.slice(0, 7)}</td>
                    <td className="px-4 py-2 text-right">
          {formatValue(series, r.nowcast_mu)}{sigmaDisplay(series, r.nowcast_sigma)}
        </td>
                    <td className="px-4 py-2 text-right">{formatValue(series, r.kalshi_mean_1h)}</td>
                    <td className="px-4 py-2 text-right font-semibold">{formatValue(series, r.first_print)}</td>
                    <td className="px-4 py-2 text-right text-xs font-mono text-slate-500">{r.engine ?? "—"}</td>
                    <td className="px-4 py-2 text-right"><span className={gateStatusClass(r.gate_status ?? "Shadow")}>{r.gate_status ?? "Shadow"}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section aria-label="Internals" className="rounded-xl border border-slate-800/50 bg-slate-900/20">
            <details className="group">
              <summary className="cursor-pointer px-5 py-3 text-sm font-medium text-slate-300 hover:text-white select-none">Internals</summary>
              <div className="border-t border-slate-800/40 px-5 py-4 space-y-1 text-xs text-slate-400">
                <p>The scorecard is built out of band by the `/api/jobs-scorecard` endpoint (service-role read on `jobs_scorecard`). The page renders the server's rows.</p>
              </div>
            </details>
          </section>
        </Fragment>
      )}
    </div>
  );
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 px-5 py-4">
      <div className="text-4xl font-bold tabular-nums tracking-tight text-white">{value}</div>
      <div className="mt-1 text-sm font-medium text-slate-300">{label}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

function ResponsiveChart({ points }: { points: { month: string; nowcast: number | null; kalshi: number | null; firstPrint: number | null; latest: number | null }[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={points}>
        <CartesianGrid stroke="#1e293b" />
        <XAxis dataKey="month" stroke="#64748b" fontSize={11} tick={{ fill: "#94a3b8" }} />
        <YAxis stroke="#64748b" fontSize={11} tick={{ fill: "#94a3b8" }} />
        <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155", fontSize: 12 }} />
        <Legend />
        <Line type="monotone" dataKey="firstPrint" name="First BLS print" stroke="#f8fafc" strokeWidth={2} dot={false} />
        <Line type="monotone" dataKey="nowcast" name="Our nowcast" stroke="#10b981" strokeWidth={2} />
        <Line type="monotone" dataKey="kalshi" name="Kalshi implied" stroke="#f59e0b" strokeWidth={2} />
        <Line type="monotone" dataKey="latest" name="Latest revised" stroke="#64748b" strokeWidth={1.5} strokeDasharray="4 4" dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}