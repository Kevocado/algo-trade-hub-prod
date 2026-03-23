import { useKalshiEdges } from "@/hooks/useSupabaseData";
import { CloudLightning, BarChart3, AlertCircle, Percent } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

export default function KalshiLab() {
  const { edges, loading } = useKalshiEdges();

  const getIcon = (type: string) => {
    if (type === "WEATHER") return <CloudLightning className="w-5 h-5 text-blue-400" />;
    return <BarChart3 className="w-5 h-5 text-purple-400" />;
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Prediction Lab</h1>
        <p className="text-muted-foreground mt-2">Live arbitrage edge detection for Kalshi weather and macro markets.</p>
      </div>

      {loading ? (
        <div className="flex h-32 items-center justify-center text-muted-foreground">Scanning markets...</div>
      ) : edges.length === 0 ? (
        <div className="flex h-32 items-center justify-center text-muted-foreground border rounded-lg border-dashed">No edges detected.</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {edges.map((edge) => {
            const isHighEdge = edge.edge > 5;
            
            return (
              <Card key={edge.id} className="flex flex-col overflow-hidden border-border transition-all hover:shadow-md hover:border-primary/50">
                <CardHeader className="bg-muted/30 pb-4 border-b">
                  <div className="flex justify-between items-start">
                    <div className="flex items-center gap-2">
                      <div className="p-2 bg-background rounded-md shadow-sm border">
                        {getIcon(edge.edge_type)}
                      </div>
                      <span className="text-xs font-bold tracking-wider text-muted-foreground uppercase">{edge.edge_type}</span>
                    </div>
                    <div className={`px-2.5 py-1 rounded-full text-xs font-bold flex items-center gap-1 ${
                      isHighEdge ? "bg-green-500/20 text-green-600 border border-green-500/30" : "bg-secondary text-secondary-foreground"
                    }`}>
                      EDGE:{edge.edge.toFixed(1)}%
                    </div>
                  </div>
                  <CardTitle className="mt-4 text-lg leading-tight">{edge.market_title}</CardTitle>
                </CardHeader>

                <CardContent className="pt-6 space-y-5 flex-1">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1">
                      <p className="text-xs text-muted-foreground font-medium uppercase">Model Prob</p>
                      <p className="text-2xl font-bold text-primary">{edge.model_probability.toFixed(1)}<span className="text-lg">%</span></p>
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs text-muted-foreground font-medium uppercase">Market Price</p>
                      <p className="text-2xl font-bold text-slate-500">{edge.market_price.toFixed(1)}<span className="text-lg">¢</span></p>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between text-xs">
                      <span className="text-muted-foreground">Probability Spread</span>
                      <span className="font-medium text-primary">Δ {(edge.model_probability - edge.market_price).toFixed(1)}</span>
                    </div>
                    <div className="relative h-2 rounded-full w-full bg-secondary overflow-hidden">
                       <div className="absolute top-0 left-0 h-full bg-slate-400/50" style={{ width: `${edge.market_price}%` }} />
                       <div className="absolute top-0 left-0 h-full bg-primary transition-all" style={{ width: `${edge.model_probability}%` }} />
                    </div>
                  </div>
                </CardContent>

                <CardFooter className="bg-muted/10 border-t py-3 px-6 text-xs text-muted-foreground flex gap-2">
                  <AlertCircle className="w-4 h-4 text-primary/70 shrink-0" />
                  <span className="line-clamp-2">{edge.reasoning || "No detailed reasoning provided."}</span>
                </CardFooter>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
