import { useTrades, usePortfolioState } from "@/hooks/useSupabaseData";
import { ArrowUpRight, ArrowDownRight, Activity, Info } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useMemo } from "react";

const formatCurrency = (val: number | null) => {
    if (val === null) return "—";
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 }).format(val);
};

export default function ActivePositions() {
    const { trades, loading: tradesLoading } = useTrades();
    const { portfolio, loading: portfolioLoading } = usePortfolioState();

    // Filter for only active/pending
    const activeTrades = useMemo(() => {
        return trades.filter((t) => t.status === "OPEN" || t.status === "PENDING" || t.status === "ACTIVE");
    }, [trades]);

    // Extract Regime from Portfolio State
    const regime = useMemo(() => {
        if (!portfolio?.open_positions) return "NEUTRAL";
        const pos = portfolio.open_positions as Record<string, any>;
        return (pos.regime || "NEUTRAL").toUpperCase();
    }, [portfolio]);

    const regimeColor =
        regime === "ACCUMULATION" ? "bg-profit/15 text-profit border-profit/30" :
            regime === "DISTRIBUTION" ? "bg-loss/15 text-loss border-loss/30" :
                "bg-muted/20 text-muted-foreground border-border/50";

    return (
        <div className="bg-card rounded-lg border border-border flex flex-col h-full min-h-0 shadow-lg overflow-hidden animate-fade-in">
            <div className="px-6 py-4 border-b border-border flex items-center justify-between bg-black/10">
                <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-accent/10">
                        <Activity className="w-5 h-5 text-accent" />
                    </div>
                    <div>
                        <h3 className="text-sm font-semibold text-foreground tracking-wide uppercase flex items-center gap-2">
                            Active Positions
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <Info className="w-3.5 h-3.5 text-muted-foreground hover:text-foreground cursor-help transition-colors" />
                                </TooltipTrigger>
                                <TooltipContent className="max-w-[250px] space-y-1">
                                    <p className="font-semibold text-foreground">Order Flow Board</p>
                                    <p className="text-xs text-muted-foreground">Displays all live trades pending or currently open within the portfolio. Tracks current position metrics against real-time signals.</p>
                                </TooltipContent>
                            </Tooltip>
                        </h3>
                        <span className="text-xs font-mono text-muted-foreground">{activeTrades.length} open orders</span>
                    </div>
                </div>

                {/* Market Context Badge */}
                <Tooltip>
                    <TooltipTrigger asChild>
                        <div className={`px-3 py-1 rounded border text-xs font-mono font-bold tracking-widest flex items-center gap-2 cursor-help transition-opacity hover:opacity-80 ${regimeColor}`}>
                            <span className="opacity-70 uppercase text-[10px]">Context:</span>
                            {regime}
                        </div>
                    </TooltipTrigger>
                    <TooltipContent>
                        <p className="text-xs">Current live market regime according to the Quant Agent's flow divergence metrics.</p>
                    </TooltipContent>
                </Tooltip>
            </div>

            <div className="overflow-auto flex-1 scrollbar-thin p-0">
                {tradesLoading || portfolioLoading ? (
                    <div className="p-6 space-y-3">
                        {[1, 2, 3].map((i) => (
                            <div key={i} className="h-10 bg-muted/40 rounded animate-pulse" />
                        ))}
                    </div>
                ) : activeTrades.length === 0 ? (
                    <div className="flex flex-col items-center justify-center p-12 text-center h-full">
                        <Activity className="w-8 h-8 text-muted-foreground/30 mb-3" />
                        <span className="text-sm font-medium text-muted-foreground">No active positions</span>
                        <span className="text-xs font-mono text-muted-foreground/60 mt-1">Waiting for quant engine signals...</span>
                    </div>
                ) : (
                    <table className="w-full text-sm">
                        <thead className="bg-muted/10">
                            <tr className="text-[10px] text-muted-foreground uppercase tracking-widest border-b border-border/60">
                                <th className="text-left py-3 px-6 font-medium">Symbol</th>
                                <th className="text-left py-3 px-6 font-medium">Side</th>
                                <th className="text-right py-3 px-6 font-medium">Qty</th>
                                <th className="text-right py-3 px-6 font-medium">Entry</th>
                                <th className="text-right py-3 px-6 font-medium">
                                    <Tooltip>
                                        <TooltipTrigger className="cursor-help flex items-center justify-end gap-1 ml-auto hover:text-foreground transition-colors">
                                            Live P&L
                                        </TooltipTrigger>
                                        <TooltipContent>
                                            <p className="text-xs">Unrealized Profit & Loss dynamically marked-to-market against the latest Alpaca ticks.</p>
                                        </TooltipContent>
                                    </Tooltip>
                                </th>
                                <th className="text-right py-3 px-6 font-medium">
                                    <Tooltip>
                                        <TooltipTrigger className="cursor-help flex items-center justify-end gap-1 ml-auto hover:text-foreground transition-colors">
                                            Context
                                            <Info className="w-3 h-3" />
                                        </TooltipTrigger>
                                        <TooltipContent>
                                            <p className="text-xs">Individual asset's order flow regime context (Accumulation/Distribution).</p>
                                        </TooltipContent>
                                    </Tooltip>
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {activeTrades.map((trade) => {
                                const isBuy = trade.side?.toUpperCase() === "BUY";
                                const pnl = trade.pnl ?? 0;
                                const pnlPositive = pnl >= 0;

                                return (
                                    <tr key={trade.id} className="border-b border-border/40 hover:bg-muted/20 transition-colors group">
                                        <td className="py-3 px-6 font-mono font-bold text-foreground group-hover:text-accent transition-colors">
                                            {trade.symbol}
                                        </td>
                                        <td className="py-3 px-6">
                                            <span className={`inline-flex items-center gap-1.5 text-xs font-bold px-2 py-0.5 rounded ${isBuy ? "bg-profit/10 text-profit" : "bg-loss/10 text-loss"}`}>
                                                {isBuy ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                                                {trade.side?.toUpperCase()}
                                            </span>
                                        </td>
                                        <td className="py-3 px-6 text-right font-mono text-foreground font-medium">{trade.qty}</td>
                                        <td className="py-3 px-6 text-right font-mono text-foreground/80">
                                            {formatCurrency(trade.execution_price)}
                                        </td>
                                        <td className={`py-3 px-6 text-right font-mono font-bold ${pnlPositive ? "text-profit glow-profit" : "text-loss glow-loss"}`}>
                                            {pnl !== 0 ? `${pnlPositive ? "+" : ""}${formatCurrency(pnl)}` : "—"}
                                        </td>
                                        <td className="py-3 px-6 text-right">
                                            <span className={`inline-flex items-center text-[10px] font-bold px-2 py-0.5 rounded border uppercase tracking-widest ${regimeColor}`}>
                                                {regime}
                                            </span>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    );
}
