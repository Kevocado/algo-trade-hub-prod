import { useMarketEdges } from "@/hooks/useMarketEdges";
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { CloudLightning, TrendingUp, Globe, AlertCircle, Percent, ArrowRight } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";

export default function KalshiLab() {
  const { edges, loading } = useMarketEdges();

  const filteredEdges = edges.filter(e => 
    ["WEATHER", "MACRO", "CRYPTO"].includes(e.edge_type.toUpperCase())
  );

  const getTypeIcon = (type: string) => {
    switch (type.toUpperCase()) {
      case 'WEATHER': return <CloudLightning className="w-4 h-4 text-sky-500" />;
      case 'CRYPTO': return <TrendingUp className="w-4 h-4 text-amber-500" />;
      case 'MACRO': return <Globe className="w-4 h-4 text-indigo-500" />;
      default: return <AlertCircle className="w-4 h-4 text-slate-500" />;
    }
  };

  const getTypeColor = (type: string) => {
    switch (type.toUpperCase()) {
      case 'WEATHER': return "bg-sky-500/10 text-sky-600 hover:bg-sky-500/20";
      case 'CRYPTO': return "bg-amber-500/10 text-amber-600 hover:bg-amber-500/20";
      case 'MACRO': return "bg-indigo-500/10 text-indigo-600 hover:bg-indigo-500/20";
      default: return "bg-slate-100 text-slate-600";
    }
  };

  if (loading) {
    return (
      <div className="p-8 max-w-[1400px] mx-auto animate-in fade-in duration-500">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900 mb-8">Kalshi Signals Lab</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {[1, 2, 3, 4, 5, 6].map(i => (
            <Card key={i} className="border-slate-200">
              <CardHeader className="gap-2">
                <Skeleton className="h-4 w-24 rounded-full" />
                <Skeleton className="h-12 w-full" />
              </CardHeader>
              <CardContent className="space-y-4">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-8 w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-[1400px] mx-auto space-y-8 animate-in fade-in duration-500">
      <div className="flex flex-col gap-1">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">Kalshi Signals Lab</h1>
        <p className="text-slate-500">Live quantitative edges across Weather, Macro, and Crypto markets.</p>
      </div>

      {filteredEdges.length === 0 ? (
        <div className="flex flex-col items-center justify-center p-24 text-center border-2 border-dashed border-slate-200 rounded-2xl bg-slate-50">
          <AlertCircle className="w-12 h-12 text-slate-300 mb-4" />
          <h3 className="text-lg font-semibold text-slate-900">No active edges found</h3>
          <p className="text-slate-500 mt-1 max-w-sm">The background scanner hasn't detected any profitable discrepancies yet. Waiting for market movement.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {filteredEdges.map(edge => {
            const ourProbPct = (edge.our_prob * 100).toFixed(1);
            const marketProbPct = (edge.market_prob * 100).toFixed(1);
            
            return (
              <Card key={edge.id} className="shadow-sm border-slate-200 hover:border-emerald-500/30 hover:shadow-md transition-all group flex flex-col h-full">
                <CardHeader className="pb-4 bg-slate-50/50 rounded-t-xl flex-none">
                  <div className="flex justify-between items-start gap-4 mb-3">
                    <Badge variant="secondary" className={`font-semibold flex items-center gap-1.5 px-2.5 py-0.5 border-0 ${getTypeColor(edge.edge_type)}`}>
                      {getTypeIcon(edge.edge_type)}
                      {edge.edge_type.toUpperCase()}
                    </Badge>
                    <Badge className="bg-emerald-50 text-emerald-600 border border-emerald-200 hover:bg-emerald-100 flex items-center gap-1 shadow-none">
                      <Percent className="w-3 h-3" />
                      {edge.edge_pct.toFixed(1)} Edge
                    </Badge>
                  </div>
                  <CardTitle className="text-lg leading-snug text-slate-900 group-hover:text-emerald-700 transition-colors line-clamp-3">
                    {edge.market_title || edge.title || 'Unknown Market'}
                  </CardTitle>
                </CardHeader>
                
                <CardContent className="pt-6 flex-1 flex flex-col gap-5">
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm font-medium">
                      <span className="text-slate-600 flex items-center gap-1.5"><TrendingUp className="w-4 h-4 text-emerald-500"/> Our Model</span>
                      <span className="text-slate-900 font-bold">{ourProbPct}%</span>
                    </div>
                    <Progress value={edge.our_prob * 100} className="h-2.5 bg-slate-100" indicatorClassName="bg-emerald-500" />
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between text-sm font-medium">
                      <span className="text-slate-600 flex items-center gap-1.5"><Globe className="w-4 h-4 text-slate-400"/> Kalshi</span>
                      <span className="text-slate-900">{marketProbPct}%</span>
                    </div>
                    <Progress value={edge.market_prob * 100} className="h-2.5 bg-slate-100" indicatorClassName="bg-slate-300" />
                  </div>
                </CardContent>

                <CardFooter className="pt-4 pb-5 border-t border-slate-100 bg-white rounded-b-xl flex-none">
                  <button className="w-full bg-slate-900 hover:bg-slate-800 text-white font-medium py-2.5 rounded-lg flex items-center justify-center gap-2 transition-colors text-sm shadow-sm group-hover:bg-emerald-600">
                    Trade on Kalshi <ArrowRight className="w-4 h-4 opacity-70 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all" />
                  </button>
                </CardFooter>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
