import { useState, useMemo } from "react";
import { useKalshiEdges, useFPLOptimizations } from "@/hooks/useSupabaseData";
import { Trophy, Coins, Target, Users, AlertCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { FilterBar } from "@/components/FilterBar";
import { ErrorBoundary } from "@/components/ErrorBoundary";

// Robust JSON visualizer
const SquadVisualizer = ({ payload, sport }: { payload: any, sport: string }) => {
  if (!payload || typeof payload !== 'object') {
    return <div className="p-4 text-muted-foreground text-sm italic">Payload malformed or missing.</div>;
  }

  if (sport === 'FOOTBALL') {
    // If it's a raw Kalshi edge payload for football
    if (payload.match) {
        return (
          <div className="p-4 bg-muted/20 border-t">
            <h4 className="font-semibold mb-2">{payload.match}</h4>
            <div className="grid grid-cols-2 gap-4 text-sm">
                <div>Model Prob: <span className="font-bold text-primary">{payload.model_probability}%</span></div>
                <div>Market: <span className="font-bold">{payload.kalshi_price}¢</span></div>
                <div className="col-span-2 text-muted-foreground">Prediction: {payload.prediction}</div>
            </div>
          </div>
        );
    }
    // FPL Optimization Squad payload
    const squad = payload.starting_xi || [];
    if (squad.length === 0) return <div className="p-4 text-sm">Squad data missing</div>;

    return (
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="bg-muted/50 text-xs text-muted-foreground uppercase font-semibold border-b">
            <tr>
              <th className="px-6 py-4">Player</th>
              <th className="px-6 py-4">Pos</th>
              <th className="px-6 py-4">Team</th>
              <th className="px-6 py-4 text-right pr-8">xP</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {squad.map((player: any, idx: number) => (
              <tr key={idx} className="hover:bg-muted/30">
                <td className="px-6 py-4 font-medium">{player.name || "Unknown"}</td>
                <td className="px-6 py-4"><Badge variant="outline">{player.position || "-"}</Badge></td>
                <td className="px-6 py-4 text-muted-foreground">{player.team || "-"}</td>
                <td className="px-6 py-4 text-right pr-8 font-bold text-primary">{(player.xP || 0).toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (sport === 'NBA' || sport === 'F1') {
    // Render robustly by just mapping the keys if structure is unknown, or format if known
    return (
      <div className="p-4 grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm bg-muted/10 border-t">
        {Object.entries(payload).map(([k, v]) => (
          <div key={k} className="flex justify-between items-center border-b border-border/50 pb-2">
            <span className="text-muted-foreground capitalize">{k.replace(/_/g, " ")}</span>
            <span className="font-medium text-foreground text-right">{String(v)}</span>
          </div>
        ))}
      </div>
    );
  }

  return <div className="p-4">Unsupported sport visualizer.</div>
};

export default function SportsDesk() {
  const { edges: sportsEdges, loading: edgesLoading } = useKalshiEdges();
  const { optimizations: fplData, loading: fplLoading } = useFPLOptimizations();
  
  const [activeTab, setActiveTab] = useState("FOOTBALL");
  const [leagueFilter, setLeagueFilter] = useState<string | null>(null);

  const footballEdges = sportsEdges.filter(e => e.edge_type === 'SPORTS' && (e.title?.includes("Football") || e.title?.includes("Premier League")));
  const nbaEdges = sportsEdges.filter(e => e.edge_type === 'SPORTS' && e.title?.includes("NBA"));
  const f1Edges = sportsEdges.filter(e => e.edge_type === 'SPORTS' && e.title?.includes("F1"));

  return (
    <div className="p-8 max-w-[1400px] mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Sports Analytics Desk</h1>
        <p className="text-muted-foreground mt-2">Robust multi-model parsing for Football, NBA, and F1 props.</p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="FOOTBALL">Football (Poison/FPL)</TabsTrigger>
          <TabsTrigger value="NBA">Basketball (NBA Props)</TabsTrigger>
          <TabsTrigger value="F1">Motorsport (F1 Telemetry)</TabsTrigger>
        </TabsList>

        <FilterBar 
          options={activeTab === 'FOOTBALL' ? ["Premier League", "La Liga", "Champions League"] : []}
          activeFilter={leagueFilter}
          onFilterChange={setLeagueFilter}
        />

        <TabsContent value="FOOTBALL" className="space-y-6">
          {fplLoading || edgesLoading ? (
            <div className="space-y-4">
              <Skeleton className="h-[300px] w-full rounded-xl" />
              <Skeleton className="h-[300px] w-full rounded-xl" />
            </div>
          ) : fplData.length === 0 && footballEdges.length === 0 ? (
            <div className="flex flex-col h-64 items-center justify-center text-muted-foreground border rounded-lg border-dashed bg-muted/10">
              <AlertCircle className="w-8 h-8 mb-4 opacity-50" />
               <p>No football predictions or lineups currently available.</p>
            </div>
          ) : (
            <>
              {footballEdges.map((opt) => (
                <Card key={opt.id} className="overflow-hidden border-border shadow-sm">
                  <CardHeader className="bg-primary/5 pb-4"><CardTitle className="text-lg">{opt.title || opt.market_title}</CardTitle></CardHeader>
                  <ErrorBoundary><SquadVisualizer sport="FOOTBALL" payload={opt.raw_payload} /></ErrorBoundary>
                </Card>
              ))}
              {fplData.map((opt) => (
                <Card key={opt.id} className="overflow-hidden border-border shadow-sm">
                  <CardHeader className="bg-primary/5 pb-4"><CardTitle className="text-lg">FPL Optimizer ({opt.strategy})</CardTitle></CardHeader>
                  <ErrorBoundary><SquadVisualizer sport="FOOTBALL" payload={opt.squad_json} /></ErrorBoundary>
                </Card>
              ))}
            </>
          )}
        </TabsContent>

        <TabsContent value="NBA" className="space-y-6">
          {edgesLoading ? (
            <Skeleton className="h-[300px] w-full rounded-xl" />
          ) : nbaEdges.length === 0 ? (
             <div className="flex flex-col h-64 items-center justify-center text-muted-foreground border rounded-lg border-dashed bg-muted/10">
              <AlertCircle className="w-8 h-8 mb-4 opacity-50" />
               <p>No active NBA player prop edges found.</p>
            </div>
          ) : (
            gridOrList(nbaEdges, "NBA")
          )}
        </TabsContent>

        <TabsContent value="F1" className="space-y-6">
           {edgesLoading ? (
            <Skeleton className="h-[300px] w-full rounded-xl" />
          ) : f1Edges.length === 0 ? (
             <div className="flex flex-col h-64 items-center justify-center text-muted-foreground border rounded-lg border-dashed bg-muted/10">
              <AlertCircle className="w-8 h-8 mb-4 opacity-50" />
               <p>No active F1 telemetry signals generated.</p>
            </div>
          ) : (
            gridOrList(f1Edges, "F1")
          )}
        </TabsContent>

      </Tabs>
    </div>
  );

  function gridOrList(edges: any[], sport: string) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {edges.map(opt => (
           <Card key={opt.id} className="overflow-hidden shadow-sm">
             <CardHeader className="bg-primary/5 pb-4"><CardTitle className="text-lg">{opt.title}</CardTitle></CardHeader>
             <ErrorBoundary><SquadVisualizer sport={sport} payload={opt.raw_payload} /></ErrorBoundary>
           </Card>
        ))}
      </div>
    );
  }
}
