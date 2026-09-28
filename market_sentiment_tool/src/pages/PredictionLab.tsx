import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMarketEdges, KalshiEdge } from "@/hooks/useMarketEdges";
import { Loader2, TrendingUp, Cloud, Globe, Trophy, Brain, ExternalLink, Zap, Activity, AlertTriangle } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { GateBadge } from "@/components/GateBadge";
import WithheldEdgesNotice from "@/components/WithheldEdgesNotice";
import {
  NOT_MEASURED,
  edgePctNumber,
  edgePctText,
  edgeReason,
  meanEdgePct,
  meanEdgeReason,
  probReason,
  probText,
} from "@/lib/edgeFigures";
import { enforceDisplayOnlyPartition } from "@/lib/displayOnlyEngines";
import { TIER_LABELS, isExecutableSportsEdge, rejectReasonLabel, sportsTierOf } from "@/lib/sportsEdges";

const TIER_BADGE_CLASS: Record<string, string> = {
  top_pick: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  flagged: "bg-amber-500/10 text-amber-400 border-amber-500/30",
  unreviewed: "bg-slate-500/10 text-slate-400 border-slate-500/30",
  filtered: "bg-rose-500/10 text-rose-400 border-rose-500/30",
};

const EdgeCard = ({ edge }: { edge: KalshiEdge }) => {
  // Sports edges carry a reviewer tier in raw_payload. A candidate the filter REJECTED must not
  // be rendered like a Top Pick behind an "Execute Trade" button.
  const sportsTier = sportsTierOf(edge);
  const executable = isExecutableSportsEdge(sportsTier);
  const rejectReasons: string[] = Array.isArray(edge.raw_payload?.reject_reasons)
    ? edge.raw_payload.reject_reasons
    : [];
  const getIcon = (type: string) => {
    switch (type) {
      case 'WEATHER': return <Cloud className="w-4 h-4 text-sky-400" />;
      case 'MACRO': return <Globe className="w-4 h-4 text-amber-400" />;
      case 'SPORTS': return <Trophy className="w-4 h-4 text-emerald-400" />;
      default: return <TrendingUp className="w-4 h-4 text-slate-400" />;
    }
  };

  // The three figures are `number | null`: `useMarketEdges` no longer defaults a missing one to 0,
  // because a model probability of 0 is a prediction and an edge of 0.0 is a measurement, and
  // neither is what a row that recorded nothing is. So each one formats through `edgeFigures` and
  // a row that has none shows a dash and says why, rather than a confident number nobody measured.
  const modelProb = probText(edge.our_prob);
  const marketPrice = probText(edge.market_prob, "cents");
  const edgePct = edgePctText(edge.edge_pct);
  // The badge's colour is a claim too. A row with no edge recorded is not a "below 10%" row; it is
  // an unmeasured one, so it takes the muted class rather than the lowest band, which would be a
  // verdict on a number that does not exist.
  const edgeBand = !edgePctNumber(edge.edge_pct)
    ? "bg-slate-500/10 text-slate-400 border-slate-500/30"
    : Math.abs(edge.edge_pct) > 15 ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
    : Math.abs(edge.edge_pct) > 10 ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
    : 'bg-slate-500/10 text-slate-400 border-slate-500/30';

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
          <div className="flex flex-col items-end gap-1">
          <Badge variant="outline" className={`
            ${edgeBand}
            px-2 py-0.5 rounded-full text-[10px] font-bold
          `} title={edgeReason(edge.edge_pct) ?? undefined}>
            {edgePct === NOT_MEASURED ? "EDGE —" : `${edgePct} EDGE`}
          </Badge>
          <GateBadge edge={edge} />
          {sportsTier && (
            <Badge
              variant="outline"
              title={sportsTier === "filtered"
                ? "Rejected by the sports candidate filter. Shown for transparency, not tradeable."
                : "Sports reviewer tier"}
              className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${
                TIER_BADGE_CLASS[sportsTier] ?? TIER_BADGE_CLASS.unreviewed
              }`}
            >
              {TIER_LABELS[sportsTier]}
            </Badge>
          )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-4 space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1">
            <p className="text-[10px] text-slate-500 font-bold uppercase">Our Model</p>
            <p className="text-xl font-black text-white" title={probReason(edge.our_prob) ?? undefined}>
              {modelProb}
            </p>
          </div>
          <div className="space-y-1 text-right">
            <p className="text-[10px] text-slate-500 font-bold uppercase">Market Ask</p>
            <p className="text-xl font-black text-slate-300" title={probReason(edge.market_prob, "cents") ?? undefined}>
              {marketPrice}
            </p>
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
           {executable ? (
             <button className="flex-1 bg-emerald-500 hover:bg-emerald-400 text-emerald-950 font-bold py-2 rounded-md text-xs transition-colors flex items-center justify-center gap-2">
               <Zap className="w-3 h-3" /> Execute Trade
             </button>
           ) : (
             <p className="flex-1 bg-rose-500/5 border border-rose-500/30 text-rose-300 font-bold py-2 px-2 rounded-md text-xs text-center">
               Rejected by candidate filter — not tradeable
               {rejectReasons.length > 0 && (
                 <span className="block font-normal normal-case text-rose-400/80 mt-0.5">
                   {rejectReasons.map(rejectReasonLabel).join(" · ")}
                 </span>
               )}
             </p>
           )}
           <button className="p-2 aspect-square bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-md transition-colors group-hover:border-emerald-500/30">
             <ExternalLink className="w-3 h-3 text-slate-400" />
           </button>
        </div>
      </CardContent>
    </Card>
  );
};

export default function PredictionLab() {
  const { edges: readEdges, withheld: readWithheld, loading, error: edgesError, truncated } = useMarketEdges();
  const [activeTab, setActiveTab] = useState("all");

  // The hook already withholds display-only rows, and that is where the standing rule lives. The
  // same rule is applied again here because THIS is the last line before `EdgeCard`, which prints
  // `{edge_pct}% EDGE` for anything in `edges`: a `cpi_nowcast` row that reached it would claim a
  // 20.0% edge on an engine that has none. Anything display-only that arrives in the opportunity
  // bucket -- from a stub, a new caller, a hook regression -- is pulled back and shown as withheld.
  const { edges, withheld } = enforceDisplayOnlyPartition<KalshiEdge>(readEdges, readWithheld);

  // The board's headline average. Over the rows that recorded an edge, and null when none did --
  // the old `reduce(... || 0) / (length || 1)` counted every unmeasured row as a zero in the sum
  // while still counting it in the denominator, so a board could go quiet and its headline number
  // would slide towards 0.00% because data was missing, and an empty board reported a confident
  // 0.00% for having no edges at all.
  const heat = meanEdgePct(edges);
  const heatReason = edgesError ?? meanEdgeReason(heat);

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
            {/* A failed read has no mean, and neither has a board whose rows recorded no edge. `0.00%`
                and `0` are measurements of nothing that was measured, which is the same defect as a
                defaulted figure. */}
            <p className={`text-2xl font-black ${heatReason && heat.value === null ? "text-slate-600" : "text-emerald-500"}`} title={heatReason ?? undefined}>
              {heat.value === null ? NOT_MEASURED : `${heat.value.toFixed(2)}%`}
            </p>
          </div>
          <div className="h-10 w-px bg-slate-800 hidden md:block" />
          <div className="text-right">
            <p className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">Active Edges</p>
            <p className={`text-2xl font-black ${edgesError ? "text-slate-600" : "text-white"}`} title={edgesError ?? undefined}>
              {edgesError ? "—" : edges.length}
            </p>
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
            edgesError ? (
              /* A FAILED read, not an empty one. "No high-confidence edges detected" is a finding,
                 and a read that never completed cannot produce one. The ambiguity this component
                 was built to remove -- a row that never existed against a row I could not see --
                 was being reintroduced a layer up, by the board rendering the same emptiness. */
              <div className="flex flex-col items-center justify-center gap-3 py-32 border-2 border-dashed border-rose-900/60 rounded-3xl">
                <AlertTriangle className="w-10 h-10 text-rose-800" />
                <p className="text-rose-300 font-bold uppercase tracking-tighter">
                  The edge table could not be read
                </p>
                <p className="text-xs text-rose-200/70 max-w-md text-center">{edgesError}</p>
                <p className="text-xs text-slate-500 text-center">
                  Nothing is being claimed about which edges exist. This is not an empty result.
                </p>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-32 space-y-4 border-2 border-dashed border-slate-900 rounded-3xl">
                <TrendingUp className="w-12 h-12 text-slate-800" />
                <p className="text-slate-500 font-bold uppercase tracking-tighter">No high-confidence edges detected in {activeTab}</p>
              </div>
            )
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
              {filteredEdges.map((edge) => (
                <EdgeCard key={edge.id} edge={edge} />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Ruling 1's visible half. The hook withholds these rows and conserves them, but a row that is
          read and not rendered is indistinguishable from there having been no rows -- so a MACRO tab
          that merely got quieter would read as "the engine was retired". It was relabelled. Placed
          under the board because that is where the quiet it explains shows up. The hook's `error`
          and `truncated` travel through: a failed read must not render as "nothing was withheld",
          and the count is a count of the newest 100 rows read, not of the table. */}
      <WithheldEdgesNotice withheld={withheld} readError={edgesError} truncated={truncated} />
      
      {/* Risk Disclosure Section */}
      <div className="mt-16 p-6 rounded-2xl bg-slate-900/40 border border-slate-800/60 text-slate-500 text-[10px] uppercase tracking-widest font-bold leading-relaxed">
         ⚠️ High-Frequency Prediction Alpha: Modeling and probability assessments are provided "as-is" for educational and backtesting purposes. Market entry involves significant capital risk. Ensure strict bankroll management (Kelley Criterion recommended).
      </div>
    </div>
  );
}
