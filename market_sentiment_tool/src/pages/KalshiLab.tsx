import { useState, useMemo } from "react";
import { useKalshiEdges } from "@/hooks/useSupabaseData";
import { CloudLightning, BarChart3, AlertCircle, Percent, Trophy, ArrowDownWideNarrow, Clock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { FilterBar } from "@/components/FilterBar";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";

export default function KalshiLab() {
  const { edges, loading } = useKalshiEdges();
  const [activeFilter, setActiveFilter] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<"EDGE" | "TIME">("EDGE");

  const getIcon = (type: string) => {
    const t = type.toUpperCase();
    if (t === "WEATHER") return <CloudLightning className="w-5 h-5 text-blue-400" />;
    if (t === "SPORTS") return <Trophy className="w-5 h-5 text-emerald-400" />;
    return <BarChart3 className="w-5 h-5 text-purple-400" />;
  };

  const processedEdges = useMemo(() => {
    let result = edges.filter(e => ['WEATHER', 'MACRO', 'CRYPTO'].includes(e.edge_type?.toUpperCase()));
    if (activeFilter) {
      result = result.filter(e => e.edge_type.toUpperCase() === activeFilter.toUpperCase());
    }
    
    if (sortBy === "EDGE") {
      result.sort((a, b) => b.edge_pct - a.edge_pct);
    } else {
      result.sort((a, b) => new Date(b.discovered_at).getTime() - new Date(a.discovered_at).getTime());
    }
    return result;
  }, [edges, activeFilter, sortBy]);

  return (
    <div className="p-8 max-w-[1600px] mx-auto space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Prediction Lab</h1>
          <p className="text-muted-foreground mt-2">Live high-volume arbitrage edge detection matrix.</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant={sortBy === "EDGE" ? "default" : "outline"} size="sm" onClick={() => setSortBy("EDGE")}>
            <ArrowDownWideNarrow className="w-4 h-4 mr-2" /> Sort by Edge %
          </Button>
          <Button variant={sortBy === "TIME" ? "default" : "outline"} size="sm" onClick={() => setSortBy("TIME")}>
            <Clock className="w-4 h-4 mr-2" /> Sort by Time
          </Button>
        </div>
      </div>

      <FilterBar 
        options={["WEATHER", "MACRO", "CRYPTO"]} 
        activeFilter={activeFilter} 
        onFilterChange={setActiveFilter} 
      />

      {loading ? (
        <div className="columns-1 md:columns-2 xl:columns-3 2xl:columns-4 gap-6 space-y-6">
          {[1, 2, 3, 4, 5, 6].map(i => (
            <Card key={i} className="break-inside-avoid">
              <CardHeader><Skeleton className="h-6 w-3/4" /><Skeleton className="h-4 w-1/2 mt-2" /></CardHeader>
              <CardContent className="space-y-4"><Skeleton className="h-24 w-full" /></CardContent>
            </Card>
          ))}
        </div>
      ) : processedEdges.length === 0 ? (
        <div className="flex flex-col h-64 items-center justify-center text-muted-foreground border rounded-lg border-dashed bg-muted/10">
          <AlertCircle className="w-8 h-8 mb-4 text-muted-foreground/50" />
          <p>No active edges found for this filter.</p>
        </div>
      ) : (
        <div className="columns-1 md:columns-2 lg:columns-3 2xl:columns-4 gap-6 space-y-6">
          {processedEdges.map((edge) => {
            const edgeVal = (edge.edge_pct || edge.edge) * 100; // handle normalized vs raw
            const isMegaEdge = edgeVal > 10;
            const isHighEdge = edgeVal > 5 && !isMegaEdge;
            
            return (
              <Card key={edge.id} className={`break-inside-avoid flex flex-col overflow-hidden border transition-all hover:shadow-lg ${
                isMegaEdge ? "border-emerald-500/50 shadow-[0_0_15px_rgba(16,185,129,0.15)] ring-1 ring-emerald-500/20" : "border-border"
              }`}>
                <CardHeader className={`pb-4 border-b ${isMegaEdge ? "bg-emerald-500/10" : "bg-muted/30"}`}>
                  <div className="flex justify-between items-start mb-3">
                    <div className="flex items-center gap-2">
                      <div className="p-2 bg-background rounded-md shadow-sm border">
                        {getIcon(edge.edge_type)}
                      </div>
                      <span className="text-xs font-bold tracking-wider text-muted-foreground uppercase">{edge.edge_type}</span>
                    </div>
                    <div className={`px-2.5 py-1 rounded-full text-xs font-bold flex items-center gap-1 ${
                      isMegaEdge ? "bg-emerald-500 text-emerald-50" :
                      isHighEdge ? "bg-green-500/20 text-green-600 border border-green-500/30" : "bg-secondary text-secondary-foreground"
                    }`}>
                      EDGE: {edgeVal.toFixed(1)}%
                    </div>
                  </div>
                  <CardTitle className="text-lg leading-tight">{edge.title || edge.market_title}</CardTitle>
                </CardHeader>

                <CardContent className="pt-6 pb-2">
                  <div className="grid grid-cols-2 gap-4 mb-5">
                    <div className="space-y-1">
                      <p className="text-xs text-muted-foreground font-medium uppercase">Model Prob</p>
                      <p className="text-2xl font-bold text-primary">{(edge.our_prob * 100).toFixed(1)}<span className="text-lg">%</span></p>
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs text-muted-foreground font-medium uppercase">Market</p>
                      <p className="text-2xl font-bold text-slate-500">{(edge.market_prob * 100).toFixed(1)}<span className="text-lg">¢</span></p>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="relative h-2 rounded-full w-full bg-secondary overflow-hidden">
                       <div className="absolute top-0 left-0 h-full bg-slate-400/50" style={{ width: `${edge.market_prob * 100}%` }} />
                       <div className="absolute top-0 left-0 h-full bg-primary transition-all shadow-[0_0_10px_rgba(255,255,255,0.5)]" style={{ width: `${edge.our_prob * 100}%` }} />
                    </div>
                  </div>
                </CardContent>

                <CardFooter className="bg-muted/5 border-t py-3 px-6 text-xs text-muted-foreground flex gap-2">
                  <AlertCircle className="w-4 h-4 text-primary/70 shrink-0" />
                  <span className="line-clamp-3">
                    {edge.raw_payload ? JSON.stringify(edge.raw_payload) : (edge.reasoning || "System execution model signal.")}
                  </span>
                </CardFooter>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
