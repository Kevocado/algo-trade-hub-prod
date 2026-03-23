import { usePortfolioState } from "@/hooks/useSupabaseData";
import { Activity, AlertTriangle, BarChart3, Target, Info } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useMemo, forwardRef } from "react";

interface OrderFlowData {
  regime: string;
  skew: number | null;
  poc: number | null;
  divergence: string | null;
}

function parseOrderFlow(openPositions: unknown): OrderFlowData {
  const defaults: OrderFlowData = { regime: "NEUTRAL", skew: null, poc: null, divergence: null };
  if (!openPositions || typeof openPositions !== "object") return defaults;

  const data = openPositions as Record<string, unknown>;
  return {
    regime: typeof data.regime === "string" ? data.regime.toUpperCase() : defaults.regime,
    skew: typeof data.skew === "number" ? data.skew : null,
    poc: typeof data.poc === "number" ? data.poc : null,
    divergence: typeof data.divergence === "string" ? data.divergence : null,
  };
}

const OrderFlowContext = forwardRef<HTMLDivElement, {}>((props, ref) => {
  const { portfolio, loading } = usePortfolioState();

  const flow = useMemo(() => {
    if (!portfolio) return parseOrderFlow(null);
    return parseOrderFlow(portfolio.open_positions);
  }, [portfolio]);

  const isAccumulation = flow.regime === "ACCUMULATION";
  const isDistribution = flow.regime === "DISTRIBUTION";

  const regimeColor = isAccumulation
    ? "text-green-500 border-green-500/40 bg-green-500/5 glow-profit"
    : isDistribution
      ? "text-red-500 border-red-500/40 bg-red-500/5 glow-loss"
      : "text-gray-300 border-gray-600/40 bg-gray-600/10";

  const regimeGlow = isAccumulation ? "glow-profit" : isDistribution ? "glow-loss" : "";

  return (
    <div className="rounded-lg border border-border bg-card p-4 animate-fade-in">
      <div className="flex items-center gap-2 mb-4">
        <Activity className="w-4 h-4 text-info" />
        <h2 className="text-sm font-semibold text-foreground uppercase tracking-wider">Order Flow Context</h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Regime Badge */}
        <div className={`rounded-lg border p-4 flex flex-col items-center justify-center gap-2 transition-all duration-500 ${regimeColor}`}>
          <div className="flex items-center gap-1">
            <span className="text-[10px] font-mono uppercase tracking-widest text-muted-foreground">Market Regime</span>
            <Tooltip>
              <TooltipTrigger asChild>
                <Info className="w-3 h-3 text-muted-foreground hover:text-foreground cursor-help transition-colors" />
              </TooltipTrigger>
              <TooltipContent className="max-w-[220px]">
                <p className="text-xs font-medium">Market Regime</p>
                <p className="text-xs text-muted-foreground">Identifies if institutional volume is accumulating (buying) or distributing (selling) based on aggregate order flow.</p>
              </TooltipContent>
            </Tooltip>
          </div>
          {loading ? (
            <div className="h-7 w-32 bg-muted/30 rounded animate-pulse" />
          ) : (
            <span className={`text-lg font-bold font-mono tracking-wide ${regimeGlow}`}>
              {flow.regime}
            </span>
          )}
        </div>

        {/* Skew & POC */}
        <div className="rounded-lg border border-border bg-secondary/30 p-4 flex gap-4">
          <div className="flex-1 flex flex-col items-center gap-1">
            <div className="flex items-center gap-1 text-muted-foreground">
              <BarChart3 className="w-3 h-3" />
              <span className="text-[10px] font-mono uppercase tracking-widest">Vol Skew</span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Info className="w-3 h-3 text-muted-foreground hover:text-foreground cursor-help transition-colors" />
                </TooltipTrigger>
                <TooltipContent className="max-w-[250px]">
                  <p className="text-xs font-medium">Volume Skewness</p>
                  <p className="text-xs text-muted-foreground">Positive = volume concentrated lower (absorbing sellers). Negative = volume concentrated higher (absorbing buyers).</p>
                </TooltipContent>
              </Tooltip>
            </div>
            {loading ? (
              <div className="h-6 w-16 bg-muted/30 rounded animate-pulse" />
            ) : (
              <span className="text-lg font-bold font-mono text-foreground">
                {flow.skew !== null ? flow.skew.toFixed(2) : "—"}
              </span>
            )}
          </div>
          <div className="w-px bg-border" />
          <div className="flex-1 flex flex-col items-center gap-1">
            <div className="flex items-center gap-1 text-muted-foreground">
              <Target className="w-3 h-3" />
              <span className="text-[10px] font-mono uppercase tracking-widest">POC</span>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Info className="w-3 h-3 text-muted-foreground hover:text-foreground cursor-help transition-colors" />
                </TooltipTrigger>
                <TooltipContent className="max-w-[200px]">
                  <p className="text-xs font-medium">Point of Control</p>
                  <p className="text-xs text-muted-foreground">The specific price level where the highest volume was traded in the current window.</p>
                </TooltipContent>
              </Tooltip>
            </div>
            {loading ? (
              <div className="h-6 w-20 bg-muted/30 rounded animate-pulse" />
            ) : (
              <span className="text-lg font-bold font-mono text-foreground">
                {flow.poc !== null ? `$${flow.poc.toLocaleString()}` : "—"}
              </span>
            )}
          </div>
        </div>

        {/* Divergence Warning */}
        <div className={`rounded-lg border p-4 flex flex-col items-center justify-center gap-2 transition-all duration-500 ${flow.divergence
          ? "border-warn/40 bg-warn/5 border-glow-warn"
          : "border-border bg-secondary/20"
          }`}>
          <div className="flex items-center gap-1 text-muted-foreground">
            <AlertTriangle className={`w-3 h-3 ${flow.divergence ? "text-warn" : ""}`} />
            <span className="text-[10px] font-mono uppercase tracking-widest">Divergence</span>
            <Tooltip>
              <TooltipTrigger asChild>
                <Info className="w-3 h-3 text-muted-foreground hover:text-foreground cursor-help transition-colors" />
              </TooltipTrigger>
              <TooltipContent className="max-w-[220px]">
                <p className="text-xs font-medium">Flow Divergence</p>
                <p className="text-xs text-muted-foreground">Flags high-risk conditions where aggressive buy/sell volume contradicts the actual price movement.</p>
              </TooltipContent>
            </Tooltip>
          </div>
          {loading ? (
            <div className="h-6 w-24 bg-muted/30 rounded animate-pulse" />
          ) : flow.divergence ? (
            <span className="text-sm font-semibold font-mono text-warn animate-pulse-glow glow-warn text-center">
              {flow.divergence}
            </span>
          ) : (
            <span className="text-sm font-mono text-muted-foreground">None</span>
          )}
        </div>
      </div>
    </div>
  );
});

export default OrderFlowContext;
