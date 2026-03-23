import { Activity, LogOut } from "lucide-react";
import { TooltipProvider } from "@/components/ui/tooltip";
import PortfolioHero from "@/components/PortfolioHero";
import AgentCommandCenter from "@/components/AgentCommandCenter";
import ActivePositions from "@/components/ActivePositions";
import AgentLogsTerminal from "@/components/AgentLogsTerminal";
import OrderFlowContext from "@/components/OrderFlowContext";
import PnLTracker from "@/components/PnLTracker";
import PerformanceCalendar from "@/components/PerformanceCalendar";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";

const Index = () => {
  const { signOut } = useAuth();

  return (
    <TooltipProvider>
      <div className="min-h-screen bg-background">
        {/* Header */}
        <header className="border-b border-border px-6 py-4">
          <div className="max-w-[1600px] mx-auto flex items-center gap-3">
            <Activity className="w-6 h-6 text-profit" />
            <h1 className="text-xl font-bold text-foreground tracking-tight">AlgoTrader</h1>
            <span className="ml-2 text-[10px] font-mono font-bold text-profit bg-profit/10 px-2 py-0.5 rounded-full uppercase tracking-widest">
              Dashboard
            </span>
            <div className="ml-auto">
              <Button variant="ghost" size="sm" onClick={signOut} className="text-muted-foreground hover:text-foreground">
                <LogOut className="w-4 h-4 mr-1" />
                Sign Out
              </Button>
            </div>
          </div>
        </header>

        {/* Content */}
        <main className="max-w-[1600px] mx-auto p-6 space-y-6">
          {/* Order Flow Context */}
          <OrderFlowContext />

          {/* Portfolio Hero */}
          <PortfolioHero />

          {/* Agent Command Center */}
          <AgentCommandCenter />

          {/* Split Pane: Trades + Logs */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 h-[500px] max-h-[500px] overflow-hidden">
            <ActivePositions />
            <AgentLogsTerminal />
          </div>

          {/* Performance Suite */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 h-[400px] max-h-[400px] overflow-hidden">
            <PnLTracker />
            <PerformanceCalendar />
          </div>
        </main>
      </div>
    </TooltipProvider>
  );
};

export default Index;
