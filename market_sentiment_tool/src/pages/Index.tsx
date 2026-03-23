import { useAgentLogs } from "@/hooks/useSupabaseData";
import { Terminal, Activity, ShieldAlert, Cpu } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function Index() {
  const { logs, loading } = useAgentLogs();

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Swarm War Room</h1>
          <p className="text-muted-foreground mt-2">Live telemetry from the autonomous quant orchestration swarm.</p>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 bg-green-500/10 text-green-500 rounded-full text-sm font-medium border border-green-500/20">
          <Activity className="w-4 h-4 animate-pulse" />
          Swarm Active
        </div>
      </div>

      <Card className="border-border bg-card shadow-sm overflow-hidden">
        <CardHeader className="border-b bg-muted/40 py-4">
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <Terminal className="w-4 h-4 text-primary" />
            Agent Activity Logs
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="h-[600px] overflow-y-auto bg-black/95 p-4 font-mono text-sm">
            {loading ? (
              <div className="text-muted-foreground flex items-center gap-2">
                <Cpu className="w-4 h-4 animate-spin" /> Booting agent streams...
              </div>
            ) : logs.length === 0 ? (
              <div className="text-muted-foreground">Awaiting agent transmissions...</div>
            ) : (
              <div className="space-y-3">
                {logs.map((log) => (
                  <div key={log.id} className="flex gap-4 p-2 rounded hover:bg-white/5 transition-colors border border-transparent hover:border-white/10">
                    <div className="shrink-0 text-muted-foreground text-xs pt-0.5">
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </div>
                    <div className={`shrink-0 w-20 font-bold text-xs pt-0.5 ${
                      log.log_level === "ERROR" ? "text-red-500" :
                      log.log_level === "WARN" ? "text-yellow-500" :
                      "text-blue-400"
                    }`}>
                      [{log.log_level}]
                    </div>
                    <div>
                      <div className="text-green-400 font-semibold mb-1 flex items-center gap-2">
                        {log.module}
                        {log.log_level === "ERROR" && <ShieldAlert className="w-3 h-3 text-red-500" />}
                      </div>
                      <div className="text-slate-300 leading-relaxed whitespace-pre-wrap">{log.message}</div>
                      {log.reasoning_context && (
                        <pre className="mt-2 text-xs bg-black/50 p-2 rounded border border-white/10 text-slate-400 overflow-x-auto max-w-3xl">
                          {JSON.stringify(log.reasoning_context, null, 2)}
                        </pre>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
