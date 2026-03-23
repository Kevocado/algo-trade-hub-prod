import { useFPLOptimizations } from "@/hooks/useSupabaseData";
import { Trophy, Coins, Target, Users } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function SportsDesk() {
  const { optimizations, loading } = useFPLOptimizations();

  return (
    <div className="p-8 max-w-[1400px] mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Sports Desk</h1>
        <p className="text-muted-foreground mt-2">AI-driven Fantasy Premier League and NBA linear lineup optimizations.</p>
      </div>

      {loading ? (
        <div className="flex h-40 items-center justify-center text-muted-foreground">Solving LP configurations...</div>
      ) : optimizations.length === 0 ? (
        <div className="flex h-40 items-center justify-center text-muted-foreground border rounded-lg border-dashed">No optimizations found.</div>
      ) : (
        <div className="space-y-8">
          {optimizations.map((opt) => (
            <Card key={opt.id} className="overflow-hidden border-border shadow-sm">
              <CardHeader className="bg-primary/5 border-b pb-6">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                  <div>
                    <CardTitle className="flex items-center gap-2 text-xl">
                      <Trophy className="w-5 h-5 text-primary" />
                      Optimized Squad
                      <Badge variant="outline" className="ml-2 bg-background font-mono text-xs text-muted-foreground">
                        {new Date(opt.created_at).toLocaleString()}
                      </Badge>
                    </CardTitle>
                    <CardDescription className="mt-2 text-sm max-w-xl">
                      Generated using the <span className="font-semibold text-foreground capitalize">{opt.strategy}</span> strategy matrix.
                    </CardDescription>
                  </div>
                  
                  <div className="flex flex-wrap gap-4">
                    <div className="bg-background border rounded-lg p-3 flex items-center gap-3 shadow-sm min-w-[140px]">
                      <div className="p-2 bg-green-500/10 rounded-md text-green-600"><Target className="w-4 h-4" /></div>
                      <div>
                        <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Expected Pts</p>
                        <p className="text-lg font-bold text-foreground">{opt.total_score.toFixed(1)}</p>
                      </div>
                    </div>
                    <div className="bg-background border rounded-lg p-3 flex items-center gap-3 shadow-sm min-w-[140px]">
                      <div className="p-2 bg-yellow-500/10 rounded-md text-yellow-600"><Coins className="w-4 h-4" /></div>
                      <div>
                        <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Budget Used</p>
                        <p className="text-lg font-bold text-foreground">£{opt.total_cost.toFixed(1)}m</p>
                      </div>
                    </div>
                  </div>
                </div>
              </CardHeader>
              
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm text-left">
                    <thead className="bg-muted/50 text-xs text-muted-foreground uppercase font-semibold border-b">
                      <tr>
                        <th className="px-6 py-4">Player</th>
                        <th className="px-6 py-4">Position</th>
                        <th className="px-6 py-4">Team</th>
                        <th className="px-6 py-4">Price</th>
                        <th className="px-6 py-4 text-right pr-8">xP (Expected)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {opt.squad_json?.starting_xi?.map((player: any, idx: number) => (
                        <tr key={idx} className="hover:bg-muted/30 transition-colors">
                          <td className="px-6 py-4 font-medium text-foreground flex items-center gap-2">
                            {player.name}
                            {opt.captain === player.name && (
                              <Badge className="bg-yellow-500/20 text-yellow-700 hover:bg-yellow-500/30 border-yellow-500/30 ml-2 py-0 h-5">
                                CAPTAIN
                              </Badge>
                            )}
                          </td>
                          <td className="px-6 py-4"><Badge variant="outline" className="text-xs">{player.position}</Badge></td>
                          <td className="px-6 py-4 text-muted-foreground">{player.team}</td>
                          <td className="px-6 py-4 font-medium">£{player.price.toFixed(1)}m</td>
                          <td className="px-6 py-4 text-right pr-8 font-bold text-primary">{player.xP.toFixed(2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
