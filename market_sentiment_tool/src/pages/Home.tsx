import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { TrendingUp, Wallet, ArrowUpRight, Activity } from "lucide-react";

// Mock Data for Equity Curve
const chartData = [
  { day: "01", equity: 10000 }, { day: "05", equity: 10800 },
  { day: "10", equity: 11200 }, { day: "15", equity: 10900 },
  { day: "20", equity: 12500 }, { day: "25", equity: 14100 },
  { day: "30", equity: 15400 }
];

// Mock Data for Open Positions
const openPositions = [
  { id: 1, market: "Will Bitcoin exceed $100k by March?", type: "CRYPTO", side: "YES", shares: 450, avg: 41, cur: 58, pnl: "+$76.50", status: "Winning" },
  { id: 2, market: "Will the Fed cut rates in May?", type: "MACRO", side: "NO", shares: 1200, avg: 22, cur: 18, pnl: "-$48.00", status: "Losing" },
  { id: 3, market: "Will Miami hit 90°F this week?", type: "WEATHER", side: "YES", shares: 300, avg: 65, cur: 80, pnl: "+$45.00", status: "Winning" },
  { id: 4, market: "Lakers vs Celtics (Spread -4.5)", type: "SPORTS", side: "YES", shares: 80, avg: 50, cur: 50, pnl: "$0.00", status: "Neutral" },
];

export default function Home() {
  return (
    <div className="p-8 max-w-[1400px] mx-auto space-y-8 animate-in fade-in duration-500">
      
      <div className="flex flex-col gap-1">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">Portfolio Overview</h1>
        <p className="text-slate-500">Welcome back. Your automated engines are currently tracking 4 active partitions.</p>
      </div>

      {/* Top Row: Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="shadow-sm border-slate-200">
          <CardHeader className="flex flex-row items-center justify-between pb-2 bg-slate-50/50">
            <CardTitle className="text-sm font-semibold text-slate-500 uppercase tracking-wider">Total Value</CardTitle>
            <Wallet className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent className="pt-4">
            <div className="text-3xl font-bold tracking-tight text-slate-900">$15,400.00</div>
            <p className="text-sm text-slate-500 mt-2 flex items-center gap-1">
              <span className="text-emerald-500 font-medium flex items-center"><ArrowUpRight className="h-3 w-3 mr-0.5"/> 24%</span> from last month
            </p>
          </CardContent>
        </Card>
        <Card className="shadow-sm border-slate-200">
          <CardHeader className="flex flex-row items-center justify-between pb-2 bg-slate-50/50">
            <CardTitle className="text-sm font-semibold text-slate-500 uppercase tracking-wider">Daily PnL</CardTitle>
            <TrendingUp className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent className="pt-4">
            <div className="text-3xl font-bold tracking-tight text-emerald-500">+$342.50</div>
            <p className="text-sm text-slate-500 mt-2 flex items-center gap-1">
              Live unrealized gains across 4 open markets
            </p>
          </CardContent>
        </Card>
        <Card className="shadow-sm border-slate-200">
          <CardHeader className="flex flex-row items-center justify-between pb-2 bg-slate-50/50">
            <CardTitle className="text-sm font-semibold text-slate-500 uppercase tracking-wider">Available Cash</CardTitle>
            <Activity className="h-4 w-4 text-emerald-500" />
          </CardHeader>
          <CardContent className="pt-4">
            <div className="text-3xl font-bold tracking-tight text-slate-900">$2,100.00</div>
            <p className="text-sm text-slate-500 mt-2">
              Ready to deploy. Searching for edges...
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Middle Row: Equity Curve */}
      <Card className="shadow-sm border-slate-200">
        <CardHeader className="bg-slate-50/50 border-b border-slate-100">
          <CardTitle>30-Day Equity Curve</CardTitle>
          <CardDescription>Simulated backtest combined with live forward-tracking.</CardDescription>
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
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
              <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{fill: '#64748b'}} dy={10} />
              <YAxis axisLine={false} tickLine={false} tickFormatter={(val) => `$${val/1000}k`} tick={{fill: '#64748b'}} dx={-10} />
              <Tooltip 
                contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)' }}
                formatter={(value: number) => [`$${value.toLocaleString()}`, "Equity"]}
                labelStyle={{ color: '#64748b', fontWeight: 600, marginBottom: '4px' }}
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
      <Card className="shadow-sm border-slate-200">
        <CardHeader className="bg-slate-50/50 border-b border-slate-100">
          <CardTitle>Live Open Positions</CardTitle>
          <CardDescription>Active Kalshi contracts managed by the automated engine.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader className="bg-slate-50/50">
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-[300px] pl-6">Market</TableHead>
                <TableHead>Subsystem</TableHead>
                <TableHead>Side</TableHead>
                <TableHead className="text-right">Shares</TableHead>
                <TableHead className="text-right">Avg Price</TableHead>
                <TableHead className="text-right">Current</TableHead>
                <TableHead className="text-right pr-6">Unrealized PnL</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {openPositions.map((pos) => (
                <TableRow key={pos.id} className="cursor-pointer hover:bg-slate-50 transition-colors">
                  <TableCell className="font-semibold text-slate-900 pl-6">{pos.market}</TableCell>
                  <TableCell>
                    <Badge variant="secondary" className="bg-slate-100 text-slate-600 hover:bg-slate-200">
                      {pos.type}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge className={pos.side === "YES" ? "bg-emerald-500 hover:bg-emerald-600" : "bg-rose-500 hover:bg-rose-600"}>
                      {pos.side}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-medium">{pos.shares.toLocaleString()}</TableCell>
                  <TableCell className="text-right text-slate-600 font-medium">{pos.avg}¢</TableCell>
                  <TableCell className="text-right font-bold text-slate-900">{pos.cur}¢</TableCell>
                  <TableCell className={`text-right pr-6 font-bold ${pos.status === 'Winning' ? 'text-emerald-500' : pos.status === 'Losing' ? 'text-rose-500' : 'text-slate-400'}`}>
                    {pos.pnl}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

    </div>
  );
}
