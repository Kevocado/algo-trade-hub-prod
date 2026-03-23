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
  const ncaaEdges = sportsEdges.filter(e => e.edge_type === 'SPORTS' && e.title?.includes("NCAA"));

  return (
    <div className="p-8 max-w-[1400px] mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Sports Analytics Desk</h1>
        <p className="text-muted-foreground mt-2">Robust multi-model parsing for Football, NBA, NCAA, and F1 props.</p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="FOOTBALL">Football (Poison/FPL)</TabsTrigger>
          <TabsTrigger value="NBA">Basketball (NBA Props)</TabsTrigger>
          <TabsTrigger value="NCAA">March Madness</TabsTrigger>
          <TabsTrigger value="F1">Motorsport (F1 Telemetry)</TabsTrigger>
        </TabsList>

        <FilterBar 
          options={activeTab === 'FOOTBALL' ? ["Premier League", "La Liga", "Champions League"] : []}
          activeFilter={leagueFilter}
          onFilterChange={setLeagueFilter}
        />

        <TabsContent value="FOOTBALL" className="space-y-6">
          {fplLoading || edgesLoading ? (
             <Skeleton className="h-[300px] w-full rounded-xl" />
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
          {edgesLoading ? <Skeleton className="h-[300px] w-full rounded-xl" /> : nbaEdges.length === 0 ? (
             <div className="flex flex-col h-64 items-center justify-center text-muted-foreground border rounded-lg border-dashed bg-muted/10">
               <p>No active NBA player prop edges found.</p>
            </div>
          ) : gridOrList(nbaEdges, "NBA")}
        </TabsContent>

        <TabsContent value="NCAA" className="space-y-6">
          {edgesLoading ? <Skeleton className="h-[300px] w-full rounded-xl" /> : ncaaEdges.length === 0 ? (
             <div className="flex flex-col h-64 items-center justify-center text-muted-foreground border rounded-lg border-dashed bg-muted/10">
               <p>No active NCAA tournament games found.</p>
            </div>
          ) : gridOrList(ncaaEdges, "NCAA")}
        </TabsContent>

        <TabsContent value="F1" className="space-y-6">
           {edgesLoading ? <Skeleton className="h-[300px] w-full rounded-xl" /> : f1Edges.length === 0 ? (
             <div className="flex flex-col h-64 items-center justify-center text-muted-foreground border rounded-lg border-dashed bg-muted/10">
               <p>No active F1 telemetry signals generated.</p>
            </div>
          ) : gridOrList(f1Edges, "F1")}
        </TabsContent>

      </Tabs>
    </div>
  );

  function gridOrList(edges: any[], sport: string) {
    return (
      <div className="grid grid-cols-1 xl:grid-cols-2 2xl:grid-cols-3 gap-6">
        {edges.map(opt => {
           const hasMarket = opt.market_prob > 0;
           return (
           <Card key={opt.id} className="overflow-hidden shadow-sm flex flex-col hover:border-primary/50 transition-colors">
             <CardHeader className="bg-muted/10 pb-4 border-b">
                <div className="flex justify-between items-start mb-2">
                    <Badge variant="outline" className="text-[10px] tracking-wider font-bold uppercase">{sport}</Badge>
                    <div className="text-right">
                        <div className="text-[10px] text-muted-foreground uppercase font-bold tracking-widest">Model Win Prob</div>
                        <div className="font-bold text-primary text-2xl leading-none mt-1">{(opt.our_prob * 100).toFixed(1)}%</div>
                    </div>
                </div>
                <CardTitle className="text-lg leading-tight mt-2">{opt.title || opt.market_title}</CardTitle>
             </CardHeader>
             
             <CardContent className="pt-5 flex-1 space-y-4">
                {opt.raw_payload?.away_logo && opt.raw_payload?.home_logo && (
                    <div className="flex justify-center items-center gap-6 py-2">
                        <img src={opt.raw_payload.away_logo} className="w-16 h-16 object-contain drop-shadow-md" alt="Away Logo" />
                        <span className="text-muted-foreground/50 font-black italic text-xl">VS</span>
                        <img src={opt.raw_payload.home_logo} className="w-16 h-16 object-contain drop-shadow-md" alt="Home Logo" />
                    </div>
                )}
                
                {!hasMarket ? (
                    <div className="w-full text-center p-4 mt-2 bg-muted/30 border border-dashed border-muted-foreground/30 rounded-lg text-muted-foreground text-sm font-semibold tracking-wide uppercase">
                        ⏳ Awaiting Kalshi Market
                    </div>
                ) : (
                    <div className="space-y-2 mt-2 p-4 bg-muted/10 rounded-lg border">
                        <div className="flex justify-between text-xs font-bold mb-1 uppercase tracking-wider">
                            <span className="text-primary">Model: {(opt.our_prob * 100).toFixed(1)}%</span>
                            <span className="text-slate-500">Market: {(opt.market_prob * 100).toFixed(1)}¢</span>
                        </div>
                        <div className="relative h-2.5 rounded-full w-full bg-secondary overflow-hidden shadow-inner">
                           <div className="absolute top-0 left-0 h-full bg-slate-400/50" style={{ width: `${opt.market_prob * 100}%` }} />
                           <div className="absolute top-0 left-0 h-full bg-primary shadow-[0_0_10px_rgba(255,255,255,0.3)] transition-all" style={{ width: `${opt.our_prob * 100}%` }} />
                        </div>
                    </div>
                )}
             </CardContent>
             
             <ErrorBoundary><SquadVisualizer sport={sport} payload={opt.raw_payload} /></ErrorBoundary>
           </Card>
           );
        })}
      </div>
    );
  }
}
