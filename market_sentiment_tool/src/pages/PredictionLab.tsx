import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMarketEdges, KalshiEdge } from "@/hooks/useMarketEdges";
import { Loader2, TrendingUp, Cloud, Globe, Trophy, Brain, ExternalLink, Zap, Activity } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";

const EdgeCard = ({ edge }: { edge: KalshiEdge }) => {
  const getIcon = (type: string) => {
    switch (type) {
      case 'WEATHER': return <Cloud className="w-4 h-4 text-sky-400" />;
      case 'MACRO': return <Globe className="w-4 h-4 text-amber-400" />;
      case 'SPORTS': return <Trophy className="w-4 h-4 text-emerald-400" />;
      default: return <TrendingUp className="w-4 h-4 text-slate-400" />;
    }
  };

  const modelProb = (edge.our_prob * 100).toFixed(1);
  const marketPrice = (edge.market_prob * 100).toFixed(1);
  const edgePct = edge.edge_pct.toFixed(1);

  return (
    <Card className="bg-slate-900/40 border-slate-800 hover:border-emerald-500/50 transition-all duration-300 group overflow-hidden">
      <CardHeader className="pb-3 border-b border-slate-800/50 bg-slate-900/20">
        <div className="flex justify-between items-start">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-md bg-slate-800/50 border border-slate-700">
              {getIcon(edge.edge_type)}
            </div>
            <div>
              <CardTitle className="text-sm font-bold text-slate-100 line-clamp-1">
                {edge.market_title || edge.title || "Untitled Market"}
              </CardTitle>
              <CardDescription className="text-[10px] uppercase tracking-widest text-slate-500 font-semibold mt-0.5">
                {edge.market_id}
              </CardDescription>
            </div>
          </div>
          <Badge variant="outline" className={`
            ${Math.abs(edge.edge_pct) > 15 ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 
              Math.abs(edge.edge_pct) > 10 ? 'bg-amber-500/10 text-amber-400 border-amber-500/30' : 
              'bg-slate-500/10 text-slate-400 border-slate-500/30'}
            px-2 py-0.5 rounded-full text-[10px] font-bold
          `}>
            {edgePct}% EDGE
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="pt-4 space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1">
            <p className="text-[10px] text-slate-500 font-bold uppercase">Our Model</p>
            <p className="text-xl font-black text-white">{modelProb}%</p>
          </div>
          <div className="space-y-1 text-right">
            <p className="text-[10px] text-slate-500 font-bold uppercase">Market Ask</p>
            <p className="text-xl font-black text-slate-300">{marketPrice}¢</p>
          </div>
        </div>

        {edge.ui_reasoning && edge.ai_summary ? (
          <div className="p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/10 space-y-2 relative overflow-hidden">
            <div className="absolute top-0 right-0 p-1 opacity-20">
              <Brain className="w-4 h-4 text-emerald-400" />
            </div>
            <p className="text-[10px] font-bold text-emerald-400 uppercase flex items-center gap-1">
              <Brain className="w-3 h-3" /> AI Reasoning
            </p>
            <p className="text-xs text-slate-300 leading-relaxed italic">
              "{edge.ai_summary}"
            </p>
          </div>
        ) : (
          <div className="p-3 rounded-lg bg-slate-900/40 border border-slate-800 space-y-1">
             <p className="text-[10px] font-bold text-slate-500 uppercase">Analysis</p>
             <p className="text-xs text-slate-400 line-clamp-2 italic">
               Waiting for deep-dive validation...
             </p>
          </div>
        )}

        <div className="flex gap-2 pt-2">
           <button className="flex-1 bg-emerald-500 hover:bg-emerald-400 text-emerald-950 font-bold py-2 rounded-md text-xs transition-colors flex items-center justify-center gap-2">
             <Zap className="w-3 h-3" /> Execute Trade
           </button>
           <button className="p-2 aspect-square bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-md transition-colors group-hover:border-emerald-500/30">
             <ExternalLink className="w-3 h-3 text-slate-400" />
           </button>
        </div>
      </CardContent>
    </Card>
  );
};

export default function PredictionLab() {
  const { edges, loading } = useMarketEdges();
  const [activeTab, setActiveTab] = useState("all");

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-slate-950 gap-4">
        <Loader2 className="w-12 h-12 text-emerald-500 animate-spin" />
        <p className="text-slate-400 font-mono text-sm tracking-tighter animate-pulse text-uppercase">Refreshing Alpha...</p>
      </div>
    );
  }

  const filteredEdges = activeTab === "all" ? edges : edges.filter(e => e.edge_type === activeTab.toUpperCase());

  return (
    <div className="p-8 max-w-[1600px] mx-auto space-y-8 min-h-screen bg-slate-950 text-slate-100">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-900 pb-8">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-4xl font-black tracking-tight text-white uppercase italic">Prediction Lab</h1>
            <Badge className="bg-emerald-500 text-emerald-950 font-bold px-3">BETA</Badge>
          </div>
          <p className="text-slate-400 font-medium">Cross-engine market evaluation & edge discovery engine.</p>
        </div>
        
        <div className="flex items-center gap-6">
          <div className="text-right">
            <p className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">Global Heat</p>
            <p className="text-2xl font-black text-emerald-500">{(edges.reduce((a, b) => a + (b.edge_pct || 0), 0) / (edges.length || 1)).toFixed(2)}%</p>
          </div>
          <div className="h-10 w-px bg-slate-800 hidden md:block" />
          <div className="text-right">
            <p className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">Active Edges</p>
            <p className="text-2xl font-black text-white">{edges.length}</p>
          </div>
        </div>
      </div>

      <Tabs defaultValue="all" className="space-y-8" onValueChange={setActiveTab}>
        <div className="flex flex-col md:flex-row gap-4 items-center justify-between bg-slate-900/20 p-2 rounded-xl border border-slate-900">
          <TabsList className="bg-transparent h-auto p-0 gap-2">
            <TabsTrigger value="all" className="data-[state=active]:bg-emerald-500 data-[state=active]:text-emerald-950 font-bold rounded-lg px-6 py-2 transition-all">ALL</TabsTrigger>
            <TabsTrigger value="macro" className="data-[state=active]:bg-amber-500 data-[state=active]:text-amber-950 font-bold rounded-lg px-6 py-2 transition-all">MACRO</TabsTrigger>
            <TabsTrigger value="sports" className="data-[state=active]:bg-sky-500 data-[state=active]:text-sky-950 font-bold rounded-lg px-6 py-2 transition-all">SPORTS</TabsTrigger>
            <TabsTrigger value="weather" className="data-[state=active]:bg-indigo-500 data-[state=active]:text-indigo-950 font-bold rounded-lg px-6 py-2 transition-all">WEATHER</TabsTrigger>
          </TabsList>

          <div className="flex items-center gap-2 text-[10px] font-bold text-slate-500 uppercase bg-slate-800/50 px-4 py-2 rounded-lg border border-slate-700/50">
             <Activity className="w-3 h-3 text-emerald-500" />
             Live Feed Active
          </div>
        </div>

        <TabsContent value={activeTab} className="m-0 focus-visible:outline-none">
          {filteredEdges.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-32 space-y-4 border-2 border-dashed border-slate-900 rounded-3xl">
              <TrendingUp className="w-12 h-12 text-slate-800" />
              <p className="text-slate-500 font-bold uppercase tracking-tighter">No high-confidence edges detected in {activeTab}</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
              {filteredEdges.map((edge) => (
                <EdgeCard key={edge.id} edge={edge} />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
      
      {/* Risk Disclosure Section */}
      <div className="mt-16 p-6 rounded-2xl bg-slate-900/40 border border-slate-800/60 text-slate-500 text-[10px] uppercase tracking-widest font-bold leading-relaxed">
         ⚠️ High-Frequency Prediction Alpha: Modeling and probability assessments are provided "as-is" for educational and backtesting purposes. Market entry involves significant capital risk. Ensure strict bankroll management (Kelley Criterion recommended).
      </div>
    </div>
  );
}
