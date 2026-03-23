import { useMarketEdges } from "@/hooks/useMarketEdges";
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { Trophy, Clock, AlertCircle, Percent, Info } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";

export default function SportsDesk() {
  const { edges, loading } = useMarketEdges();

  const sportsEdges = edges.filter(e => e.edge_type.toUpperCase() === "SPORTS");
  
  const getSubsystemEdges = (subsystem: string) => {
    return sportsEdges.filter(e => {
        const payloadSystem = e.raw_payload?.subsystem?.toUpperCase() || "";
        return payloadSystem.includes(subsystem.toUpperCase());
    });
  };

  const ncaaEdges = getSubsystemEdges("NCAA");
  const nbaEdges = getSubsystemEdges("NBA");
  const f1Edges = getSubsystemEdges("F1");
  const soccerEdges = getSubsystemEdges("SOCCER");

  const renderGameCard = (edge: any) => {
    const ourProbPct = (edge.our_prob * 100).toFixed(1);
    const marketProbPct = (edge.market_prob * 100).toFixed(1);
    const isAwaiting = edge.market_prob === 0;
    
    // Parse Logos
    const awayLogo = edge.raw_payload?.away_logo || edge.team_logos?.away;
    const homeLogo = edge.raw_payload?.home_logo || edge.team_logos?.home;
    const awayTeam = edge.raw_payload?.awayTeam || "Away";
    const homeTeam = edge.raw_payload?.homeTeam || "Home";

    return (
      <Dialog key={edge.id}>
        <DialogTrigger asChild>
          <Card className="shadow-sm border-slate-200 hover:border-indigo-500/30 hover:shadow-md transition-all group flex flex-col h-full cursor-pointer bg-white">
            <CardHeader className="pb-4 border-b border-slate-100 flex-none bg-slate-50/50 rounded-t-xl">
              <div className="flex justify-between items-start mb-3">
                <Badge className="bg-indigo-50 text-indigo-700 border border-indigo-200 shadow-none">
                  {edge.raw_payload?.subsystem?.toUpperCase() || "SPORTS"}
                </Badge>
                {isAwaiting ? (
                   <Badge variant="outline" className="text-slate-500 border-slate-300 bg-slate-50 flex items-center gap-1">
                     <Clock className="w-3 h-3" /> Awaiting Market
                   </Badge>
                ) : (
                  <Badge className="bg-emerald-50 text-emerald-600 border border-emerald-200 flex items-center gap-1 shadow-none">
                    <Percent className="w-3 h-3" />
                    {edge.edge_pct.toFixed(1)} Edge
                  </Badge>
                )}
              </div>
              
              {/* Matchup Layout */}
              {awayLogo || homeLogo ? (
                <div className="flex items-center justify-between mt-2 pt-2">
                  <div className="flex flex-col items-center gap-2">
                    {awayLogo ? <img src={awayLogo} alt="Away" className="w-12 h-12 object-contain filter drop-shadow-sm" /> : <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center text-xs font-bold text-slate-400">AWAY</div>}
                    <span className="text-xs font-bold text-slate-600 text-center">{awayTeam}</span>
                  </div>
                  <div className="text-sm font-bold text-slate-300">VS</div>
                  <div className="flex flex-col items-center gap-2">
                    {homeLogo ? <img src={homeLogo} alt="Home" className="w-12 h-12 object-contain filter drop-shadow-sm" /> : <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center text-xs font-bold text-slate-400">HOME</div>}
                    <span className="text-xs font-bold text-slate-600 text-center">{homeTeam}</span>
                  </div>
                </div>
              ) : (
                <CardTitle className="text-lg leading-snug text-slate-900 line-clamp-2 mt-2">
                  {edge.title || edge.market_title || 'Sports Event'}
                </CardTitle>
              )}
            </CardHeader>
            
            <CardContent className="pt-6 flex-1 flex flex-col gap-5">
               <div className="space-y-2">
                 <div className="flex justify-between text-sm font-medium">
                   <span className="text-slate-600 flex items-center gap-1.5"><Trophy className="w-4 h-4 text-emerald-500"/> Our Model (Win Prob)</span>
                   <span className="text-slate-900 font-bold text-lg">{ourProbPct}%</span>
                 </div>
                 <Progress value={edge.our_prob * 100} className="h-2.5 bg-slate-100" indicatorClassName="bg-emerald-500" />
               </div>

               {!isAwaiting && (
                 <div className="space-y-2">
                   <div className="flex justify-between text-sm font-medium">
                     <span className="text-slate-600 flex items-center gap-1.5"><span className="w-4 h-4 rounded-full bg-slate-200 border border-slate-300" /> Kalshi Implied</span>
                     <span className="text-slate-900">{marketProbPct}%</span>
                   </div>
                   <Progress value={edge.market_prob * 100} className="h-2.5 bg-slate-100" indicatorClassName="bg-slate-300" />
                 </div>
               )}
            </CardContent>

            <CardFooter className="pt-3 pb-3 border-t border-slate-100 bg-slate-50 rounded-b-xl flex-none">
              <div className="w-full flex items-center justify-center gap-1.5 text-xs font-medium text-indigo-600 group-hover:text-indigo-700">
                <Info className="w-3.5 h-3.5" /> View Engine Telemetry
              </div>
            </CardFooter>
          </Card>
        </DialogTrigger>
        
        {/* Drill-Down Dialog */}
        <DialogContent className="max-w-2xl bg-white p-0 overflow-hidden border-slate-200">
          <div className="bg-indigo-600 p-6 text-white pb-8">
            <DialogHeader>
              <DialogTitle className="text-2xl font-bold flex flex-col gap-2">
                <Badge className="w-fit bg-indigo-500 hover:bg-indigo-500 text-indigo-50 border-indigo-400">
                  {edge.raw_payload?.subsystem?.toUpperCase() || "SPORTS"} TELEMETRY
                </Badge>
                {edge.title || edge.market_title || 'Matchup Details'}
              </DialogTitle>
            </DialogHeader>
          </div>
          <div className="p-6 -mt-4">
            <Card className="border-0 shadow-lg relative z-10 bg-white">
               <CardContent className="p-6">
                 <div className="grid grid-cols-2 gap-6 mb-6">
                   <div className="p-4 rounded-xl bg-slate-50 border border-slate-100">
                     <div className="text-sm font-medium text-slate-500 mb-1">Algorithmic Win Probability</div>
                     <div className="text-3xl font-bold text-emerald-600">{ourProbPct}%</div>
                   </div>
                   <div className="p-4 rounded-xl bg-slate-50 border border-slate-100">
                     <div className="text-sm font-medium text-slate-500 mb-1">Market Implied Odds</div>
                     <div className="text-3xl font-bold text-slate-900">{isAwaiting ? "Awaiting" : `${marketProbPct}%`}</div>
                   </div>
                 </div>
                 
                 <h4 className="text-sm font-bold text-slate-900 uppercase tracking-widest mb-3 border-b border-slate-100 pb-2">Raw Engine Payload</h4>
                 <div className="bg-slate-900 rounded-xl p-4 overflow-auto max-h-[300px]">
                   <pre className="text-xs text-emerald-400 font-mono leading-relaxed">
                     {JSON.stringify(edge.raw_payload, null, 2)}
                   </pre>
                 </div>
               </CardContent>
            </Card>
          </div>
        </DialogContent>
      </Dialog>
    );
  };

  const renderEmptyState = (tabName: string) => (
    <div className="flex flex-col items-center justify-center py-24 text-center border-2 border-dashed border-slate-200 rounded-2xl bg-slate-50 mt-6">
      <Trophy className="w-12 h-12 text-slate-300 mb-4" />
      <h3 className="text-lg font-semibold text-slate-900">No active {tabName} markets</h3>
      <p className="text-slate-500 mt-1 max-w-sm">The background scanner hasn't detected any upcoming matches or profitable discrepancies yet.</p>
    </div>
  );

  return (
    <div className="p-8 max-w-[1400px] mx-auto space-y-8 animate-in fade-in duration-500">
      <div className="flex flex-col gap-1 mb-8">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">Sports Desk</h1>
        <p className="text-slate-500">Dedicated pre-match odds and telemetry tracking for high-liquidity sports.</p>
      </div>

      <Tabs defaultValue="ncaa" className="w-full">
        <TabsList className="grid w-full max-w-2xl grid-cols-4 bg-slate-100 p-1 rounded-xl">
          <TabsTrigger value="ncaa" className="rounded-lg data-[state=active]:bg-white data-[state=active]:text-indigo-700 data-[state=active]:shadow-sm transition-all font-medium py-2.5">NCAA Hoops</TabsTrigger>
          <TabsTrigger value="nba" className="rounded-lg data-[state=active]:bg-white data-[state=active]:text-indigo-700 data-[state=active]:shadow-sm transition-all font-medium py-2.5">NBA Props</TabsTrigger>
          <TabsTrigger value="f1" className="rounded-lg data-[state=active]:bg-white data-[state=active]:text-indigo-700 data-[state=active]:shadow-sm transition-all font-medium py-2.5">Formula 1</TabsTrigger>
          <TabsTrigger value="soccer" className="rounded-lg data-[state=active]:bg-white data-[state=active]:text-indigo-700 data-[state=active]:shadow-sm transition-all font-medium py-2.5">Soccer</TabsTrigger>
        </TabsList>

        {loading ? (
          <div className="mt-8 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
             {[1, 2, 3].map(i => (
               <Skeleton key={i} className="h-[300px] w-full rounded-xl" />
             ))}
          </div>
        ) : (
          <>
            <TabsContent value="ncaa" className="mt-8">
              {ncaaEdges.length === 0 ? renderEmptyState("NCAA") : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                  {ncaaEdges.map(renderGameCard)}
                </div>
              )}
            </TabsContent>
            
            <TabsContent value="nba" className="mt-8">
              {nbaEdges.length === 0 ? renderEmptyState("NBA") : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                  {nbaEdges.map(renderGameCard)}
                </div>
              )}
            </TabsContent>
            
            <TabsContent value="f1" className="mt-8">
              {f1Edges.length === 0 ? renderEmptyState("Formula 1") : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                  {f1Edges.map(renderGameCard)}
                </div>
              )}
            </TabsContent>
            
            <TabsContent value="soccer" className="mt-8">
              {soccerEdges.length === 0 ? renderEmptyState("Soccer") : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                  {soccerEdges.map(renderGameCard)}
                </div>
              )}
            </TabsContent>
          </>
        )}
      </Tabs>
    </div>
  );
}
