import { Shield, ShieldOff, AlertTriangle, Info } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useUserSettings } from "@/hooks/useSupabaseData";
import { useState } from "react";

export default function AgentCommandCenter() {
  const { settings, loading, toggleAutoTrade } = useUserSettings();
  const [toggling, setToggling] = useState(false);

  const isActive = settings?.auto_trade_enabled ?? false;

  const handleToggle = async (checked: boolean) => {
    setToggling(true);
    await toggleAutoTrade(checked);
    setToggling(false);
  };

  if (loading) {
    return (
      <div className="bg-card rounded-lg border border-border p-6 animate-pulse">
        <div className="h-5 bg-muted rounded w-48 mb-4" />
        <div className="h-10 bg-muted rounded w-full" />
      </div>
    );
  }

  return (
    <div className={`bg-card rounded-lg border p-6 transition-colors ${isActive ? "border-profit/30 border-glow-profit" : "border-loss/30 border-glow-loss"}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {isActive ? (
            <Shield className="w-6 h-6 text-profit" />
          ) : (
            <ShieldOff className="w-6 h-6 text-loss" />
          )}
          <div>
            <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
              Agent Kill Switch
              <Tooltip>
                <TooltipTrigger asChild>
                  <Info className="w-4 h-4 text-muted-foreground hover:text-foreground cursor-help transition-colors" />
                </TooltipTrigger>
                <TooltipContent className="max-w-[250px]">
                  <p className="text-xs">Master toggle for the AI strategy. When LIVE, the CIO agent is authorized to execute trades. When OFF, the agent operates in read-only analysis mode.</p>
                </TooltipContent>
              </Tooltip>
            </h3>
            <p className="text-sm text-muted-foreground">
              {isActive ? "Agent is actively trading" : "Agent is offline — no trades will execute"}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <span className={`text-xs font-mono font-bold uppercase tracking-widest ${isActive ? "text-profit animate-pulse-glow" : "text-loss"}`}>
            {isActive ? "LIVE" : "OFF"}
          </span>
          <Switch
            checked={isActive}
            onCheckedChange={handleToggle}
            disabled={toggling}
            className="data-[state=checked]:bg-profit data-[state=unchecked]:bg-loss"
          />
        </div>
      </div>

      {settings?.max_daily_drawdown && (
        <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground border-t border-border pt-3">
          <AlertTriangle className="w-3.5 h-3.5 text-warn" />
          <span>Max daily drawdown: <span className="font-mono text-warn">{(settings.max_daily_drawdown * 100).toFixed(1)}%</span></span>
          <Tooltip>
            <TooltipTrigger asChild>
              <Info className="w-3.5 h-3.5 cursor-help" />
            </TooltipTrigger>
            <TooltipContent className="max-w-[250px]">
              <p className="text-xs">If the portfolio drops by this percentage in a single day, the kill switch auto-engages to protect capital.</p>
            </TooltipContent>
          </Tooltip>
        </div>
      )}
    </div>
  );
}
