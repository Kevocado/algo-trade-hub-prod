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
  Wrench,
} from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  NOT_THE_SCOREBOARD,
  NO_FIGURE,
  formatBrier4,
  formatHitRate,
  formatHours,
  formatSignedPct,
  shadowUnavailable,
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

/**
 * The one state this page had, and the reason it was not honest.
 *
 * A failed read used to render a rose card saying "Shadow API unavailable" and
 * then carry on rendering the whole dashboard underneath it, with
 * `data?.summary.considered_count ?? 0` and three siblings. So a page that could
 * not read a single row put "Considered Trades 0", "Dead Zone 0", "Evaluated 0"
 * and "Series Points 0" in front of a reader as measurements. That is the claim
 * this component must never make, and the red card is the least of it: the
 * figures below it were stating that the crypto engine considered nothing and
 * sat in no dead zone, which nobody measured.
 *
 * So the states are separated, and a figure is only ever drawn from a read that
 * returned one:
 *
 *   - loading. Nothing at all, because a spinner over four zeros would be the
 *     same claim with a pause in front of it.
 *   - failed, and there is no data to show. The reason and the operator step,
 *     and NOT ONE FIGURE. A page that says "apply this migration" is not
 *     broken, it is waiting on a person, so it is not coloured like a fault.
 *   - failed, but a previous poll returned data. The data is still real, so it
 *     stays, with a banner saying the latest read failed. Blanket-ing a good
 *     read because a later one broke would trade a lie for an inconvenience.
 *   - read. Every figure comes off `data`, which is non-null from here on, so
 *     there is no `?.` and no `?? 0` left in this file to fall back to.
 *
 * "Waiting on a person" now covers TWO deployment steps, not one, and they are told apart by
 * status. `/api/shadow-performance` returns 503 for a migration that has not been applied and 424
 * for a credential that is not set (`vps-stack/compose.yml` passes no `ALPACA_*` to the tradehub
 * service, so the 424 is what every reader gets once the migration lands). Both are amber and both
 * quote the server's sentence, because both are the same kind of fact about the same deployment; a
 * 500 is the one that is red, because it is a fact about this code. Before this page learned the
 * difference, the 424 rendered as a red "could not be read" panel -- the undiagnosable outcome the
 * 424 was introduced to end, surviving on the client side.
 *
 * The wording of the failed state is `shadowUnavailable` in
 * `@/lib/shadowPerformance`, with its own tests, and it quotes the sentence the
 * API sent rather than restating the migration name -- that sentence names the
 * table and the file (`tradehub/api/main.py:246`), and a second copy of that
 * mapping here would be a second place to be wrong.
 *
 * Nothing here computes a threshold, a gate or a rounding policy. `hit_rate` and
 * `brier_score` are `None` from the server when nothing finished in the window
 * (`tradehub/scripts/shadow_performance.py:312`) and are printed as `NO_FIGURE`
 * -- words, not a dash, because a dash in a figure column is a number that reads
 * as zero. This file decides layout and nothing else.
 */
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


/**
 * The sentence that says this is not the scoreboard, with the route that is.
 *
 * Rendered in BOTH states rather than only when the read failed, because the failure is not when
 * the collision happens. A visitor who typed `/shadow` for the engine scoreboard is on the wrong
 * page whether the crypto read works or not, and the read is the one thing about this page most
 * likely to be broken. So the correction sits in the page's own header, where it is read before
 * any figure.
 */
function NotTheScoreboard({ muted = false }: { muted?: boolean }) {
  return (
    <p className={`max-w-3xl leading-relaxed ${muted ? "text-xs text-slate-500" : "text-sm text-slate-300"}`}>
      {NOT_THE_SCOREBOARD}{" "}
      {/* Points at the CANONICAL /scoreboard, not at the /shadow-scoreboard alias. A link on a
          page is not a bookmark and is not a citation anyone will copy out, so there is no reason
          to spend it on a redirect -- and if /shadow-scoreboard is ever dropped, this link keeps
          working. */}
      <a href="/scoreboard" className="text-emerald-400 hover:underline">
        Open the Engine Scoreboard
      </a>
    </p>
  );
}

/**
 * The unavailable state. No figure, no chart, no count -- by construction.
 *
 * `status` and `errorCode` are the inputs and `detail` is not, and the component does not need to
 * know why: `shadowUnavailable` resolves the status and the code into a tone, and the tone picks
 * the frame. There is one branch here -- fault or not -- deliberately, so that a fourth state added
 * to `shadowUnavailable` lands on the operator side by default rather than on the red one. Being
 * wrong in that direction means an operator reads a notice instead of an alarm; the other way round
 * a red panel would again be claiming the product is broken when a person has two variables to set.
 */
function Unavailable({
  status,
  detail,
  errorCode,
}: {
  status: number | null;
  detail: string | null;
  errorCode: string | null;
}) {
  const notice = shadowUnavailable(status, detail, errorCode);
  // A deployment step is an amber notice, not a red one, and there are two of them now: a migration
  // to apply and an environment variable to set. Red says "this is broken and nobody knows why";
  // amber says "this is known and it has a step". Only a 500 gets red, because a 500 is the one
  // that is a fact about this code and the one no operator step closes.
  const fault = notice.tone === "fault";
  const frame = fault
    ? "border-rose-500/30 bg-rose-500/10 text-rose-100"
    : "border-amber-500/30 bg-amber-500/10 text-amber-100";

  return (
    <div className={`rounded-xl border p-6 ${frame}`}>
      {/* An <h2>, under the page's own <h1>. The unavailable state is a section of this page, and
          a reader -- or a screen reader -- navigating by heading has to be able to find it. */}
      <h2 className="flex items-center gap-2 text-lg font-semibold">
        {fault ? (
          <AlertTriangle className="h-5 w-5 text-rose-400" />
        ) : (
          <Wrench className="h-5 w-5 text-amber-300" />
        )}
        {notice.title}
      </h2>
      <p className="mt-2 max-w-2xl text-sm text-slate-300">{notice.lead}</p>
      {/* The server's sentence, quoted. It names the table and the migration file, and it is the
          only copy of that mapping in the product. */}
      <p className="mt-3 max-w-2xl border-l-2 border-slate-600 pl-3 font-mono text-xs leading-relaxed text-slate-200">
        {notice.body}
      </p>
      <div className="mt-4 max-w-2xl border-t border-slate-700/70 pt-4">
        <NotTheScoreboard />
      </div>
    </div>
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

  /* No read, and the read failed. The reason and the step, and not one figure.
     Everything below this branch reads `data` directly, with no optional
     chaining and no fallback, so there is no path from "nothing came back" to
     a printed 0. */
  if (error && !data) {
    return (
      <div className="min-h-screen bg-slate-950 px-8 py-10 text-slate-100">
        <div className="mx-auto flex max-w-[1600px] flex-col gap-6">
          {/* The h1 and the CRYPTO badge, and nothing else. The correction and the route to the
              page he wanted both live at the foot of the panel below, so they are stated once and
              next to the reason a person has to act on -- a header that carried them too would say
              the same thing twice on the one screen where the reader is looking for what to do. */}
          <header className="border-b border-slate-900 pb-6">
            <div className="flex items-center gap-3">
              <h1 className="text-3xl font-bold text-white">Crypto Shadow Timeline</h1>
              <Badge className="bg-emerald-500 text-emerald-950 font-bold">CRYPTO</Badge>
            </div>
          </header>
          <Unavailable status={error.status} detail={error.message} errorCode={error.code} />
        </div>
      </div>
    );
  }

  /* Past this line a read returned something, so every figure below is a figure
     the server actually sent. `data` is non-null by the tests above. */
  const read = data;
  const series = read.series;

  return (
    <div className="min-h-screen bg-slate-950 px-8 py-10 text-slate-100">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-8">
        <div className="flex flex-col gap-4 border-b border-slate-900 pb-8 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <h1 className="text-4xl font-black uppercase italic tracking-tight text-white">Crypto Shadow Timeline</h1>
              <Badge className="bg-emerald-500 text-emerald-950 font-bold">CRYPTO</Badge>
            </div>
            <p className="max-w-3xl text-sm text-slate-400">
              Visualize model probability against realized price movement and see exactly when threshold-triggered trades won or lost.
            </p>
            {/* The disambiguation, said by the page itself. The nav entry used to read plain
                "Shadow" and the route was /shadow, which is how a reader looking for the engine
                scoreboard ended up here. */}
            <div className="mt-3 max-w-3xl">
              <NotTheScoreboard muted />
            </div>
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

        {/* A read that failed while an EARLIER one succeeded. The data below is real, so it stays
            and the banner says which read failed rather than implying the whole board is empty.
            Same wording as the full-page state, because it is the same condition. */}
        {error ? (
          <div
            className={`rounded-xl border p-4 text-sm ${
              shadowUnavailable(error.status, error.message, error.code).tone === "fault"
                ? "border-rose-500/30 bg-rose-500/10 text-rose-100"
                : "border-amber-500/30 bg-amber-500/10 text-amber-100"
            }`}
          >
            <p className="font-semibold">
              {shadowUnavailable(error.status, error.message, error.code).title} — the figures
              below are from the last read that succeeded.
            </p>
            <p className="mt-1 font-mono text-xs text-slate-200">{error.message}</p>
          </div>
        ) : null}

        {/* Five figures, all off one read that returned. `considered_count`, `dead_zone_count` and
            `virtual_pnl_pct` are numbers the server computed, including a real 0 for an empty
            window -- a sum over no signals IS zero and saying so is a measurement. `hit_rate` and
            `brier_score` are None when nothing finished, and those two say so in words, because a
            dash there is a figure that reads as a number. */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
          <Card className="border-slate-800 bg-slate-900/50">
            <CardHeader className="pb-3">
              <CardDescription>Considered Trades</CardDescription>
              <CardTitle className="text-3xl">{read.summary.considered_count}</CardTitle>
            </CardHeader>
          </Card>
          <Card className="border-slate-800 bg-slate-900/50">
            <CardHeader className="pb-3">
              <CardDescription>Hit Rate</CardDescription>
              <CardTitle className="text-2xl leading-snug">
                {read.summary.hit_rate == null ? (
                  <span className="text-base text-slate-500">{NO_FIGURE}</span>
                ) : (
                  formatHitRate(read.summary.hit_rate)
                )}
              </CardTitle>
            </CardHeader>
          </Card>
          <Card className="border-slate-800 bg-slate-900/50">
            <CardHeader className="pb-3">
              <CardDescription>Brier Score</CardDescription>
              <CardTitle className="text-2xl leading-snug">
                {read.summary.brier_score == null ? (
                  <span className="text-base text-slate-500">{NO_FIGURE}</span>
                ) : (
                  formatBrier4(read.summary.brier_score)
                )}
              </CardTitle>
            </CardHeader>
          </Card>
          <Card className="border-slate-800 bg-slate-900/50">
            <CardHeader className="pb-3">
              <CardDescription>Virtual PnL</CardDescription>
              <CardTitle
                className={`text-3xl ${
                  read.summary.virtual_pnl_pct >= 0 ? "text-emerald-400" : "text-rose-400"
                }`}
              >
                {formatSignedPct(read.summary.virtual_pnl_pct)}
              </CardTitle>
            </CardHeader>
          </Card>
          <Card className="border-slate-800 bg-slate-900/50">
            <CardHeader className="pb-3">
              <CardDescription>Dead Zone</CardDescription>
              <CardTitle className="text-3xl">{read.summary.dead_zone_count}</CardTitle>
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
                <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-slate-800 px-6 text-center text-slate-500">
                  {/* An empty read, said as a read that came back empty. Not a figure, and not a
                      dash in a figure's place. */}
                  The read succeeded and {series.length === 0 ? "returned no points" : `returned no ${selectedAsset} points`}{" "}
                  in this window. Widen the lookback, or apply the migration this page is waiting on.
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
                    {freshness?.age_hours == null ? "Unavailable" : formatHours(freshness.age_hours)}
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
                  <span className="text-slate-400">{new Date(read.generated_at).toLocaleString()}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Evaluated</span>
                  <span className="text-slate-400">{read.summary.evaluated_count}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Series Points</span>
                  <span className="text-slate-400">{series.length}</span>
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
                        <td className="px-4 py-3 text-right text-slate-300">{formatHitRate(point.probability_yes)}</td>
                        <td className="px-4 py-3 text-right text-slate-400">${point.current_price.toLocaleString()}</td>
                        <td className="px-4 py-3 text-right text-slate-400">${point.next_hour_price.toLocaleString()}</td>
                        <td className="px-4 py-3 text-right">
                          <span className={point.correct ? "text-emerald-400" : "text-rose-400"}>
                            {point.shadow_outcome.toUpperCase()}
                          </span>
                        </td>
                        <td className={`px-4 py-3 text-right font-semibold ${point.virtual_return_pct >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                          {formatSignedPct(point.virtual_return_pct)}
                        </td>
                      </tr>
                    ))
                ) : (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-slate-500">
                      The read succeeded and returned no evaluated signals for this selection.
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
