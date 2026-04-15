import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  ComposedChart,
  Dot,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  AlertTriangle,
  BrainCircuit,
  Loader2,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  type ShadowPerformancePoint,
  filterShadowSeriesByAsset,
  getShadowAssets,
  getShadowMarkerColor,
  getShadowMarkerRadius,
  getShadowThresholdValue,
} from "@/lib/shadowPerformance";
import { useShadowPerformance } from "@/hooks/useShadowPerformance";

const DOMAIN = "crypto";
const HOURS_OPTIONS = [6, 12, 24, 48, 72];

function ShadowMarker(props: Record<string, unknown>) {
  const { cx, cy, payload } = props as {
    cx?: number;
    cy?: number;
    payload?: ShadowPerformancePoint;
  };
  if (cx == null || cy == null || !payload || !payload.threshold_triggered) {
    return null;
  }
  return (
    <Dot
      cx={cx}
      cy={cy}
      r={getShadowMarkerRadius(payload)}
      fill={getShadowMarkerColor(payload)}
      stroke="#020617"
      strokeWidth={1.5}
    />
  );
}


export default function ShadowBacktester() {
  const [hours, setHours] = useState(24);
  const [selectedAsset, setSelectedAsset] = useState("BTC");
  const { data, loading, refreshing, error, reload } = useShadowPerformance({ domain: DOMAIN, hours });

  const assets = useMemo(() => getShadowAssets(data?.series || []), [data?.series]);

  useEffect(() => {
    if (!assets.length) {
      return;
    }
    if (!assets.includes(selectedAsset)) {
      setSelectedAsset(assets[0]);
    }
  }, [assets, selectedAsset]);

  const assetSeries = useMemo(
    () => filterShadowSeriesByAsset(data?.series || [], selectedAsset),
    [data?.series, selectedAsset],
  );
  const thresholdValue = getShadowThresholdValue(data?.thresholds || {}, selectedAsset);
  const freshness = data?.freshness?.[selectedAsset];

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950">
        <div className="flex items-center gap-3 text-slate-300">
          <Loader2 className="h-6 w-6 animate-spin text-emerald-400" />
          <span className="font-semibold uppercase tracking-[0.25em] text-sm">Loading Shadow Backtester</span>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 px-8 py-10 text-slate-100">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-8">
        <div className="flex flex-col gap-4 border-b border-slate-900 pb-8 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <h1 className="text-4xl font-black uppercase italic tracking-tight text-white">Shadow Backtester</h1>
              <Badge className="bg-emerald-500 text-emerald-950 font-bold">CRYPTO</Badge>
            </div>
            <p className="max-w-3xl text-sm text-slate-400">
              Visualize model probability against realized price movement and see exactly when threshold-triggered trades won or lost.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-1">
              {["crypto", "weather", "macro"].map((domain) => (
                <button
                  key={domain}
                  type="button"
                  disabled={domain !== DOMAIN}
                  className={`rounded-lg px-4 py-2 text-xs font-bold uppercase tracking-widest transition-colors ${
                    domain === DOMAIN
                      ? "bg-emerald-500 text-emerald-950"
                      : "cursor-not-allowed text-slate-500"
                  }`}
                >
                  {domain}
                </button>
              ))}
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-1">
              {HOURS_OPTIONS.map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setHours(value)}
                  className={`rounded-lg px-4 py-2 text-xs font-bold uppercase tracking-widest transition-colors ${
                    hours === value
                      ? "bg-sky-500 text-sky-950"
                      : "text-slate-400 hover:bg-slate-800 hover:text-slate-100"
                  }`}
                >
                  {value}h
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={reload}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-2 text-xs font-bold uppercase tracking-widest text-slate-200 transition-colors hover:border-emerald-500/50 hover:text-emerald-300"
            >
              <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>

        {error ? (
          <Card className="border-rose-500/30 bg-rose-500/10">
            <CardContent className="flex items-center gap-3 p-6 text-rose-100">
              <AlertTriangle className="h-5 w-5 text-rose-400" />
              <div>
                <p className="font-semibold">Shadow API unavailable</p>
                <p className="text-sm text-rose-200/80">{error}</p>
              </div>
            </CardContent>
          </Card>
        ) : null}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
          <Card className="border-slate-800 bg-slate-900/50">
            <CardHeader className="pb-3">
              <CardDescription>Considered Trades</CardDescription>
              <CardTitle className="text-3xl">{data?.summary.considered_count ?? 0}</CardTitle>
            </CardHeader>
          </Card>
          <Card className="border-slate-800 bg-slate-900/50">
            <CardHeader className="pb-3">
              <CardDescription>Hit Rate</CardDescription>
              <CardTitle className="text-3xl">
                {data?.summary.hit_rate == null ? "—" : `${(data.summary.hit_rate * 100).toFixed(1)}%`}
              </CardTitle>
            </CardHeader>
          </Card>
          <Card className="border-slate-800 bg-slate-900/50">
            <CardHeader className="pb-3">
              <CardDescription>Brier Score</CardDescription>
              <CardTitle className="text-3xl">
                {data?.summary.brier_score == null ? "—" : data.summary.brier_score.toFixed(4)}
              </CardTitle>
            </CardHeader>
          </Card>
          <Card className="border-slate-800 bg-slate-900/50">
            <CardHeader className="pb-3">
              <CardDescription>Virtual PnL</CardDescription>
              <CardTitle
                className={`text-3xl ${
                  (data?.summary.virtual_pnl_pct || 0) >= 0 ? "text-emerald-400" : "text-rose-400"
                }`}
              >
                {data?.summary.virtual_pnl_pct == null ? "—" : `${data.summary.virtual_pnl_pct >= 0 ? "+" : ""}${data.summary.virtual_pnl_pct.toFixed(2)}%`}
              </CardTitle>
            </CardHeader>
          </Card>
          <Card className="border-slate-800 bg-slate-900/50">
            <CardHeader className="pb-3">
              <CardDescription>Dead Zone</CardDescription>
              <CardTitle className="text-3xl">{data?.summary.dead_zone_count ?? 0}</CardTitle>
            </CardHeader>
          </Card>
        </div>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
          <Card className="border-slate-800 bg-slate-900/50">
            <CardHeader className="flex flex-col gap-4 border-b border-slate-800/70 pb-5 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <CardTitle className="text-2xl text-white">Probability vs Price</CardTitle>
                <CardDescription>
                  Left axis shows current price. Right axis shows model probability and the active threshold line.
                </CardDescription>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-950/80 p-1">
                {assets.map((asset) => (
                  <button
                    key={asset}
                    type="button"
                    onClick={() => setSelectedAsset(asset)}
                    className={`rounded-lg px-4 py-2 text-xs font-bold uppercase tracking-widest transition-colors ${
                      selectedAsset === asset
                        ? "bg-amber-500 text-amber-950"
                        : "text-slate-400 hover:bg-slate-800 hover:text-slate-100"
                    }`}
                  >
                    {asset}
                  </button>
                ))}
              </div>
            </CardHeader>
            <CardContent className="h-[520px] pt-6">
              {assetSeries.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={assetSeries} margin={{ top: 12, right: 16, left: 16, bottom: 8 }}>
                    <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="timestamp"
                      tick={{ fill: "#94a3b8", fontSize: 11 }}
                      minTickGap={30}
                      tickFormatter={(value) =>
                        new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                      }
                    />
                    <YAxis
                      yAxisId="price"
                      tick={{ fill: "#94a3b8", fontSize: 11 }}
                      domain={["dataMin - 25", "dataMax + 25"]}
                      tickFormatter={(value) => `$${Number(value).toLocaleString()}`}
                    />
                    <YAxis
                      yAxisId="probability"
                      orientation="right"
                      tick={{ fill: "#94a3b8", fontSize: 11 }}
                      domain={[0, 1]}
                      tickFormatter={(value) => `${Math.round(Number(value) * 100)}%`}
                    />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#020617", border: "1px solid #1e293b", borderRadius: 12 }}
                      labelFormatter={(value) => new Date(value).toLocaleString()}
                      formatter={(value: number, name: string) => {
                        if (name === "current_price") {
                          return [`$${value.toLocaleString()}`, "Current Price"];
                        }
                        if (name === "probability_yes") {
                          return [`${(value * 100).toFixed(1)}%`, "Probability YES"];
                        }
                        return [value, name];
                      }}
                    />
                    <Legend />
                    {thresholdValue != null ? (
                      <ReferenceLine
                        yAxisId="probability"
                        y={thresholdValue}
                        stroke="#f59e0b"
                        strokeDasharray="5 5"
                        label={{ value: `${selectedAsset} YES threshold`, fill: "#fbbf24", fontSize: 11 }}
                      />
                    ) : null}
                    <Line
                      yAxisId="price"
                      type="monotone"
                      dataKey="current_price"
                      name="current_price"
                      stroke="#38bdf8"
                      strokeWidth={2.5}
                      dot={false}
                      activeDot={{ r: 4 }}
                    />
                    <Line
                      yAxisId="probability"
                      type="monotone"
                      dataKey="probability_yes"
                      name="probability_yes"
                      stroke="#a855f7"
                      strokeWidth={2.5}
                      dot={false}
                      activeDot={{ r: 4 }}
                    />
                    <Scatter
                      yAxisId="probability"
                      name="shadow_markers"
                      data={assetSeries}
                      shape={<ShadowMarker />}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-slate-800 text-slate-500">
                  No completed {selectedAsset} shadow points in this window.
                </div>
              )}
            </CardContent>
          </Card>

          <div className="space-y-6">
            <Card className="border-slate-800 bg-slate-900/50">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-white">
                  <Activity className="h-4 w-4 text-emerald-400" />
                  Freshness
                </CardTitle>
                <CardDescription>Latest bar health for the selected asset.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4 text-sm text-slate-300">
                <div className="flex items-center justify-between">
                  <span>Status</span>
                  <Badge className={freshness?.is_stale ? "bg-rose-500 text-rose-950" : "bg-emerald-500 text-emerald-950"}>
                    {freshness?.is_stale ? "STALE" : "FRESH"}
                  </Badge>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <span>Latest Bar</span>
                  <span className="text-right text-slate-400">
                    {freshness?.latest_bar ? new Date(freshness.latest_bar).toLocaleString() : "Unavailable"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Age</span>
                  <span className="text-slate-400">
                    {freshness?.age_hours == null ? "Unavailable" : `${freshness.age_hours.toFixed(2)}h`}
                  </span>
                </div>
              </CardContent>
            </Card>

            <Card className="border-slate-800 bg-slate-900/50">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-white">
                  <BrainCircuit className="h-4 w-4 text-violet-400" />
                  Visual Read
                </CardTitle>
                <CardDescription>Interpretation guide for the chart.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm text-slate-300">
                <p>Green markers indicate threshold-triggered trades that finished as wins.</p>
                <p>Red markers indicate threshold-triggered trades that finished as losses.</p>
                <p>The amber reference line is the active YES threshold for the selected asset.</p>
              </CardContent>
            </Card>

            <Card className="border-slate-800 bg-slate-900/50">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-white">
                  <ShieldAlert className="h-4 w-4 text-amber-400" />
                  Window Health
                </CardTitle>
                <CardDescription>Domain-wide context for the active lookback.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-sm text-slate-300">
                <div className="flex items-center justify-between">
                  <span>Generated</span>
                  <span className="text-slate-400">
                    {data?.generated_at ? new Date(data.generated_at).toLocaleString() : "Unavailable"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Evaluated</span>
                  <span className="text-slate-400">{data?.summary.evaluated_count ?? 0}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Series Points</span>
                  <span className="text-slate-400">{data?.series.length ?? 0}</span>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>

        <Card className="border-slate-800 bg-slate-900/50">
          <CardHeader className="border-b border-slate-800/70">
            <CardTitle className="text-white">Recent Evaluated Signals</CardTitle>
            <CardDescription>
              Completed next-hour outcomes for the active asset. Only threshold-triggered signals are shown.
            </CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto p-0">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-900/80 text-xs uppercase tracking-widest text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left">Time</th>
                  <th className="px-4 py-3 text-left">Ticker</th>
                  <th className="px-4 py-3 text-right">Prob YES</th>
                  <th className="px-4 py-3 text-right">Current</th>
                  <th className="px-4 py-3 text-right">Next Hour</th>
                  <th className="px-4 py-3 text-right">Outcome</th>
                  <th className="px-4 py-3 text-right">Virtual Return</th>
                </tr>
              </thead>
              <tbody>
                {assetSeries.length ? (
                  assetSeries
                    .slice()
                    .reverse()
                    .map((point) => (
                      <tr key={`${point.asset}-${point.timestamp}-${point.market_ticker}`} className="border-t border-slate-800/70">
                        <td className="px-4 py-3 text-slate-300">{new Date(point.timestamp).toLocaleString()}</td>
                        <td className="px-4 py-3 font-medium text-white">{point.market_ticker}</td>
                        <td className="px-4 py-3 text-right text-slate-300">{(point.probability_yes * 100).toFixed(1)}%</td>
                        <td className="px-4 py-3 text-right text-slate-400">${point.current_price.toLocaleString()}</td>
                        <td className="px-4 py-3 text-right text-slate-400">${point.next_hour_price.toLocaleString()}</td>
                        <td className="px-4 py-3 text-right">
                          <span className={point.correct ? "text-emerald-400" : "text-rose-400"}>
                            {point.shadow_outcome.toUpperCase()}
                          </span>
                        </td>
                        <td className={`px-4 py-3 text-right font-semibold ${point.virtual_return_pct >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                          {point.virtual_return_pct >= 0 ? "+" : ""}
                          {point.virtual_return_pct.toFixed(2)}%
                        </td>
                      </tr>
                    ))
                ) : (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-slate-500">
                      No evaluated signals available for this selection.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
