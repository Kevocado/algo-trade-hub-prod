import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
// Pages
import Home from "@/pages/Home";
import PredictionLab from "@/pages/PredictionLab";
import ShadowBacktester from "@/pages/ShadowBacktester";
import Models from "@/pages/Models";
import Scoreboard from "@/pages/Scoreboard";
import SportsEdges from "@/pages/SportsEdges";
import JobsScorecard from "@/pages/JobsScorecard";
import CpiDisplay from "@/pages/CpiDisplay";
import { usePortfolio } from "@/hooks/usePortfolio";
import { portfolioHeadline } from "@/lib/portfolioTruth";
import { LayoutDashboard, Activity, Wallet, Brain, Cpu, LineChart, Scale, Trophy, Briefcase, BarChart3 } from "lucide-react";

const Sidebar = () => {
  const { portfolio } = usePortfolio();
  // The sidebar used to render "LIVE BALANCE $0.00" from an empty table, which reads as a flat
  // book. This product places no orders, so it says that instead of showing a number nobody can act
  // on -- and an unreadable payload reads as unknown, never as zero.
  const headline = portfolioHeadline(portfolio);
  
  return (
    <div className="w-64 bg-slate-950 text-slate-200 border-r border-slate-900 h-screen sticky top-0 flex flex-col">
      <div className="p-6">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center border border-emerald-500/40">
            <Activity className="w-5 h-5 text-emerald-400" />
          </div>
          <span className="text-xl font-bold tracking-tight text-white uppercase italic">Algo Trade Hub</span>
        </div>
      </div>
      
      <nav className="flex-1 px-4 space-y-2 mt-4">
        <NavLink 
          to="/" 
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <LayoutDashboard className="w-5 h-5" /> Portfolio
        </NavLink>
        <NavLink 
          to="/lab" 
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <Brain className="w-5 h-5 text-emerald-500" /> Prediction Lab
        </NavLink>
        <NavLink 
          to="/shadow" 
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <LineChart className="w-5 h-5 text-amber-400" /> Shadow
        </NavLink>
        <NavLink
          to="/models"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          {/* "Models", not "Engines": the product's own word for these is engine, and that word
              appears in every row of the page, but the person reading the nav asked what the MODELS
              are doing and did not know the site had any. It sits above Scoreboard in the list
              because it is the frame the other pages sit inside. */}
          <Cpu className="w-5 h-5 text-indigo-400" /> Models
        </NavLink>
        <NavLink
          to="/scoreboard"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          {/* "Scoreboard", not "Shadow": /shadow is the crypto shadow-timeline backtester, a
              different page that happens to share a name with this one. */}
          <Scale className="w-5 h-5 text-rose-400" /> Scoreboard
        </NavLink>
        <NavLink
          to="/sports"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <Trophy className="w-5 h-5 text-cyan-400" /> Sports
        </NavLink>
        <NavLink
          to="/jobs"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <Briefcase className="w-5 h-5 text-sky-400" /> Jobs Scorecard
        </NavLink>
        {/* Label says "Display", not "Nowcast" or "Edges". This board is NOT a board of
            opportunities, and a nav entry that reads like the other four would put the claim back
            that the page spends its length taking away. */}
        <NavLink
          to="/cpi"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <BarChart3 className="w-5 h-5 text-amber-400" /> CPI Display
        </NavLink>
      </nav>

      <div className="p-4 border-t border-slate-900">
        <div className="bg-slate-900/50 rounded-xl p-4 border border-slate-800 shadow-sm">
          <div className="flex items-center gap-2 mb-2 text-slate-400 text-sm font-medium uppercase tracking-tighter">
            <Wallet className="w-4 h-4" aria-hidden="true" /> {headline.label}
          </div>
          <div
            className={`text-2xl font-bold tracking-tight ${
              headline.tone === "muted" ? "text-slate-400" : "text-white"
            }`}
          >
            {headline.value}
          </div>
          <div className="text-[10px] text-emerald-400 flex items-center gap-1 mt-1 font-black bg-emerald-500/10 w-fit px-2 py-0.5 rounded-full border border-emerald-500/20 uppercase">
             Live Telemetry
          </div>
        </div>
      </div>
    </div>
  );
};

const AppShell = ({ children }: { children: React.ReactNode }) => {
  return (
    <div className="flex min-h-screen bg-slate-950">
      <Sidebar />
      <main className="flex-1 min-h-screen overflow-auto bg-slate-950 text-slate-100">
        {children}
      </main>
    </div>
  );
};

function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/lab" element={<PredictionLab />} />
          <Route path="/shadow" element={<ShadowBacktester />} />
          <Route path="/models" element={<Models />} />
          <Route path="/scoreboard" element={<Scoreboard />} />
          <Route path="/sports" element={<SportsEdges />} />
          <Route path="/jobs" element={<JobsScorecard />} />
          <Route path="/cpi" element={<CpiDisplay />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}

export default App;
