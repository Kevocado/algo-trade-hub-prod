import { TrendingUp, TrendingDown, DollarSign, Info } from "lucide-react";
import { Tooltip as ChartTooltip } from "recharts";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, ResponsiveContainer } from "recharts";
import { usePortfolioHistory } from "@/hooks/useSupabaseData";

const formatTimeShort = (ts: string) => {
    const d = new Date(ts);
    return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
};

const formatCurrency = (val: number) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 }).format(val);

export default function PnLTracker() {
    const { history, loading } = usePortfolioHistory();

    // Create chart data array
    const chartData = history.map((h) => ({
        time: formatTimeShort(h.timestamp || new Date().toISOString()),
        equity: h.total_equity,
        rawTimestamp: h.timestamp,
    }));

    // Calculate metrics
    const currentEquity = chartData.length > 0 ? chartData[chartData.length - 1].equity : 100000;
    const startEquity = chartData.length > 0 ? chartData[0].equity : 100000;
    const changeAmt = currentEquity - startEquity;
    const changePct = startEquity !== 0 ? (changeAmt / startEquity) * 100 : 0;

    const isPositive = changeAmt >= 0;

    return (
        <div className="rounded-lg border border-border bg-card flex flex-col h-full animate-fade-in shadow-lg">
            <div className="px-6 py-4 border-b border-border flex items-center justify-between bg-black/10">
                <div className="flex items-center gap-3">
                    <div className={`p-2 rounded-lg ${isPositive ? 'bg-profit/10' : 'bg-loss/10'}`}>
                        <TrendingUp className={`w-5 h-5 ${isPositive ? 'text-profit glow-profit' : 'text-loss glow-loss'}`} />
                    </div>
                    <div>
                        <h3 className="text-sm font-semibold text-foreground tracking-wide uppercase flex items-center gap-2">
                            Total Equity
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <Info className="w-3.5 h-3.5 text-muted-foreground hover:text-foreground cursor-help transition-colors" />
                                </TooltipTrigger>
                                <TooltipContent className="max-w-[250px] space-y-1">
                                    <p className="font-semibold text-foreground">Equity Curve</p>
                                    <p className="text-xs text-muted-foreground">Live visualization of the portfolio's total liquidation value over time.</p>
                                </TooltipContent>
                            </Tooltip>
                        </h3>
                        <div className="flex items-baseline gap-2">
                            <span className="text-2xl font-bold font-mono tracking-tight text-white">{formatCurrency(currentEquity)}</span>
                            <span className={`text-sm font-mono font-medium ${isPositive ? 'text-profit' : 'text-loss'}`}>
                                {isPositive ? '+' : ''}{formatCurrency(changeAmt)} ({isPositive ? '+' : ''}{changePct.toFixed(2)}%)
                            </span>
                        </div>
                    </div>
                </div>

                {loading && (
                    <div className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-info animate-pulse" />
                        <span className="text-xs font-mono text-muted-foreground uppercase tracking-widest">Loading...</span>
                    </div>
                )}
                {!loading && (
                    <div className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-profit animate-pulse-glow" />
                        <span className="text-xs font-mono text-profit uppercase tracking-widest">Live</span>
                    </div>
                )}
            </div>

            <div className="flex-1 p-6 min-h-[300px] w-full relative">
                {chartData.length < 2 && !loading ? (
                    <div className="absolute inset-0 flex items-center justify-center text-muted-foreground font-mono text-sm">
                        Waiting for more data points...
                    </div>
                ) : (
                    <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                            <defs>
                                <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="5%" stopColor={isPositive ? "hsl(142, 72%, 50%)" : "hsl(0, 84%, 60%)"} stopOpacity={0.4} />
                                    <stop offset="95%" stopColor={isPositive ? "hsl(142, 72%, 50%)" : "hsl(0, 84%, 60%)"} stopOpacity={0} />
                                </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" stroke="hsl(220, 14%, 15%)" vertical={false} />
                            <XAxis
                                dataKey="time"
                                tick={{ fill: "hsl(215, 12%, 50%)", fontSize: 10 }}
                                axisLine={false}
                                tickLine={false}
                                tickMargin={10}
                                minTickGap={30}
                            />
                            <YAxis
                                domain={['auto', 'auto']}
                                tick={{ fill: "hsl(215, 12%, 50%)", fontSize: 10 }}
                                axisLine={false}
                                tickLine={false}
                                tickFormatter={(val) => `$${val.toLocaleString()}`}
                                width={80}
                            />
                            <ChartTooltip
                                contentStyle={{
                                    background: "hsl(220, 18%, 10%)",
                                    border: "1px solid hsl(220, 14%, 18%)",
                                    borderRadius: 8,
                                    color: "hsl(210, 20%, 90%)",
                                    fontSize: 12,
                                    boxShadow: "0 10px 15px -3px rgba(0, 0, 0, 0.5)"
                                }}
                                itemStyle={{ color: "hsl(210, 20%, 90%)", fontWeight: 600, fontFamily: "monospace" }}
                                formatter={(value: number) => [formatCurrency(value), "Equity"]}
                                labelStyle={{ color: "hsl(215, 12%, 50%)", marginBottom: 4 }}
                            />
                            <Area
                                type="monotone"
                                dataKey="equity"
                                stroke={isPositive ? "hsl(142, 72%, 50%)" : "hsl(0, 84%, 60%)"}
                                fill="url(#equityGradient)"
                                strokeWidth={3}
                                animationDuration={300}
                                isAnimationActive={false} // Disable to prevent glitching on rapid live updates
                            />
                        </AreaChart>
                    </ResponsiveContainer>
                )}
            </div>
        </div>
    );
}
