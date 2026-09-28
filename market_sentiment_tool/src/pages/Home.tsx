import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { TrendingUp, Wallet, ArrowUpRight, Activity, Loader2, Brain } from "lucide-react";
import { usePortfolio, usePortfolioMetrics } from "@/hooks/usePortfolio";
import { moneyMetric } from "@/lib/portfolioTruth";
import { useMarketEdges, type KalshiEdge } from "@/hooks/useMarketEdges";
import { enforceDisplayOnlyPartition } from "@/lib/displayOnlyEngines";
import WithheldEdgesNotice from "@/components/WithheldEdgesNotice";
import { GateBadge } from "@/components/GateBadge";
import { Skeleton } from "@/components/ui/skeleton";

// Mock Data for Equity Curve
const chartData = [
  { day: "01", equity: 10000 }, { day: "05", equity: 10800 },
  { day: "10", equity: 11200 }, { day: "15", equity: 10900 },
  { day: "20", equity: 12500 }, { day: "25", equity: 14100 },
  { day: "30", equity: 15400 }
];

export default function Home() {
  const { metrics, loading: mLoading } = usePortfolioMetrics();
  const { portfolio, positions: paperPositions, loading: pLoading } = usePortfolio();
  const { edges: readEdges, withheld: readWithheld, loading: eLoading } = useMarketEdges();
  // Same rule as the Prediction Lab, same reason: this page renders `edge_pct` as a headline
  // number, so a display-only row reaching `topEdges` would read as an opportunity. The hook
  // withholds it; this is the reader being the last line as well.
  const { edges, withheld } = enforceDisplayOnlyPartition<KalshiEdge>(readEdges, readWithheld);

  const loading = mLoading || pLoading || eLoading;

  if (loading) {
    return (
      <div className="p-8 max-w-[1400px] mx-auto space-y-8 bg-slate-950">
        <div className="flex flex-col gap-1 border-b border-slate-900 pb-6 mb-2">
           <Skeleton className="h-10 w-64 bg-slate-900" />
           <Skeleton className="h-4 w-96 bg-slate-900 mt-2" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Skeleton className="h-32 bg-slate-900" />
          <Skeleton className="h-32 bg-slate-900" />
          <Skeleton className="h-32 bg-slate-900" />
        </div>
      </div>
    );
  }

  // These were `?? 0`, which is not a measured zero: PnLSummary carries no daily_pnl and no
  // cash_balance, so all three figures were missing numbers rendered as confident ones, under
  // headings claiming live equity and real-time P&L. This product places no orders, so they are
  // unknown until it does -- a dash, with the reason, not $0.00.
  const totalValue = moneyMetric(metrics?.total_value, metrics);
  const dailyPnL = moneyMetric(metrics?.daily_pnl, metrics, { signed: true });
  const availableCash = moneyMetric(metrics?.cash_balance, metrics);
  // From the API's paper ledger. Always empty today: this product places no orders.
  const positions = paperPositions;

  // Top 3 edges with AI summary
  const topEdges = edges
    .filter(e => e.ui_reasoning && e.ai_summary)
    .slice(0, 3);

  return (
    <div className="p-8 max-w-[1400px] mx-auto space-y-8 animate-in fade-in duration-500 bg-slate-950 min-h-screen text-slate-100">
      
      <div className="flex flex-col gap-1 border-b border-slate-900 pb-6 mb-2">
        <h1 className="text-4xl font-black tracking-tight text-white uppercase italic">War Room HQ</h1>
        <p className="text-slate-400 font-medium">Aggregating cross-engine alpha & real-time Kalshi telemetry.</p>
      </div>

      {/* An engine that is no longer an edge engine is relabelled, not removed. Without this the War
          Room's edge board simply gets quieter, which is indistinguishable from CPI never having
          existed -- and CPI did exist, and was measured. */}
      <WithheldEdgesNotice withheld={withheld} />

      {/* AI War Room Section */}
      {topEdges.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
             <Brain className="w-5 h-5 text-emerald-400" />
             <h2 className="text-lg font-bold uppercase tracking-widest text-emerald-500">AI High-Conviction Edges</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {topEdges.map((edge) => (
              <Card key={edge.id} className="bg-emerald-500/5 border-emerald-500/20 shadow-xl backdrop-blur-md hover:border-emerald-500/40 transition-all duration-300">
                <CardHeader className="pb-2">
                  <div className="flex justify-between items-start">
                    <Badge className="bg-emerald-500 text-emerald-950 text-[10px] font-bold uppercase tracking-tighter">{edge.edge_type}</Badge>
                    <div className="flex items-center gap-2">
                      <GateBadge edge={edge} />
                      <span className="text-xl font-black text-emerald-400">+{edge.edge_pct.toFixed(1)}%</span>
                    </div>
                  </div>
                  <CardTitle className="text-sm font-bold text-white mt-2 line-clamp-1">{edge.market_title}</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-slate-300 leading-relaxed italic border-l-2 border-emerald-500/30 pl-3 py-1">
                    "{edge.ai_summary}"
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Top Row: Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="bg-slate-900/40 border-slate-800 shadow-xl overflow-hidden group hover:border-slate-700 transition-all">
          <div className="absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity">
            <Activity className="w-12 h-12 text-slate-400" />
          </div>
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-widest">
              <TrendingUp className="w-4 h-4 text-emerald-500" /> Total Value
            </div>
            <CardTitle
              className={`text-3xl font-black tracking-tight ${
                totalValue.known ? "text-white" : "text-slate-500"
              }`}
              title={totalValue.note}
            >
              {totalValue.value}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {/* "Live equity" was never true: no order has ever been placed. */}
            <p className="text-xs text-slate-500 font-medium uppercase tracking-tight">
              {totalValue.known
                ? "Settled cash across all markets."
                : "No orders placed, so there is no equity to report."}
            </p>
          </CardContent>
        </Card>

        <Card className="bg-slate-900/40 border-slate-800 shadow-xl overflow-hidden group hover:border-slate-700 transition-all">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-widest">
              {/* Neutral when unknown: a green or red arrow would imply a direction that was never measured. */}
              <ArrowUpRight className={`w-4 h-4 ${
                !dailyPnL.known ? "text-slate-500" : dailyPnL.value.startsWith("-") ? "text-rose-500" : "text-emerald-500"
              }`} /> Daily PnL
            </div>
            <CardTitle
              className={`text-3xl font-black tracking-tight ${
                !dailyPnL.known
                  ? "text-slate-500"
                  : dailyPnL.value.startsWith("-")
                    ? "text-rose-400"
                    : "text-emerald-400"
              }`}
              title={dailyPnL.note}
            >
              {dailyPnL.value}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {/* "Real-time profit/loss" was never true either. */}
            <p className="text-xs text-slate-500 font-medium uppercase tracking-tight">
              {dailyPnL.known
                ? "Realised profit/loss for the current 24h cycle."
                : "No orders placed, so there is no profit or loss."}
            </p>
          </CardContent>
        </Card>

        <Card className="bg-slate-900/40 border-slate-800 shadow-xl overflow-hidden group hover:border-slate-700 transition-all">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-widest">
              <Wallet className="w-4 h-4 text-amber-500" /> Available Cash
            </div>
            <CardTitle
              className={`text-3xl font-black tracking-tight ${
                availableCash.known ? "text-white" : "text-slate-500"
              }`}
              title={availableCash.note}
            >
              {availableCash.value}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-slate-500 font-medium uppercase tracking-tight">Liquid purchasing power ready for immediate deployment.</p>
          </CardContent>
        </Card>
      </div>

      {/* Middle Row: Equity Curve */}
      <Card className="shadow-lg border-slate-800 bg-slate-900/50 backdrop-blur-sm">
        <CardHeader className="bg-slate-900/20 border-b border-slate-800">
          <CardTitle className="text-white">Growth Trajectory</CardTitle>
          <CardDescription className="text-slate-400">Aggregated account performance history.</CardDescription>
        </CardHeader>
        <CardContent className="pt-6 h-[400px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
              <defs>
                <linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#1e293b" />
              <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{fill: '#94a3b8'}} dy={10} />
              <YAxis axisLine={false} tickLine={false} tickFormatter={(val) => `$${val/1000}k`} tick={{fill: '#94a3b8'}} dx={-10} />
              <Tooltip 
                contentStyle={{ backgroundColor: '#0f172a', borderRadius: '8px', border: '1px solid #1e293b', boxShadow: 'none' }}
                formatter={(value: number) => [`$${value.toLocaleString()}`, "Equity"]}
                labelStyle={{ color: '#94a3b8', fontWeight: 600, marginBottom: '4px' }}
              />
              <Area 
                type="monotone" 
                dataKey="equity" 
                stroke="#10b981" 
                strokeWidth={3}
                fillOpacity={1} 
                fill="url(#colorEquity)" 
              />
            </AreaChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      {/* Bottom Row: Open Positions */}
      <Card className="shadow-lg border-slate-800 bg-slate-900/50 backdrop-blur-sm">
        <CardHeader className="bg-slate-900/20 border-b border-slate-800">
          <CardTitle className="text-white">Paper Ledger</CardTitle>
          <CardDescription className="text-slate-400">
            A record of positions the Hub would have taken. It places no orders, so this stays empty
            unless a paper-trading feature is switched on deliberately.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader className="bg-slate-900/50">
              <TableRow className="hover:bg-transparent border-slate-800">
                <TableHead className="w-[300px] pl-6 text-slate-400">Market</TableHead>
                <TableHead className="text-slate-400 text-right">Side</TableHead>
                <TableHead className="text-slate-400 text-right">Contracts</TableHead>
                <TableHead className="text-slate-400 text-right">Avg Cost</TableHead>
                <TableHead className="text-slate-400 text-right pr-6">P&amp;L (cents)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-10 text-slate-500">
                    This product places no orders. Nothing is ever bought or sold &mdash; every row on this
                    site is a suggestion, and an engine is only promoted once its settled results beat
                    the market after fees.
                  </TableCell>
                </TableRow>
              ) : (
                positions.map((pos, idx) => (
                  <TableRow key={idx} className="border-slate-800 hover:bg-slate-800/30 transition-colors">
                    <TableCell className="font-semibold text-white pl-6">{pos.ticker ?? "—"}</TableCell>
                    <TableCell className="text-right font-medium text-slate-300">
                      {pos.side ? (
                        <Badge variant="outline" className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20">
                          {pos.side.toUpperCase()}
                        </Badge>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell className="text-right text-slate-400 font-medium">{pos.contracts ?? "—"}</TableCell>
                    <TableCell className="text-right font-bold text-white">
                      {typeof pos.avg_cost_cents === "number" ? `${pos.avg_cost_cents}¢` : "—"}
                    </TableCell>
                    <TableCell className="text-right pr-6 font-bold text-slate-300">
                      {typeof pos.pnl_cents === "number" ? pos.pnl_cents.toFixed(1) : "—"}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

    </div>
  );
}
