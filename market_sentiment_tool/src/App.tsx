import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
// Pages
import Home from "@/pages/Home";
import PredictionLab from "@/pages/PredictionLab";
import ShadowBacktester from "@/pages/ShadowBacktester";
import { usePortfolio } from "@/hooks/usePortfolio";
import { LayoutDashboard, Activity, Wallet, Brain, LineChart } from "lucide-react";

const Sidebar = () => {
  const { portfolio } = usePortfolio();
  const balance = portfolio?.balance ?? 0;
  
  return (
    <div className="w-64 bg-slate-950 text-slate-200 border-r border-slate-900 h-screen sticky top-0 flex flex-col">
      <div className="p-6">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/20 flex items-center justify-center border border-emerald-500/40">
            <Activity className="w-5 h-5 text-emerald-400" />
          </div>
          <span className="text-xl font-bold tracking-tight text-white uppercase italic">Algo Hub</span>
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
      </nav>

      <div className="p-4 border-t border-slate-900">
        <div className="bg-slate-900/50 rounded-xl p-4 border border-slate-800 shadow-sm">
          <div className="flex items-center gap-2 mb-2 text-slate-400 text-sm font-medium uppercase tracking-tighter">
            <Wallet className="w-4 h-4" /> Live Balance
          </div>
          <div className="text-2xl font-bold text-white tracking-tight">
            ${Math.floor(balance).toLocaleString()}
            <span className="text-slate-500 text-sm">.{((balance % 1) * 100).toFixed(0).padStart(2, '0')}</span>
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
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}

export default App;
