import { useAgentLogs } from "@/hooks/useSupabaseData";
import { Terminal, Info } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useEffect, useRef } from "react";

const levelColor = (level: string | null) => {
  switch (level?.toUpperCase()) {
    case "ERROR": return "text-loss";
    case "WARN": case "WARNING": return "text-warn glow-warn";
    case "INFO": return "text-info";
    case "DEBUG": return "text-muted-foreground";
    default: return "text-foreground";
  }
};

const levelBadge = (level: string | null) => {
  const l = level?.toUpperCase() ?? "LOG";
  switch (l) {
    case "ERROR": return "bg-loss/15 text-loss";
    case "WARN": case "WARNING": return "bg-warn/20 text-warn border border-warn/20";
    case "INFO": return "bg-info/15 text-info";
    default: return "bg-muted text-muted-foreground";
  }
};

const QUANT_MODULES = ["lightgbm", "quantengine", "quant", "quant_engine", "orderflow"];
const LLM_MODULES = ["llama.cpp", "llm", "qualitative", "reasoning", "gpt"];

const moduleColor = (mod: string) => {
  const lower = mod.toLowerCase();
  if (lower.includes("quant")) return "text-blue-500";
  if (lower.includes("macro")) return "text-purple-500 glow-purple";
  if (lower.includes("cio")) return "text-orange-500";
  if (QUANT_MODULES.some((q) => lower.includes(q))) return "text-info";
  if (LLM_MODULES.some((q) => lower.includes(q))) return "text-purple glow-purple";
  return "text-muted-foreground";
};

const warnRowBg = (level: string | null) => {
  const l = level?.toUpperCase();
  if (l === "WARN" || l === "WARNING") return "bg-warn/5";
  if (l === "ERROR") return "bg-loss/5";
  return "hover:bg-muted/10";
};

const formatTime = (ts: string | null) => {
  if (!ts) return "00:00:00";
  return new Date(ts).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
};

export default function AgentLogsTerminal() {
  const { logs, loading, status } = useAgentLogs();
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = 0;
    }
  }, [logs]);

  return (
    <div className="bg-terminal rounded-lg border border-border flex flex-col h-full min-h-0 overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center gap-2 shrink-0">
        <Terminal className="w-4 h-4 text-profit" />
        <h3 className="text-sm font-semibold text-foreground uppercase tracking-wider flex items-center gap-2">
          Agent Logs
          <Tooltip>
            <TooltipTrigger asChild>
              <Info className="w-3.5 h-3.5 text-muted-foreground hover:text-foreground cursor-help transition-colors" />
            </TooltipTrigger>
            <TooltipContent className="max-w-[250px] space-y-1">
              <p className="font-semibold text-foreground">Real-Time Event Stream</p>
              <p className="text-xs text-muted-foreground">Monitors the live execution behavior of the autonomous market agents. Blue/Purple tags denote quantitative and LLM evaluation modules.</p>
            </TooltipContent>
          </Tooltip>
        </h3>
        <div className="ml-auto flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full animate-pulse ${status === 'connected' ? 'bg-profit' : status === 'error' ? 'bg-loss' : 'bg-warn'}`} />
          <span className={`text-xs font-mono uppercase ${status === 'connected' ? 'text-profit' : status === 'error' ? 'text-loss' : 'text-warn'}`}>
            {status === 'connected' ? 'streaming' : status}
          </span>
        </div>
      </div>

      <div ref={containerRef} className="overflow-y-auto min-h-0 flex-1 p-3 space-y-1 scrollbar-thin font-mono text-xs">
        {loading ? (
          <div className="space-y-2">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-4 bg-muted/30 rounded animate-pulse" />
            ))}
          </div>
        ) : logs.length === 0 ? (
          <div className="text-muted-foreground text-center py-8">No logs yet</div>
        ) : (
          logs.map((log) => (
            <div key={log.id} className={`flex gap-2 leading-relaxed px-1 rounded animate-fade-in ${warnRowBg(log.log_level)}`}>
              <span className="text-muted-foreground shrink-0">{formatTime(log.timestamp)}</span>
              <span className={`shrink-0 px-1.5 py-0 rounded text-[10px] font-bold uppercase ${levelBadge(log.log_level)}`}>
                {(log.log_level ?? "LOG").toUpperCase().slice(0, 4)}
              </span>
              <div className="flex flex-col gap-1 w-full overflow-hidden">
                <div className="flex gap-2">
                  <span className={`shrink-0 ${moduleColor(log.module)}`}>[{log.module}]</span>
                </div>
                <div className={`whitespace-pre-wrap break-words mt-1 p-2 rounded bg-black/20 ${levelColor(log.log_level)} border border-white/5`}>
                  {log.message}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
