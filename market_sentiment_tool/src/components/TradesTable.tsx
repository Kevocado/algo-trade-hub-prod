import { useTrades } from "@/hooks/useSupabaseData";
import { ArrowUpRight, ArrowDownRight, Clock } from "lucide-react";

const formatTime = (ts: string | null) => {
  if (!ts) return "—";
  return new Date(ts).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

export default function TradesTable() {
  const { trades, loading } = useTrades();

  return (
    <div className="bg-card rounded-lg border border-border flex flex-col h-full">
      <div className="px-4 py-3 border-b border-border flex items-center gap-2">
        <Clock className="w-4 h-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold text-foreground uppercase tracking-wider">Live Order Flow</h3>
        <span className="ml-auto text-xs font-mono text-muted-foreground">{trades.length} orders</span>
      </div>

      <div className="overflow-auto flex-1 scrollbar-thin">
        {loading ? (
          <div className="p-4 space-y-2">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-8 bg-muted rounded animate-pulse" />
            ))}
          </div>
        ) : trades.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground text-sm">No trades recorded yet</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                <th className="text-left p-3">Time</th>
                <th className="text-left p-3">Symbol</th>
                <th className="text-left p-3">Side</th>
                <th className="text-right p-3">Qty</th>
                <th className="text-right p-3">Price</th>
                <th className="text-right p-3">P&L</th>
                <th className="text-center p-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade) => {
                const isBuy = trade.side?.toUpperCase() === "BUY";
                const pnl = trade.pnl ?? 0;
                const pnlPositive = pnl >= 0;
                return (
                  <tr key={trade.id} className="border-b border-border/50 hover:bg-muted/30 transition-colors">
                    <td className="p-3 font-mono text-xs text-muted-foreground">{formatTime(trade.timestamp)}</td>
                    <td className="p-3 font-mono font-bold text-foreground">{trade.symbol}</td>
                    <td className="p-3">
                      <span className={`inline-flex items-center gap-1 text-xs font-bold ${isBuy ? "text-profit" : "text-loss"}`}>
                        {isBuy ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                        {trade.side?.toUpperCase()}
                      </span>
                    </td>
                    <td className="p-3 text-right font-mono text-foreground">{trade.qty}</td>
                    <td className="p-3 text-right font-mono text-foreground">
                      {trade.execution_price ? `$${Number(trade.execution_price).toFixed(2)}` : "—"}
                    </td>
                    <td className={`p-3 text-right font-mono font-bold ${pnlPositive ? "text-profit" : "text-loss"}`}>
                      {pnl !== 0 ? `${pnlPositive ? "+" : ""}$${pnl.toFixed(2)}` : "—"}
                    </td>
                    <td className="p-3 text-center">
                      <span className={`text-xs font-mono px-2 py-0.5 rounded-full ${
                        trade.status === "FILLED" ? "bg-profit/10 text-profit" :
                        trade.status === "PENDING" ? "bg-warn/10 text-warn" :
                        "bg-muted text-muted-foreground"
                      }`}>
                        {trade.status}
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
