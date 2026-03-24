import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { TrendingUp, Wallet, ArrowUpRight, Activity, Loader2, Brain } from "lucide-react";
import { usePortfolio, usePortfolioMetrics } from "@/hooks/usePortfolio";
import { useMarketEdges } from "@/hooks/useMarketEdges";
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
  const { portfolio, loading: pLoading } = usePortfolio();
  const { edges, loading: eLoading } = useMarketEdges();

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

  const balance = metrics?.cash_balance ?? 0;
  const portfolioValue = metrics?.total_value ?? 0;
  const dailyPnL = metrics?.daily_pnl ?? 0;
  const positions = portfolio?.open_positions ?? [];

  const isPnLPositive = dailyPnL >= 0;

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
                    <span className="text-xl font-black text-emerald-400">+{edge.edge_pct.toFixed(1)}%</span>
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
            <CardTitle className="text-3xl font-black text-white tracking-tight">
              ${portfolioValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-slate-500 font-medium uppercase tracking-tight">Live equity + settled cash across all markets.</p>
          </CardContent>
        </Card>

        <Card className={`bg-slate-900/40 border-slate-800 shadow-xl overflow-hidden group hover:border-slate-700 transition-all border-l-4 ${isPnLPositive ? 'border-l-emerald-500' : 'border-l-rose-500'}`}>
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-widest">
              <ArrowUpRight className={`w-4 h-4 ${isPnLPositive ? 'text-emerald-500' : 'text-rose-500'}`} /> Daily PnL
            </div>
            <CardTitle className={`text-3xl font-black tracking-tight ${isPnLPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
              {isPnLPositive ? '+' : ''}${dailyPnL.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-slate-500 font-medium uppercase tracking-tight">Real-time profit/loss for the current 24h cycle.</p>
          </CardContent>
        </Card>

        <Card className="bg-slate-900/40 border-slate-800 shadow-xl overflow-hidden group hover:border-slate-700 transition-all">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-widest">
              <Wallet className="w-4 h-4 text-amber-500" /> Available Cash
            </div>
            <CardTitle className="text-3xl font-black text-white tracking-tight">
              ${balance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
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
          <CardTitle className="text-white">Live Operations</CardTitle>
          <CardDescription className="text-slate-400">Active Kalshi contracts currently managed by the Hub.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader className="bg-slate-900/50">
              <TableRow className="hover:bg-transparent border-slate-800">
                <TableHead className="w-[300px] pl-6 text-slate-400">Position Ticker</TableHead>
                <TableHead className="text-slate-400 text-right">Quantity</TableHead>
                <TableHead className="text-slate-400 text-right">Avg Entry</TableHead>
                <TableHead className="text-slate-400 text-right">Current Price</TableHead>
                <TableHead className="text-slate-400 text-right pr-6">Cost Basis</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-10 text-slate-500">No active positions detected in Kalshi account.</TableCell>
                </TableRow>
              ) : (
                positions.map((pos, idx) => (
                  <TableRow key={idx} className="border-slate-800 hover:bg-slate-800/30 transition-colors">
                    <TableCell className="font-semibold text-white pl-6">{pos.ticker}</TableCell>
                    <TableCell className="text-right font-medium text-slate-300">
                      <Badge variant="outline" className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20">
                        {pos.position > 0 ? 'YES' : 'NO'} {Math.abs(pos.position)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right text-slate-400 font-medium">{pos.average_price}¢</TableCell>
                    <TableCell className="text-right font-bold text-white">{pos.current_price ? pos.current_price + '¢' : '—'}</TableCell>
                    <TableCell className="text-right pr-6 font-bold text-slate-300">
                      ${(pos.total_traded / 100).toFixed(2)}
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
