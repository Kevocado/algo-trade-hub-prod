import { useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, Loader2 } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useJobsScorecard } from "@/hooks/useJobsScorecard";
import { formatValue, summarizeScorecard, toChartPoints, type JobsSeries } from "@/lib/jobsScorecard";

const SERIES: { key: JobsSeries; label: string }[] = [
  { key: "payrolls", label: "Payrolls (KXPAYROLLS)" },
  { key: "unemployment", label: "Unemployment (KXU3)" },
];

const fmtScore = (value: number | null, digits = 3) => (value === null ? "—" : value.toFixed(digits));

export default function JobsScorecard() {
  const [series, setSeries] = useState<JobsSeries>("payrolls");
  const { rows, loading, error } = useJobsScorecard(series);
  const points = useMemo(() => toChartPoints(rows), [rows]);
  const summary = useMemo(() => summarizeScorecard(rows), [rows]);
  const errDigits = series === "payrolls" ? 1 : 2;

  return (
    <div className="min-h-screen bg-slate-950 px-8 py-10 text-slate-100">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-8">
        <div className="flex flex-col gap-4 border-b border-slate-900 pb-8 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <h1 className="text-4xl font-black uppercase italic tracking-tight text-white">Jobs Scorecard</h1>
            <p className="max-w-3xl text-sm text-slate-400">
              Kalshi settles on the BLS first print, not the revised number. Each row compares our nowcast and the
              Kalshi-implied estimate (one hour before the release) with the first print, then shows how the number
              was revised afterwards.
            </p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-1">
            {SERIES.map((s) => (
              <button
                key={s.key}
                onClick={() => setSeries(s.key)}
                className={`rounded-lg px-4 py-2 text-xs font-bold uppercase tracking-widest ${
                  series === s.key ? "bg-emerald-500/20 text-emerald-300" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <Card className="border-rose-500/30 bg-rose-500/10">
            <CardContent className="flex items-center gap-3 p-6 text-rose-100">
              <AlertTriangle className="h-5 w-5 text-rose-400" />
              <p className="text-sm">{error}</p>
            </CardContent>
          </Card>
        )}

        {loading ? (
          <div className="flex items-center gap-3 text-slate-300">
            <Loader2 className="h-5 w-5 animate-spin text-emerald-400" /> Loading scorecard
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
              <Card className="border-slate-800 bg-slate-900/50">
                <CardHeader className="pb-3">
                  <CardDescription>Releases scored</CardDescription>
                  <CardTitle className="text-3xl">{summary.scored} / {summary.months}</CardTitle>
                </CardHeader>
              </Card>
              <Card className="border-slate-800 bg-slate-900/50">
                <CardHeader className="pb-3">
                  <CardDescription>Mean abs error vs first print: ours / Kalshi</CardDescription>
                  <CardTitle className="text-3xl">
                    {fmtScore(summary.nowcastMae, errDigits)} / {fmtScore(summary.kalshiMae, errDigits)}
                  </CardTitle>
                </CardHeader>
              </Card>
              <Card className="border-slate-800 bg-slate-900/50">
                <CardHeader className="pb-3">
                  <CardDescription>Ladder Brier: ours / Kalshi</CardDescription>
                  <CardTitle className="text-3xl">
                    {fmtScore(summary.nowcastBrier)} / {fmtScore(summary.kalshiBrier)}
                  </CardTitle>
                </CardHeader>
              </Card>
              <Card className="border-slate-800 bg-slate-900/50">
                <CardHeader className="pb-3">
                  <CardDescription>Months our estimate was closer</CardDescription>
                  <CardTitle className="text-3xl">{summary.nowcastCloser}</CardTitle>
                </CardHeader>
              </Card>
            </div>

            <Card className="border-slate-800 bg-slate-900/50">
              <CardHeader>
                <CardTitle>Nowcast vs Kalshi vs first print vs latest</CardTitle>
              </CardHeader>
              <CardContent className="h-[360px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={points}>
                    <CartesianGrid stroke="#1e293b" />
                    <XAxis dataKey="month" stroke="#64748b" fontSize={11} />
                    <YAxis stroke="#64748b" fontSize={11} />
                    <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
                    <Legend />
                    <Line type="monotone" dataKey="firstPrint" name="First print" stroke="#f8fafc" strokeWidth={2} />
                    <Line type="monotone" dataKey="nowcast" name="Our nowcast" stroke="#10b981" />
                    <Line type="monotone" dataKey="kalshi" name="Kalshi implied" stroke="#f59e0b" />
                    <Line type="monotone" dataKey="latest" name="Latest revised" stroke="#64748b" strokeDasharray="4 4" />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card className="border-slate-800 bg-slate-900/50">
              <CardContent className="overflow-x-auto p-0">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase tracking-wider text-slate-400">
                    <tr>
                      {["Month", "Release", "Nowcast ±σ", "Kalshi", "First print", "2nd", "3rd", "Benchmark",
                        "Latest", "|err| ours", "|err| Kalshi"].map((h) => (
                        <th key={h} className="px-4 py-3">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[...rows].reverse().map((row) => (
                      <tr key={row.reference_month} className="border-t border-slate-800">
                        <td className="px-4 py-2 font-mono">{row.reference_month.slice(0, 7)}</td>
                        <td className="px-4 py-2 text-slate-400">{row.release_date ?? "—"}</td>
                        <td className="px-4 py-2">
                          {formatValue(series, row.nowcast_mu)}
                          {row.nowcast_sigma !== null && (
                            <span className="text-slate-500"> ±{formatValue(series, row.nowcast_sigma).replace("+", "")}</span>
                          )}
                        </td>
                        <td className="px-4 py-2">{formatValue(series, row.kalshi_mean_1h)}</td>
                        <td className="px-4 py-2 font-bold">{formatValue(series, row.first_print)}</td>
                        <td className="px-4 py-2">{formatValue(series, row.rev2)}</td>
                        <td className="px-4 py-2">{formatValue(series, row.rev3)}</td>
                        <td className="px-4 py-2">{formatValue(series, row.benchmark)}</td>
                        <td className="px-4 py-2 text-slate-400">{formatValue(series, row.latest)}</td>
                        <td className="px-4 py-2">{fmtScore(row.nowcast_abs_err === null ? null : Number(row.nowcast_abs_err), errDigits)}</td>
                        <td className="px-4 py-2">{fmtScore(row.kalshi_abs_err === null ? null : Number(row.kalshi_abs_err), errDigits)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
